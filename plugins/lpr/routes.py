# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for LPR (License Plate Recognition) plugin.

Provides REST endpoints for:
- Watchlist management (CRUD)
- Plate search
- Recent detections
- Detection submission (from external ALPR systems)
- Plugin statistics
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

try:
    from app.auth import require_auth
except ImportError:
    async def require_auth():  # type: ignore[misc]
        return {"sub": "anonymous"}


class WatchlistAddRequest(BaseModel):
    """Request to add a plate to the watchlist."""
    plate_number: str = Field(..., max_length=20)
    reason: str = Field(default="", max_length=500)
    priority: str = Field(default="normal", pattern=r"^(low|normal|high|critical)$")
    owner: str = Field(default="", max_length=200)
    vehicle_description: str = Field(default="", max_length=500)
    alert_on_match: bool = True


class DetectionSubmitRequest(BaseModel):
    """Submit a plate detection from an external source."""
    plate_number: str
    camera_id: str = ""
    confidence: float = 0.0
    bbox: Optional[list[int]] = None
    vehicle_type: str = ""
    vehicle_color: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None


def create_router(plugin: Any) -> APIRouter:
    """Create FastAPI router for LPR plugin."""
    router = APIRouter(prefix="/api/lpr", tags=["lpr"])

    @router.get("/")
    async def lpr_status():
        """LPR plugin status and statistics."""
        return {
            "plugin": plugin.plugin_id,
            "version": plugin.version,
            "healthy": plugin.healthy,
            "stats": plugin.get_stats(),
        }

    @router.get("/watchlist")
    async def get_watchlist():
        """Get all watchlist entries."""
        return {"watchlist": plugin.get_watchlist()}

    @router.post("/watchlist")
    async def add_to_watchlist(req: WatchlistAddRequest, user: dict = Depends(require_auth)):
        """Add a plate to the watchlist."""
        entry = plugin.add_to_watchlist(
            plate_number=req.plate_number,
            reason=req.reason,
            priority=req.priority,
            owner=req.owner,
            vehicle_description=req.vehicle_description,
            alert_on_match=req.alert_on_match,
        )
        return {"status": "added", "entry": entry}

    @router.delete("/watchlist/{plate_number}")
    async def remove_from_watchlist(plate_number: str, user: dict = Depends(require_auth)):
        """Remove a plate from the watchlist."""
        removed = plugin.remove_from_watchlist(plate_number)
        if removed:
            return {"status": "removed", "plate_number": plate_number}
        return {"status": "not_found", "plate_number": plate_number}

    @router.get("/watchlist/check/{plate_number}")
    async def check_watchlist(plate_number: str):
        """Check if a plate is on the watchlist."""
        match = plugin.check_watchlist(plate_number)
        return {
            "plate_number": plate_number.upper(),
            "on_watchlist": match is not None,
            "entry": match,
        }

    @router.get("/detections")
    async def get_detections(count: int = Query(default=50, ge=1, le=1000)):
        """Get recent plate detections."""
        detections = plugin.get_recent_detections(count=count)
        return {"detections": detections, "count": len(detections)}

    @router.post("/detections")
    async def submit_detection(req: DetectionSubmitRequest):
        """Submit a plate detection from an external ALPR system."""
        location = None
        if req.lat is not None and req.lng is not None:
            location = (req.lat, req.lng)

        detection = plugin.record_detection(
            plate_number=req.plate_number,
            camera_id=req.camera_id,
            confidence=req.confidence,
            bbox=req.bbox,
            vehicle_type=req.vehicle_type,
            vehicle_color=req.vehicle_color,
            location=location,
        )
        return {"status": "recorded", "detection": detection}

    @router.get("/search")
    async def search_plates(q: str = ""):
        """Search detection history for a plate number."""
        if not q:
            return {"query": "", "results": [], "count": 0}
        results = plugin.search_plates(q)
        return {"query": q.upper(), "results": results, "count": len(results)}

    return router
