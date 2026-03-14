# Motion Sensor Demo

Standalone demo that simulates a PIR/radar motion sensor publishing detections over MQTT. Used for testing the edge tracker and RF motion plugins without physical hardware.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point, MQTT connection, detection loop |
| `sensor.py` | Simulated motion sensor with configurable patterns |
| `patterns.py` | Motion event patterns (walk-by, loiter, vehicle) |
| `mqtt_client.py` | MQTT publish helper |
| `config.py` | Configuration (broker, topic, intervals) |

## Usage

```bash
pip install -r requirements.txt
python main.py
```

Publishes motion events to `tritium/{site}/sensors/{id}/motion` topic.

## Test

```bash
cd tests && python -m pytest
```
