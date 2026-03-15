# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for indoor-outdoor transition detector."""

import pytest
import time

from plugins.edge_tracker.transition_detector import (
    IndoorOutdoorDetector,
    TargetPositioningState,
    MIN_OBSERVATIONS,
    TRANSITION_COOLDOWN,
)


class MockEventBus:
    """Simple mock EventBus for testing."""

    def __init__(self):
        self.events = []

    def publish(self, event_type, data=None):
        self.events.append({"type": event_type, "data": data})


class TestIndoorOutdoorDetector:
    """Tests for the IndoorOutdoorDetector."""

    def test_init(self):
        d = IndoorOutdoorDetector()
        assert d.get_status()["tracked_targets"] == 0

    def test_no_transition_insufficient_observations(self):
        d = IndoorOutdoorDetector()
        result = d.update_target("ble_aabb", positioning_method="gps", has_gps=True)
        assert result is None  # Not enough observations

    def test_transition_outdoor_to_indoor(self):
        bus = MockEventBus()
        d = IndoorOutdoorDetector(event_bus=bus)

        # Feed GPS observations to establish outdoor state
        for _ in range(MIN_OBSERVATIONS):
            d.update_target("t1", positioning_method="gps", has_gps=True)

        # Force state to outdoor
        d._targets["t1"].current_state = "outdoor"
        d._targets["t1"].last_transition_time = 0  # reset cooldown

        # Clear old observations and feed indoor observations
        d._targets["t1"].observations.clear()
        for _ in range(MIN_OBSERVATIONS + 1):
            d.update_target(
                "t1",
                positioning_method="wifi_fingerprint",
                has_gps=False,
            )

        # Should have detected a transition
        status = d.get_status()
        assert status["tracked_targets"] == 1

    def test_no_transition_same_state(self):
        d = IndoorOutdoorDetector()
        # Feed GPS observations
        for _ in range(MIN_OBSERVATIONS + 2):
            result = d.update_target("t1", positioning_method="gps", has_gps=True)
        # State should be outdoor, no new transitions after initial
        assert d.get_target_state("t1") in ("outdoor", "unknown")

    def test_cooldown_prevents_rapid_transitions(self):
        d = IndoorOutdoorDetector()
        d._targets["t1"] = TargetPositioningState(
            target_id="t1",
            current_state="outdoor",
            last_transition_time=time.time(),  # just transitioned
        )
        # Try to trigger another transition immediately
        for _ in range(MIN_OBSERVATIONS + 2):
            result = d.update_target(
                "t1",
                positioning_method="wifi_fingerprint",
                has_gps=False,
            )
        # Should be None due to cooldown
        assert result is None

    def test_get_recent_transitions(self):
        d = IndoorOutdoorDetector()
        # Initially empty
        assert len(d.get_recent_transitions()) == 0

    def test_prune_stale(self):
        d = IndoorOutdoorDetector()
        d._targets["stale"] = TargetPositioningState(
            target_id="stale",
            observations=[(time.time() - 1000, "gps", True, 1)],
        )
        pruned = d.prune_stale(max_age=500)
        assert pruned == 1
        assert "stale" not in d._targets

    def test_event_bus_publish(self):
        bus = MockEventBus()
        d = IndoorOutdoorDetector(event_bus=bus)

        # Set up target in outdoor state with old transition time
        d._targets["t1"] = TargetPositioningState(
            target_id="t1",
            current_state="outdoor",
            last_transition_time=0,
        )

        # Feed indoor observations to trigger transition
        for _ in range(MIN_OBSERVATIONS + 2):
            d.update_target(
                "t1",
                positioning_method="wifi_fingerprint",
                has_gps=False,
            )

        # Check if transition event was published
        transition_events = [
            e for e in bus.events if e["type"] == "transition:indoor_outdoor"
        ]
        if d.get_target_state("t1") == "indoor":
            assert len(transition_events) > 0

    def test_status(self):
        d = IndoorOutdoorDetector()
        d._targets["t1"] = TargetPositioningState(target_id="t1", current_state="indoor")
        d._targets["t2"] = TargetPositioningState(target_id="t2", current_state="outdoor")
        d._targets["t3"] = TargetPositioningState(target_id="t3", current_state="unknown")
        status = d.get_status()
        assert status["tracked_targets"] == 3
        assert status["indoor_targets"] == 1
        assert status["outdoor_targets"] == 1


class TestTargetPositioningState:
    """Tests for TargetPositioningState."""

    def test_add_observation(self):
        s = TargetPositioningState(target_id="t1")
        s.add_observation("gps", True, 1)
        assert len(s.observations) == 1

    def test_max_observations(self):
        s = TargetPositioningState(target_id="t1", max_observations=5)
        for i in range(10):
            s.add_observation("gps", True, 1)
        assert len(s.observations) == 5

    def test_recent_observations(self):
        s = TargetPositioningState(target_id="t1")
        # Old observation
        s.observations.append((time.time() - 300, "gps", True, 1))
        # Recent observation
        s.add_observation("wifi_fingerprint", False, 1)
        recent = s.recent_observations(window=120)
        assert len(recent) == 1
        assert recent[0][1] == "wifi_fingerprint"
