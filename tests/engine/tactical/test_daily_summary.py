# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for daily summary generator."""

import time
import pytest
from unittest.mock import MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'src'))

from engine.tactical.daily_summary import DailySummaryGenerator


class MockEventStore:
    """Mock event store for testing."""

    def __init__(self, events=None):
        self._events = events or []
        self.recorded = []

    def query_time_range(self, start=None, end=None):
        return [
            e for e in self._events
            if (start is None or e.get("timestamp", 0) >= start)
            and (end is None or e.get("timestamp", 0) < end)
        ]

    def record(self, event_type=None, data=None):
        self.recorded.append({"event_type": event_type, "data": data})


class MockEventBus:
    """Mock event bus that records published events."""

    def __init__(self):
        self.events = []

    def publish(self, event_type, data=None):
        self.events.append({"type": event_type, "data": data})


class TestDailySummaryGenerator:
    """Tests for DailySummaryGenerator."""

    def test_generate_empty_summary(self):
        gen = DailySummaryGenerator()
        summary = gen.generate_summary()
        assert summary["unique_targets"] == 0
        assert summary["total_sightings"] == 0
        assert summary["total_events"] == 0
        assert summary["highest_threat_level"] == "none"
        assert len(summary["hourly_activity"]) == 24

    def test_generate_with_events(self):
        now = time.time()
        events = [
            {
                "event_type": "target_sighting",
                "timestamp": now - 3600,
                "data": {"target_id": "ble_aa", "source": "ble"},
            },
            {
                "event_type": "target_sighting",
                "timestamp": now - 3500,
                "data": {"target_id": "ble_bb", "source": "ble"},
            },
            {
                "event_type": "target_sighting",
                "timestamp": now - 3000,
                "data": {"target_id": "det_person_1", "source": "camera"},
            },
            {
                "event_type": "target_detected",
                "timestamp": now - 2000,
                "data": {"target_id": "ble_cc", "source": "ble"},
            },
            {
                "event_type": "target_lost",
                "timestamp": now - 1000,
                "data": {"target_id": "ble_aa", "source": "ble"},
            },
            {
                "event_type": "escalation",
                "timestamp": now - 500,
                "data": {"level": "elevated"},
            },
            {
                "event_type": "alert",
                "timestamp": now - 400,
                "data": {"message": "Threat detected"},
            },
        ]
        store = MockEventStore(events)
        bus = MockEventBus()
        gen = DailySummaryGenerator(event_store=store, event_bus=bus)
        summary = gen.generate_summary()

        assert summary["total_events"] == 7
        assert summary["unique_targets"] >= 3
        assert summary["new_targets"] == 1  # ble_cc via target_detected
        assert summary["departed_targets"] == 1  # ble_aa via target_lost
        assert summary["sightings_by_source"]["ble"] == 3  # 2 sightings + 1 detected
        assert summary["sightings_by_source"]["camera"] == 1
        assert summary["highest_threat_level"] == "elevated"
        assert summary["alerts_raised"] == 1

        # Should publish daily_summary event
        assert len(bus.events) == 1
        assert bus.events[0]["type"] == "daily_summary"

        # Should store in event store
        assert len(store.recorded) == 1

    def test_get_recent_summaries(self):
        gen = DailySummaryGenerator()
        gen.generate_summary("2026-03-10")
        gen.generate_summary("2026-03-11")
        gen.generate_summary("2026-03-12")

        recent = gen.get_recent_summaries(2)
        assert len(recent) == 2
        assert recent[0]["date"] == "2026-03-11"
        assert recent[1]["date"] == "2026-03-12"

    def test_get_summary_for_date(self):
        gen = DailySummaryGenerator()
        gen.generate_summary("2026-03-10")
        gen.generate_summary("2026-03-11")

        result = gen.get_summary_for_date("2026-03-10")
        assert result is not None
        assert result["date"] == "2026-03-10"

        result = gen.get_summary_for_date("2026-01-01")
        assert result is None

    def test_get_trend(self):
        gen = DailySummaryGenerator()
        # No data
        trend = gen.get_trend()
        assert trend["trend"] == "unknown"
        assert trend["days"] == 0

    def test_get_trend_with_data(self):
        gen = DailySummaryGenerator()
        for i in range(7):
            gen.generate_summary(f"2026-03-{10 + i:02d}")

        trend = gen.get_trend(days=7)
        assert trend["days"] == 7
        assert trend["trend"] in ("stable", "increasing", "decreasing")

    def test_convoy_counting(self):
        now = time.time()
        events = [
            {
                "event_type": "convoy_detected",
                "timestamp": now - 1000,
                "data": {"convoy_id": "convoy_1"},
            },
            {
                "event_type": "convoy_detected",
                "timestamp": now - 500,
                "data": {"convoy_id": "convoy_2"},
            },
        ]
        store = MockEventStore(events)
        gen = DailySummaryGenerator(event_store=store)
        summary = gen.generate_summary()
        assert summary["convoys_detected"] == 2

    def test_busiest_hour(self):
        now = time.time()
        from datetime import datetime, timezone
        # Create many events at hour 14
        base_hour_14 = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc).timestamp()
        events = []
        for i in range(10):
            events.append({
                "event_type": "target_sighting",
                "timestamp": base_hour_14 + i * 60,
                "data": {"target_id": f"t_{i}", "source": "ble"},
            })
        # A few at other hours
        base_hour_10 = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc).timestamp()
        events.append({
            "event_type": "target_sighting",
            "timestamp": base_hour_10,
            "data": {"target_id": "t_x", "source": "wifi"},
        })

        store = MockEventStore(events)
        gen = DailySummaryGenerator(event_store=store)
        summary = gen.generate_summary("2026-03-15")
        assert summary["busiest_hour"] == 14
        assert summary["busiest_hour_count"] == 10

    def test_summary_retention_limit(self):
        gen = DailySummaryGenerator()
        # Generate 100 summaries — should keep only last 90
        for i in range(100):
            gen.generate_summary(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}")

        recent = gen.get_recent_summaries(100)
        assert len(recent) <= 90
