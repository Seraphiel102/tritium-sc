# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Command history API — audit log of all commands sent to edge devices."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet/commands", tags=["fleet"])


@router.get("/history")
async def command_history(request: Request, limit: int = 100):
    """GET /api/fleet/commands/history — list all commands sent to edge devices.

    Returns:
        {
            "commands": [
                {
                    "command_id": "cmd_abc123",
                    "device_id": "tritium-01",
                    "device_group": null,
                    "command": "reboot",
                    "payload": {},
                    "sent_at": 1710000000,
                    "result": "acknowledged",
                    "acked_at": 1710000005
                }
            ],
            "count": 1,
            "source": "live"
        }
    """
    store = getattr(request.app.state, "command_history_store", None)
    if store is None:
        return {"commands": [], "count": 0, "source": "unavailable"}

    commands = store.get_recent(limit)
    return {
        "commands": commands,
        "count": len(commands),
        "source": "live",
    }


@router.get("/stats")
async def command_stats(request: Request):
    """GET /api/fleet/commands/stats — summary statistics for command history."""
    store = getattr(request.app.state, "command_history_store", None)
    if store is None:
        return {
            "total_sent": 0,
            "acknowledged": 0,
            "failed": 0,
            "timed_out": 0,
            "pending": 0,
            "source": "unavailable",
        }

    stats = store.get_stats()
    return {**stats, "source": "live"}
