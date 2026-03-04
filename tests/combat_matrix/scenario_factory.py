# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Converts BattleConfig into scenario JSON files for the game router."""

from __future__ import annotations

import json
import math
from pathlib import Path

from tests.combat_matrix.config_matrix import BattleConfig, LOADOUT_PROFILES

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios" / "battle"


def build_scenario_dict(config: BattleConfig) -> dict:
    """Build a BattleScenario-compatible dict from a BattleConfig."""
    profile = LOADOUT_PROFILES[config.loadout_profile]

    # Place defenders in ring pattern (replicating scenario.spread_defenders logic)
    defenders = []
    count = config.defender_count
    if count == 1:
        defenders.append({
            "asset_type": config.defender_types[0],
            "position": [0.0, 0.0],
            "name": "Defender-1",
        })
    elif count > 1:
        inner_count = min(count, 4)
        inner_radius = config.map_bounds * 0.30
        for i in range(inner_count):
            angle = (2 * math.pi * i) / inner_count
            x = round(inner_radius * math.cos(angle), 1)
            y = round(inner_radius * math.sin(angle), 1)
            defenders.append({
                "asset_type": config.defender_types[i],
                "position": [x, y],
                "name": f"Defender-{i + 1}",
            })
        remaining = count - inner_count
        if remaining > 0:
            outer_radius = config.map_bounds * 0.60
            for i in range(remaining):
                angle = (2 * math.pi * i) / remaining + math.pi / remaining
                x = round(outer_radius * math.cos(angle), 1)
                y = round(outer_radius * math.sin(angle), 1)
                idx = inner_count + i
                defenders.append({
                    "asset_type": config.defender_types[idx],
                    "position": [x, y],
                    "name": f"Defender-{idx + 1}",
                })

    # Single wave with all hostiles
    spawn_group: dict = {
        "asset_type": config.hostile_type,
        "count": config.hostile_count,
        "speed": 1.5,
        "health": 80.0,
    }
    # Apply weapon overrides from loadout profile
    for key in ("weapon_damage", "weapon_range", "weapon_cooldown", "ammo_count", "ammo_max"):
        if key in config.weapon_overrides:
            spawn_group[key] = config.weapon_overrides[key]

    return {
        "scenario_id": config.config_id,
        "name": f"Matrix: {config.config_id}",
        "description": (
            f"{config.defender_count}v{config.hostile_count} "
            f"loadout={config.loadout_profile} "
            f"bounds={config.map_bounds}m"
        ),
        "map_bounds": config.map_bounds,
        "max_hostiles": max(config.hostile_count + 10, 200),
        "waves": [
            {
                "name": f"Wave 1 ({profile.name})",
                "groups": [spawn_group],
                "speed_mult": 1.0,
                "health_mult": 1.0,
            }
        ],
        "defenders": defenders,
    }


def write_scenario(config: BattleConfig) -> Path:
    """Write scenario JSON and return the file path."""
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    data = build_scenario_dict(config)
    path = SCENARIOS_DIR / f"_matrix_{config.config_id}.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def cleanup() -> None:
    """Remove all _matrix_* scenario files."""
    if not SCENARIOS_DIR.is_dir():
        return
    for f in SCENARIOS_DIR.glob("_matrix_*.json"):
        f.unlink()
