# Automation Engine Plugin

**If-then rules that trigger actions on events.**

## Overview

The Automation Engine subscribes to all EventBus events and evaluates them
against user-defined rules. When an event matches a rule's trigger pattern
and all conditions are satisfied, the rule's actions execute.

## Rule Structure

Each rule has:
- **trigger** — Event type pattern to match (exact or glob with `*`)
- **conditions** — List of field checks (eq, gt, lt, contains, regex, etc.)
- **actions** — List of action specs to execute when conditions pass
- **cooldown_seconds** — Minimum time between firings (prevents flooding)

## Action Types

| Type | Description |
|------|-------------|
| `alert` | Publish alert event to EventBus |
| `command` | Send MQTT command to a device |
| `tag` | Add a tag to a target/dossier |
| `escalate` | Change threat level for a target |
| `notify` | Publish a notification event |
| `log` | Log a message at specified level |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/automation/rules` | List all rules |
| POST | `/api/automation/rules` | Create a rule |
| GET | `/api/automation/rules/{id}` | Get a rule |
| PUT | `/api/automation/rules/{id}` | Update a rule |
| DELETE | `/api/automation/rules/{id}` | Delete a rule |
| POST | `/api/automation/rules/{id}/enable` | Enable a rule |
| POST | `/api/automation/rules/{id}/disable` | Disable a rule |
| POST | `/api/automation/rules/{id}/test` | Dry-run test a rule |
| POST | `/api/automation/test` | Dry-run test all rules |
| GET | `/api/automation/stats` | Engine statistics |

## Example Rules (seeded on first run)

1. **Alert on unknown device in restricted zone** — trigger: `geofence:enter`, condition: alliance=unknown, action: alert
2. **Escalate strong unknown signal** — trigger: `ble:suspicious_device`, action: escalate threat to high
3. **Tag returning device** — trigger: `ble:new_device`, condition: seen_count>5, action: tag as "frequent"
