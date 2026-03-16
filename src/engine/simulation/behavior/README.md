# Simulation Behavior

Unit behavior AI for the battle simulation engine. Each behavior module implements autonomous decision-making for a specific unit type.

## Key Files

- `base.py` — BaseBehavior abstract class
- `turret.py` — Turret targeting, tracking, engagement
- `drone.py` — Drone patrol, pursuit, attack patterns
- `rover.py` — Ground rover navigation and engagement
- `hostile.py` — Enemy AI: spawning, attack runs, evasion
- `coordinator.py` — Multi-unit coordination and formation behavior

## Related

- Simulation engine: `src/engine/simulation/engine.py`
- Unit types: `src/engine/units/`
