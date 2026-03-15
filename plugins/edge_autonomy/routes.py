# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Edge Autonomy plugin."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_auth

if TYPE_CHECKING:
    from .plugin import EdgeAutonomyPlugin


class DecisionSubmitRequest(BaseModel):
    device_id: str = ""
    decision_type: str = "alert"
    trigger: str = "unknown_ble"
    confidence: float = 0.5
    action_taken: str = ""
    description: str = ""
    target_id: str = ""
    trigger_data: dict = Field(default_factory=dict)
    threshold_value: float = 0.0
    measured_value: float = 0.0


class OverrideRequest(BaseModel):
    reason: str = ""
    by: str = ""
    corrective_action: str = ""


def create_router(plugin: EdgeAutonomyPlugin) -> APIRouter:
    """Build edge autonomy API router."""
    router = APIRouter(prefix="/api/edge-autonomy", tags=["edge-autonomy"])

    @router.get("/decisions")
    async def list_decisions(
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ):
        decisions = plugin.list_decisions(device_id, status, limit)
        return {"decisions": decisions, "count": len(decisions)}

    @router.get("/decisions/{decision_id}")
    async def get_decision(decision_id: str):
        decisions = plugin.list_decisions()
        decision = next((d for d in decisions if d.get("decision_id") == decision_id), None)
        if decision is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return {"decision": decision}

    @router.post("/decisions", status_code=201)
    async def submit_decision(req: DecisionSubmitRequest, user: dict = Depends(require_auth)):
        """Submit an autonomous decision (typically from edge MQTT)."""
        decision = plugin.receive_decision(req.model_dump())
        return {"decision": decision}

    @router.post("/decisions/{decision_id}/confirm")
    async def confirm_decision(decision_id: str, req: OverrideRequest, user: dict = Depends(require_auth)):
        result = plugin.confirm_decision(decision_id, req.reason, req.by)
        if result is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return {"decision": result}

    @router.post("/decisions/{decision_id}/override")
    async def override_decision(decision_id: str, req: OverrideRequest, user: dict = Depends(require_auth)):
        result = plugin.override_decision(
            decision_id, req.reason, req.by, req.corrective_action,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Decision not found")
        return {"decision": result}

    @router.get("/stats")
    async def get_stats():
        return plugin.get_stats()

    @router.get("/devices/{device_id}/accuracy")
    async def get_device_accuracy(device_id: str):
        stats = plugin.get_stats()
        device_stats = stats.get("device_stats", {}).get(device_id)
        if device_stats is None:
            raise HTTPException(status_code=404, detail="No data for device")
        return {"device_id": device_id, **device_stats}

    return router
