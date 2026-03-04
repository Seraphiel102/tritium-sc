# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Compute expectations from config and check metrics against them."""

from __future__ import annotations

from tests.combat_matrix.config_matrix import BattleConfig
from tests.combat_matrix.metrics import Assertion, BattleMetrics


def compute_expectations(config: BattleConfig) -> dict:
    """Derive expected values from the battle configuration."""
    total_ammo = config.total_ammo
    total_combatants = config.defender_count + config.hostile_count
    # min_shots: at least 1 shot per combatant OR 5% of ammo, whichever is less
    # This accounts for quick battles where units die before expending much ammo
    min_shots = max(1, min(total_ammo // 20, total_combatants))
    return {
        "exact_friendlies": config.defender_count,
        "exact_hostiles": config.hostile_count,
        "max_units": config.defender_count + config.hostile_count,
        "min_shots": min_shots,
        "max_shots": total_ammo,
        "min_hits": 1,
        "min_eliminations": 1,
    }


def check_assertions(
    config: BattleConfig,
    metrics: BattleMetrics,
) -> list[Assertion]:
    """Run all assertion checks and return results.

    Does NOT raise — callers decide what to do with failures.
    """
    exp = compute_expectations(config)
    assertions: list[Assertion] = []

    def _add(name: str, severity: str, expected, actual, passed: bool, msg: str = ""):
        assertions.append(Assertion(
            name=name, severity=severity,
            expected=expected, actual=actual,
            passed=passed, message=msg,
        ))

    # -- Critical assertions ---------------------------------------------------

    _add(
        "initial_friendly_count",
        "critical",
        exp["exact_friendlies"],
        metrics.initial_friendly_count,
        metrics.initial_friendly_count == exp["exact_friendlies"],
        f"Expected {exp['exact_friendlies']} friendlies, got {metrics.initial_friendly_count}",
    )

    # For large hostile counts (>10), accept 90% spawned (staggered spawn + fast kills)
    hostile_threshold = exp["exact_hostiles"]
    if exp["exact_hostiles"] > 10:
        hostile_threshold = int(exp["exact_hostiles"] * 0.9)
    _add(
        "initial_hostile_count",
        "critical",
        f">= {hostile_threshold}" if hostile_threshold != exp["exact_hostiles"] else exp["exact_hostiles"],
        metrics.initial_hostile_count,
        metrics.initial_hostile_count >= hostile_threshold,
        f"Expected >={hostile_threshold} hostiles (config={exp['exact_hostiles']}), got {metrics.initial_hostile_count}",
    )

    _add(
        "max_total_units",
        "critical",
        f"<= {exp['max_units']}",
        metrics.max_total_units,
        metrics.max_total_units <= exp["max_units"],
        f"Max units {metrics.max_total_units} exceeds {exp['max_units']}",
    )

    _add(
        "zero_neutrals",
        "critical",
        0,
        metrics.neutral_count_max,
        metrics.neutral_count_max == 0,
        f"Found {metrics.neutral_count_max} neutral units during battle",
    )

    _add(
        "min_shots_fired",
        "critical",
        f">= {exp['min_shots']}",
        metrics.total_shots_fired,
        metrics.total_shots_fired >= exp["min_shots"],
        f"Only {metrics.total_shots_fired} shots (need >= {exp['min_shots']}, total ammo={config.total_ammo})",
    )

    _add(
        "max_shots_fired",
        "critical",
        f"<= {exp['max_shots']}",
        metrics.total_shots_fired,
        metrics.total_shots_fired <= exp["max_shots"],
        f"Fired {metrics.total_shots_fired} shots but only {exp['max_shots']} total ammo",
    )

    _add(
        "min_hits",
        "critical",
        f">= {exp['min_hits']}",
        metrics.total_shots_hit,
        metrics.total_shots_hit >= exp["min_hits"],
        f"Zero hits — combat system may be broken",
    )

    _add(
        "min_eliminations",
        "critical",
        f">= {exp['min_eliminations']}",
        metrics.total_eliminations,
        metrics.total_eliminations >= exp["min_eliminations"],
        f"Zero eliminations — nobody died",
    )

    _add(
        "game_concludes",
        "critical",
        "victory or defeat",
        metrics.game_result,
        metrics.game_result in ("victory", "defeat"),
        f"Game ended with '{metrics.game_result}' instead of victory/defeat",
    )

    # -- Major assertions ------------------------------------------------------

    # Per-unit ammo should decrease
    ammo_decreased = False
    if metrics.snapshots:
        # Group by target_id and check if any unit's ammo decreased
        from collections import defaultdict
        by_unit: dict[str, list] = defaultdict(list)
        for snap in metrics.snapshots:
            by_unit[snap.target_id].append(snap)
        for tid, snaps in by_unit.items():
            if len(snaps) >= 2:
                first_ammo = snaps[0].ammo_count
                last_ammo = snaps[-1].ammo_count
                if last_ammo < first_ammo:
                    ammo_decreased = True
                    break
    _add(
        "ammo_decreases",
        "major",
        "at least 1 unit ammo decreased",
        ammo_decreased,
        ammo_decreased,
        "No unit showed ammo decrease across snapshots",
    )

    # Per-unit health decreases when hit
    health_decreased = False
    if metrics.snapshots:
        from collections import defaultdict
        by_unit_h: dict[str, list] = defaultdict(list)
        for snap in metrics.snapshots:
            by_unit_h[snap.target_id].append(snap)
        for tid, snaps in by_unit_h.items():
            if len(snaps) >= 2:
                first_hp = snaps[0].health
                min_hp = min(s.health for s in snaps)
                if min_hp < first_hp:
                    health_decreased = True
                    break
    _add(
        "health_decreases",
        "major",
        "at least 1 unit health decreased",
        health_decreased,
        health_decreased,
        "No unit showed health decrease across snapshots",
    )

    _add(
        "ws_projectile_events",
        "major",
        "> 0",
        metrics.ws_projectile_fired,
        metrics.ws_projectile_fired > 0,
        "Zero projectile_fired WebSocket events",
    )

    _add(
        "ws_eliminated_events",
        "major",
        "> 0",
        metrics.ws_target_eliminated,
        metrics.ws_target_eliminated > 0,
        "Zero target_eliminated WebSocket events",
    )

    _add(
        "ws_game_over_event",
        "major",
        "1",
        metrics.ws_game_over,
        metrics.ws_game_over >= 1,
        "No game_over WebSocket event received",
    )

    # At least 2 distinct units fired
    units_that_fired = sum(
        1 for u in metrics.unit_stats if u.get("shots_fired", 0) > 0
    )
    _add(
        "multi_unit_fire",
        "major",
        ">= 2",
        units_that_fired,
        units_that_fired >= 2,
        f"Only {units_that_fired} units fired shots",
    )

    # -- Minor assertions (informational) --------------------------------------

    _add(
        "green_blobs_visible",
        "minor",
        True,
        metrics.green_blob_detected,
        metrics.green_blob_detected,
        "No green (friendly) blobs detected in screenshots",
    )

    _add(
        "red_blobs_visible",
        "minor",
        True,
        metrics.red_blob_detected,
        metrics.red_blob_detected,
        "No red (hostile) blobs detected in screenshots",
    )

    _add(
        "bright_fx_pixels",
        "minor",
        "> 0",
        metrics.bright_fx_max,
        metrics.bright_fx_max > 0,
        "No bright FX pixels detected (explosions, muzzle flash)",
    )

    _add(
        "frame_motion",
        "minor",
        True,
        metrics.frame_motion_detected,
        metrics.frame_motion_detected,
        "No frame-to-frame motion detected",
    )

    _add(
        "audio_rms",
        "minor",
        "> 0",
        round(metrics.audio_rms, 6),
        metrics.audio_rms > 0,
        "Audio RMS is zero — combat sounds may not be served",
    )

    # Per-unit accuracy
    for u in metrics.unit_stats:
        acc = u.get("accuracy", 0.0)
        sf = u.get("shots_fired", 0)
        if sf > 0:
            _add(
                f"accuracy_{u.get('name', 'unknown')}",
                "minor",
                "0.0 - 1.0",
                round(acc, 4),
                0.0 <= acc <= 1.0,
                f"Unit {u.get('name')} accuracy={acc:.4f} (fired={sf})",
            )

    # MVP identification
    mvp_found = any(u.get("kills", 0) > 0 for u in metrics.unit_stats)
    _add(
        "mvp_exists",
        "minor",
        True,
        mvp_found,
        mvp_found,
        "No unit has any kills — no MVP possible",
    )

    # Battle duration
    _add(
        "battle_duration",
        "minor",
        "> 5s",
        round(metrics.battle_duration, 1),
        metrics.battle_duration > 5.0,
        f"Battle lasted only {metrics.battle_duration:.1f}s",
    )

    return assertions
