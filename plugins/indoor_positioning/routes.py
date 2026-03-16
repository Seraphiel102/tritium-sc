# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the indoor positioning plugin.

Provides REST endpoints for:
- GET /api/indoor/position/{target_id} — fused indoor position for a target
- GET /api/indoor/positions — all cached indoor positions
- POST /api/indoor/wifi-observation — submit WiFi RSSI observation
- GET /api/indoor/status — fusion engine status
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .fusion import IndoorPositionFusion

try:
    from app.auth import optional_auth
except ImportError:
    async def optional_auth():  # type: ignore[misc]
        return None


class WiFiObservationRequest(BaseModel):
    """Submit a WiFi RSSI observation for a target."""
    target_id: str = Field(..., max_length=200)
    rssi_map: dict[str, float] = Field(..., description="BSSID -> RSSI map")


def create_router(fusion: IndoorPositionFusion) -> APIRouter:
    """Build and return the indoor positioning APIRouter."""
    router = APIRouter(prefix="/api/indoor", tags=["indoor-positioning"])

    @router.get("/position/{target_id}")
    async def get_position(target_id: str):
        """Get fused indoor position for a target.

        Combines WiFi fingerprint matching (kNN on RSSI vectors) with
        BLE RSSI-based trilateration. Returns position with uncertainty
        radius and room-level localization if a floor plan is available.
        """
        # Try to compute a fresh estimate
        fused = fusion.estimate_position(target_id)
        if fused is None:
            # Fall back to cached
            fused = fusion.get_cached_position(target_id)
        if fused is None:
            raise HTTPException(
                status_code=404,
                detail=f"No indoor position data for target '{target_id}'",
            )
        return {"position": fused.to_dict()}

    @router.get("/positions")
    async def get_all_positions(
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        """Get all cached fused indoor positions."""
        all_pos = fusion.get_all_positions()
        items = [p.to_dict() for p in list(all_pos.values())[:limit]]
        return {"positions": items, "count": len(items)}

    @router.post("/wifi-observation")
    async def submit_wifi_observation(body: WiFiObservationRequest):
        """Submit a WiFi RSSI observation for a target.

        The observation is stored and used in the next position
        estimation call for this target.
        """
        if not body.rssi_map:
            raise HTTPException(status_code=400, detail="rssi_map cannot be empty")
        fusion.update_wifi_observation(body.target_id, body.rssi_map)
        return {"stored": True, "target_id": body.target_id, "bssid_count": len(body.rssi_map)}

    @router.get("/status")
    async def get_status():
        """Get indoor positioning fusion engine status."""
        return {
            "tracked_targets": fusion.tracked_targets,
            "engine": "wifi_ble_fusion",
            "methods": ["fingerprint_knn", "ble_trilateration"],
        }

    return router
