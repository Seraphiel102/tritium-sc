# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the SDR Monitor plugin.

Provides REST endpoints for listing detected ISM band devices,
frequency activity summaries, and detection statistics.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query


def create_router(plugin: Any) -> APIRouter:
    """Build SDR Monitor API router.

    Parameters
    ----------
    plugin:
        SDRMonitorPlugin instance.
    """
    router = APIRouter(prefix="/api/sdr_monitor", tags=["sdr_monitor"])

    @router.get("/devices")
    async def get_devices():
        """List all detected ISM band devices.

        Returns devices detected via rtl_433 MQTT feed, including
        weather stations, TPMS sensors, doorbells, key fobs, etc.
        """
        devices = plugin.get_devices()
        return {"devices": devices, "count": len(devices)}

    @router.get("/spectrum")
    async def get_spectrum():
        """Get frequency activity summary.

        Returns a map of frequency (MHz) to message count, showing
        which ISM frequencies have the most activity.
        """
        return plugin.get_spectrum()

    @router.get("/stats")
    async def get_stats():
        """Get detection counts by device type and overall statistics."""
        return plugin.get_stats()

    @router.get("/signals")
    async def get_signals(limit: int = Query(default=50, ge=1, le=2000)):
        """Get recent signal history."""
        signals = plugin.get_signals(limit=limit)
        return {"signals": signals, "count": len(signals)}

    @router.get("/health")
    async def get_health():
        """Return plugin health status."""
        stats = plugin.get_stats()
        return {
            "healthy": plugin.healthy,
            "plugin_id": plugin.plugin_id,
            "version": plugin.version,
            "devices_active": stats.get("devices_active", 0),
            "messages_received": stats.get("messages_received", 0),
        }

    @router.post("/ingest")
    async def ingest_message(body: dict):
        """Manually ingest an rtl_433 JSON message.

        Useful for testing or when rtl_433 data arrives via HTTP
        instead of MQTT.
        """
        result = plugin.ingest_message(body)
        return {"status": "ok", "device": result}

    return router
