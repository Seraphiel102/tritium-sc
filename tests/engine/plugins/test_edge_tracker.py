# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Edge Tracker plugin — BLE/WiFi device tracking."""

import logging
import queue
import time
from unittest.mock import MagicMock, patch

import pytest

from engine.plugins.base import PluginContext, PluginInterface


def _make_plugin():
    """Import and instantiate EdgeTrackerPlugin."""
    from plugins.edge_tracker.plugin import EdgeTrackerPlugin
    return EdgeTrackerPlugin()


def _make_ctx(event_bus=None, tracker=None, app=None):
    """Build a minimal PluginContext with mocks."""
    return PluginContext(
        event_bus=event_bus or MagicMock(),
        target_tracker=tracker or MagicMock(),
        simulation_engine=None,
        settings={},
        app=app,
        logger=logging.getLogger("test-edge-tracker"),
        plugin_manager=MagicMock(),
    )


# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerIdentity:
    """Verify plugin metadata and interface compliance."""

    def test_implements_plugin_interface(self):
        plugin = _make_plugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_id(self):
        plugin = _make_plugin()
        assert plugin.plugin_id == "tritium.edge-tracker"

    def test_name(self):
        plugin = _make_plugin()
        assert plugin.name == "Edge Tracker"

    def test_version(self):
        plugin = _make_plugin()
        assert plugin.version == "1.0.0"

    def test_capabilities(self):
        plugin = _make_plugin()
        caps = plugin.capabilities
        assert "bridge" in caps
        assert "data_source" in caps
        assert "routes" in caps
        assert "ui" in caps


# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerConfigure:
    """Verify configure() wires up dependencies."""

    def test_configure_stores_event_bus(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        assert plugin._event_bus is bus

    def test_configure_stores_target_tracker(self):
        plugin = _make_plugin()
        tracker = MagicMock()
        ctx = _make_ctx(tracker=tracker)
        plugin.configure(ctx)
        assert plugin._tracker is tracker

    def test_configure_initializes_ble_classifier(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        assert plugin._ble_classifier is not None

    def test_configure_initializes_trilateration(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        assert plugin._trilateration is not None

    def test_configure_initializes_handoff_tracker(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        assert plugin._handoff_tracker is not None

    def test_configure_without_app_skips_routes(self):
        """No crash if app is None."""
        plugin = _make_plugin()
        ctx = _make_ctx(app=None)
        plugin.configure(ctx)
        # Just verifying no exception raised


# ---------------------------------------------------------------------------
# Start / stop lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerLifecycle:
    """Verify start/stop lifecycle and health reporting."""

    def test_not_healthy_before_start(self):
        plugin = _make_plugin()
        assert plugin.healthy is False

    def test_start_sets_running(self):
        plugin = _make_plugin()
        bus = MagicMock()
        bus.subscribe.return_value = queue.Queue()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        plugin.start()
        assert plugin.healthy is True
        plugin.stop()

    def test_stop_clears_running(self):
        plugin = _make_plugin()
        bus = MagicMock()
        bus.subscribe.return_value = queue.Queue()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        plugin.start()
        plugin.stop()
        assert plugin.healthy is False

    def test_double_start_is_safe(self):
        plugin = _make_plugin()
        bus = MagicMock()
        bus.subscribe.return_value = queue.Queue()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        plugin.start()
        plugin.start()  # second call should be a no-op
        assert plugin.healthy is True
        plugin.stop()

    def test_double_stop_is_safe(self):
        plugin = _make_plugin()
        bus = MagicMock()
        bus.subscribe.return_value = queue.Queue()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        plugin.start()
        plugin.stop()
        plugin.stop()  # second call should be a no-op
        assert plugin.healthy is False

    def test_stop_unsubscribes_event_bus(self):
        plugin = _make_plugin()
        bus = MagicMock()
        q = queue.Queue()
        bus.subscribe.return_value = q
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        plugin.start()
        plugin.stop()
        bus.unsubscribe.assert_called_once_with(q)

    def test_stop_closes_ble_store(self):
        plugin = _make_plugin()
        bus = MagicMock()
        bus.subscribe.return_value = queue.Queue()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        mock_store = MagicMock()
        plugin._store = mock_store
        plugin.start()
        plugin.stop()
        mock_store.close.assert_called_once()


# ---------------------------------------------------------------------------
# BLE presence handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerBlePresence:
    """Verify BLE presence event processing."""

    def _configured_plugin(self):
        plugin = _make_plugin()
        bus = MagicMock()
        tracker = MagicMock()
        ctx = _make_ctx(event_bus=bus, tracker=tracker)
        plugin.configure(ctx)
        # Inject a mock store so persistence calls succeed
        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = [
            {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65, "node_id": "node-1"},
        ]
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store
        return plugin, bus, tracker, mock_store

    def test_ble_presence_records_sightings(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_ble_presence({
            "node_id": "node-1",
            "node_ip": "10.0.0.1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        store.record_sightings_batch.assert_called_once()
        batch = store.record_sightings_batch.call_args[0][0]
        assert len(batch) == 1
        assert batch[0]["mac"] == "AA:BB:CC:DD:EE:FF"
        assert batch[0]["node_id"] == "node-1"

    def test_ble_presence_emits_update(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        bus.publish.assert_called()
        # Check that edge:ble_update was published
        call_args = [c[0] for c in bus.publish.call_args_list]
        assert any("edge:ble_update" in str(a) for a in call_args)

    def test_ble_presence_pushes_to_target_tracker(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        tracker.update_from_ble.assert_called_once()
        call_data = tracker.update_from_ble.call_args[0][0]
        assert call_data["mac"] == "AA:BB:CC:DD:EE:FF"

    def test_ble_presence_without_store_is_noop(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        plugin._store = None
        # Should not raise
        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [{"mac": "AA:BB:CC:DD:EE:FF", "rssi": -65}],
        })

    def test_ble_presence_empty_devices(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [],
        })
        store.record_sightings_batch.assert_not_called()

    def test_ble_presence_caches_edge_device_type(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "AirPods", "rssi": -55,
                 "device_type": "headphones"},
            ],
        })
        assert plugin._edge_device_types.get("AA:BB:CC:DD:EE:FF") == "headphones"


# ---------------------------------------------------------------------------
# WiFi presence handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerWifiPresence:
    """Verify WiFi presence event processing."""

    def _configured_plugin(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        mock_store = MagicMock()
        mock_store.get_active_wifi_networks.return_value = [
            {"ssid": "HomeNet", "bssid": "11:22:33:44:55:66", "rssi": -45},
        ]
        plugin._store = mock_store
        return plugin, bus, mock_store

    def test_wifi_presence_records_sightings(self):
        plugin, bus, store = self._configured_plugin()
        plugin._on_wifi_presence({
            "node_id": "node-1",
            "networks": [
                {"ssid": "HomeNet", "bssid": "11:22:33:44:55:66", "rssi": -45,
                 "channel": 6, "auth_type": "WPA2"},
            ],
        })
        store.record_wifi_sightings_batch.assert_called_once()
        batch = store.record_wifi_sightings_batch.call_args[0][0]
        assert len(batch) == 1
        assert batch[0]["ssid"] == "HomeNet"
        assert batch[0]["channel"] == 6

    def test_wifi_presence_emits_update(self):
        plugin, bus, store = self._configured_plugin()
        plugin._on_wifi_presence({
            "node_id": "node-1",
            "networks": [
                {"ssid": "HomeNet", "bssid": "11:22:33:44:55:66", "rssi": -45},
            ],
        })
        bus.publish.assert_called()
        call_args = [c[0] for c in bus.publish.call_args_list]
        assert any("edge:wifi_update" in str(a) for a in call_args)

    def test_wifi_presence_without_store_is_noop(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        plugin._store = None
        plugin._on_wifi_presence({
            "node_id": "node-1",
            "networks": [{"ssid": "Test", "bssid": "AA:BB:CC:DD:EE:FF", "rssi": -50}],
        })

    def test_wifi_presence_empty_networks(self):
        plugin, bus, store = self._configured_plugin()
        plugin._on_wifi_presence({
            "node_id": "node-1",
            "networks": [],
        })
        store.record_wifi_sightings_batch.assert_not_called()


# ---------------------------------------------------------------------------
# Heartbeat handling
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerHeartbeat:
    """Verify fleet heartbeat event processing."""

    def _configured_plugin(self):
        plugin = _make_plugin()
        bus = MagicMock()
        tracker = MagicMock()
        ctx = _make_ctx(event_bus=bus, tracker=tracker)
        plugin.configure(ctx)
        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_active_wifi_networks.return_value = []
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store
        return plugin, bus, tracker, mock_store

    def test_heartbeat_extracts_ble_data(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_fleet_heartbeat({
            "node_id": "tritium-01",
            "ip": "10.0.0.5",
            "ble": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Watch", "rssi": -70},
            ],
        })
        store.record_sightings_batch.assert_called_once()

    def test_heartbeat_extracts_wifi_data(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_fleet_heartbeat({
            "node_id": "tritium-01",
            "wifi": [
                {"ssid": "TestNet", "bssid": "11:22:33:44:55:66", "rssi": -50},
            ],
        })
        store.record_wifi_sightings_batch.assert_called_once()

    def test_heartbeat_both_ble_and_wifi(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_fleet_heartbeat({
            "node_id": "tritium-01",
            "ble": [{"mac": "AA:BB:CC:DD:EE:FF", "rssi": -70}],
            "wifi": [{"ssid": "Net", "bssid": "11:22:33:44:55:66", "rssi": -50}],
        })
        store.record_sightings_batch.assert_called_once()
        store.record_wifi_sightings_batch.assert_called_once()

    def test_heartbeat_no_sensor_data(self):
        plugin, bus, tracker, store = self._configured_plugin()
        plugin._on_fleet_heartbeat({
            "node_id": "tritium-01",
            "ip": "10.0.0.5",
        })
        store.record_sightings_batch.assert_not_called()
        store.record_wifi_sightings_batch.assert_not_called()

    def test_heartbeat_without_store_is_noop(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        plugin._store = None
        plugin._on_fleet_heartbeat({
            "node_id": "tritium-01",
            "ble": [{"mac": "AA:BB:CC:DD:EE:FF", "rssi": -70}],
        })


# ---------------------------------------------------------------------------
# Event routing via _handle_event
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerEventRouting:
    """Verify _handle_event dispatches to the correct handler."""

    def _configured_plugin(self):
        plugin = _make_plugin()
        ctx = _make_ctx()
        plugin.configure(ctx)
        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_active_wifi_networks.return_value = []
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store
        return plugin

    def test_routes_ble_presence(self):
        plugin = self._configured_plugin()
        with patch.object(plugin, "_on_ble_presence") as mock:
            plugin._handle_event({"type": "fleet.ble_presence", "data": {"devices": []}})
            mock.assert_called_once_with({"devices": []})

    def test_routes_wifi_presence(self):
        plugin = self._configured_plugin()
        with patch.object(plugin, "_on_wifi_presence") as mock:
            plugin._handle_event({"type": "fleet.wifi_presence", "data": {"networks": []}})
            mock.assert_called_once_with({"networks": []})

    def test_routes_heartbeat(self):
        plugin = self._configured_plugin()
        with patch.object(plugin, "_on_fleet_heartbeat") as mock:
            plugin._handle_event({"type": "fleet.heartbeat", "data": {"node_id": "n1"}})
            mock.assert_called_once_with({"node_id": "n1"})

    def test_routes_ble_interrogation(self):
        plugin = self._configured_plugin()
        with patch.object(plugin, "_on_ble_interrogation") as mock:
            plugin._handle_event({"type": "fleet.ble_interrogation", "data": {"mac": "AA:BB"}})
            mock.assert_called_once_with({"mac": "AA:BB"})

    def test_unknown_event_type_ignored(self):
        plugin = self._configured_plugin()
        # Should not raise
        plugin._handle_event({"type": "fleet.unknown_event", "data": {}})


# ---------------------------------------------------------------------------
# BLE classifier integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerBleClassifier:
    """Verify BLE classifier is invoked during presence events."""

    def test_classifier_called_for_each_device(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)
        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store

        mock_classifier = MagicMock()
        plugin._ble_classifier = mock_classifier

        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:01", "name": "Dev1", "rssi": -55},
                {"mac": "AA:BB:CC:DD:EE:02", "name": "Dev2", "rssi": -70},
            ],
        })
        assert mock_classifier.classify.call_count == 2


# ---------------------------------------------------------------------------
# Trilateration integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerTrilateration:
    """Verify trilateration engine receives sightings."""

    def test_trilateration_records_when_node_position_available(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)

        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_node_position.return_value = {
            "lat": 37.7749, "lon": -122.4194, "x": 0, "y": 0,
        }
        plugin._store = mock_store

        mock_trilat = MagicMock()
        mock_trilat.estimate_position.return_value = None
        plugin._trilateration = mock_trilat

        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        mock_trilat.record_sighting.assert_called_once()
        call_kwargs = mock_trilat.record_sighting.call_args[1]
        assert call_kwargs["mac"] == "AA:BB:CC:DD:EE:FF"
        assert call_kwargs["node_id"] == "node-1"
        assert call_kwargs["node_lat"] == 37.7749

    def test_trilateration_skipped_without_node_position(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)

        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store

        mock_trilat = MagicMock()
        plugin._trilateration = mock_trilat

        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        mock_trilat.record_sighting.assert_not_called()


# ---------------------------------------------------------------------------
# Handoff tracker integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeTrackerHandoff:
    """Verify handoff tracker receives BLE sightings."""

    def test_handoff_tracker_fed_on_ble_presence(self):
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)

        mock_store = MagicMock()
        mock_store.get_active_devices.return_value = []
        mock_store.get_node_position.return_value = None
        plugin._store = mock_store

        mock_handoff = MagicMock()
        plugin._handoff_tracker = mock_handoff

        plugin._on_ble_presence({
            "node_id": "node-1",
            "devices": [
                {"mac": "AA:BB:CC:DD:EE:FF", "name": "Phone", "rssi": -65},
            ],
        })
        mock_handoff.update_visibility.assert_called_once()
        call_kwargs = mock_handoff.update_visibility.call_args[1]
        assert call_kwargs["sensor_id"] == "node-1"
        assert "ble_aabbccddeeff" in call_kwargs["target_id"]

    def test_handoff_callback_publishes_event(self):
        from engine.tactical.target_handoff import HandoffEvent
        plugin = _make_plugin()
        bus = MagicMock()
        ctx = _make_ctx(event_bus=bus)
        plugin.configure(ctx)

        event = HandoffEvent(
            handoff_id="h1",
            target_id="ble_aabbccddeeff",
            from_sensor="node-1",
            to_sensor="node-2",
            gap_seconds=5.0,
            confidence=0.9,
        )
        plugin._on_target_handoff(event)
        bus.publish.assert_called_once()
        assert bus.publish.call_args[0][0] == "edge:target_handoff"
