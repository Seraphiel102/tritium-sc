# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for anomaly baseline awareness in the Sensorium.

Verifies that Amy's L3 awareness layer correctly processes RF anomaly
alerts and incorporates them into her narrative and thinking context.
"""

from __future__ import annotations

import time

import pytest

from amy.brain.sensorium import Sensorium


@pytest.mark.unit
class TestAnomalyAwareness:
    """Tests for RF anomaly integration in the sensorium."""

    def test_update_anomalies_stores_alerts(self):
        """update_anomalies() populates internal anomaly alerts."""
        s = Sensorium()
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 3,
                "baseline_mean": 10,
                "baseline_std": 2.0,
                "deviation_sigma": 3.5,
                "direction": "below",
                "severity": "high",
                "description": "ble_device_count is 3.5 sigma below baseline",
                "timestamp": time.time(),
            }
        ]
        s.update_anomalies(anomalies)
        assert len(s._anomaly_alerts) == 1
        assert s._anomaly_summary != ""

    def test_anomaly_context_returns_string(self):
        """anomaly_context() returns human-readable summary."""
        s = Sensorium()
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 3,
                "baseline_mean": 10,
                "baseline_std": 2.0,
                "deviation_sigma": 3.5,
                "direction": "below",
                "severity": "high",
                "description": "ble_device_count is 3.5 sigma below baseline",
                "timestamp": time.time(),
            }
        ]
        s.update_anomalies(anomalies)
        ctx = s.anomaly_context()
        assert "RF ANOMALY ALERT" in ctx
        assert "fewer BLE devices" in ctx

    def test_anomaly_context_empty_when_no_anomalies(self):
        """anomaly_context() returns empty string when no anomalies."""
        s = Sensorium()
        assert s.anomaly_context() == ""

    def test_anomaly_appears_in_rich_narrative(self):
        """Anomaly alerts should appear in the rich_narrative header."""
        s = Sensorium()
        anomalies = [
            {
                "metric_name": "wifi_network_count",
                "current_value": 20,
                "baseline_mean": 8,
                "baseline_std": 1.5,
                "deviation_sigma": 8.0,
                "direction": "above",
                "severity": "high",
                "description": "wifi_network_count is 8.0 sigma above baseline",
                "timestamp": time.time(),
            }
        ]
        s.update_anomalies(anomalies)
        narrative = s.rich_narrative()
        assert "RF ANOMALY ALERT" in narrative or "RF anomaly" in narrative.lower()

    def test_anomaly_triggers_mood_shift(self):
        """RF anomaly events should shift mood toward vigilance."""
        s = Sensorium()
        initial_arousal = s._mood_arousal
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 0,
                "baseline_mean": 15,
                "baseline_std": 3.0,
                "deviation_sigma": 5.0,
                "direction": "below",
                "severity": "high",
                "description": "ble_device_count is 5.0 sigma below baseline",
                "timestamp": time.time(),
            }
        ]
        s.update_anomalies(anomalies)
        # Anomaly push should have shifted arousal up
        assert s._mood_arousal > initial_arousal

    def test_anomaly_above_ble_context(self):
        """Above-baseline BLE count generates appropriate message."""
        s = Sensorium()
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 30,
                "baseline_mean": 10,
                "baseline_std": 2.0,
                "deviation_sigma": 10.0,
                "direction": "above",
                "severity": "high",
                "timestamp": time.time(),
            }
        ]
        s.update_anomalies(anomalies)
        ctx = s.anomaly_context()
        assert "more BLE devices" in ctx

    def test_multiple_anomalies_combined(self):
        """Multiple anomalies are combined in the summary."""
        s = Sensorium()
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 2,
                "baseline_mean": 10,
                "baseline_std": 2.0,
                "deviation_sigma": 4.0,
                "direction": "below",
                "severity": "high",
                "timestamp": time.time(),
            },
            {
                "metric_name": "rssi_mean",
                "current_value": -85.0,
                "baseline_mean": -60.0,
                "baseline_std": 5.0,
                "deviation_sigma": 5.0,
                "direction": "below",
                "severity": "high",
                "timestamp": time.time(),
            },
        ]
        s.update_anomalies(anomalies)
        ctx = s.anomaly_context()
        assert "BLE" in ctx
        assert "RSSI" in ctx.upper() or "rssi" in ctx.lower() or "average" in ctx.lower()

    def test_stale_anomalies_not_shown(self):
        """Anomalies older than 30 minutes should not appear in context."""
        s = Sensorium()
        old_time = time.time() - 3600  # 1 hour ago
        anomalies = [
            {
                "metric_name": "ble_device_count",
                "current_value": 2,
                "baseline_mean": 10,
                "baseline_std": 2.0,
                "deviation_sigma": 4.0,
                "direction": "below",
                "severity": "high",
                "timestamp": old_time,
            },
        ]
        s.update_anomalies(anomalies)
        ctx = s.anomaly_context()
        assert ctx == ""
