# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target timeline / biography API — per-target temporal intelligence.

Provides the "target biography" view: first seen, last seen, total time
tracked, number of sightings by source, position trail, and dossier data.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/targets", tags=["target-timeline"])


def _get_tracker(request: Request):
    """Get target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        tracker = getattr(amy, "target_tracker", None)
        if tracker is not None:
            return tracker
    return None


def _get_dossier_store(request: Request):
    """Get dossier store from Amy if available."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "dossier_store", None)
    return None


@router.get("/{target_id}/timeline")
async def get_target_timeline(request: Request, target_id: str):
    """Return the full timeline / biography for a single target.

    Includes:
    - first_seen / last_seen timestamps
    - total_tracked_seconds
    - source breakdown (sightings per source type)
    - position trail (last 50 positions)
    - confirming sources
    - dossier data if correlated with other signals
    """
    tracker = _get_tracker(request)
    if tracker is None:
        return JSONResponse({"error": "Target tracker not available"}, status_code=503)

    target = tracker.get_target(target_id)
    if target is None:
        return JSONResponse({"error": f"Target '{target_id}' not found"}, status_code=404)

    now = time.monotonic()

    # Basic target info
    result = target.to_dict()

    # History / trail data
    history = tracker.history
    trail = history.get_trail(target_id, max_points=50)

    # Compute first_seen from trail or target data
    first_seen_ts = target.last_seen  # fallback
    if trail:
        first_seen_ts = trail[0][2]  # oldest trail point timestamp

    total_tracked_s = now - first_seen_ts if first_seen_ts < now else 0.0

    # Source breakdown from confirming sources
    source_breakdown: dict[str, int] = {}
    for src in target.confirming_sources:
        source_breakdown[src] = source_breakdown.get(src, 0) + 1
    # Always include the primary source
    source_breakdown[target.source] = source_breakdown.get(target.source, 0) + 1

    # Sighting count approximation from trail length
    sighting_count = len(trail) if trail else 1

    # Speed/heading from history
    speed_estimate = history.estimate_speed(target_id) if hasattr(history, "estimate_speed") else target.speed
    heading_estimate = history.estimate_heading(target_id) if hasattr(history, "estimate_heading") else target.heading

    # Dossier data
    dossier_data = None
    dossier_store = _get_dossier_store(request)
    if dossier_store is not None:
        dossier = dossier_store.find_by_signal(target_id)
        if dossier is not None:
            dossier_data = dossier.to_dict()

    timeline = {
        "target_id": target_id,
        "name": target.name,
        "alliance": target.alliance,
        "asset_type": target.asset_type,
        "source": target.source,
        "status": target.status,
        "position": result.get("position"),
        "lat": result.get("lat"),
        "lng": result.get("lng"),
        "heading": heading_estimate,
        "speed": speed_estimate,
        "battery": target.battery,
        "position_confidence": target.effective_confidence,
        "threat_score": target.threat_score,
        "confirming_sources": list(target.confirming_sources),
        "velocity_suspicious": target.velocity_suspicious,
        # Timeline-specific fields
        "first_seen": first_seen_ts,
        "last_seen": target.last_seen,
        "total_tracked_seconds": round(total_tracked_s, 1),
        "sighting_count": sighting_count,
        "source_breakdown": source_breakdown,
        "trail": [
            {"x": t[0], "y": t[1], "timestamp": t[2]}
            for t in trail[-50:]
        ],
        "dossier": dossier_data,
    }

    return timeline


@router.get("/{target_id}/biography")
async def get_target_biography(request: Request, target_id: str):
    """Return a human-readable biography / narrative summary for a target.

    This is the narrative version of the timeline, suitable for display
    in a target info panel.
    """
    tracker = _get_tracker(request)
    if tracker is None:
        return JSONResponse({"error": "Target tracker not available"}, status_code=503)

    target = tracker.get_target(target_id)
    if target is None:
        return JSONResponse({"error": f"Target '{target_id}' not found"}, status_code=404)

    now = time.monotonic()
    history = tracker.history
    trail = history.get_trail(target_id, max_points=100)

    first_seen_ts = trail[0][2] if trail else target.last_seen
    total_tracked_s = now - first_seen_ts if first_seen_ts < now else 0.0
    sighting_count = len(trail) if trail else 1

    # Build narrative
    parts = []
    parts.append(
        f"{target.name} ({target.asset_type}) — classified as {target.alliance}."
    )

    # Time tracking
    if total_tracked_s < 60:
        time_str = f"{total_tracked_s:.0f} seconds"
    elif total_tracked_s < 3600:
        time_str = f"{total_tracked_s / 60:.1f} minutes"
    else:
        time_str = f"{total_tracked_s / 3600:.1f} hours"
    parts.append(f"Tracked for {time_str} with {sighting_count} position updates.")

    # Source info
    sources = list(target.confirming_sources) or [target.source]
    if len(sources) > 1:
        parts.append(f"Confirmed by {len(sources)} sources: {', '.join(sources)}.")
    else:
        parts.append(f"Detected via {sources[0]}.")

    # Confidence
    conf = target.effective_confidence
    if conf > 0.8:
        parts.append("High confidence position.")
    elif conf > 0.4:
        parts.append("Moderate confidence position.")
    elif conf > 0:
        parts.append("Low confidence — position may be stale.")

    # Threat
    if target.threat_score > 0.5:
        parts.append(f"THREAT SCORE: {target.threat_score:.2f} — elevated threat level.")
    elif target.threat_score > 0:
        parts.append(f"Threat score: {target.threat_score:.2f}.")

    if target.velocity_suspicious:
        parts.append("WARNING: Suspicious velocity detected — possible spoofing or GPS glitch.")

    # Dossier
    dossier_store = _get_dossier_store(request)
    if dossier_store is not None:
        dossier = dossier_store.find_by_signal(target_id)
        if dossier is not None:
            parts.append(
                f"Correlated identity: dossier {dossier.uuid[:8]}... "
                f"with {len(dossier.signal_ids)} linked signals."
            )

    return {
        "target_id": target_id,
        "biography": " ".join(parts),
        "total_tracked_seconds": round(total_tracked_s, 1),
        "sighting_count": sighting_count,
    }
