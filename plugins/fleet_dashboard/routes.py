# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Fleet Dashboard plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

if TYPE_CHECKING:
    from .plugin import FleetDashboardPlugin


def create_router(plugin: FleetDashboardPlugin) -> APIRouter:
    """Build and return the fleet dashboard APIRouter."""

    router = APIRouter(prefix="/api/fleet", tags=["fleet-dashboard"])

    @router.get("/devices")
    async def list_devices():
        """List all tracked fleet devices with status."""
        devices = plugin.get_devices()
        return {"devices": devices, "count": len(devices)}

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str):
        """Get a single fleet device by ID."""
        device = plugin.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        return {"device": device}

    @router.get("/summary")
    async def get_summary():
        """Fleet summary: online/offline/stale counts, avg battery, totals."""
        return plugin.get_summary()

    @router.get("/devices/{device_id}/sparkline")
    async def get_device_sparkline(device_id: str):
        """Get target count history for a device, suitable for sparkline rendering.

        Returns an array of {ts, count} entries over the last hour.
        """
        history = plugin.get_target_history(device_id)
        return {"device_id": device_id, "history": history, "count": len(history)}

    @router.get("/sparklines")
    async def get_all_sparklines():
        """Get target count sparkline data for all devices."""
        histories = plugin.get_all_target_histories()
        return {
            "sparklines": {
                did: {"history": h, "count": len(h)}
                for did, h in histories.items()
            },
            "device_count": len(histories),
        }

    return router
