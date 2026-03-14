# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mission management API — CRUD for coordinated multi-asset operations.

Endpoints:
    GET    /api/missions              — list missions (filter by status/type)
    POST   /api/missions              — create a mission
    GET    /api/missions/{id}         — get mission details
    PUT    /api/missions/{id}         — update a mission
    DELETE /api/missions/{id}         — delete a mission
    POST   /api/missions/{id}/start   — transition to active
    POST   /api/missions/{id}/pause   — pause an active mission
    POST   /api/missions/{id}/complete — mark completed
    POST   /api/missions/{id}/abort   — abort the mission
    POST   /api/missions/{id}/objectives/{oid}/complete — complete an objective
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from tritium_lib.models.mission import (
    GeofenceZone,
    Mission,
    MissionObjective,
    MissionStatus,
    MissionType,
)

router = APIRouter(prefix="/api/missions", tags=["missions"])

# In-memory store — keyed by mission_id
_missions: dict[str, Mission] = {}


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class ObjectiveRequest(BaseModel):
    description: str = ""
    priority: int = 1


class GeofenceZoneRequest(BaseModel):
    name: str = ""
    vertices: list[list[float]] = []  # [[lat, lng], ...]
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_m: Optional[float] = None


class CreateMissionRequest(BaseModel):
    title: str
    type: str = "custom"
    description: str = ""
    assigned_assets: list[str] = []
    objectives: list[ObjectiveRequest] = []
    geofence_zone: Optional[GeofenceZoneRequest] = None
    priority: int = 3
    tags: list[str] = []
    created_by: str = ""


class UpdateMissionRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_assets: Optional[list[str]] = None
    objectives: Optional[list[ObjectiveRequest]] = None
    geofence_zone: Optional[GeofenceZoneRequest] = None
    priority: Optional[int] = None
    tags: Optional[list[str]] = None


class AbortRequest(BaseModel):
    reason: str = ""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _validate_type(type_str: str) -> MissionType:
    try:
        return MissionType(type_str)
    except ValueError:
        valid = [t.value for t in MissionType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mission type '{type_str}'. Valid: {valid}",
        )


def _build_geofence(gz: GeofenceZoneRequest) -> GeofenceZone:
    return GeofenceZone(
        zone_id=uuid.uuid4().hex[:12],
        name=gz.name,
        vertices=[tuple(v) for v in gz.vertices],
        center_lat=gz.center_lat,
        center_lng=gz.center_lng,
        radius_m=gz.radius_m,
    )


def _get_mission(mission_id: str) -> Mission:
    m = _missions.get(mission_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mission not found")
    return m


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
async def list_missions(
    status: Optional[str] = Query(None),
    mission_type: Optional[str] = Query(None, alias="type"),
    limit: int = Query(100, le=500),
):
    """List missions, newest first."""
    missions = sorted(_missions.values(), key=lambda m: m.created, reverse=True)

    if status:
        try:
            s = MissionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")
        missions = [m for m in missions if m.status == s]

    if mission_type:
        t = _validate_type(mission_type)
        missions = [m for m in missions if m.type == t]

    return [m.to_dict() for m in missions[:limit]]


@router.post("", status_code=201)
async def create_mission(request: CreateMissionRequest):
    """Create a new mission."""
    mt = _validate_type(request.type)

    objectives = [
        MissionObjective(description=o.description, priority=o.priority)
        for o in request.objectives
    ]

    gz = _build_geofence(request.geofence_zone) if request.geofence_zone else None

    mission = Mission(
        title=request.title,
        type=mt,
        description=request.description,
        assigned_assets=request.assigned_assets,
        objectives=objectives,
        geofence_zone=gz,
        priority=request.priority,
        tags=request.tags,
        created_by=request.created_by,
    )

    _missions[mission.mission_id] = mission
    return mission.to_dict()


@router.get("/{mission_id}")
async def get_mission(mission_id: str):
    """Get mission details."""
    return _get_mission(mission_id).to_dict()


@router.put("/{mission_id}")
async def update_mission(mission_id: str, request: UpdateMissionRequest):
    """Update mission fields (only modifiable in non-terminal states)."""
    m = _get_mission(mission_id)
    if m.is_terminal:
        raise HTTPException(status_code=409, detail="Cannot modify a terminal mission")

    if request.title is not None:
        m.title = request.title
    if request.description is not None:
        m.description = request.description
    if request.assigned_assets is not None:
        m.assigned_assets = request.assigned_assets
    if request.objectives is not None:
        m.objectives = [
            MissionObjective(description=o.description, priority=o.priority)
            for o in request.objectives
        ]
    if request.geofence_zone is not None:
        m.geofence_zone = _build_geofence(request.geofence_zone)
    if request.priority is not None:
        m.priority = request.priority
    if request.tags is not None:
        m.tags = request.tags

    return m.to_dict()


@router.delete("/{mission_id}")
async def delete_mission(mission_id: str):
    """Delete a mission."""
    if mission_id not in _missions:
        raise HTTPException(status_code=404, detail="Mission not found")
    del _missions[mission_id]
    return {"status": "deleted", "mission_id": mission_id}


@router.post("/{mission_id}/start")
async def start_mission(mission_id: str):
    """Transition mission to active status."""
    m = _get_mission(mission_id)
    if m.status not in (MissionStatus.DRAFT, MissionStatus.PLANNED, MissionStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start mission in status '{m.status.value}'",
        )
    m.start()
    return m.to_dict()


@router.post("/{mission_id}/pause")
async def pause_mission(mission_id: str):
    """Pause an active mission."""
    m = _get_mission(mission_id)
    if m.status != MissionStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Can only pause active missions")
    m.pause()
    return m.to_dict()


@router.post("/{mission_id}/complete")
async def complete_mission(mission_id: str):
    """Mark mission as completed."""
    m = _get_mission(mission_id)
    if m.status not in (MissionStatus.ACTIVE, MissionStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot complete mission in status '{m.status.value}'",
        )
    m.complete()
    return m.to_dict()


@router.post("/{mission_id}/abort")
async def abort_mission(mission_id: str, request: AbortRequest):
    """Abort a mission."""
    m = _get_mission(mission_id)
    if m.is_terminal:
        raise HTTPException(status_code=409, detail="Mission is already in a terminal state")
    m.abort(request.reason)
    return m.to_dict()


@router.post("/{mission_id}/objectives/{objective_id}/complete")
async def complete_objective(mission_id: str, objective_id: str):
    """Mark a specific objective as completed."""
    m = _get_mission(mission_id)
    if not m.complete_objective(objective_id):
        raise HTTPException(status_code=404, detail="Objective not found")
    return m.to_dict()
