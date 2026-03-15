# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the system-wide threat level calculator."""

import time
import pytest

from engine.tactical.threat_level_calculator import (
    ThreatLevelCalculator,
    score_to_level,
    HOSTILE_TARGET_WEIGHT,
    GEOFENCE_BREACH_WEIGHT,
    THREAT_FEED_MATCH_WEIGHT,
)


class FakeEventBus:
    """Minimal EventBus stub for testing."""

    def __init__(self):
        self.published = []

    def subscribe(self):
        import queue
        return queue.Queue()

    def publish(self, event_type, data=None):
        self.published.append({"type": event_type, "data": data})


class FakeTarget:
    def __init__(self, alliance="unknown", threat_level="none", threat_score=0.0):
        self.alliance = alliance
        self.threat_level = threat_level
        self.threat_score = threat_score


class FakeTracker:
    def __init__(self, targets=None):
        self._targets = targets or []

    def all_targets(self):
        return self._targets


class FakeEscalation:
    def __init__(self, threats=None):
        self._threats = threats or []

    def get_active_threats(self):
        return self._threats


class TestScoreToLevel:
    def test_green(self):
        assert score_to_level(0) == "green"
        assert score_to_level(9) == "green"

    def test_yellow(self):
        assert score_to_level(10) == "yellow"
        assert score_to_level(29) == "yellow"

    def test_orange(self):
        assert score_to_level(30) == "orange"
        assert score_to_level(59) == "orange"

    def test_red(self):
        assert score_to_level(60) == "red"
        assert score_to_level(89) == "red"

    def test_black(self):
        assert score_to_level(90) == "black"
        assert score_to_level(100) == "black"


class TestThreatLevelCalculator:
    def test_green_when_no_threats(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        escalation = FakeEscalation()
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        assert calc.current_level == "green"
        assert calc.current_score == 0.0

    def test_hostile_targets_raise_level(self):
        bus = FakeEventBus()
        targets = [FakeTarget(alliance="hostile") for _ in range(3)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        expected_score = 3 * HOSTILE_TARGET_WEIGHT
        assert calc.current_score == expected_score
        assert calc.current_level == "orange"

    def test_single_hostile_yellow(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_level == "yellow"

    def test_geofence_breaches(self):
        bus = FakeEventBus()
        tracker = FakeTracker()
        threats = [object() for _ in range(3)]
        escalation = FakeEscalation(threats)
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        expected = 3 * GEOFENCE_BREACH_WEIGHT
        assert calc.current_score == expected
        assert calc.current_level == "orange"

    def test_behavioral_anomalies(self):
        bus = FakeEventBus()
        targets = [FakeTarget(threat_score=0.8) for _ in range(2)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score > 0
        assert calc.current_level == "yellow"

    def test_combined_signals(self):
        bus = FakeEventBus()
        targets = [
            FakeTarget(alliance="hostile"),
            FakeTarget(alliance="hostile"),
            FakeTarget(threat_score=0.9),
        ]
        threats = [object(), object()]
        tracker = FakeTracker(targets)
        escalation = FakeEscalation(threats)
        calc = ThreatLevelCalculator(bus, tracker, escalation)
        calc._calculate()
        # 2 hostile * 10 + 2 geofence * 15 + 1 anomaly * 8 = 58
        assert calc.current_level == "orange"

    def test_publishes_on_level_change(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert len(bus.published) == 1
        assert bus.published[0]["type"] == "system:threat_level"
        assert bus.published[0]["data"]["level"] == "yellow"

    def test_no_publish_when_level_unchanged(self):
        bus = FakeEventBus()
        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        bus.published.clear()
        calc._calculate()
        assert len(bus.published) == 0

    def test_get_status(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        status = calc.get_status()
        assert "level" in status
        assert "score" in status
        assert status["level"] == "green"

    def test_score_clamped_to_100(self):
        bus = FakeEventBus()
        targets = [FakeTarget(alliance="hostile") for _ in range(20)]
        tracker = FakeTracker(targets)
        calc = ThreatLevelCalculator(bus, tracker)
        calc._calculate()
        assert calc.current_score == 100.0

    def test_set_tracker(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        calc._calculate()
        assert calc.current_level == "green"

        tracker = FakeTracker([FakeTarget(alliance="hostile")])
        calc.set_tracker(tracker)
        calc._calculate()
        assert calc.current_level == "yellow"

    def test_threat_feed_match_increment(self):
        bus = FakeEventBus()
        calc = ThreatLevelCalculator(bus)
        calc._threat_feed_matches = 2
        calc._threat_feed_match_time = time.monotonic()
        calc._calculate()
        expected = 2 * THREAT_FEED_MATCH_WEIGHT
        assert calc.current_score == expected
