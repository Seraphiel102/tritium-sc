# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""BattleScenario — data model for city-scale combat scenarios.

This is SEPARATE from ``engine.scenarios.schema.Scenario`` which defines
Amy's behavioral testing scenarios.  BattleScenario is purely about combat
simulation: wave definitions with mixed hostile types, pre-placed defenders,
and map bounds.

Usage:
    scenario = load_battle_scenario("tests/scenarios/battle/street_combat.json")
    engine.game_mode.load_scenario(scenario)
    engine.game_mode.begin_war()
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpawnGroup:
    """A group of same-type hostiles within a wave."""

    asset_type: str  # "person", "hostile_vehicle", "hostile_leader"
    count: int
    speed: float = 1.5
    health: float = 80.0
    drone_variant: str | None = None  # "scout_swarm", "attack_swarm", "bomber_swarm"

    # Optional combat overrides (applied AFTER apply_combat_profile defaults)
    max_health: float | None = None
    weapon_range: float | None = None
    weapon_cooldown: float | None = None
    weapon_damage: float | None = None
    ammo_count: int | None = None
    ammo_max: int | None = None


@dataclass
class WaveDefinition:
    """Defines a single wave: one or more spawn groups + multipliers."""

    name: str
    groups: list[SpawnGroup]
    speed_mult: float = 1.0
    health_mult: float = 1.0
    briefing: str | None = None
    threat_level: str | None = None
    intel: str | None = None

    @property
    def total_count(self) -> int:
        return sum(g.count for g in self.groups)


@dataclass
class DefenderConfig:
    """A pre-placed friendly defender."""

    asset_type: str  # "turret", "rover", "drone", etc.
    position: tuple[float, float]
    name: str | None = None

    # Optional combat overrides (applied AFTER apply_combat_profile defaults)
    health: float | None = None
    max_health: float | None = None
    weapon_range: float | None = None
    weapon_cooldown: float | None = None
    weapon_damage: float | None = None
    ammo_count: int | None = None
    ammo_max: int | None = None
    speed: float | None = None


@dataclass
class BattleScenario:
    """Complete battle scenario definition."""

    scenario_id: str
    name: str
    description: str
    map_bounds: float
    waves: list[WaveDefinition]
    defenders: list[DefenderConfig] = field(default_factory=list)
    max_hostiles: int = 200
    tags: list[str] = field(default_factory=list)
    mode_config: dict[str, Any] | None = None  # Mode-specific settings (civil_unrest, drone_swarm)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "map_bounds": self.map_bounds,
            "max_hostiles": self.max_hostiles,
            "tags": self.tags,
            "waves": [
                {
                    "name": w.name,
                    "groups": [
                        {
                            "asset_type": g.asset_type,
                            "count": g.count,
                            "speed": g.speed,
                            "health": g.health,
                            **({"drone_variant": g.drone_variant} if g.drone_variant else {}),
                            **({"max_health": g.max_health} if g.max_health is not None else {}),
                            **({"weapon_range": g.weapon_range} if g.weapon_range is not None else {}),
                            **({"weapon_cooldown": g.weapon_cooldown} if g.weapon_cooldown is not None else {}),
                            **({"weapon_damage": g.weapon_damage} if g.weapon_damage is not None else {}),
                            **({"ammo_count": g.ammo_count} if g.ammo_count is not None else {}),
                            **({"ammo_max": g.ammo_max} if g.ammo_max is not None else {}),
                        }
                        for g in w.groups
                    ],
                    "speed_mult": w.speed_mult,
                    "health_mult": w.health_mult,
                    **({"briefing": w.briefing} if w.briefing else {}),
                    **({"threat_level": w.threat_level} if w.threat_level else {}),
                    **({"intel": w.intel} if w.intel else {}),
                }
                for w in self.waves
            ],
            "defenders": [
                {
                    "asset_type": d.asset_type,
                    "position": list(d.position),
                    "name": d.name,
                    **({"health": d.health} if d.health is not None else {}),
                    **({"max_health": d.max_health} if d.max_health is not None else {}),
                    **({"weapon_range": d.weapon_range} if d.weapon_range is not None else {}),
                    **({"weapon_cooldown": d.weapon_cooldown} if d.weapon_cooldown is not None else {}),
                    **({"weapon_damage": d.weapon_damage} if d.weapon_damage is not None else {}),
                    **({"ammo_count": d.ammo_count} if d.ammo_count is not None else {}),
                    **({"ammo_max": d.ammo_max} if d.ammo_max is not None else {}),
                    **({"speed": d.speed} if d.speed is not None else {}),
                }
                for d in self.defenders
            ],
        }
        if self.mode_config is not None:
            result["mode_config"] = self.mode_config
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BattleScenario:
        waves = []
        for w in data["waves"]:
            groups = [
                SpawnGroup(
                    asset_type=g["asset_type"],
                    count=g["count"],
                    speed=g.get("speed", 1.5),
                    health=g.get("health", 80.0),
                    drone_variant=g.get("drone_variant"),
                    max_health=g.get("max_health"),
                    weapon_range=g.get("weapon_range"),
                    weapon_cooldown=g.get("weapon_cooldown"),
                    weapon_damage=g.get("weapon_damage"),
                    ammo_count=g.get("ammo_count"),
                    ammo_max=g.get("ammo_max"),
                )
                for g in w["groups"]
            ]
            waves.append(WaveDefinition(
                name=w["name"],
                groups=groups,
                speed_mult=w.get("speed_mult", 1.0),
                health_mult=w.get("health_mult", 1.0),
                briefing=w.get("briefing"),
                threat_level=w.get("threat_level"),
                intel=w.get("intel"),
            ))

        defenders = []
        for d in data.get("defenders", []):
            pos = d["position"]
            defenders.append(DefenderConfig(
                asset_type=d["asset_type"],
                position=(float(pos[0]), float(pos[1])),
                name=d.get("name"),
                health=d.get("health"),
                max_health=d.get("max_health"),
                weapon_range=d.get("weapon_range"),
                weapon_cooldown=d.get("weapon_cooldown"),
                weapon_damage=d.get("weapon_damage"),
                ammo_count=d.get("ammo_count"),
                ammo_max=d.get("ammo_max"),
                speed=d.get("speed"),
            ))

        return cls(
            scenario_id=data["scenario_id"],
            name=data["name"],
            description=data.get("description", ""),
            map_bounds=data.get("map_bounds", 200.0),
            waves=waves,
            defenders=defenders,
            max_hostiles=data.get("max_hostiles", 200),
            tags=data.get("tags", []),
            mode_config=data.get("mode_config"),
        )


def apply_scenario_overrides(target, config) -> None:
    """Apply optional combat overrides from a DefenderConfig or SpawnGroup onto a SimulationTarget.

    Call AFTER target.apply_combat_profile() so these values override profile defaults.
    Only fields that are not None are applied.
    """
    if getattr(config, "health", None) is not None:
        target.health = config.health
        target.max_health = config.max_health if config.max_health is not None else config.health
    if getattr(config, "max_health", None) is not None and getattr(config, "health", None) is None:
        target.max_health = config.max_health
    if getattr(config, "weapon_range", None) is not None:
        target.weapon_range = config.weapon_range
    if getattr(config, "weapon_cooldown", None) is not None:
        target.weapon_cooldown = config.weapon_cooldown
    if getattr(config, "weapon_damage", None) is not None:
        target.weapon_damage = config.weapon_damage
    if getattr(config, "ammo_count", None) is not None:
        target.ammo_count = config.ammo_count
        target.ammo_max = config.ammo_max if config.ammo_max is not None else config.ammo_count
    if getattr(config, "ammo_max", None) is not None and getattr(config, "ammo_count", None) is None:
        target.ammo_max = config.ammo_max
    if getattr(config, "speed", None) is not None:
        target.speed = config.speed


def load_battle_scenario(path: str) -> BattleScenario:
    """Load a BattleScenario from a JSON file.

    Raises:
        FileNotFoundError: If path does not exist.
        json.JSONDecodeError: If file is not valid JSON.
        KeyError/TypeError: If required fields are missing.
    """
    with open(path) as f:
        data = json.load(f)
    return BattleScenario.from_dict(data)


# Default defender types to cycle through when none are specified
_DEFAULT_DEFENDER_TYPES = [
    "turret", "rover", "drone", "heavy_turret",
    "missile_turret", "scout_drone", "tank", "apc",
]


def spread_defenders(
    count: int,
    map_bounds: float,
    unit_types: list[str] | None = None,
) -> list[DefenderConfig]:
    """Distribute *count* defenders across the map in strategic positions.

    Positions are arranged in concentric rings so they cover multiple
    quadrants and are not all clustered at the center.  A single
    defender is placed near center; 2-4 form a ring at 30% bounds;
    5+ add an outer ring at 60% bounds.

    Args:
        count: Number of defenders to place.
        map_bounds: Map half-size (e.g. 200.0 for a 400m map).
        unit_types: Optional list of asset_type strings (length must
            match *count*).  If ``None``, cycles through default types.

    Returns:
        List of DefenderConfig with spread positions.
    """
    import math

    if unit_types is None:
        types = [_DEFAULT_DEFENDER_TYPES[i % len(_DEFAULT_DEFENDER_TYPES)]
                 for i in range(count)]
    else:
        types = list(unit_types)

    configs: list[DefenderConfig] = []

    if count == 0:
        return configs

    if count == 1:
        configs.append(DefenderConfig(
            asset_type=types[0],
            position=(0.0, 0.0),
            name=f"Defender-1",
        ))
        return configs

    # Place defenders in a ring pattern
    # Inner ring (30% of bounds) for first min(count, 4) defenders
    inner_count = min(count, 4)
    inner_radius = map_bounds * 0.30
    for i in range(inner_count):
        angle = (2 * math.pi * i) / inner_count
        x = inner_radius * math.cos(angle)
        y = inner_radius * math.sin(angle)
        configs.append(DefenderConfig(
            asset_type=types[i],
            position=(round(x, 1), round(y, 1)),
            name=f"Defender-{i + 1}",
        ))

    # Outer ring (60% of bounds) for remaining defenders
    remaining = count - inner_count
    if remaining > 0:
        outer_radius = map_bounds * 0.60
        for i in range(remaining):
            # Offset angle so outer ring doesn't align with inner
            angle = (2 * math.pi * i) / remaining + math.pi / remaining
            x = outer_radius * math.cos(angle)
            y = outer_radius * math.sin(angle)
            idx = inner_count + i
            configs.append(DefenderConfig(
                asset_type=types[idx],
                position=(round(x, 1), round(y, 1)),
                name=f"Defender-{idx + 1}",
            ))

    return configs
