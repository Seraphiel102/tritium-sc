# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CombatSystem — projectile flight, hit detection, and damage resolution.

Architecture
------------
CombatSystem manages the lifecycle of Projectile instances:

  1. ``fire()`` creates a Projectile if the source unit passes ``can_fire()``.
     The projectile starts at the source's position and flies toward the
     target's position at the time of firing.

  2. ``tick()`` advances each projectile toward its target_pos.  When the
     projectile enters the hit radius (1.5 units) of the *target* (tracked
     by ID, not by frozen position), damage is applied.  If the target is
     eliminated (health <= 0), a ``target_eliminated`` event is published
     and the interceptor's ``eliminations`` counter is incremented.

  3. Projectiles that fly past their target_pos by 3 units without hitting
     anything are marked as missed and removed.

Elimination streaks are tracked per source_id.  Consecutive neutralizations
within a single game session trigger escalating announcements (3=KILLING
SPREE, 5=RAMPAGE, 7=DOMINATING, 10=GODLIKE).  The streak counter resets
when the source is eliminated.

Events are published on the EventBus for the frontend and Amy's announcer:
  - ``projectile_fired``: new dart/rocket in the air
  - ``projectile_hit``: damage applied
  - ``target_eliminated``: health reached zero
  - ``elimination_streak``: milestone reached
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.comms.event_bus import EventBus
    from .target import SimulationTarget
    from .upgrades import UpgradeSystem

# Hit detection radius — projectile is "close enough" to count as a hit.
# Must be large enough to account for target movement during projectile flight.
HIT_RADIUS = 5.0

# Miss distance — projectile has overshot target by this much
MISS_OVERSHOOT = 8.0

# Elimination streak thresholds and names
_STREAK_NAMES: list[tuple[int, str]] = [
    (10, "GODLIKE"),
    (7, "DOMINATING"),
    (5, "RAMPAGE"),
    (3, "ON A STREAK"),
]


@dataclass
class Projectile:
    """A single projectile in flight."""

    id: str
    source_id: str
    source_name: str
    target_id: str
    position: tuple[float, float]
    target_pos: tuple[float, float]
    speed: float = 25.0
    damage: float = 10.0
    projectile_type: str = "nerf_dart"  # nerf_dart, nerf_rocket, water_balloon
    source_type: str = ""  # asset_type of the firing unit
    source_pos: tuple[float, float] = (0.0, 0.0)  # origin position at time of fire
    created_at: float = field(default_factory=time.time)
    hit: bool = False
    missed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "target_id": self.target_id,
            "position": {"x": self.position[0], "y": self.position[1]},
            "target_pos": {"x": self.target_pos[0], "y": self.target_pos[1]},
            "source_pos": {"x": self.source_pos[0], "y": self.source_pos[1]},
            "speed": self.speed,
            "damage": self.damage,
            "projectile_type": self.projectile_type,
            "hit": self.hit,
            "missed": self.missed,
        }


class CombatSystem:
    """Manages projectiles, hit detection, and damage resolution."""

    def __init__(self, event_bus: EventBus, stats_tracker=None,
                 weapon_system=None, upgrade_system: UpgradeSystem | None = None) -> None:
        self._projectiles: dict[str, Projectile] = {}
        self._event_bus = event_bus
        self._elimination_streaks: dict[str, int] = {}
        self._stats_tracker = stats_tracker
        self._weapon_system = weapon_system
        self._upgrade_system = upgrade_system

    @property
    def projectile_count(self) -> int:
        return len(self._projectiles)

    def fire(
        self,
        source: SimulationTarget,
        target: SimulationTarget,
        projectile_type: str = "nerf_dart",
        terrain_map=None,
        aim_pos: tuple[float, float] | None = None,
    ) -> Projectile | None:
        """Fire a projectile from *source* at *target*.

        Returns the Projectile if fired, None if source cannot fire.
        Updates source.last_fired timestamp.
        When terrain_map is provided, checks line_of_sight before firing.
        """
        if not source.can_fire():
            return None

        # Ammo check: if ammo_count == 0, cannot fire; if > 0, decrement
        if source.ammo_count == 0:
            return None
        if source.ammo_count > 0:
            source.ammo_count -= 1

        # Sync inventory weapon ammo with target.ammo_count depletion
        if hasattr(source, 'inventory') and source.inventory is not None:
            active_wp = source.inventory.get_active_weapon()
            if active_wp is not None and active_wp.ammo > 0:
                active_wp.ammo -= 1
                # Auto-switch when active weapon runs dry
                if active_wp.ammo <= 0:
                    source.inventory.auto_switch_weapon()

        # Check range (with upgrade modifier)
        dx = target.position[0] - source.position[0]
        dy = target.position[1] - source.position[1]
        dist = math.hypot(dx, dy)
        effective_range = source.weapon_range
        if self._upgrade_system is not None:
            effective_range *= self._upgrade_system.get_stat_modifier(
                source.target_id, "weapon_range"
            )
        if dist > effective_range:
            return None

        # Check LOS if terrain map is available
        if terrain_map is not None:
            if not terrain_map.line_of_sight(source.position, target.position):
                return None

        # Weapon system integration: reload check, accuracy, ammo
        if self._weapon_system is not None:
            if self._weapon_system.is_reloading(source.target_id):
                return None
            weapon = self._weapon_system.get_weapon(source.target_id)
            if weapon is not None:
                if random.random() > weapon.accuracy:
                    source.last_fired = time.time()
                    return None  # missed due to weapon accuracy
                self._weapon_system.consume_ammo(source.target_id)

        source.last_fired = time.time()

        # Determine effective damage from the best available source:
        #   1. Weapon system weapon (synced from inventory at add_target time)
        #   2. target.weapon_damage (flat combat profile fallback)
        # The weapon system is the canonical source of weapon stats during
        # engine-integrated combat.  Direct inventory damage lookup is NOT
        # used here because __post_init__ auto-builds inventory with catalog
        # stats that may differ from the combat profile weapon_damage.
        effective_damage = source.weapon_damage
        if self._weapon_system is not None:
            ws_weapon = self._weapon_system.get_weapon(source.target_id)
            if ws_weapon is not None and ws_weapon.damage > 0:
                effective_damage = ws_weapon.damage
        if self._upgrade_system is not None:
            effective_damage *= self._upgrade_system.get_stat_modifier(
                source.target_id, "weapon_damage"
            )

        proj = Projectile(
            id=str(uuid.uuid4()),
            source_id=source.target_id,
            source_name=source.name,
            target_id=target.target_id,
            position=source.position,
            target_pos=aim_pos if aim_pos is not None else target.position,
            speed=80.0,
            damage=effective_damage,
            projectile_type=projectile_type,
            source_type=source.asset_type,
            source_pos=source.position,
        )
        self._projectiles[proj.id] = proj

        self._event_bus.publish("projectile_fired", {
            "id": proj.id,
            "source_id": source.target_id,
            "source_name": source.name,
            "source_type": source.asset_type,
            "source_pos": {"x": source.position[0], "y": source.position[1]},
            "target_id": target.target_id,
            "target_pos": {"x": target.position[0], "y": target.position[1]},
            "projectile_type": projectile_type,
            "damage": proj.damage,
        })
        # Record shot in stats tracker
        if self._stats_tracker is not None:
            self._stats_tracker.on_shot_fired(source.target_id)
        return proj

    def tick(self, dt: float, targets: dict[str, SimulationTarget],
             cover_system=None) -> None:
        """Advance all projectiles, resolve hits and misses.

        When *cover_system* is provided, damage is reduced by the target's
        cover bonus (0.0-0.8) on each hit.
        """
        to_remove: list[str] = []

        for proj in self._projectiles.values():
            if proj.hit or proj.missed:
                to_remove.append(proj.id)
                continue

            # Move projectile toward target's CURRENT position (semi-guided)
            target = targets.get(proj.target_id)
            aim_pos = target.position if (target is not None and target.status in ("active", "idle", "stationary")) else proj.target_pos
            dx = aim_pos[0] - proj.position[0]
            dy = aim_pos[1] - proj.position[1]
            dist_to_aim = math.hypot(dx, dy)

            if dist_to_aim > 0:
                step = proj.speed * dt
                if step >= dist_to_aim:
                    proj.position = aim_pos
                else:
                    proj.position = (
                        proj.position[0] + (dx / dist_to_aim) * step,
                        proj.position[1] + (dy / dist_to_aim) * step,
                    )

            # Check hit: is the projectile within HIT_RADIUS of the actual target?
            if target is not None and target.status in ("active", "idle", "stationary"):
                tdx = proj.position[0] - target.position[0]
                tdy = proj.position[1] - target.position[1]
                dist_to_target = math.hypot(tdx, tdy)

                if dist_to_target <= HIT_RADIUS:
                    proj.hit = True
                    # Apply cover damage reduction
                    effective_damage = proj.damage
                    if cover_system is not None:
                        cover_bonus = cover_system.get_cover_bonus(
                            target.position, proj.position, target.target_id
                        )
                        effective_damage = proj.damage * (1.0 - cover_bonus)
                    # Apply upgrade damage reduction
                    if self._upgrade_system is not None:
                        reduction = self._upgrade_system.get_stat_modifier(
                            target.target_id, "damage_reduction"
                        )
                        effective_damage *= (1.0 - reduction)
                    # Apply inventory armor damage reduction
                    if hasattr(target, 'inventory') and target.inventory is not None:
                        armor_reduction = target.inventory.total_damage_reduction()
                        if armor_reduction > 0:
                            effective_damage *= (1.0 - armor_reduction)
                            target.inventory.damage_armor(1)
                    # Cap total damage reduction at 80% (minimum 20% of original damage)
                    min_damage = proj.damage * 0.2
                    if effective_damage < min_damage:
                        effective_damage = min_damage
                    eliminated = target.apply_damage(effective_damage)
                    self._event_bus.publish("projectile_hit", {
                        "projectile_id": proj.id,
                        "target_id": target.target_id,
                        "target_name": target.name,
                        "damage": effective_damage,
                        "remaining_health": target.health,
                        "source_id": proj.source_id,
                        "source_type": proj.source_type,
                        "source_name": proj.source_name,
                        "source_pos": {"x": proj.source_pos[0], "y": proj.source_pos[1]},
                        "projectile_type": proj.projectile_type,
                        "position": {"x": target.position[0], "y": target.position[1]},
                    })
                    # Record hit in stats tracker
                    if self._stats_tracker is not None:
                        self._stats_tracker.on_shot_hit(
                            proj.source_id, target.target_id, effective_damage
                        )

                    if eliminated:
                        # Increment interceptor stats
                        interceptor = targets.get(proj.source_id)
                        interceptor_name = proj.source_name
                        if interceptor is not None:
                            interceptor.kills += 1
                            interceptor_name = interceptor.name

                        self._event_bus.publish("target_eliminated", {
                            "target_id": target.target_id,
                            "target_name": target.name,
                            "target_type": target.asset_type,
                            "interceptor_id": proj.source_id,
                            "interceptor_name": interceptor_name,
                            "interceptor_type": proj.source_type,
                            "position": {"x": target.position[0], "y": target.position[1]},
                            "method": proj.projectile_type,
                        })
                        # Record kill in stats tracker
                        if self._stats_tracker is not None:
                            self._stats_tracker.on_kill(
                                proj.source_id, target.target_id
                            )

                        # Elimination streak tracking
                        self._elimination_streaks[proj.source_id] = (
                            self._elimination_streaks.get(proj.source_id, 0) + 1
                        )
                        streak = self._elimination_streaks[proj.source_id]
                        streak_name = self._get_streak_name(streak)
                        if streak_name:
                            self._event_bus.publish("elimination_streak", {
                                "interceptor_id": proj.source_id,
                                "interceptor_name": interceptor_name,
                                "streak": streak,
                                "streak_name": streak_name,
                            })

                    to_remove.append(proj.id)
                    continue

            # Check miss: projectile exceeded max flight time (5 seconds)
            flight_time = time.time() - proj.created_at
            if flight_time > 5.0:
                proj.missed = True
                to_remove.append(proj.id)

        for pid in to_remove:
            self._projectiles.pop(pid, None)

    def reset_streaks(self) -> None:
        """Reset all elimination streak counters."""
        self._elimination_streaks.clear()

    def reset_streak(self, target_id: str) -> None:
        """Reset elimination streak for a specific unit (e.g. when eliminated)."""
        self._elimination_streaks.pop(target_id, None)

    def get_active_projectiles(self) -> list[dict]:
        """Return serializable list of active projectiles for frontend rendering."""
        return [p.to_dict() for p in self._projectiles.values()
                if not p.hit and not p.missed]

    def detonate_bomber(
        self,
        bomber: SimulationTarget,
        targets: dict[str, SimulationTarget],
        radius: float = 5.0,
    ) -> list[str]:
        """Detonate a bomber drone, applying AoE damage.

        Applies bomber's weapon_damage to all targets within *radius*
        (excluding the bomber itself). Returns list of damaged target IDs.

        Args:
            bomber: The bomber drone detonating.
            targets: All targets in the simulation.
            radius: Blast radius in meters.

        Returns:
            List of target IDs that were damaged.
        """
        damage = bomber.weapon_damage
        damaged: list[str] = []
        r2 = radius * radius

        for tid, t in targets.items():
            if tid == bomber.target_id:
                continue
            dx = t.position[0] - bomber.position[0]
            dy = t.position[1] - bomber.position[1]
            if dx * dx + dy * dy <= r2:
                t.apply_damage(damage)
                damaged.append(tid)

        # Publish detonation event
        self._event_bus.publish("bomber_detonation", {
            "bomber_id": bomber.target_id,
            "position": {"x": bomber.position[0], "y": bomber.position[1]},
            "radius": radius,
            "damage": damage,
        })

        # Mark bomber as eliminated
        bomber.health = 0
        bomber.status = "eliminated"

        return damaged

    def clear(self) -> None:
        """Remove all projectiles."""
        self._projectiles.clear()

    @staticmethod
    def _get_streak_name(streak: int) -> str | None:
        """Return the streak announcement name, or None if not a milestone."""
        for threshold, name in _STREAK_NAMES:
            if streak == threshold:
                return name
        return None
