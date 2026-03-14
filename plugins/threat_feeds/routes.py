# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Threat Feeds plugin.

Provides REST endpoints for listing, adding, removing, importing, and
checking threat indicators.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from .feeds import ThreatFeedManager, ThreatIndicator, INDICATOR_TYPES


# -- Request / response models ------------------------------------------------

class AddIndicatorRequest(BaseModel):
    indicator_type: str
    value: str
    threat_level: str = "suspicious"
    source: str = "manual"
    description: str = ""


class CheckRequest(BaseModel):
    indicator_type: str
    value: str


class ImportRequest(BaseModel):
    content: str
    format: str = "json"  # json or csv


# -- Router factory ------------------------------------------------------------

def create_router(manager: ThreatFeedManager) -> APIRouter:
    """Build and return the threat-feeds APIRouter."""

    router = APIRouter(prefix="/api/threats", tags=["threat-feeds"])

    # -- List all indicators ---------------------------------------------------

    @router.get("/")
    async def list_indicators(indicator_type: Optional[str] = None):
        """List all threat indicators, optionally filtered by type."""
        if indicator_type and indicator_type not in INDICATOR_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid indicator_type. Must be one of: {INDICATOR_TYPES}",
            )
        indicators = manager.get_all(indicator_type=indicator_type)
        return {
            "indicators": [i.to_dict() for i in indicators],
            "count": len(indicators),
        }

    # -- Add indicator ---------------------------------------------------------

    @router.post("/")
    async def add_indicator(body: AddIndicatorRequest):
        """Add a single threat indicator."""
        if body.indicator_type not in INDICATOR_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid indicator_type. Must be one of: {INDICATOR_TYPES}",
            )
        ind = ThreatIndicator(
            indicator_type=body.indicator_type,
            value=body.value,
            threat_level=body.threat_level,
            source=body.source,
            description=body.description,
        )
        result = manager.add_indicator(ind)
        return {"indicator": result.to_dict(), "added": True}

    # -- Remove indicator ------------------------------------------------------

    @router.delete("/{indicator_type}/{value:path}")
    async def remove_indicator(indicator_type: str, value: str):
        """Remove a threat indicator by type and value."""
        removed = manager.remove_indicator(indicator_type, value)
        if not removed:
            raise HTTPException(status_code=404, detail="Indicator not found")
        return {"removed": True, "indicator_type": indicator_type, "value": value}

    # -- Check a value ---------------------------------------------------------

    @router.post("/check")
    async def check_indicator(body: CheckRequest):
        """Check a value against threat feeds."""
        if body.indicator_type not in INDICATOR_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid indicator_type. Must be one of: {INDICATOR_TYPES}",
            )
        match = manager.check(body.indicator_type, body.value)
        if match is not None:
            return {"match": True, "indicator": match.to_dict()}
        return {"match": False, "indicator": None}

    # -- Import from content ---------------------------------------------------

    @router.post("/import")
    async def import_indicators(body: ImportRequest):
        """Import indicators from JSON or CSV content string."""
        try:
            count = manager.load_indicators_from_content(
                body.content, format=body.format
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Import failed: {exc}",
            )
        return {"imported": count, "total": manager.count}

    # -- Stats -----------------------------------------------------------------

    @router.get("/stats")
    async def threat_stats():
        """Summary statistics about loaded threat indicators."""
        all_indicators = manager.get_all()
        by_type: dict[str, int] = {}
        by_level: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for ind in all_indicators:
            by_type[ind.indicator_type] = by_type.get(ind.indicator_type, 0) + 1
            by_level[ind.threat_level] = by_level.get(ind.threat_level, 0) + 1
            by_source[ind.source] = by_source.get(ind.source, 0) + 1
        return {
            "total": len(all_indicators),
            "by_type": by_type,
            "by_level": by_level,
            "by_source": by_source,
        }

    return router
