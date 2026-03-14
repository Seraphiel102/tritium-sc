# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Plugin management API.

Lists installed plugins, their status, capabilities, and health.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _get_manager(request: Request):
    """Get plugin manager from app state, or None."""
    try:
        return request.app.state.plugin_manager
    except (AttributeError, KeyError):
        return None


@router.get("")
async def list_plugins(request: Request):
    """List all registered plugins with status."""
    mgr = _get_manager(request)
    if mgr is None:
        return []
    return mgr.list_plugins()


@router.get("/health")
async def plugin_health(request: Request):
    """Health check for all running plugins."""
    mgr = _get_manager(request)
    if mgr is None:
        return {}
    return mgr.health_check()


@router.get("/dependencies")
async def plugin_dependencies(request: Request):
    """Plugin dependency graph — which plugins depend on which services.

    Returns nodes (plugins and services) and edges (dependency/provides
    relationships) for visualization in the system health panel.
    """
    mgr = _get_manager(request)
    if mgr is None:
        return {"nodes": [], "edges": []}

    plugins = mgr.list_plugins()
    nodes = []
    edges = []
    service_set = set()

    for p in plugins:
        pid = p["id"]
        nodes.append({
            "id": pid,
            "name": p["name"],
            "type": "plugin",
            "healthy": p["healthy"],
            "status": p["status"],
        })

        # Dependencies
        for dep in p.get("dependencies", []):
            edges.append({"from": pid, "to": dep, "type": "depends"})
            service_set.add(dep)

        # Capabilities (services provided)
        for cap in p.get("capabilities", []):
            edges.append({"from": pid, "to": cap, "type": "provides"})
            service_set.add(cap)

    # Add service nodes that aren't also plugins
    plugin_ids = {p["id"] for p in plugins}
    for svc in service_set:
        if svc not in plugin_ids:
            nodes.append({
                "id": svc,
                "name": svc,
                "type": "service",
                "healthy": True,
                "status": "available",
            })

    return {"nodes": nodes, "edges": edges}


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str, request: Request):
    """Get details for a specific plugin."""
    mgr = _get_manager(request)
    if mgr is None:
        return JSONResponse(status_code=404, content={"detail": "No plugin manager"})

    plugin = mgr.get_plugin(plugin_id)
    if plugin is None:
        return JSONResponse(status_code=404, content={"detail": f"Plugin '{plugin_id}' not found"})

    return {
        "id": plugin.plugin_id,
        "name": plugin.name,
        "version": plugin.version,
        "capabilities": sorted(plugin.capabilities),
        "dependencies": list(plugin.dependencies),
        "healthy": plugin.healthy,
    }
