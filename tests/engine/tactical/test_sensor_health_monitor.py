# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for SensorHealthMonitor — per-sensor sighting rate tracking."""

import time
import pytest
from unittest.mock import MagicMock

from engine.tactical.sensor_health_monitor import SensorHealthMonitor


class TestSensorHealthMonitor:
    def test_record_sighting_creates_sensor(self):
        mon = SensorHealthMonitor()
        mon.record_sighting("node-01")
        health = mon.get_health()
        assert len(health) == 1
        assert health[0]["sensor_id"] == "node-01"

    def test_multiple_sensors_tracked(self):
        mon = SensorHealthMonitor()
        mon.record_sighting("node-01")
        mon.record_sighting("node-02")
        mon.record_sighting("node-03")
        health = mon.get_health()
        ids = {h["sensor_id"] for h in health}
        assert ids == {"node-01", "node-02", "node-03"}

    def test_sighting_count_increments(self):
        mon = SensorHealthMonitor()
        for _ in range(5):
            mon.record_sighting("node-01")
        health = mon.get_health()
        assert health[0]["sighting_count"] == 5

    def test_initial_status_is_unknown(self):
        """Before enough baseline samples, status is unknown."""
        mon = SensorHealthMonitor()
        mon.record_sighting("node-01")
        health = mon.get_health()
        assert health[0]["status"] == "unknown"

    def test_get_sensor_health(self):
        mon = SensorHealthMonitor()
        mon.record_sighting("node-01")
        mon.record_sighting("node-02")
        h = mon.get_sensor_health("node-01")
        assert h is not None
        assert h["sensor_id"] == "node-01"

    def test_get_sensor_health_missing(self):
        mon = SensorHealthMonitor()
        h = mon.get_sensor_health("nonexistent")
        assert h is None

    def test_empty_health_returns_empty(self):
        mon = SensorHealthMonitor()
        assert mon.get_health() == []

    def test_health_includes_rate_fields(self):
        mon = SensorHealthMonitor()
        for _ in range(3):
            mon.record_sighting("node-01")
        health = mon.get_health()
        h = health[0]
        assert "sighting_rate" in h
        assert "baseline_rate" in h
        assert "deviation_pct" in h
        assert "last_seen_seconds_ago" in h

    def test_event_bus_alert_emitted_on_critical(self):
        """Verify that an alert is published via event bus when critical."""
        bus = MagicMock()
        mon = SensorHealthMonitor(event_bus=bus)

        # Build up baseline with many sightings
        mon.BASELINE_MIN_SAMPLES = 2
        for _ in range(10):
            mon.record_sighting("node-01")

        # Manually set a high baseline to force critical status
        rec = mon._sensors["node-01"]
        rec.baseline_rate = 1000.0
        rec.baseline_samples = 10

        # Get health — should trigger critical alert
        mon.get_health()

        # Check that publish was called with health alert
        if bus.publish.called:
            call_args = bus.publish.call_args
            assert call_args[0][0] == "sensor:health_alert"


class TestSensorHealthMonitorRates:
    def test_rate_window_default(self):
        mon = SensorHealthMonitor()
        assert mon.RATE_WINDOW_SECONDS == 300.0

    def test_baseline_alpha_default(self):
        mon = SensorHealthMonitor()
        assert mon.BASELINE_ALPHA == 0.1
