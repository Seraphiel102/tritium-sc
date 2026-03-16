# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for WiFi probe proximity estimator."""

import time
import pytest

from plugins.wifi_fingerprint.probe_proximity import (
    ProbeProximityEstimator,
    ProbeObservation,
    ProximityEstimate,
    TIMING_WINDOW,
    MIN_NODES,
)


class MockEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, data=None):
        self.events.append({"type": event_type, "data": data})


class TestProbeProximityEstimator:
    """Tests for ProbeProximityEstimator."""

    def test_init(self):
        e = ProbeProximityEstimator()
        status = e.get_status()
        assert status["tracked_devices"] == 0
        assert status["total_estimates"] == 0

    def test_single_node_no_estimate(self):
        e = ProbeProximityEstimator()
        result = e.ingest_probe(
            device_mac="AA:BB:CC:DD:EE:FF",
            ssid="MyNetwork",
            node_id="node-1",
            rssi=-50,
        )
        assert result is None  # Need at least 2 nodes

    def test_multi_node_produces_estimate(self):
        e = ProbeProximityEstimator()
        now = time.time()

        # Node 1 sees the probe first
        result1 = e.ingest_probe(
            device_mac="AA:BB:CC:DD:EE:FF",
            ssid="TestNet",
            node_id="node-1",
            rssi=-45,
            timestamp=now,
        )
        assert result1 is None

        # Node 2 sees the same probe slightly later
        result2 = e.ingest_probe(
            device_mac="AA:BB:CC:DD:EE:FF",
            ssid="TestNet",
            node_id="node-2",
            rssi=-65,
            timestamp=now + 0.5,
        )
        assert result2 is not None
        assert result2.closest_node == "node-1"
        assert result2.confidence > 0

    def test_strongest_rssi_and_earliest_wins(self):
        e = ProbeProximityEstimator()
        now = time.time()

        # Node A: weak signal, earliest
        e.ingest_probe("AA:BB:CC:00:11:22", "Net", "nodeA", -80, now)
        # Node B: strong signal, slightly later
        result = e.ingest_probe("AA:BB:CC:00:11:22", "Net", "nodeB", -30, now + 0.1)

        assert result is not None
        # NodeA was earliest, but nodeB has much stronger RSSI
        # With time_delta of 0.1s (small), timing is similar, so RSSI should tip it
        rankings = result.node_rankings
        assert len(rankings) == 2

    def test_three_nodes(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("11:22:33:44:55:66", "Corp", "n1", -40, now)
        e.ingest_probe("11:22:33:44:55:66", "Corp", "n2", -60, now + 0.3)
        result = e.ingest_probe("11:22:33:44:55:66", "Corp", "n3", -75, now + 1.0)

        assert result is not None
        assert result.closest_node == "n1"
        assert len(result.node_rankings) == 3

    def test_different_ssids_separate(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net1", "node-1", -50, now)
        result = e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net2", "node-2", -60, now + 0.5)

        # Different SSIDs — should not produce estimate
        assert result is None

    def test_outside_window_no_estimate(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "node-1", -50, now - TIMING_WINDOW - 1)
        result = e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "node-2", -60, now)

        # Outside timing window — should not produce estimate
        assert result is None

    def test_get_estimates(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n1", -50, now)
        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n2", -60, now + 0.5)

        estimates = e.get_estimates()
        assert len(estimates) == 1
        assert estimates[0]["device_mac"] == "aa:bb:cc:dd:ee:ff"

    def test_get_closest_node(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n1", -40, now)
        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n2", -70, now + 1.0)

        closest = e.get_closest_node("AA:BB:CC:DD:EE:FF")
        assert closest == "n1"

    def test_get_closest_node_not_found(self):
        e = ProbeProximityEstimator()
        assert e.get_closest_node("XX:XX:XX:XX:XX:XX") is None

    def test_prune_stale(self):
        e = ProbeProximityEstimator()
        e._observations["old_mac"] = [
            ProbeObservation(
                device_mac="old_mac", ssid="s", node_id="n",
                rssi=-50, timestamp=time.time() - 1000,
            )
        ]
        pruned = e.prune_stale(max_age=500)
        assert pruned == 1
        assert "old_mac" not in e._observations

    def test_event_bus_publish(self):
        bus = MockEventBus()
        e = ProbeProximityEstimator(event_bus=bus)
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n1", -50, now)
        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n2", -60, now + 0.5)

        proximity_events = [
            ev for ev in bus.events if ev["type"] == "wifi_probe:proximity"
        ]
        assert len(proximity_events) == 1

    def test_estimate_to_dict(self):
        est = ProximityEstimate(
            device_mac="aa:bb",
            ssid="Test",
            timestamp=1000.0,
            node_rankings=[{"node_id": "n1", "rank": 1, "score": 0.8}],
            closest_node="n1",
            confidence=0.8,
        )
        d = est.to_dict()
        assert d["device_mac"] == "aa:bb"
        assert d["closest_node"] == "n1"
        assert d["confidence"] == 0.8

    def test_mac_normalization(self):
        e = ProbeProximityEstimator()
        now = time.time()

        e.ingest_probe("AA:BB:CC:DD:EE:FF", "Net", "n1", -50, now)
        e.ingest_probe("aa:bb:cc:dd:ee:ff", "Net", "n2", -60, now + 0.5)

        # Both should match (lowercase normalization)
        estimates = e.get_estimates()
        assert len(estimates) == 1
