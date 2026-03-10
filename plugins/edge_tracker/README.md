# Edge Tracker Plugin

BLE and WiFi device tracking from tritium-edge sensor nodes.

## What It Does

Bridges live presence data from your ESP32-S3 fleet into the Command Center. Every BLE device and WiFi network your edge nodes detect shows up on the tactical map in real time.

- Listens for `fleet.ble_presence`, `fleet.wifi_presence`, and `fleet.heartbeat` events
- Persists sightings using tritium-lib's `BleStore` (SQLite)
- Emits `edge:ble_update` and `edge:wifi_update` for the frontend map panel
- REST API for querying active devices, targets, sighting history, and node positions

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ble/devices` | Active BLE devices |
| GET | `/api/ble/targets` | Tracked BLE targets |
| POST | `/api/ble/targets` | Add a target (mac, label, color) |
| DELETE | `/api/ble/targets/{mac}` | Remove a target |
| GET | `/api/ble/history/{mac}` | Sighting history for a device |
| GET | `/api/ble/stats` | Database statistics |
| GET | `/api/wifi/networks` | Active WiFi networks |

## Requirements

- `tritium-lib` installed with BLE store support (`pip install -e ".[full]"`)
- At least one tritium-edge node running the BLE scanner service

## How It Works

```
ESP32-S3 node (BLE scan) → MQTT → fleet bridge → EventBus
    → EdgeTrackerPlugin → BleStore (SQLite) → edge:ble_update → WebSocket → map panel
```

The plugin auto-discovers via the standard plugin loader. No configuration needed — just drop it in `plugins/` and restart.
