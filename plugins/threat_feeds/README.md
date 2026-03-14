# Threat Feeds Plugin

Threat intelligence feed integration for TRITIUM-SC. Imports known-bad
indicators (MAC addresses, SSIDs, IPs, device names) and automatically
checks every new BLE/WiFi device against the feed.

## Features

- Load indicators from JSON or CSV files
- Manual indicator management via REST API
- Auto-check new devices via EventBus subscription
- Enrichment pipeline integration (auto-enrich new targets)
- Alert publication on indicator match
- Persistent storage at `data/threat_feeds/indicators.json`
- Ships with 10 seed indicators (5 MACs, 5 SSIDs)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/threats/` | List all indicators (optional `?indicator_type=` filter) |
| POST | `/api/threats/` | Add a single indicator |
| DELETE | `/api/threats/{type}/{value}` | Remove an indicator |
| POST | `/api/threats/check` | Check a value against feeds |
| POST | `/api/threats/import` | Bulk import from JSON/CSV content |
| GET | `/api/threats/stats` | Summary statistics |

## Indicator Types

- `mac` — MAC address (e.g., `DE:AD:BE:EF:00:01`)
- `ssid` — WiFi network name (e.g., `FreeWiFi-EVIL`)
- `ip` — IP address (e.g., `192.168.1.100`)
- `device_name` — BLE device name (e.g., `EvilDevice`)

## Threat Levels

- `suspicious` — warrants investigation
- `hostile` — confirmed threat

## Import Format

### JSON
```json
[
  {
    "indicator_type": "mac",
    "value": "DE:AD:BE:EF:00:01",
    "threat_level": "hostile",
    "source": "my-feed",
    "description": "Known bad device"
  }
]
```

### CSV
```csv
indicator_type,value,threat_level,source,description
mac,DE:AD:BE:EF:00:01,hostile,my-feed,Known bad device
```
