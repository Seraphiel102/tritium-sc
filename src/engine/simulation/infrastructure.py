# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""InfrastructureHealth -- infrastructure damage tracking for drone swarm mode.

Tracks a single health pool representing the defended infrastructure.
Damage comes from three sources:

  1. ``apply_damage()``              -- direct damage (any source)
  2. ``apply_bomber_detonation()``   -- bomber drone self-destruct within 15m of POI
  3. ``apply_attack_fire()``         -- projectile impact within 10m of POI (25% damage)

Each damage application publishes an ``infrastructure_damage`` event on the
EventBus so the frontend and game mode can react.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus

# Proximity radii
_BOMBER_RADIUS = 15.0   # meters — bomber detonation proximity
_ATTACK_RADIUS = 10.0   # meters — attack fire proximity
_ATTACK_FRACTION = 0.25  # 25% of projectile damage to infrastructure


class InfrastructureHealth:
    """Track infrastructure damage in drone swarm mode."""

    def __init__(self, event_bus: EventBus, max_health: float = 1000.0) -> None:
        """
        Args:
            event_bus: EventBus for publishing infrastructure_damage events
            max_health: starting health (default 1000)
        """
        self._event_bus = event_bus
        self._max_health = max_health
        self._health = max_health

    def apply_damage(
        self,
        amount: float,
        source_id: str,
        source_type: str,
        position: tuple[float, float] | None = None,
    ) -> float:
        """Reduce health by *amount* (floor at 0).

        Publishes an ``infrastructure_damage`` event.

        Args:
            amount: damage to apply
            source_id: identifier of the damage source
            source_type: type label for the damage source
            position: optional (x, y) of the damage origin

        Returns:
            Current health after damage.
        """
        self._health = max(0.0, self._health - amount)
        self._event_bus.publish("infrastructure_damage", {
            "health": self._health,
            "max_health": self._max_health,
            "damage": amount,
            "source_id": source_id,
            "source_type": source_type,
        })
        return self._health

    def apply_bomber_detonation(
        self,
        position: tuple[float, float],
        damage: float,
        poi_buildings: list[tuple[float, float]],
    ) -> None:
        """Apply bomber detonation damage if within 15m of any POI building.

        Args:
            position: (x, y) of detonation
            damage: base damage of the detonation
            poi_buildings: list of (x, y) POI building positions
        """
        for poi in poi_buildings:
            dist = math.hypot(position[0] - poi[0], position[1] - poi[1])
            if dist <= _BOMBER_RADIUS:
                self.apply_damage(
                    amount=damage,
                    source_id="bomber",
                    source_type="bomber_detonation",
                    position=position,
                )
                return  # Only apply once even if near multiple POIs

    def apply_attack_fire(
        self,
        position: tuple[float, float],
        damage: float,
        poi_buildings: list[tuple[float, float]],
    ) -> None:
        """Apply attack fire damage (25%) if within 10m of any POI building.

        Args:
            position: (x, y) of projectile impact
            damage: base damage of the projectile
            poi_buildings: list of (x, y) POI building positions
        """
        for poi in poi_buildings:
            dist = math.hypot(position[0] - poi[0], position[1] - poi[1])
            if dist <= _ATTACK_RADIUS:
                self.apply_damage(
                    amount=damage * _ATTACK_FRACTION,
                    source_id="attacker",
                    source_type="attack_fire",
                    position=position,
                )
                return  # Only apply once even if near multiple POIs

    def is_destroyed(self) -> bool:
        """Return True if health <= 0."""
        return self._health <= 0

    def get_state(self) -> dict:
        """Return current infrastructure state.

        Returns:
            dict with health, max_health, percent keys
        """
        pct = (self._health / self._max_health) * 100.0 if self._max_health > 0 else 0.0
        return {
            "health": self._health,
            "max_health": self._max_health,
            "percent": pct,
        }
