# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Amy personality configuration API.

Operators can adjust Amy's personality parameters:
- aggression: how quickly she escalates
- curiosity: how eager to investigate unknowns
- verbosity: how much she narrates
- caution: risk awareness
- initiative: autonomous action willingness

Also supports preset profiles (patrol, battle, stealth, observer).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_role

router = APIRouter(prefix="/api/amy", tags=["amy-personality"])


# Import personality model from tritium-lib (with fallback)
try:
    from tritium_lib.models.personality import (
        CommanderPersonality,
        PRESET_PERSONALITIES,
    )
except ImportError:
    # Inline fallback if tritium-lib not installed yet
    CommanderPersonality = None  # type: ignore[assignment,misc]
    PRESET_PERSONALITIES = {}  # type: ignore[assignment]


class PersonalityUpdateRequest(BaseModel):
    """Request body for PUT /api/amy/personality."""
    aggression: float = Field(0.5, ge=0.0, le=1.0)
    curiosity: float = Field(0.5, ge=0.0, le=1.0)
    verbosity: float = Field(0.5, ge=0.0, le=1.0)
    caution: float = Field(0.5, ge=0.0, le=1.0)
    initiative: float = Field(0.5, ge=0.0, le=1.0)


class PresetRequest(BaseModel):
    """Request body for POST /api/amy/personality/preset."""
    preset: str  # "patrol", "battle", "stealth", "observer", "default"


def _get_amy(request: Request):
    """Get Amy commander from app state."""
    return getattr(request.app.state, "amy", None)


def _get_personality(amy) -> dict:
    """Extract current personality from Amy, or return defaults."""
    personality = getattr(amy, "_personality", None)
    if personality is not None and hasattr(personality, "to_dict"):
        return personality.to_dict()
    # Fallback: read individual attributes
    return {
        "aggression": getattr(amy, "_aggression", 0.5),
        "curiosity": getattr(amy, "_curiosity", 0.5),
        "verbosity": getattr(amy, "_verbosity", 0.5),
        "caution": getattr(amy, "_caution", 0.5),
        "initiative": getattr(amy, "_initiative", 0.5),
    }


def _set_personality(amy, data: dict) -> dict:
    """Apply personality traits to Amy."""
    if CommanderPersonality is not None:
        p = CommanderPersonality.from_dict(data)
        amy._personality = p
        result = p.to_dict()
        result["profile_label"] = p.profile_label
        return result
    else:
        # Manual attribute set
        for key in ("aggression", "curiosity", "verbosity", "caution", "initiative"):
            val = max(0.0, min(1.0, data.get(key, 0.5)))
            setattr(amy, f"_{key}", val)
        return {k: getattr(amy, f"_{k}", 0.5) for k in ("aggression", "curiosity", "verbosity", "caution", "initiative")}


@router.get("/personality")
async def get_personality(request: Request):
    """Get Amy's current personality configuration."""
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    personality = _get_personality(amy)

    # Get profile label
    label = "balanced"
    p = getattr(amy, "_personality", None)
    if p is not None and hasattr(p, "profile_label"):
        label = p.profile_label

    return {
        "personality": personality,
        "profile_label": label,
        "presets": list(PRESET_PERSONALITIES.keys()) if PRESET_PERSONALITIES else ["default", "patrol", "battle", "stealth", "observer"],
    }


@router.put("/personality")
async def update_personality(
    request: Request,
    body: PersonalityUpdateRequest,
    user: dict = Depends(require_role("admin", "commander")),
):
    """Update Amy's personality parameters.

    Requires commander or admin role. Observers/analysts cannot modify
    Amy's behaviour.

    All values are clamped to [0.0, 1.0].
    """
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    result = _set_personality(amy, body.model_dump())

    # Publish event so UI updates
    event_bus = getattr(amy, "event_bus", None)
    if event_bus is not None:
        event_bus.publish("personality_changed", result)

    return {
        "status": "ok",
        "personality": result,
    }


@router.post("/personality/preset")
async def apply_preset(
    request: Request,
    body: PresetRequest,
    user: dict = Depends(require_role("admin", "commander")),
):
    """Apply a preset personality profile.

    Requires commander or admin role. Valid presets: default, patrol,
    battle, stealth, observer.
    """
    amy = _get_amy(request)
    if amy is None:
        return JSONResponse({"error": "Amy is not running"}, status_code=503)

    if PRESET_PERSONALITIES:
        preset = PRESET_PERSONALITIES.get(body.preset)
        if preset is None:
            return JSONResponse(
                {"error": f"Unknown preset '{body.preset}'. Valid: {list(PRESET_PERSONALITIES.keys())}"},
                status_code=400,
            )
        data = preset.to_dict()
    else:
        # Fallback presets if tritium-lib not available
        _fallbacks = {
            "default": {"aggression": 0.5, "curiosity": 0.5, "verbosity": 0.5, "caution": 0.5, "initiative": 0.5},
            "patrol": {"aggression": 0.3, "curiosity": 0.7, "verbosity": 0.5, "caution": 0.6, "initiative": 0.5},
            "battle": {"aggression": 0.8, "curiosity": 0.4, "verbosity": 0.3, "caution": 0.3, "initiative": 0.8},
            "stealth": {"aggression": 0.2, "curiosity": 0.3, "verbosity": 0.1, "caution": 0.8, "initiative": 0.3},
            "observer": {"aggression": 0.1, "curiosity": 0.9, "verbosity": 0.7, "caution": 0.7, "initiative": 0.2},
        }
        data = _fallbacks.get(body.preset)
        if data is None:
            return JSONResponse(
                {"error": f"Unknown preset '{body.preset}'"},
                status_code=400,
            )

    result = _set_personality(amy, data)

    event_bus = getattr(amy, "event_bus", None)
    if event_bus is not None:
        event_bus.publish("personality_changed", {**result, "preset": body.preset})

    return {
        "status": "ok",
        "preset": body.preset,
        "personality": result,
    }
