# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TacticalEventStore — EventBus-integrated event persistence."""

import time
from unittest.mock import MagicMock, call

import pytest

from engine.tactical.event_store import TacticalEventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(event_bus=None, db_path=":memory:"):
    """Create a TacticalEventStore for testing."""
    return TacticalEventStore(
        event_bus=event_bus,
        db_path=db_path,
        site_id="test_site",
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_create(self):
        store = _make_store()
        assert store is not None
        store.close()

    def test_start_stop(self):
        store = _make_store()
        store.start()
        store.stop()
        store.close()

    def test_double_start(self):
        store = _make_store()
        store.start()
        store.start()  # no crash
        store.stop()
        store.close()

    def test_stop_before_start(self):
        store = _make_store()
        store.stop()  # no crash
        store.close()

    def test_close_stops_first(self):
        store = _make_store()
        store.start()
        store.close()  # should also stop


# ---------------------------------------------------------------------------
# Direct recording
# ---------------------------------------------------------------------------

class TestDirectRecording:
    def test_record_event(self):
        store = _make_store()
        eid = store.record(
            "target_sighting",
            source="ble_scanner",
            target_id="ble_AA:BB:CC:DD:EE:FF",
            summary="New BLE device detected",
            data={"rssi": -45},
        )
        assert len(eid) > 0
        store.close()

    def test_record_and_query(self):
        store = _make_store()
        store.record(
            "target_sighting",
            source="ble_scanner",
            target_id="ble_test",
            data={"rssi": -60},
        )
        events = store.query_time_range(limit=10)
        assert len(events) == 1
        assert events[0].event_type == "target_sighting"
        assert events[0].target_id == "ble_test"
        assert events[0].site_id == "test_site"
        store.close()

    def test_record_multiple_types(self):
        store = _make_store()
        store.record("target_sighting", target_id="t1")
        store.record("alert", severity="warning", target_id="t1")
        store.record("geofence_enter", target_id="t1")

        events = store.query_time_range(limit=100)
        assert len(events) == 3
        store.close()


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration:
    def test_subscribes_on_start(self):
        bus = MagicMock()
        bus.subscribe.return_value = "sub_handle"
        store = _make_store(event_bus=bus)
        store.start()

        assert bus.subscribe.call_count > 0
        store.close()

    def test_event_handler_persists(self):
        store = _make_store()
        store.start()

        # Simulate an event arriving via the handler
        store._on_event(
            "target_sighting",
            data={"source": "ble", "target_id": "ble_test", "rssi": -50},
        )

        events = store.query_time_range(limit=10)
        assert len(events) == 1
        assert events[0].event_type == "target_sighting"
        assert events[0].source == "ble"
        store.close()

    def test_event_handler_extracts_position(self):
        store = _make_store()
        store.start()

        store._on_event(
            "target_detected",
            data={"lat": 40.7128, "lng": -74.0060, "target_id": "det_1"},
        )

        events = store.query_time_range(limit=10)
        assert len(events) == 1
        assert events[0].position_lat == pytest.approx(40.7128, abs=0.001)
        assert events[0].position_lng == pytest.approx(-74.0060, abs=0.001)
        store.close()

    def test_not_started_ignores_events(self):
        store = _make_store()
        # Don't call start()
        store._on_event("target_sighting", data={"target_id": "t1"})
        events = store.query_time_range(limit=10)
        assert len(events) == 0
        store.close()


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestQueries:
    def _populated_store(self) -> TacticalEventStore:
        store = _make_store()
        now = time.time()
        store.record("target_sighting", target_id="t1", source="ble")
        store.record("target_sighting", target_id="t2", source="wifi")
        store.record("alert", target_id="t1", severity="warning", source="threat_classifier")
        store.record("geofence_enter", target_id="t2", source="geofence")
        store.record("target_correlation", target_id="t1", source="correlator")
        return store

    def test_query_by_type(self):
        store = self._populated_store()
        events = store.query_by_type("target_sighting")
        assert len(events) == 2
        store.close()

    def test_query_by_target(self):
        store = self._populated_store()
        events = store.query_by_target("t1")
        assert len(events) == 3  # sighting + alert + correlation
        store.close()

    def test_count(self):
        store = self._populated_store()
        assert store.count() == 5
        assert store.count(event_type="alert") == 1
        store.close()

    def test_get_stats(self):
        store = self._populated_store()
        stats = store.get_stats()
        assert stats["total_events"] == 5
        assert "target_sighting" in stats["by_type"]
        assert stats["by_type"]["target_sighting"] == 2
        store.close()


# ---------------------------------------------------------------------------
# Hourly breakdown and top targets
# ---------------------------------------------------------------------------

class TestAnalytics:
    def test_hourly_breakdown(self):
        store = _make_store()
        # Record events at known times
        now = time.time()
        store.record("target_sighting", target_id="t1")
        store.record("target_sighting", target_id="t2")

        hourly = store.get_hourly_breakdown()
        assert isinstance(hourly, dict)
        # At least one hour has events
        assert sum(hourly.values()) >= 2
        store.close()

    def test_top_targets(self):
        store = _make_store()
        store.record("target_sighting", target_id="t1")
        store.record("target_sighting", target_id="t1")
        store.record("target_sighting", target_id="t1")
        store.record("target_sighting", target_id="t2")

        top = store.get_top_targets(limit=10)
        assert len(top) == 2
        assert top[0]["target_id"] == "t1"
        assert top[0]["event_count"] == 3
        assert top[1]["target_id"] == "t2"
        assert top[1]["event_count"] == 1
        store.close()

    def test_top_targets_skips_empty(self):
        store = _make_store()
        store.record("state_change")  # no target_id
        top = store.get_top_targets()
        assert len(top) == 0
        store.close()

    def test_cleanup(self):
        store = _make_store()
        for i in range(10):
            store.record("target_sighting", target_id=f"t{i}")
        deleted = store.cleanup()
        assert deleted == 0  # within default limit
        store.close()
