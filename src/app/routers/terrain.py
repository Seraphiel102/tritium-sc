# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Terrain analysis and RF coverage API endpoints.

Provides elevation profiles, line-of-sight checks, RF propagation
estimates, and sensor coverage analysis for placement optimization.

Endpoints:
    POST /api/terrain/propagation  — estimate RF signal at distance
    POST /api/terrain/coverage     — compute coverage grid for a sensor
    POST /api/terrain/los          — line-of-sight check between two points
    GET  /api/terrain/types        — list terrain types
"""

import math
from threading import Lock

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


# --- Request/Response models ---


class PropagationRequest(BaseModel):
    """Request to estimate RF signal propagation."""

    tx_power_dbm: float = 0.0
    distance_m: float = 100.0
    frequency_mhz: float = 2400.0
    terrain_type: str = "suburban"
    sensor_height_m: float = 2.0


class PropagationResponse(BaseModel):
    """RF propagation estimate result."""

    distance_m: float
    frequency_mhz: float
    terrain_type: str
    free_space_loss_db: float
    terrain_loss_db: float
    estimated_rssi_dbm: float
    coverage_quality: str  # excellent, good, fair, poor, none


class CoverageRequest(BaseModel):
    """Request to compute sensor coverage analysis."""

    sensor_lat: float
    sensor_lng: float
    sensor_height_m: float = 2.0
    tx_power_dbm: float = 0.0
    frequency_mhz: float = 2400.0
    range_m: float = 100.0
    terrain_type: str = "suburban"
    grid_resolution_m: float = 10.0
    sensitivity_dbm: float = -90.0  # minimum detectable signal


class LOSRequest(BaseModel):
    """Line-of-sight check request."""

    start_lat: float
    start_lng: float
    start_height_m: float = 2.0
    end_lat: float
    end_lng: float
    end_height_m: float = 2.0


# --- Helpers ---

_TERRAIN_MAP = {
    "urban": "urban",
    "suburban": "suburban",
    "rural": "rural",
    "forest": "forest",
    "water": "water",
    "desert": "desert",
    "mountain": "mountain",
    "indoor": "indoor",
    "unknown": "unknown",
}

# Terrain loss factors (dB per decade of distance at 2.4 GHz)
_TERRAIN_FACTORS = {
    "urban": 30.0,
    "suburban": 20.0,
    "rural": 10.0,
    "forest": 25.0,
    "water": 5.0,
    "desert": 8.0,
    "mountain": 15.0,
    "indoor": 35.0,
    "unknown": 20.0,
}


def _fspl(distance_m: float, frequency_mhz: float) -> float:
    """Free-space path loss in dB."""
    if distance_m <= 0 or frequency_mhz <= 0:
        return 0.0
    freq_hz = frequency_mhz * 1e6
    c = 299792458.0
    return (
        20 * math.log10(distance_m)
        + 20 * math.log10(freq_hz)
        + 20 * math.log10(4 * math.pi / c)
    )


def _terrain_loss(distance_m: float, frequency_mhz: float, terrain: str) -> float:
    """Total path loss including terrain effects."""
    fspl = _fspl(distance_m, frequency_mhz)
    extra = _TERRAIN_FACTORS.get(terrain, 20.0)
    if distance_m > 1:
        extra *= math.log2(max(distance_m, 2)) / 10.0
    return fspl + extra


def _quality_label(rssi_dbm: float) -> str:
    """Map RSSI to a human-readable quality label."""
    if rssi_dbm >= -50:
        return "excellent"
    elif rssi_dbm >= -70:
        return "good"
    elif rssi_dbm >= -85:
        return "fair"
    elif rssi_dbm >= -100:
        return "poor"
    return "none"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# --- Endpoints ---


@router.post("/propagation", response_model=PropagationResponse)
async def estimate_propagation(request: PropagationRequest):
    """Estimate RF signal strength at a given distance and terrain."""
    terrain = _TERRAIN_MAP.get(request.terrain_type, "unknown")
    fspl = _fspl(request.distance_m, request.frequency_mhz)
    total_loss = _terrain_loss(request.distance_m, request.frequency_mhz, terrain)
    rssi = request.tx_power_dbm - total_loss

    return PropagationResponse(
        distance_m=request.distance_m,
        frequency_mhz=request.frequency_mhz,
        terrain_type=terrain,
        free_space_loss_db=round(fspl, 2),
        terrain_loss_db=round(total_loss, 2),
        estimated_rssi_dbm=round(rssi, 2),
        coverage_quality=_quality_label(rssi),
    )


@router.post("/coverage")
async def compute_coverage(request: CoverageRequest):
    """Compute coverage grid for a sensor placement.

    Returns a grid of cells with signal strength estimates.
    Limited to 10,000 cells max to prevent DoS.
    """
    terrain = _TERRAIN_MAP.get(request.terrain_type, "unknown")
    resolution = max(request.grid_resolution_m, 5.0)  # minimum 5m resolution
    max_cells = 10000

    # Generate grid
    cells = []
    covered_count = 0

    # Convert range to lat/lng steps
    meters_per_deg_lat = 111320
    meters_per_deg_lng = meters_per_deg_lat * math.cos(math.radians(request.sensor_lat))

    step_lat = resolution / meters_per_deg_lat
    step_lng = resolution / max(meters_per_deg_lng, 1)

    half_range_lat = request.range_m / meters_per_deg_lat
    half_range_lng = request.range_m / max(meters_per_deg_lng, 1)

    lat = request.sensor_lat - half_range_lat
    while lat <= request.sensor_lat + half_range_lat and len(cells) < max_cells:
        lng = request.sensor_lng - half_range_lng
        while lng <= request.sensor_lng + half_range_lng and len(cells) < max_cells:
            dist = _haversine_m(request.sensor_lat, request.sensor_lng, lat, lng)
            if dist <= request.range_m and dist > 0:
                loss = _terrain_loss(dist, request.frequency_mhz, terrain)
                rssi = request.tx_power_dbm - loss
                covered = rssi >= request.sensitivity_dbm
                if covered:
                    covered_count += 1
                cells.append({
                    "latitude": round(lat, 7),
                    "longitude": round(lng, 7),
                    "signal_strength_dbm": round(rssi, 1),
                    "covered": covered,
                    "distance_m": round(dist, 1),
                })
            lng += step_lng
        lat += step_lat

    total = len(cells) if cells else 1
    return {
        "sensor_lat": request.sensor_lat,
        "sensor_lng": request.sensor_lng,
        "terrain_type": terrain,
        "range_m": request.range_m,
        "grid_resolution_m": resolution,
        "total_cells": len(cells),
        "covered_cells": covered_count,
        "coverage_percent": round(100 * covered_count / total, 1),
        "cells": cells,
    }


@router.post("/los")
async def check_line_of_sight(request: LOSRequest):
    """Check line-of-sight between two points.

    Simplified flat-earth model (no elevation data).
    Returns distance and estimated LOS status.
    """
    distance = _haversine_m(
        request.start_lat, request.start_lng,
        request.end_lat, request.end_lng,
    )

    # Without real elevation data, assume LOS is clear for short distances
    # and questionable for longer ones
    los_clear = distance < 500  # simple heuristic

    return {
        "distance_m": round(distance, 1),
        "has_line_of_sight": los_clear,
        "note": "Simplified model — no elevation data loaded" if not los_clear else "Clear LOS (flat terrain assumed)",
        "start": {"lat": request.start_lat, "lng": request.start_lng, "height_m": request.start_height_m},
        "end": {"lat": request.end_lat, "lng": request.end_lng, "height_m": request.end_height_m},
    }


@router.get("/types")
async def get_terrain_types():
    """List available terrain types with their RF characteristics."""
    return [
        {
            "type": t,
            "loss_factor_db": f,
            "description": {
                "urban": "Dense buildings, high multipath",
                "suburban": "Mixed residential/commercial",
                "rural": "Open fields, few obstructions",
                "forest": "Tree canopy, foliage absorption",
                "water": "Open water, minimal obstruction",
                "desert": "Flat, dry, minimal vegetation",
                "mountain": "Elevation changes, rock reflections",
                "indoor": "Walls, floors, furniture",
                "unknown": "Default propagation model",
            }.get(t, ""),
        }
        for t, f in _TERRAIN_FACTORS.items()
    ]
