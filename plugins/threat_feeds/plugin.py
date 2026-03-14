# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ThreatFeedPlugin — known-bad indicator intelligence for BLE/WiFi devices.

Loads threat indicators from JSON/CSV feeds and checks every new device
against the known-bad list. Matches auto-escalate threat level and publish
alerts on the EventBus.

Registers as an enrichment provider so the EnrichmentPipeline automatically
checks new targets.
"""

from __future__ import annotations

import logging
import os
import queue as queue_mod
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .feeds import ThreatFeedManager, seed_default_indicators

log = logging.getLogger("threat-feeds")


class ThreatFeedPlugin(PluginInterface):
    """Threat intelligence feed plugin.

    Checks BLE/WiFi devices against known-bad indicator feeds.
    Auto-escalates threats and publishes alerts.
    """

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._manager: Optional[ThreatFeedManager] = None
        self._enrichment_pipeline: Any = None

        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

    # -- PluginInterface identity ----------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.threat-feeds"

    @property
    def name(self) -> str:
        return "Threat Feeds"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- PluginInterface lifecycle ---------------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        """Initialize ThreatFeedManager, register routes and enrichment."""
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._logger = ctx.logger or log

        # Initialize manager with data directory
        data_dir = os.path.join(os.getcwd(), "data", "threat_feeds")
        self._manager = ThreatFeedManager(data_dir=data_dir)

        # Seed default indicators if the store is empty
        if self._manager.count == 0:
            count = seed_default_indicators(self._manager)
            self._logger.info("Seeded %d default threat indicators", count)

        # Register enrichment provider if pipeline is available
        try:
            from engine.tactical.enrichment import EnrichmentPipeline
            # The pipeline instance may be on the plugin manager or context
            pm = ctx.plugin_manager
            if pm is not None and hasattr(pm, "enrichment_pipeline"):
                pipeline = pm.enrichment_pipeline
                if pipeline is not None:
                    pipeline.register_provider(
                        "threat_feed",
                        self._manager.enrichment_provider,
                    )
                    self._enrichment_pipeline = pipeline
                    self._logger.info("Registered threat feed enrichment provider")
        except Exception as exc:
            self._logger.debug("Enrichment pipeline not available: %s", exc)

        # Register FastAPI routes
        self._register_routes()

        self._logger.info(
            "Threat Feed plugin configured with %d indicators",
            self._manager.count,
        )

    def start(self) -> None:
        """Start background event listener for BLE/WiFi device events."""
        if self._running:
            return
        self._running = True

        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="threat-feed-events",
            )
            self._event_thread.start()

        self._logger.info("Threat Feed plugin started")

    def stop(self) -> None:
        """Clean up resources."""
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._logger.info("Threat Feed plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    @property
    def manager(self) -> ThreatFeedManager | None:
        """Expose manager for direct access (testing, CLI, etc.)."""
        return self._manager

    # -- Event handling --------------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Background loop: check new devices against threat feeds."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._handle_event(event)
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Threat feed event error: %s", exc)

    def _handle_event(self, event: dict) -> None:
        """Process a single EventBus event — check new devices."""
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type in ("ble:new_device", "edge:ble_update"):
            self._check_ble_event(data)
        elif event_type in ("edge:wifi_update",):
            self._check_wifi_event(data)
        elif event_type == "fleet.heartbeat":
            self._check_heartbeat(data)

    def _check_ble_event(self, data: dict) -> None:
        """Check BLE devices against threat feeds."""
        if self._manager is None:
            return

        devices = data.get("devices", [])
        for dev in devices:
            mac = dev.get("mac", "")
            name = dev.get("name", "")

            if mac:
                match = self._manager.check_mac(mac)
                if match:
                    self._publish_alert(match, dev)
                    continue

            if name:
                match = self._manager.check("device_name", name)
                if match:
                    self._publish_alert(match, dev)

    def _check_wifi_event(self, data: dict) -> None:
        """Check WiFi networks against threat feeds."""
        if self._manager is None:
            return

        networks = data.get("networks", [])
        for net in networks:
            ssid = net.get("ssid", "")
            if ssid:
                match = self._manager.check_ssid(ssid)
                if match:
                    self._publish_alert(match, net)

    def _check_heartbeat(self, data: dict) -> None:
        """Check heartbeat BLE/WiFi data against threat feeds."""
        if self._manager is None:
            return

        ble_data = data.get("ble", data.get("ble_devices", []))
        for dev in ble_data:
            mac = dev.get("mac", "")
            if mac:
                match = self._manager.check_mac(mac)
                if match:
                    self._publish_alert(match, dev)

        wifi_data = data.get("wifi", data.get("wifi_networks", []))
        for net in wifi_data:
            ssid = net.get("ssid", "")
            if ssid:
                match = self._manager.check_ssid(ssid)
                if match:
                    self._publish_alert(match, net)

    def _publish_alert(self, indicator: Any, device_data: dict) -> None:
        """Publish a threat alert on the EventBus."""
        if self._event_bus is None:
            return

        alert = {
            "indicator": indicator.to_dict(),
            "device": device_data,
            "timestamp": time.time(),
        }

        self._event_bus.publish("threat:indicator_match", data=alert)
        log.warning(
            "THREAT MATCH: %s=%s (%s) — %s",
            indicator.indicator_type,
            indicator.value,
            indicator.threat_level,
            indicator.description,
        )

    # -- HTTP routes -----------------------------------------------------------

    def _register_routes(self) -> None:
        """Register FastAPI routes for threat feed management."""
        if not self._app or not self._manager:
            return

        from .routes import create_router

        router = create_router(self._manager)
        self._app.include_router(router)
