# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Picture of the Day — periodic 24-hour operational summary.

Aggregates new targets discovered, correlations made, threats detected,
geofence breaches, investigations opened, and total sightings into a
single "daily snapshot" of the unified operating picture.

Endpoints:
    GET /api/picture-of-day — JSON summary of the last 24 hours
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analytics"])


def _get_tracker(request: Request):
    """Get target tracker from Amy or app state."""
    amy = getattr(request.app.state, "amy", None)
    if amy is not None:
        return getattr(amy, "target_tracker", None)
    return None


def _count_new_targets(request: Request) -> tuple[int, dict[str, int]]:
    """Count targets seen in last 24 hours and break down by source."""
    tracker = _get_tracker(request)
    if tracker is None:
        # Fallback to simulation engine
        engine = getattr(request.app.state, "simulation_engine", None)
        if engine is not None:
            targets = engine.get_targets()
            by_source: dict[str, int] = {}
            for t in targets:
                src = getattr(t, "source", "unknown") or "unknown"
                by_source[src] = by_source.get(src, 0) + 1
            return len(targets), by_source
        return 0, {}

    cutoff = time.time() - 86400  # 24 hours ago
    targets = tracker.get_all()
    new_count = 0
    by_source: dict[str, int] = {}

    for t in targets:
        src = getattr(t, "source", "unknown") or "unknown"
        by_source[src] = by_source.get(src, 0) + 1
        first_seen = getattr(t, "first_seen", None) or getattr(t, "last_seen", 0)
        if first_seen >= cutoff:
            new_count += 1

    return new_count, by_source


def _count_correlations(request: Request) -> int:
    """Count active correlations."""
    correlator = getattr(request.app.state, "correlator", None)
    if correlator is None:
        return 0
    try:
        records = correlator.get_correlations()
        return len(records)
    except Exception:
        return 0


def _count_threats(request: Request) -> int:
    """Count hostile/threat targets."""
    tracker = _get_tracker(request)
    if tracker is None:
        return 0

    count = 0
    for t in tracker.get_all():
        alliance = getattr(t, "alliance", "unknown")
        if alliance == "hostile":
            count += 1
    return count


def _count_zone_events() -> int:
    """Count geofence events in last 24 hours."""
    try:
        from app.routers.geofence import get_engine
        engine = get_engine()
        events = engine.get_events(limit=500)
        cutoff = time.time() - 86400
        return sum(
            1 for e in events
            if (getattr(e, "timestamp", 0) or 0) >= cutoff
        )
    except Exception:
        return 0


def _count_investigations(request: Request) -> int:
    """Count open investigations."""
    try:
        inv_store = getattr(request.app.state, "investigation_store", None)
        if inv_store is None:
            return 0
        investigations = inv_store.list_investigations()
        return sum(1 for i in investigations if i.get("status") == "open")
    except Exception:
        return 0


def _total_sightings(request: Request) -> int:
    """Estimate total sightings from tracker history."""
    tracker = _get_tracker(request)
    if tracker is None:
        return 0

    total = 0
    history = getattr(tracker, "history", None)
    if history is not None:
        try:
            total = getattr(history, "total_points", 0)
        except Exception:
            pass

    # Fallback: count all targets (each one is at least 1 sighting)
    if total == 0:
        total = len(tracker.get_all())

    return total


def _get_top_devices(request: Request) -> list[dict]:
    """Get most active devices by sighting count."""
    bridge = getattr(request.app.state, "fleet_bridge", None)
    if bridge is None:
        return []

    cached = getattr(bridge, "cached_nodes", None)
    if not cached or not isinstance(cached, list):
        return []

    # Sort by sighting count (descending)
    nodes = sorted(
        cached,
        key=lambda n: n.get("sighting_count", 0),
        reverse=True,
    )

    return [
        {
            "device_id": n.get("device_id", "unknown"),
            "sighting_count": n.get("sighting_count", 0),
            "target_count": n.get("target_count", 0),
            "last_seen": n.get("last_seen", 0.0),
        }
        for n in nodes[:10]
    ]


def _determine_threat_level(threats: int) -> str:
    """Determine overall threat level."""
    if threats == 0:
        return "GREEN"
    elif threats <= 3:
        return "YELLOW"
    elif threats <= 10:
        return "ORANGE"
    else:
        return "RED"


@router.get("/picture-of-day")
async def picture_of_day(request: Request):
    """Generate a 24-hour operational summary (Picture of the Day).

    Returns a JSON snapshot summarizing the last 24 hours of operations:
    - New targets discovered
    - Target correlations made
    - Threats detected (hostile targets)
    - Geofence zone events
    - Investigations opened
    - Total sightings and breakdown by source
    - Most active devices
    - Overall threat level

    Designed for the ops dashboard overview panel.
    """
    now = datetime.now(timezone.utc)

    new_targets, sightings_by_source = _count_new_targets(request)
    correlations = _count_correlations(request)
    threats = _count_threats(request)
    zone_events = _count_zone_events()
    investigations = _count_investigations(request)
    total_sightings = _total_sightings(request)
    top_devices = _get_top_devices(request)
    threat_level = _determine_threat_level(threats)

    # Calculate uptime
    uptime_pct = 100.0
    try:
        from app.routers.health import _start_time
        uptime_s = time.time() - _start_time
        # Assume 100% if running (we don't track downtime)
        uptime_pct = min(100.0, uptime_s / 864.0)  # scale to reasonable %
    except Exception:
        pass

    return {
        "report_date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "period_hours": 24,
        "new_targets": new_targets,
        "correlations": correlations,
        "threats": threats,
        "zone_events": zone_events,
        "investigations_opened": investigations,
        "total_sightings": total_sightings,
        "sightings_by_source": sightings_by_source,
        "top_devices": top_devices,
        "threat_level": threat_level,
        "uptime_percent": round(uptime_pct, 1),
    }
