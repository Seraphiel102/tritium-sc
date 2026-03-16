# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""API documentation endpoint — auto-discovers all routes from FastAPI's OpenAPI schema.

GET /api/docs returns a JSON catalog of every registered API endpoint with
method, path, description, tags, and parameter schemas.  Useful for
integration, tooling, and agent introspection without relying on Swagger UI.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("")
async def api_catalog(request: Request):
    """Return a JSON catalog of all API endpoints.

    Auto-discovered from FastAPI's OpenAPI schema.  Each entry includes:
    - method: HTTP method (GET, POST, etc.)
    - path: URL path pattern
    - summary: Short description
    - description: Full description (if any)
    - tags: Route tags
    - parameters: Query/path parameter schemas
    - request_body: Request body schema (if any)
    """
    app = request.app
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    endpoints = []

    for path, methods in sorted(paths.items()):
        for method, spec in sorted(methods.items()):
            if method in ("options", "head"):
                continue

            entry = {
                "method": method.upper(),
                "path": path,
                "summary": spec.get("summary", ""),
                "description": spec.get("description", ""),
                "tags": spec.get("tags", []),
                "operation_id": spec.get("operationId", ""),
            }

            # Extract parameters
            params = spec.get("parameters", [])
            if params:
                entry["parameters"] = [
                    {
                        "name": p.get("name", ""),
                        "in": p.get("in", ""),
                        "required": p.get("required", False),
                        "schema": p.get("schema", {}),
                    }
                    for p in params
                ]

            # Extract request body
            body = spec.get("requestBody")
            if body:
                content = body.get("content", {})
                json_body = content.get("application/json", {})
                if json_body:
                    entry["request_body"] = json_body.get("schema", {})

            endpoints.append(entry)

    return {
        "title": openapi.get("info", {}).get("title", ""),
        "version": openapi.get("info", {}).get("version", ""),
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


@router.get("/summary")
async def api_summary(request: Request):
    """Return a compact summary: just method + path + summary for each endpoint."""
    app = request.app
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    endpoints = []

    for path, methods in sorted(paths.items()):
        for method, spec in sorted(methods.items()):
            if method in ("options", "head"):
                continue
            endpoints.append({
                "method": method.upper(),
                "path": path,
                "summary": spec.get("summary", ""),
                "tags": spec.get("tags", []),
            })

    return {
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
    }


@router.get("/tags")
async def api_tags(request: Request):
    """Return endpoints grouped by tag."""
    app = request.app
    openapi = app.openapi()
    paths = openapi.get("paths", {})
    by_tag: dict[str, list[dict]] = {}

    for path, methods in sorted(paths.items()):
        for method, spec in sorted(methods.items()):
            if method in ("options", "head"):
                continue
            tags = spec.get("tags", ["untagged"])
            for tag in tags:
                by_tag.setdefault(tag, []).append({
                    "method": method.upper(),
                    "path": path,
                    "summary": spec.get("summary", ""),
                })

    return {
        "tag_count": len(by_tag),
        "tags": {
            tag: {"count": len(eps), "endpoints": eps}
            for tag, eps in sorted(by_tag.items())
        },
    }
