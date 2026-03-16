# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Historical analytics API — aggregate statistics for time periods.

Provides historical analysis of tactical events stored in the
TacticalEventStore.  Returns aggregate counts, busiest hours,
most-seen devices, correlation success rates, and event type breakdown.

Endpoints:
    GET /api/analytics/history?start=<epoch>&end=<epoch>
        Returns aggregate statistics for the given time window.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _get_event_store(request: Request):
    """Get the TacticalEventStore from app state, or None."""
    return getattr(request.app.state, "tactical_event_store", None)


@router.get("/history")
async def get_history_analytics(
    request: Request,
    start: Optional[float] = Query(None, description="Start timestamp (unix epoch)"),
    end: Optional[float] = Query(None, description="End timestamp (unix epoch)"),
    hours: Optional[float] = Query(None, description="Look-back window in hours (alternative to start/end)"),
):
    """Get aggregate statistics for a time period.

    Query parameters:
        start: Unix epoch start time
        end: Unix epoch end time
        hours: Alternative to start — look back N hours from now

    Returns JSON with:
        - total_events: total count in window
        - events_by_type: breakdown by event type
        - events_by_severity: breakdown by severity
        - events_by_source: breakdown by sensor source
        - busiest_hours: event counts by hour-of-day (0-23)
        - top_targets: most-seen targets
        - correlation_stats: correlation success/failure counts
        - time_range: actual start/end of returned data
    """
    store = _get_event_store(request)

    # Handle hours parameter
    if hours is not None and start is None:
        start = time.time() - (hours * 3600)
    if end is None:
        end = time.time()

    # If no store is configured, return empty analytics
    if store is None:
        return JSONResponse(content={
            "total_events": 0,
            "events_by_type": {},
            "events_by_severity": {},
            "events_by_source": {},
            "busiest_hours": {},
            "top_targets": [],
            "correlation_stats": {
                "total_correlations": 0,
                "successful": 0,
                "rate": 0.0,
            },
            "time_range": {
                "start": start,
                "end": end,
                "duration_hours": ((end - start) / 3600) if start else 0,
            },
            "generated_at": time.time(),
            "source": "no_store",
        })

    # Gather stats from the store
    stats = store.get_stats(start=start, end=end)

    # Hourly breakdown
    hourly = store.get_hourly_breakdown(start=start, end=end)

    # Top targets
    top_targets = store.get_top_targets(start=start, end=end, limit=20)

    # Correlation stats
    total_correlations = store.count(event_type="target_correlation", start=start, end=end)
    # Look for correlation success/failure in the data
    successful_correlations = total_correlations  # all recorded correlations are successful
    failed_correlations = store.count(event_type="correlation_failed", start=start, end=end)
    total_corr_attempts = successful_correlations + failed_correlations
    corr_rate = (successful_correlations / total_corr_attempts) if total_corr_attempts > 0 else 0.0

    # Target type breakdown
    target_sightings = store.count(event_type="target_sighting", start=start, end=end)
    target_detected = store.count(event_type="target_detected", start=start, end=end)
    target_lost = store.count(event_type="target_lost", start=start, end=end)
    alerts = store.count(event_type="alert", start=start, end=end) + store.count(
        event_type="alert_raised", start=start, end=end
    )
    geofence_events = (
        store.count(event_type="geofence_enter", start=start, end=end)
        + store.count(event_type="geofence_exit", start=start, end=end)
        + store.count(event_type="geofence_event", start=start, end=end)
    )

    duration_hours = ((end - start) / 3600) if start else 0

    result = {
        "total_events": stats.get("total_events", 0),
        "events_by_type": stats.get("by_type", {}),
        "events_by_severity": stats.get("by_severity", {}),
        "events_by_source": stats.get("by_source", {}),
        "busiest_hours": hourly,
        "top_targets": top_targets,
        "target_activity": {
            "sightings": target_sightings,
            "detected": target_detected,
            "lost": target_lost,
            "alerts": alerts,
            "geofence_events": geofence_events,
        },
        "correlation_stats": {
            "total_correlations": total_correlations,
            "successful": successful_correlations,
            "failed": failed_correlations,
            "rate": round(corr_rate, 4),
        },
        "time_range": {
            "start": start,
            "end": end,
            "duration_hours": round(duration_hours, 2),
            "oldest_event": stats.get("oldest_event"),
            "newest_event": stats.get("newest_event"),
        },
        "generated_at": time.time(),
    }

    return result
