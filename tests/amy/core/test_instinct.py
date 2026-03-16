# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for amy.brain.instinct — L2 autonomous response layer."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from amy.brain.instinct import InstinctLayer


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._subs: list[queue.Queue] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.published.append((event_type, data or {}))
        msg = {"type": event_type, "data": data or {}}
        for q in self._subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        self._subs.append(q)
        return q

    def unsubscribe(self, q) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass


class MockSensorium:
    def __init__(self):
        self.pushed: list[tuple[str, str]] = []

    def push(self, channel: str, text: str, importance: float = 0.5):
        self.pushed.append((channel, text))


class MockTrackedTarget:
    def __init__(
        self,
        target_id: str,
        alliance: str = "friendly",
        position: tuple[float, float] = (0.0, 0.0),
        battery: float = 1.0,
        status: str = "active",
        name: str = "Unit",
        asset_type: str = "rover",
    ):
        self.target_id = target_id
        self.alliance = alliance
        self.position = position
        self.battery = battery
        self.status = status
        self.name = name
        self.asset_type = asset_type


class MockTargetTracker:
    def __init__(self, targets: list | None = None):
        self._targets: list[MockTrackedTarget] = targets or []

    def get_all(self):
        return list(self._targets)

    def get_target(self, target_id):
        for t in self._targets:
            if t.target_id == target_id:
                return t
        return None

    def get_friendlies(self):
        return [t for t in self._targets if t.alliance == "friendly"]

    def get_hostiles(self):
        return [t for t in self._targets if t.alliance == "hostile"]


class MockSimTarget:
    def __init__(self, target_id, name="Unit", asset_type="rover",
                 position=(0, 0), alliance="friendly"):
        self.target_id = target_id
        self.name = name
        self.asset_type = asset_type
        self.position = position
        self.alliance = alliance
        self.waypoints = []
        self._waypoint_index = 0
        self.loop_waypoints = True
        self.status = "idle"


class MockSimEngine:
    def __init__(self, targets=None):
        self._targets = {t.target_id: t for t in (targets or [])}

    def get_target(self, target_id):
        return self._targets.get(target_id)


class MockInvestigation:
    def __init__(self, inv_id="inv-001"):
        self.inv_id = inv_id


class MockInvestigationEngine:
    def __init__(self):
        self.investigations_created: list = []

    def auto_investigate_threat(self, dossier_id, threat_level, dossier_name=""):
        inv = MockInvestigation()
        self.investigations_created.append({
            "dossier_id": dossier_id,
            "threat_level": threat_level,
            "dossier_name": dossier_name,
        })
        return inv


class MockDossierManager:
    def __init__(self, dossiers=None):
        self._dossiers = dossiers or {}

    def get_dossier_for_target(self, target_id):
        return self._dossiers.get(target_id)


class MockCommander:
    """Minimal commander mock for instinct layer tests."""

    def __init__(self):
        self.event_bus = MockEventBus()
        self.sensorium = MockSensorium()
        self.target_tracker = MockTargetTracker()
        self.simulation_engine = None
        self.mqtt_bridge = None
        self.dossier_manager = None
        self.investigation_engine = None
        self.instinct_layer = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def commander():
    return MockCommander()


@pytest.fixture
def instinct(commander):
    layer = InstinctLayer(commander)
    yield layer
    layer.stop()


# ===================================================================
# Lifecycle tests
# ===================================================================


class TestInstinctLifecycle:
    @pytest.mark.unit
    def test_start_stop(self, commander):
        layer = InstinctLayer(commander)
        layer.start()
        assert layer._running is True
        layer.stop()
        assert layer._running is False

    @pytest.mark.unit
    def test_double_start_is_idempotent(self, commander):
        layer = InstinctLayer(commander)
        layer.start()
        layer.start()  # Should not crash
        assert layer._running is True
        layer.stop()


# ===================================================================
# Watch list tests
# ===================================================================


class TestWatchList:
    @pytest.mark.unit
    def test_add_and_check(self, instinct):
        instinct.add_to_watch_list("AA:BB:CC:DD:EE:FF")
        assert instinct.is_on_watch_list("AA:BB:CC:DD:EE:FF")

    @pytest.mark.unit
    def test_remove(self, instinct):
        instinct.add_to_watch_list("AA:BB:CC:DD:EE:FF")
        instinct.remove_from_watch_list("AA:BB:CC:DD:EE:FF")
        assert not instinct.is_on_watch_list("AA:BB:CC:DD:EE:FF")

    @pytest.mark.unit
    def test_case_insensitive(self, instinct):
        instinct.add_to_watch_list("aa:bb:cc:dd:ee:ff")
        assert instinct.is_on_watch_list("AA:BB:CC:DD:EE:FF")

    @pytest.mark.unit
    def test_watch_list_property_returns_copy(self, instinct):
        instinct.add_to_watch_list("AA:BB:CC:DD:EE:FF")
        wl = instinct.watch_list
        wl.add("FAKE")
        assert "FAKE" not in instinct.watch_list


# ===================================================================
# Threat escalation handler tests
# ===================================================================


class TestThreatEscalationHandler:
    @pytest.mark.unit
    def test_creates_investigation_on_hostile(self, commander):
        """When threat reaches hostile and dossier exists, create investigation."""
        commander.dossier_manager = MockDossierManager({
            "target-01": {"dossier_id": "d-001", "name": "Suspect Alpha"},
        })
        commander.investigation_engine = MockInvestigationEngine()
        commander.target_tracker = MockTargetTracker([
            MockTrackedTarget("target-01", alliance="hostile", name="Suspect Alpha"),
        ])

        layer = InstinctLayer(commander)
        layer._on_threat_escalation({
            "target_id": "target-01",
            "new_level": "hostile",
            "old_level": "suspicious",
        })

        assert len(commander.investigation_engine.investigations_created) == 1
        assert commander.investigation_engine.investigations_created[0]["dossier_id"] == "d-001"
        assert layer.response_count >= 1

    @pytest.mark.unit
    def test_skips_non_hostile(self, commander):
        """Only hostile escalations trigger investigation."""
        commander.dossier_manager = MockDossierManager({
            "target-01": {"dossier_id": "d-001", "name": "Test"},
        })
        commander.investigation_engine = MockInvestigationEngine()

        layer = InstinctLayer(commander)
        layer._on_threat_escalation({
            "target_id": "target-01",
            "new_level": "suspicious",
        })

        assert len(commander.investigation_engine.investigations_created) == 0

    @pytest.mark.unit
    def test_respects_cooldown(self, commander):
        """Same target should not trigger investigation within cooldown."""
        commander.dossier_manager = MockDossierManager({
            "t1": {"dossier_id": "d1", "name": "Test"},
        })
        commander.investigation_engine = MockInvestigationEngine()
        commander.target_tracker = MockTargetTracker([
            MockTrackedTarget("t1", alliance="hostile", name="Test"),
        ])

        layer = InstinctLayer(commander)
        layer._on_threat_escalation({"target_id": "t1", "new_level": "hostile"})
        layer._on_threat_escalation({"target_id": "t1", "new_level": "hostile"})

        # Second call should be suppressed by cooldown
        assert len(commander.investigation_engine.investigations_created) == 1

    @pytest.mark.unit
    def test_narrates_in_sensorium(self, commander):
        """Escalation should push a thought to the sensorium."""
        commander.target_tracker = MockTargetTracker([
            MockTrackedTarget("t1", alliance="hostile", name="Intruder"),
        ])

        layer = InstinctLayer(commander)
        layer._on_threat_escalation({"target_id": "t1", "new_level": "hostile"})

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert any("hostile" in t.lower() for t in thoughts)


# ===================================================================
# Geofence handler tests
# ===================================================================


class TestGeofenceHandler:
    @pytest.mark.unit
    def test_dispatches_on_restricted_zone(self, commander):
        """Restricted zone entry should dispatch nearest asset."""
        rover = MockTrackedTarget("rover-01", position=(5, 5), asset_type="rover")
        commander.target_tracker = MockTargetTracker([rover])

        sim_target = MockSimTarget("rover-01", position=(5, 5))
        commander.simulation_engine = MockSimEngine([sim_target])

        layer = InstinctLayer(commander)
        layer._on_geofence_enter({
            "target_id": "intruder-01",
            "zone_type": "restricted",
            "zone_name": "Server Room",
            "zone_id": "zone-1",
            "position": [10, 10],
        })

        # Should dispatch rover-01
        dispatches = [
            (t, d) for t, d in commander.event_bus.published
            if t == "amy_dispatch"
        ]
        assert len(dispatches) >= 1
        assert layer.response_count >= 1

    @pytest.mark.unit
    def test_notes_monitored_zone_without_dispatch(self, commander):
        """Monitored zone entry should just note it, not dispatch."""
        layer = InstinctLayer(commander)
        layer._on_geofence_enter({
            "target_id": "visitor-01",
            "zone_type": "monitored",
            "zone_name": "Front Yard",
            "zone_id": "zone-2",
            "position": [20, 20],
        })

        dispatches = [
            (t, d) for t, d in commander.event_bus.published
            if t == "amy_dispatch"
        ]
        assert len(dispatches) == 0

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert any("Front Yard" in t for t in thoughts)

    @pytest.mark.unit
    def test_respects_geofence_cooldown(self, commander):
        """Same target/zone combo should not re-dispatch within cooldown."""
        rover = MockTrackedTarget("rover-01", position=(5, 5))
        commander.target_tracker = MockTargetTracker([rover])
        commander.simulation_engine = MockSimEngine([
            MockSimTarget("rover-01", position=(5, 5)),
        ])

        layer = InstinctLayer(commander)
        data = {
            "target_id": "intruder-01",
            "zone_type": "restricted",
            "zone_name": "Lab",
            "zone_id": "zone-3",
            "position": [10, 10],
        }
        layer._on_geofence_enter(data)
        initial_dispatches = len([
            (t, d) for t, d in commander.event_bus.published
            if t == "amy_dispatch"
        ])

        layer._on_geofence_enter(data)
        after_dispatches = len([
            (t, d) for t, d in commander.event_bus.published
            if t == "amy_dispatch"
        ])

        assert after_dispatches == initial_dispatches

    @pytest.mark.unit
    def test_handles_dict_position(self, commander):
        """Position can be dict with x/y keys."""
        layer = InstinctLayer(commander)
        layer._on_geofence_enter({
            "target_id": "x",
            "zone_type": "monitored",
            "zone_name": "Test",
            "zone_id": "z",
            "position": {"x": 5, "y": 10},
        })
        # Should not crash
        assert layer.response_count >= 1


# ===================================================================
# BLE alert handler tests
# ===================================================================


class TestBLEAlertHandler:
    @pytest.mark.unit
    def test_adds_suspicious_to_watch_list(self, commander):
        """Suspicious BLE device should be added to watch list."""
        layer = InstinctLayer(commander)
        layer._on_ble_alert({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Unknown Phone",
            "rssi": -35,
            "level": "suspicious",
        })

        assert layer.is_on_watch_list("AA:BB:CC:DD:EE:FF")
        assert layer.response_count >= 1

        watchlist_events = [
            (t, d) for t, d in commander.event_bus.published
            if t == "watchlist_add"
        ]
        assert len(watchlist_events) >= 1

    @pytest.mark.unit
    def test_notes_new_strong_device(self, commander):
        """New BLE device with strong signal should be noted."""
        layer = InstinctLayer(commander)
        layer._on_ble_alert({
            "mac": "11:22:33:44:55:66",
            "name": "New Device",
            "rssi": -40,
            "level": "new",
        })

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert any("New BLE device" in t for t in thoughts)

    @pytest.mark.unit
    def test_already_watching_updates_sensorium(self, commander):
        """Re-alerting on a watched device should update surveillance note."""
        layer = InstinctLayer(commander)
        layer.add_to_watch_list("AA:BB:CC:DD:EE:FF")

        # Reset cooldown for this test
        layer._last_ble_watchlist.clear()

        layer._on_ble_alert({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "Known Suspect",
            "rssi": -30,
            "level": "suspicious",
        })

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert any("Watch list device" in t or "surveillance" in t.lower() for t in thoughts)

    @pytest.mark.unit
    def test_respects_cooldown(self, commander):
        """Same MAC should not re-alert within cooldown."""
        layer = InstinctLayer(commander)
        layer._on_ble_alert({
            "mac": "AA:BB:CC:DD:EE:FF",
            "level": "suspicious",
            "rssi": -35,
        })
        initial_count = layer.response_count

        layer._on_ble_alert({
            "mac": "AA:BB:CC:DD:EE:FF",
            "level": "suspicious",
            "rssi": -35,
        })

        assert layer.response_count == initial_count


# ===================================================================
# Correlation handler tests
# ===================================================================


class TestCorrelationHandler:
    @pytest.mark.unit
    def test_narrates_correlation(self, commander):
        """Correlation events should produce inner monologue narration."""
        layer = InstinctLayer(commander)
        layer._on_correlation({
            "primary_id": "camera-01-person",
            "secondary_id": "ble-phone-01",
            "confidence": 0.85,
            "reason": "spatial",
            "primary_name": "Person near camera-01",
            "secondary_name": "iPhone SE",
            "primary_source": "camera",
            "secondary_source": "ble",
        })

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert len(thoughts) >= 1
        assert any("85%" in t for t in thoughts)

        narrated = [
            (t, d) for t, d in commander.event_bus.published
            if t == "correlation_narrated"
        ]
        assert len(narrated) >= 1

    @pytest.mark.unit
    def test_respects_correlation_cooldown(self, commander):
        """Rapid correlations should be throttled."""
        layer = InstinctLayer(commander)
        layer._on_correlation({
            "primary_id": "a",
            "secondary_id": "b",
            "confidence": 0.9,
            "reason": "spatial",
        })
        initial_count = layer.response_count

        layer._on_correlation({
            "primary_id": "c",
            "secondary_id": "d",
            "confidence": 0.8,
            "reason": "temporal",
        })

        assert layer.response_count == initial_count


# ===================================================================
# Correlation narration builder tests
# ===================================================================


class TestCorrelationNarration:
    @pytest.mark.unit
    def test_ble_camera_narration(self, instinct):
        text = instinct._build_correlation_narration(
            "Person A", "Phone B", 0.9, "spatial",
            {"primary_source": "camera", "secondary_source": "ble"},
        )
        assert "BLE device" in text
        assert "Phone B" in text
        assert "90%" in text

    @pytest.mark.unit
    def test_spatial_narration(self, instinct):
        text = instinct._build_correlation_narration(
            "Target A", "Target B", 0.75, "spatial",
            {"primary_source": "", "secondary_source": ""},
        )
        assert "co-located" in text.lower() or "spatial" in text.lower()

    @pytest.mark.unit
    def test_temporal_narration(self, instinct):
        text = instinct._build_correlation_narration(
            "Target A", "Target B", 0.6, "temporal",
            {"primary_source": "", "secondary_source": ""},
        )
        assert "temporal" in text.lower() or "move together" in text.lower()

    @pytest.mark.unit
    def test_generic_narration(self, instinct):
        text = instinct._build_correlation_narration(
            "Foo", "Bar", 0.5, "",
            {},
        )
        assert "Foo" in text
        assert "Bar" in text
        assert "50%" in text


# ===================================================================
# Integration: event-driven via EventBus
# ===================================================================


class TestInstinctEventDriven:
    @pytest.mark.unit
    def test_processes_event_from_bus(self, commander):
        """Instinct layer should pick up events published to the bus."""
        commander.target_tracker = MockTargetTracker([
            MockTrackedTarget("t1", alliance="hostile", name="Hostile"),
        ])

        layer = InstinctLayer(commander)
        layer.start()
        time.sleep(0.1)  # Let thread start

        # Publish a threat escalation event
        commander.event_bus.publish("threat_escalation", {
            "target_id": "t1",
            "new_level": "hostile",
            "old_level": "suspicious",
        })

        # Give the instinct thread time to process
        time.sleep(0.3)
        layer.stop()

        thoughts = [t for ch, t in commander.sensorium.pushed if ch == "thought"]
        assert any("hostile" in t.lower() for t in thoughts)
