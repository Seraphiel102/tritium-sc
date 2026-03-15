# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""IndoorPositioningPlugin — WiFi fingerprint + BLE RSSI fusion.

Fuses WiFi fingerprint matching (kNN) with BLE RSSI trilateration
to produce accurate indoor position estimates. Integrates with the
floorplan plugin for room-level localization.

Listens for:
  - wifi_fingerprint.observation — WiFi RSSI scans
  - trilateration.position_estimate — BLE position estimates
  - fleet.ble_presence — BLE sightings with position

Publishes:
  - indoor_positioning.fused_position — fused position results
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from engine.plugins.base import EventDrainPlugin, PluginContext

from .fusion import IndoorPositionFusion
from .routes import create_router

log = logging.getLogger("indoor-positioning")


class IndoorPositioningPlugin(EventDrainPlugin):
    """WiFi fingerprint + BLE RSSI indoor position fusion plugin."""

    def __init__(self) -> None:
        super().__init__()
        self._fusion: Optional[IndoorPositionFusion] = None

    # -- PluginInterface identity ----------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.indoor-positioning"

    @property
    def name(self) -> str:
        return "Indoor Positioning"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes"}

    # -- EventDrainPlugin overrides --------------------------------------------

    def _on_configure(self, ctx: PluginContext) -> None:
        """Wire up trilateration engine and floorplan store, register routes."""
        # Get trilateration engine from plugin manager or context
        trilat_engine = None
        floorplan_store = None

        plugins = ctx.plugins if hasattr(ctx, "plugins") else {}

        # Try to get the trilateration engine from edge_tracker plugin
        edge_tracker = plugins.get("tritium.edge-tracker")
        if edge_tracker and hasattr(edge_tracker, "trilateration_engine"):
            trilat_engine = edge_tracker.trilateration_engine

        # Try to get the floorplan store from floorplan plugin
        floorplan = plugins.get("tritium.floorplan")
        if floorplan and hasattr(floorplan, "store"):
            floorplan_store = floorplan.store

        self._fusion = IndoorPositionFusion(
            trilateration_engine=trilat_engine,
            floorplan_store=floorplan_store,
        )

        # Register FastAPI routes
        if self._app is not None:
            router = create_router(self._fusion)
            self._app.include_router(router)
            self._logger.info("Indoor positioning routes registered")

        self._logger.info(
            "Indoor Positioning plugin configured (trilat=%s, floorplan=%s)",
            trilat_engine is not None,
            floorplan_store is not None,
        )

    def _on_start(self) -> None:
        self._logger.info("Indoor Positioning plugin started")

    def _on_stop(self) -> None:
        self._logger.info("Indoor Positioning plugin stopped")

    def _handle_event(self, event: dict) -> None:
        """Process events for indoor positioning fusion."""
        if self._fusion is None:
            return

        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "wifi_fingerprint.observation":
            self._handle_wifi_observation(data)
        elif event_type == "trilateration.position_estimate":
            self._handle_trilat_estimate(data)
        elif event_type == "fleet.ble_presence":
            self._handle_ble_presence(data)

    # -- Event handlers --------------------------------------------------------

    def _handle_wifi_observation(self, data: dict) -> None:
        """Store WiFi RSSI observation and attempt fusion."""
        target_id = data.get("target_id") or data.get("device_id", "")
        rssi_map = data.get("rssi_map", {})

        if not target_id or not rssi_map:
            return

        self._fusion.update_wifi_observation(target_id, rssi_map)

        # Attempt fusion immediately
        fused = self._fusion.estimate_position(target_id)
        if fused and self._event_bus:
            self._event_bus.publish({
                "type": "indoor_positioning.fused_position",
                "data": fused.to_dict(),
            })

    def _handle_trilat_estimate(self, data: dict) -> None:
        """Handle BLE trilateration estimate — attempt fusion."""
        target_id = data.get("target_id") or data.get("mac", "")
        if not target_id:
            return

        if not target_id.startswith("ble_"):
            target_id = f"ble_{target_id}"

        fused = self._fusion.estimate_position(target_id)
        if fused and self._event_bus:
            self._event_bus.publish({
                "type": "indoor_positioning.fused_position",
                "data": fused.to_dict(),
            })

    def _handle_ble_presence(self, data: dict) -> None:
        """Handle BLE presence — attempt fusion if position available."""
        mac = data.get("mac", "")
        if not mac:
            return

        target_id = f"ble_{mac}"
        fused = self._fusion.estimate_position(target_id)
        if fused and self._event_bus:
            self._event_bus.publish({
                "type": "indoor_positioning.fused_position",
                "data": fused.to_dict(),
            })

    # -- Public API ------------------------------------------------------------

    @property
    def fusion(self) -> Optional[IndoorPositionFusion]:
        return self._fusion
