# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Ollama LLM status for system health dashboard.

Checks if Ollama is running, which models are loaded, and reports
GPU utilization where available. Integrated into the system health
panel alongside MQTT and Meshtastic status.

Endpoints:
    GET /api/health/ollama — Ollama service health and model inventory
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


def _check_ollama_local() -> dict:
    """Probe the local Ollama instance for health and model info."""
    import urllib.request
    import json

    result = {
        "status": "unreachable",
        "url": "http://localhost:11434",
        "models": [],
        "model_count": 0,
        "gpu_available": False,
        "error": None,
    }

    # Check if Ollama is responding
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = data.get("models", [])
            result["status"] = "running"
            result["model_count"] = len(models)
            result["models"] = [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                    "family": m.get("details", {}).get("family", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                    "quantization": m.get("details", {}).get("quantization_level", ""),
                }
                for m in models
            ]
    except Exception as e:
        result["error"] = str(e)
        return result

    # Check for running models (loaded into GPU/RAM)
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/ps",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            running = data.get("models", [])
            result["running_models"] = [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "size_vram": m.get("size_vram", 0),
                    "expires_at": m.get("expires_at", ""),
                }
                for m in running
            ]
            result["loaded_count"] = len(running)

            # If any model has VRAM usage, GPU is available
            if any(m.get("size_vram", 0) > 0 for m in running):
                result["gpu_available"] = True
    except Exception:
        result["running_models"] = []
        result["loaded_count"] = 0

    return result


def _check_ollama_fleet() -> dict | None:
    """Check OllamaFleet for multi-host status."""
    try:
        from engine.inference.fleet import OllamaFleet
        fleet = OllamaFleet(auto_discover=False)
        if fleet.count == 0:
            return None

        hosts = []
        for h in fleet.hosts:
            host_info = {
                "name": h.name,
                "url": h.url,
                "reachable": h.reachable,
                "model_count": len(h.models) if hasattr(h, "models") else 0,
            }
            if hasattr(h, "models"):
                host_info["models"] = list(h.models)
            hosts.append(host_info)

        return {
            "host_count": len(hosts),
            "hosts": hosts,
        }
    except Exception:
        return None


@router.get("/ollama")
async def ollama_health():
    """Check Ollama LLM service health.

    Returns:
    - Connection status (running/unreachable)
    - Available models with size and quantization info
    - Currently loaded models (in GPU/RAM)
    - GPU availability
    - OllamaFleet multi-host status (if configured)

    Designed for the system health dashboard panel.
    """
    local = _check_ollama_local()
    fleet = _check_ollama_fleet()

    result = {
        "local": local,
        "overall_status": local["status"],
    }

    if fleet is not None:
        result["fleet"] = fleet

    return result
