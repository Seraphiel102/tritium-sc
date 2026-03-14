# Federation Plugin

Multi-site federation via MQTT bridge. Connects separate Tritium installations for shared situational awareness.

## Capabilities

- **Site discovery** -- announce/heartbeat between sites
- **Target sharing** -- real-time position updates across sites
- **Dossier synchronization** -- share accumulated intelligence
- **Alert forwarding** -- cross-site threat notifications

## Files

| File | Purpose |
|------|---------|
| `plugin.py` | FederationPlugin lifecycle, site management, MQTT bridging |
| `routes.py` | REST API: `/api/federation/*` for site CRUD and status |

## Configuration

Sites are stored in `data/federation_sites.json`. Each site has its own MQTT client connection.

## API Endpoints

- `GET /api/federation/sites` -- list federated sites
- `POST /api/federation/sites` -- add a new federated site
- `DELETE /api/federation/sites/{id}` -- remove a site
- `GET /api/federation/status` -- federation health status
