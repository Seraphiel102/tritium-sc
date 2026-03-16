# MQTT Broker Security Guide

Tritium uses MQTT (Mosquitto) as the backbone for device-to-server communication. In development, anonymous access is enabled for convenience. In production, MQTT must be locked down with authentication and topic-based access control.

## Quick Start (Development)

Default config at `conf/mosquitto/mosquitto.conf` allows anonymous access on port 1883. This is fine for local development only.

## Production Deployment

### 1. Create a Password File

```bash
# Create the password file (first user)
mosquitto_passwd -c /mosquitto/config/passwd admin

# Add more users
mosquitto_passwd /mosquitto/config/passwd tritium-sc
mosquitto_passwd /mosquitto/config/passwd monitor

# Add edge devices (one user per device)
mosquitto_passwd /mosquitto/config/passwd device_43c001
mosquitto_passwd /mosquitto/config/passwd device_43c002
```

### 2. Update mosquitto.conf

```conf
listener 1883
protocol mqtt

# Disable anonymous access
allow_anonymous false

# Password file
password_file /mosquitto/config/passwd

# ACL file (topic-level restrictions)
acl_file /mosquitto/config/acl.conf

persistence true
persistence_location /mosquitto/data/
log_dest stdout
```

### 3. Deploy the ACL File

Copy `conf/mosquitto/acl.conf` to your Mosquitto config directory. The ACL template defines these roles:

| Role | Username Pattern | Access |
|------|-----------------|--------|
| **admin** | `admin` | Full read/write on all topics |
| **command center** | `tritium-sc` | Full read/write on `tritium/#` |
| **edge device** | `device_{id}` | Write own heartbeat/sighting/chat/status; read own commands |
| **meshtastic bridge** | `meshtastic-bridge` | Read/write `tritium/+/meshtastic/#` |
| **camera node** | client ID match | Write own frame/detections; read own commands |
| **robot node** | client ID match | Write own telemetry/thoughts; read own commands |
| **monitor** | `monitor` | Read-only on all topics |

### 4. TLS Encryption

For production, enable TLS to encrypt MQTT traffic:

```conf
listener 8883
protocol mqtt
cafile /mosquitto/certs/ca.crt
certfile /mosquitto/certs/server.crt
keyfile /mosquitto/certs/server.key
require_certificate false

# Optional: require client certificates for mutual TLS
# require_certificate true
```

Generate certificates with:

```bash
# CA
openssl req -new -x509 -days 3650 -extensions v3_ca \
    -keyout ca.key -out ca.crt -subj "/CN=Tritium MQTT CA"

# Server cert
openssl req -new -nodes -keyout server.key -out server.csr \
    -subj "/CN=mqtt.tritium.local"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days 365
```

### 5. Tritium-SC Configuration

Set these environment variables (or in `.env`):

```bash
MQTT_ENABLED=true
MQTT_HOST=localhost
MQTT_PORT=1883          # or 8883 for TLS
MQTT_USERNAME=tritium-sc
MQTT_PASSWORD=<password>
MQTT_TLS=false          # set true for TLS
MQTT_SITE_ID=home
```

### 6. Edge Device Configuration

Each edge device needs credentials provisioned during setup. The fleet server (`tritium-edge/server/`) handles this during device provisioning:

1. Device connects to fleet server over WiFi
2. Fleet server generates a unique MQTT username (`device_{device_id}`)
3. Credentials are stored in device NVS (non-volatile storage)
4. Device uses credentials for all MQTT connections

## Topic Hierarchy

All Tritium MQTT topics follow the pattern:

```
tritium/{site_id}/{domain}/{device_id}/{message_type}
```

See `docs/MQTT.md` for the full topic reference.

## Security Checklist

- [ ] `allow_anonymous false` in mosquitto.conf
- [ ] Password file created with strong passwords
- [ ] ACL file deployed restricting topic access per role
- [ ] TLS enabled on production (port 8883)
- [ ] Edge devices provisioned with unique credentials
- [ ] Firewall blocks external access to MQTT port
- [ ] Monitor user for read-only dashboards (Grafana, etc.)
- [ ] Rotate passwords periodically
- [ ] Log authentication failures for intrusion detection
