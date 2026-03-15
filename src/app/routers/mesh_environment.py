# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Mesh environment API — environment sensor data from Meshtastic nodes.

Returns temperature, humidity, and pressure readings from mesh nodes
that have environment sensors (BME280/BMP280/SHT31 etc). Used by
the weather overlay to show real sensor data on the tactical map.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mesh", tags=["mesh"])


@router.get("/environment")
async def mesh_environment(request: Request):
    """GET /api/mesh/environment — environment sensor data from mesh nodes.

    Returns a list of environment readings from Meshtastic nodes that
    have temperature/humidity/pressure sensors attached.

    Response shape:
        {
            "readings": [
                {
                    "node_id": "!ba33ff38",
                    "node_name": "Node Alpha",
                    "temperature_c": 22.5,
                    "temperature_f": 72.5,
                    "humidity_pct": 45.0,
                    "pressure_hpa": 1013.25,
                    "position": {"lat": 40.71, "lng": -74.01},
                    "age_s": 120
                }
            ],
            "count": 1,
            "source": "live"
        }
    """
    bridge = getattr(request.app.state, "meshtastic_bridge", None)
    if bridge is None:
        return {"readings": [], "count": 0, "source": "unavailable"}

    readings = []
    nodes = bridge.nodes

    for node_id, node in nodes.items():
        # Check if this node has any environment data
        # The MeshtasticNode dataclass may have been updated via telemetry
        # For the bridge pattern, env data comes through _on_telemetry
        env_data = getattr(node, "environment", None)
        if env_data is None:
            continue

        temp_c = getattr(env_data, "temperature", None) if env_data else None
        humidity = getattr(env_data, "relative_humidity", None) if env_data else None
        pressure = getattr(env_data, "barometric_pressure", None) if env_data else None

        # Skip nodes with no environment data
        if temp_c is None and humidity is None and pressure is None:
            continue

        temp_f = (temp_c * 9.0 / 5.0 + 32.0) if temp_c is not None else None

        pos = getattr(node, "position", None)
        lat = pos.get("lat") if isinstance(pos, dict) else None
        lng = pos.get("lng") if isinstance(pos, dict) else None

        import time
        last_heard = getattr(node, "last_heard", None)
        age_s = int(time.monotonic() - last_heard) if last_heard is not None else None

        readings.append({
            "node_id": node_id,
            "node_name": getattr(node, "long_name", "") or getattr(node, "short_name", "") or node_id,
            "temperature_c": round(temp_c, 1) if temp_c is not None else None,
            "temperature_f": round(temp_f, 1) if temp_f is not None else None,
            "humidity_pct": round(humidity, 1) if humidity is not None else None,
            "pressure_hpa": round(pressure, 1) if pressure is not None else None,
            "position": {"lat": lat, "lng": lng} if lat is not None and lng is not None else None,
            "age_s": age_s,
        })

    return {
        "readings": readings,
        "count": len(readings),
        "source": "live",
    }
