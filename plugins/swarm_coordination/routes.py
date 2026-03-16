# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Swarm Coordination plugin."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth import require_auth

if TYPE_CHECKING:
    from .plugin import SwarmCoordinationPlugin


class SwarmCreateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    formation: str = Field(default="line", max_length=50)
    spacing: float = Field(default=5.0, ge=0.1, le=1000.0)


class MemberAddRequest(BaseModel):
    member_id: str = ""
    device_id: str = ""
    asset_type: str = "rover"
    role: str = "support"


class SwarmCommandRequest(BaseModel):
    command: str = Field(default="hold", max_length=50)
    waypoints: Optional[list[list[float]]] = Field(default=None, max_length=500)
    formation: Optional[str] = Field(default=None, max_length=50)
    spacing: Optional[float] = Field(default=None, ge=0.1, le=1000.0)
    max_speed: Optional[float] = Field(default=None, ge=0.0, le=100.0)


def create_router(plugin: SwarmCoordinationPlugin) -> APIRouter:
    """Build swarm coordination API router."""
    router = APIRouter(prefix="/api/swarm", tags=["swarm"])

    @router.get("/swarms")
    async def list_swarms():
        return {"swarms": plugin.list_swarms(), "count": len(plugin.list_swarms())}

    @router.post("/swarms", status_code=201)
    async def create_swarm(req: SwarmCreateRequest, user: dict = Depends(require_auth)):
        swarm = plugin.create_swarm(req.name, req.formation, req.spacing)
        return {"swarm": swarm.to_dict()}

    @router.get("/swarms/{swarm_id}")
    async def get_swarm(swarm_id: str):
        swarm = plugin.get_swarm(swarm_id)
        if swarm is None:
            raise HTTPException(status_code=404, detail="Swarm not found")
        return {"swarm": swarm.to_dict()}

    @router.delete("/swarms/{swarm_id}")
    async def delete_swarm(swarm_id: str, user: dict = Depends(require_auth)):
        if not plugin.delete_swarm(swarm_id):
            raise HTTPException(status_code=404, detail="Swarm not found")
        return {"deleted": True, "swarm_id": swarm_id}

    @router.post("/swarms/{swarm_id}/members", status_code=201)
    async def add_member(swarm_id: str, req: MemberAddRequest, user: dict = Depends(require_auth)):
        swarm = plugin.get_swarm(swarm_id)
        if swarm is None:
            raise HTTPException(status_code=404, detail="Swarm not found")
        import uuid
        mid = req.member_id or str(uuid.uuid4())[:8]
        member = swarm.add_member(mid, req.device_id, req.asset_type, req.role)
        return {"member": member}

    @router.delete("/swarms/{swarm_id}/members/{member_id}")
    async def remove_member(swarm_id: str, member_id: str, user: dict = Depends(require_auth)):
        swarm = plugin.get_swarm(swarm_id)
        if swarm is None:
            raise HTTPException(status_code=404, detail="Swarm not found")
        if not swarm.remove_member(member_id):
            raise HTTPException(status_code=404, detail="Member not found")
        return {"removed": True, "member_id": member_id}

    @router.post("/swarms/{swarm_id}/command")
    async def issue_command(swarm_id: str, req: SwarmCommandRequest, user: dict = Depends(require_auth)):
        result = plugin.issue_command(
            swarm_id, req.command,
            waypoints=req.waypoints,
            formation=req.formation,
            spacing=req.spacing,
            max_speed=req.max_speed,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Swarm not found")
        return {"swarm": result}

    @router.get("/swarms/{swarm_id}/formation")
    async def get_formation(swarm_id: str):
        swarm = plugin.get_swarm(swarm_id)
        if swarm is None:
            raise HTTPException(status_code=404, detail="Swarm not found")
        offsets = swarm.compute_formation_offsets()
        return {
            "swarm_id": swarm_id,
            "formation_type": swarm.formation_type,
            "center": [swarm.center_x, swarm.center_y],
            "heading": swarm.heading,
            "spacing": swarm.spacing,
            "offsets": {k: list(v) for k, v in offsets.items()},
        }

    @router.get("/stats")
    async def get_stats():
        return plugin.get_stats()

    return router
