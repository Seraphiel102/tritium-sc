# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FleetDashboardPlugin — aggregated fleet device registry and dashboard API.

Subscribes to fleet.heartbeat and edge:ble_update events on the EventBus,
maintains an in-memory device registry with status tracking, and exposes
REST endpoints for the fleet dashboard frontend panel.

Devices not seen within PRUNE_TIMEOUT_S are pruned automatically.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from engine.plugins.base import EventDrainPlugin, PluginContext

log = logging.getLogger("fleet-dashboard")

PRUNE_TIMEOUT_S = 300  # 5 minutes
TARGET_HISTORY_MAXLEN = 60  # Keep 60 data points per device (1 per minute = 1 hour)


class FleetDashboardPlugin(EventDrainPlugin):
    """Aggregated fleet device registry with dashboard API."""

    def __init__(self) -> None:
        super().__init__()
        self._prune_thread: Optional[threading.Thread] = None

        # device_id -> device info dict
        self._devices: dict[str, dict] = {}
        self._lock = threading.Lock()

        # Target count history per device: device_id -> list of {ts, count}
        self._target_history: dict[str, list[dict]] = {}

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.fleet-dashboard"

    @property
    def name(self) -> str:
        return "Fleet Dashboard"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "ui"}

    # -- EventDrainPlugin overrides ----------------------------------------

    def _on_configure(self, ctx: PluginContext) -> None:
        self._register_routes()
        self._logger.info("Fleet Dashboard plugin configured")

    def _on_start(self) -> None:
        self._prune_thread = threading.Thread(
            target=self._prune_loop,
            daemon=True,
            name="fleet-dashboard-prune",
        )
        self._prune_thread.start()
        self._logger.info("Fleet Dashboard plugin started")

    def _on_stop(self) -> None:
        if self._prune_thread and self._prune_thread.is_alive():
            self._prune_thread.join(timeout=2.0)
        self._logger.info("Fleet Dashboard plugin stopped")

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "fleet.heartbeat":
            self._on_heartbeat(data)
        elif event_type == "edge:ble_update":
            self._on_ble_update(data)

    # -- Device registry ---------------------------------------------------

    def get_devices(self) -> list[dict]:
        """Return list of all tracked devices with computed status."""
        now = time.time()
        with self._lock:
            result = []
            for dev in self._devices.values():
                entry = dict(dev)
                age = now - entry.get("last_seen", 0)
                if age > 180:
                    entry["status"] = "offline"
                elif age > 60:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "online"
                result.append(entry)
            return result

    def get_device(self, device_id: str) -> Optional[dict]:
        """Return a single device by ID, or None."""
        now = time.time()
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            entry = dict(dev)
            age = now - entry.get("last_seen", 0)
            if age > 180:
                entry["status"] = "offline"
            elif age > 60:
                entry["status"] = "stale"
            else:
                entry["status"] = "online"
            return entry

    def get_target_history(self, device_id: str) -> list[dict]:
        """Return target count history for sparkline rendering."""
        with self._lock:
            return list(self._target_history.get(device_id, []))

    def get_all_target_histories(self) -> dict[str, list[dict]]:
        """Return target count histories for all devices."""
        with self._lock:
            return {did: list(h) for did, h in self._target_history.items()}

    def get_topology(self) -> dict:
        """Build network topology from device registry for comm-link visualization.

        Returns nodes (fleet devices with positions) and links (peer connections
        extracted from heartbeat mesh_peers data).
        """
        devices = self.get_devices()
        nodes = []
        links = []
        seen_edges: set[tuple[str, str]] = set()

        for dev in devices:
            did = dev.get("device_id", "")
            nodes.append({
                "node_id": did,
                "name": dev.get("name", did),
                "ip": dev.get("ip", ""),
                "online": dev.get("status") == "online",
                "battery": dev.get("battery"),
                "peer_count": 0,
                # Position: use stored lat/lng or derive from x/y
                "x": dev.get("x", 0),
                "y": dev.get("y", 0),
                "lat": dev.get("lat"),
                "lng": dev.get("lng"),
            })

        # Extract peer links from heartbeat mesh_peers data
        with self._lock:
            for did, dev in self._devices.items():
                peers = dev.get("mesh_peers", [])
                if not peers:
                    continue

                # Update node peer_count
                for node in nodes:
                    if node["node_id"] == did:
                        node["peer_count"] = len(peers)
                        break

                for peer in peers:
                    peer_mac = peer.get("mac", "")
                    if not peer_mac:
                        continue

                    # Dedup edges (A->B == B->A)
                    edge_key = tuple(sorted((did, peer_mac)))
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    quality = peer.get("quality", {})
                    links.append({
                        "source_id": did,
                        "target_id": peer_mac,
                        "transport": "espnow",
                        "rssi": peer.get("rssi"),
                        "quality_score": quality.get("score", 0) if isinstance(quality, dict) else 0,
                        "packet_loss_pct": quality.get("pkt_loss", 0) if isinstance(quality, dict) else 0,
                        "active": True,
                    })

        return {
            "nodes": nodes,
            "links": links,
            "node_count": len(nodes),
            "link_count": len(links),
        }

    def get_summary(self) -> dict:
        """Return fleet summary: counts by status, avg battery, total sightings."""
        devices = self.get_devices()
        online = sum(1 for d in devices if d["status"] == "online")
        stale = sum(1 for d in devices if d["status"] == "stale")
        offline = sum(1 for d in devices if d["status"] == "offline")
        batteries = [
            d["battery"] for d in devices
            if d.get("battery") is not None
        ]
        avg_battery = (
            round(sum(batteries) / len(batteries), 1)
            if batteries else None
        )
        total_ble = sum(d.get("ble_count", 0) for d in devices)
        total_wifi = sum(d.get("wifi_count", 0) for d in devices)
        return {
            "total": len(devices),
            "online": online,
            "stale": stale,
            "offline": offline,
            "avg_battery": avg_battery,
            "total_ble_sightings": total_ble,
            "total_wifi_sightings": total_wifi,
        }

    # -- Event handling ----------------------------------------------------

    def _on_heartbeat(self, data: dict) -> None:
        device_id = data.get("device_id", data.get("id", data.get("node_id")))
        if not device_id:
            return

        now = time.time()
        with self._lock:
            existing = self._devices.get(device_id, {})
            existing.update({
                "device_id": device_id,
                "name": data.get("name", data.get("hostname", existing.get("name", device_id))),
                "ip": data.get("ip", existing.get("ip", "")),
                "battery": data.get("battery_pct", data.get("battery", existing.get("battery"))),
                "uptime": data.get("uptime_s", data.get("uptime", existing.get("uptime"))),
                "ble_count": data.get("ble_count", data.get("ble_device_count", existing.get("ble_count", 0))),
                "wifi_count": data.get("wifi_count", data.get("wifi_network_count", existing.get("wifi_count", 0))),
                "free_heap": data.get("free_heap", existing.get("free_heap")),
                "firmware": data.get("version", data.get("firmware", existing.get("firmware", ""))),
                "rssi": data.get("rssi", data.get("wifi_rssi", existing.get("rssi"))),
                "last_seen": now,
            })
            # Store mesh peer data for topology visualization
            mesh_peers = data.get("mesh_peers", data.get("peers", []))
            if mesh_peers:
                existing["mesh_peers"] = mesh_peers
            self._devices[device_id] = existing

            # Record target count for sparkline history
            target_count = existing.get("ble_count", 0) + existing.get("wifi_count", 0)
            if device_id not in self._target_history:
                self._target_history[device_id] = []
            history = self._target_history[device_id]
            history.append({"ts": now, "count": target_count})
            # Trim to max length
            if len(history) > TARGET_HISTORY_MAXLEN:
                self._target_history[device_id] = history[-TARGET_HISTORY_MAXLEN:]

    def _on_ble_update(self, data: dict) -> None:
        """Handle edge:ble_update — update BLE counts for relevant devices."""
        count = data.get("count", 0)
        devices = data.get("devices", [])

        # Try to attribute BLE count to a specific device
        node_ids = set()
        for dev in devices:
            nid = dev.get("node_id")
            if nid:
                node_ids.add(nid)

        now = time.time()
        with self._lock:
            for nid in node_ids:
                if nid in self._devices:
                    self._devices[nid]["ble_count"] = count
                    self._devices[nid]["last_seen"] = now

    # -- Pruning -----------------------------------------------------------

    def _prune_loop(self) -> None:
        while self._running:
            time.sleep(30)
            self._prune_stale()

    def _prune_stale(self) -> None:
        now = time.time()
        with self._lock:
            stale_ids = [
                did for did, dev in self._devices.items()
                if now - dev.get("last_seen", 0) > PRUNE_TIMEOUT_S
            ]
            for did in stale_ids:
                del self._devices[did]
                log.debug("Pruned stale device: %s", did)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
