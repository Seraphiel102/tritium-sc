# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Addon management API — discover, enable, disable, list addons."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/addons", tags=["addons"])


@router.get("/")
async def list_addons(request: Request):
    """List all discovered addons with their status."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"addons": [], "error": "Addon loader not initialized"}
    return {"addons": loader.get_all_addons()}


@router.get("/manifests")
async def get_manifests(request: Request):
    """Get frontend manifest data for all enabled addons.

    The frontend uses this to dynamically load addon panels and layers.
    """
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return []
    return loader.get_manifests()


@router.get("/health")
async def addon_health(request: Request):
    """Addon system health summary."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    return loader.get_health()


@router.post("/{addon_id}/enable")
async def enable_addon(addon_id: str, request: Request):
    """Enable a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    ok = await loader.enable(addon_id)
    return {"addon_id": addon_id, "enabled": ok}


@router.post("/{addon_id}/disable")
async def disable_addon(addon_id: str, request: Request):
    """Disable a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    ok = await loader.disable(addon_id)
    return {"addon_id": addon_id, "disabled": ok}


@router.get("/{addon_id}/health")
async def addon_specific_health(addon_id: str, request: Request):
    """Health check for a specific addon."""
    loader = getattr(request.app.state, "addon_loader", None)
    if not loader:
        return {"error": "Addon loader not initialized"}
    entry = loader.registry.get(addon_id)
    if not entry:
        return {"error": f"Unknown addon: {addon_id}"}
    if not entry.instance:
        return {"status": "not_enabled", "addon_id": addon_id}
    return entry.instance.health_check()
