# Swarm Drone Demo

Standalone demo that simulates a drone swarm publishing telemetry over MQTT. Models coordinated flight patterns, formation changes, and area coverage missions.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, fleet coordination loop |
| `drone.py` | Individual drone simulation (position, battery, state) |
| `fleet.py` | Swarm coordination (formations, waypoints, coverage) |
| `mqtt_client.py` | MQTT publish helper |

## Usage

```bash
pip install -r requirements.txt
python main.py
```

Publishes drone telemetry to `tritium/{site}/robots/{id}/telemetry` topics.

## Test

```bash
cd tests && python -m pytest
```
