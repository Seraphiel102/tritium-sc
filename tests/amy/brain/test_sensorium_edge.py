# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for BLE and Meshtastic awareness in the Sensorium.

Verifies that Amy's L3 awareness layer correctly processes edge sensor
events (BLE device scans and Meshtastic node updates) and incorporates
them into her narrative and thinking context.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from amy.brain.sensorium import BLEDeviceSnapshot, MeshNodeSnapshot, Sensorium


# ---------------------------------------------------------------------------
# BLE device awareness
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBLEDeviceAwareness:
    """Tests for BLE device tracking in the sensorium."""

    def test_update_ble_sets_snapshot(self):
        """update_ble() populates the ble_snapshot with device counts."""
        s = Sensorium()
        s.update_ble({
            "node_id": "scanner-01",
            "devices": [
                {"addr": "AA:BB:CC:11:22:01", "name": "iPhone", "rssi": -50, "type": "phone"},
                {"addr": "AA:BB:CC:11:22:02", "name": "AirPods", "rssi": -60, "type": "audio"},
                {"addr": "DD:EE:FF:11:22:01", "name": "", "rssi": -80, "type": "unknown"},
            ],
            "count": 3,
        })
        snap = s.ble_snapshot
        assert snap.total == 3
        assert snap.known == 2
        assert snap.unknown == 1

    def test_update_ble_detects_new_devices(self):
        """update_ble() detects newly appeared devices and pushes a sensorium event."""
        s = Sensorium()
        # First scan — all devices are new
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "iPhone", "rssi": -50, "type": "phone"},
            ],
            "count": 1,
        })
        # Check that an event was pushed mentioning the new device
        narr = s.narrative()
        assert "iPhone" in narr

    def test_update_ble_no_new_device_event_on_repeat(self):
        """Repeated scans with the same MACs do not produce 'New BLE' events."""
        s = Sensorium()
        devices = [
            {"addr": "AA:11", "name": "iPhone", "rssi": -50, "type": "phone"},
        ]
        base = 1000.0
        with patch("amy.brain.sensorium.time.monotonic", return_value=base):
            s.update_ble({"devices": devices, "count": 1})

        # Second scan 10s later — same MAC, should just be a normal scan event
        with patch("amy.brain.sensorium.time.monotonic", return_value=base + 10.0):
            s.update_ble({"devices": devices, "count": 1})

        # Check events: first should mention "New", second should not
        with s._lock:
            events = [e for e in s._events if e.source == "ble"]
        texts = [e.text for e in events]
        # First event has "New", second has "BLE scan"
        assert any("New" in t for t in texts)
        assert any("BLE scan" in t for t in texts)

    def test_ble_context_returns_summary(self):
        """ble_context() returns a human-readable BLE summary string."""
        s = Sensorium()
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "iPhone", "rssi": -50, "type": "phone"},
                {"addr": "BB:22", "name": "", "rssi": -80, "type": "unknown"},
            ],
            "count": 2,
        })
        ctx = s.ble_context()
        assert "2 devices" in ctx
        assert "1 known" in ctx
        assert "1 unknown" in ctx

    def test_ble_context_includes_new_devices(self):
        """ble_context() mentions newly appeared named devices."""
        s = Sensorium()
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "Galaxy-S24", "rssi": -45, "type": "phone"},
            ],
            "count": 1,
        })
        ctx = s.ble_context()
        assert "Galaxy-S24" in ctx

    def test_ble_context_empty_when_stale(self):
        """ble_context() returns empty string when data is older than 120s."""
        s = Sensorium()
        base = 1000.0
        with patch("amy.brain.sensorium.time.monotonic", return_value=base):
            s.update_ble({
                "devices": [{"addr": "AA:11", "name": "X", "rssi": -50, "type": "phone"}],
                "count": 1,
            })
        with patch("amy.brain.sensorium.time.monotonic", return_value=base + 121.0):
            assert s.ble_context() == ""

    def test_ble_context_empty_when_no_data(self):
        """ble_context() returns empty string when no BLE data has been received."""
        s = Sensorium()
        assert s.ble_context() == ""

    def test_ble_mood_shift_on_new_device(self):
        """New BLE devices trigger a curiosity-like arousal bump."""
        s = Sensorium()
        initial_arousal = s._mood_arousal
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "NewPhone", "rssi": -50, "type": "phone"},
            ],
            "count": 1,
        })
        # Arousal should increase due to "new" keyword in the event
        assert s._mood_arousal > initial_arousal


# ---------------------------------------------------------------------------
# Meshtastic mesh node awareness
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMeshNodeAwareness:
    """Tests for Meshtastic node tracking in the sensorium."""

    def test_update_mesh_sets_snapshot(self):
        """update_mesh() populates the mesh_snapshot with node data."""
        s = Sensorium()
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1b2", "long_name": "BaseStation", "short_name": "BS1",
                 "battery": 85.0, "snr": 10.5, "position": {"lat": 37.77, "lng": -122.42}},
                {"node_id": "!c3d4", "long_name": "Rover", "short_name": "RV1",
                 "battery": 45.0, "snr": 8.2, "position": {"lat": 37.78, "lng": -122.41}},
            ],
            "count": 2,
        })
        snap = s.mesh_snapshot
        assert snap.count == 2
        assert len(snap.nodes) == 2

    def test_mesh_context_returns_summary(self):
        """mesh_context() returns a multiline mesh status string."""
        s = Sensorium()
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1b2", "short_name": "BS1", "battery": 85.0, "snr": 10.5},
                {"node_id": "!c3d4", "short_name": "RV1", "battery": 45.0, "snr": 8.2},
            ],
            "count": 2,
        })
        ctx = s.mesh_context()
        assert "2 nodes online" in ctx
        assert "BS1" in ctx
        assert "RV1" in ctx
        assert "battery" in ctx

    def test_mesh_context_empty_when_stale(self):
        """mesh_context() returns empty string when data is older than 120s."""
        s = Sensorium()
        base = 1000.0
        with patch("amy.brain.sensorium.time.monotonic", return_value=base):
            s.update_mesh({
                "nodes": [{"node_id": "!a1", "short_name": "X", "battery": 50, "snr": 5}],
                "count": 1,
            })
        with patch("amy.brain.sensorium.time.monotonic", return_value=base + 121.0):
            assert s.mesh_context() == ""

    def test_mesh_context_empty_when_no_data(self):
        """mesh_context() returns empty string when no mesh data has been received."""
        s = Sensorium()
        assert s.mesh_context() == ""

    def test_low_battery_pushes_important_event(self):
        """Nodes with battery < 30% trigger a higher-importance sensorium event."""
        s = Sensorium()
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1b2", "short_name": "BS1", "battery": 15.0, "snr": 10.5},
            ],
            "count": 1,
        })
        with s._lock:
            events = [e for e in s._events if e.source == "mesh"]
        assert len(events) == 1
        assert "Low battery" in events[0].text
        assert events[0].importance == 0.6

    def test_mesh_mood_shift_on_low_battery(self):
        """Low battery mesh events trigger mild concern (negative valence)."""
        s = Sensorium()
        initial_valence = s._mood_valence
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1b2", "short_name": "BS1", "battery": 15.0, "snr": 10.5},
            ],
            "count": 1,
        })
        # Valence should decrease due to "low battery" concern
        assert s._mood_valence < initial_valence


# ---------------------------------------------------------------------------
# Integration: BLE/Mesh in rich_narrative
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEdgeSensorsInNarrative:
    """Tests that BLE and mesh data appear in the rich narrative."""

    def test_ble_in_rich_narrative_header(self):
        """BLE context appears in the rich_narrative header."""
        s = Sensorium()
        # Need at least one non-BLE event to avoid "No recent observations"
        s.push("yolo", "1 person detected", importance=0.5)
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "iPhone", "rssi": -50, "type": "phone"},
            ],
            "count": 1,
        })
        narr = s.rich_narrative()
        assert "BLE" in narr
        assert "1 devices" in narr or "1 known" in narr

    def test_mesh_in_rich_narrative_header(self):
        """Mesh context appears in the rich_narrative header."""
        s = Sensorium()
        s.push("yolo", "1 person detected", importance=0.5)
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1b2", "short_name": "BS1", "battery": 85.0, "snr": 10.5},
            ],
            "count": 1,
        })
        narr = s.rich_narrative()
        assert "Mesh" in narr
        assert "1 nodes online" in narr

    def test_both_ble_and_mesh_in_narrative(self):
        """Both BLE and mesh context appear together in the narrative."""
        s = Sensorium()
        s.push("yolo", "quiet scene", importance=0.5)
        s.update_ble({
            "devices": [
                {"addr": "AA:11", "name": "Phone", "rssi": -50, "type": "phone"},
            ],
            "count": 1,
        })
        s.update_mesh({
            "nodes": [
                {"node_id": "!a1", "short_name": "N1", "battery": 90.0, "snr": 12.0},
            ],
            "count": 1,
        })
        narr = s.rich_narrative()
        assert "BLE" in narr
        assert "Mesh" in narr


# ---------------------------------------------------------------------------
# BLEDeviceSnapshot / MeshNodeSnapshot dataclasses
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSnapshots:
    """Tests for the snapshot dataclasses."""

    def test_ble_snapshot_defaults(self):
        snap = BLEDeviceSnapshot()
        assert snap.total == 0
        assert snap.known == 0
        assert snap.unknown == 0
        assert snap.devices == []
        assert snap.age == float("inf")

    def test_ble_snapshot_age(self):
        with patch("amy.brain.sensorium.time.monotonic", return_value=100.0):
            snap = BLEDeviceSnapshot(timestamp=95.0)
            assert snap.age == pytest.approx(5.0)

    def test_mesh_snapshot_defaults(self):
        snap = MeshNodeSnapshot()
        assert snap.count == 0
        assert snap.nodes == []
        assert snap.age == float("inf")

    def test_mesh_snapshot_age(self):
        with patch("amy.brain.sensorium.time.monotonic", return_value=100.0):
            snap = MeshNodeSnapshot(timestamp=90.0)
            assert snap.age == pytest.approx(10.0)
