# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for TargetCorrelator — sensor fusion engine."""

import time

import pytest

from src.engine.tactical.correlator import (
    CorrelationRecord,
    TargetCorrelator,
    start_correlator,
    stop_correlator,
)
from src.engine.tactical.target_tracker import TargetTracker, TrackedTarget


def _make_tracker_with(*targets: TrackedTarget) -> TargetTracker:
    """Create a TargetTracker pre-loaded with the given targets."""
    tracker = TargetTracker()
    with tracker._lock:
        for t in targets:
            tracker._targets[t.target_id] = t
    return tracker


def _ble_target(
    tid: str = "ble_aabbccdd",
    pos: tuple[float, float] = (5.0, 5.0),
    confidence: float = 0.5,
    last_seen: float | None = None,
) -> TrackedTarget:
    return TrackedTarget(
        target_id=tid,
        name=f"BLE {tid}",
        alliance="unknown",
        asset_type="ble_device",
        position=pos,
        last_seen=last_seen if last_seen is not None else time.monotonic(),
        source="ble",
        position_source="trilateration",
        position_confidence=confidence,
    )


def _yolo_target(
    tid: str = "det_person_1",
    pos: tuple[float, float] = (5.5, 5.5),
    confidence: float = 0.3,
    last_seen: float | None = None,
) -> TrackedTarget:
    return TrackedTarget(
        target_id=tid,
        name=f"Person #{tid}",
        alliance="hostile",
        asset_type="person",
        position=pos,
        last_seen=last_seen if last_seen is not None else time.monotonic(),
        source="yolo",
        position_source="yolo",
        position_confidence=confidence,
    )


class TestCorrelation:
    """Core correlation logic."""

    @pytest.mark.unit
    def test_nearby_different_sources_correlated(self):
        """Two targets near each other from different sources get correlated."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 1
        rec = records[0]
        assert rec.confidence > 0
        assert "ble" in rec.reason
        assert "yolo" in rec.reason

        # Secondary target should be removed from tracker
        remaining = tracker.get_all()
        assert len(remaining) == 1
        # The surviving target should have boosted confidence
        assert remaining[0].position_confidence > 0.5 or remaining[0].position_confidence > 0.3

    @pytest.mark.unit
    def test_far_apart_not_correlated(self):
        """Two targets far apart should NOT be correlated."""
        ble = _ble_target(pos=(0.0, 0.0))
        yolo = _yolo_target(pos=(50.0, 50.0))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 0
        assert len(tracker.get_all()) == 2

    @pytest.mark.unit
    def test_same_source_not_correlated(self):
        """Two targets from the same sensor type should NOT be correlated."""
        ble1 = _ble_target(tid="ble_aabb", pos=(5.0, 5.0))
        ble2 = _ble_target(tid="ble_ccdd", pos=(5.1, 5.1))
        tracker = _make_tracker_with(ble1, ble2)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 0
        assert len(tracker.get_all()) == 2

    @pytest.mark.unit
    def test_stale_target_not_correlated(self):
        """Old targets (beyond max_age) should NOT be correlated."""
        old_time = time.monotonic() - 60.0  # 60s ago
        ble = _ble_target(pos=(5.0, 5.0), last_seen=old_time)
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, max_age=30.0)
        records = correlator.correlate()

        assert len(records) == 0

    @pytest.mark.unit
    def test_both_stale_not_correlated(self):
        """If both targets are stale, no correlation."""
        old_time = time.monotonic() - 60.0
        ble = _ble_target(pos=(5.0, 5.0), last_seen=old_time)
        yolo = _yolo_target(pos=(5.5, 5.5), last_seen=old_time)
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, max_age=30.0)
        records = correlator.correlate()

        assert len(records) == 0


class TestMerge:
    """Merge behavior when targets are correlated."""

    @pytest.mark.unit
    def test_merged_target_has_boosted_confidence(self):
        """The surviving target should have boosted position confidence."""
        ble = _ble_target(pos=(5.0, 5.0), confidence=0.5)
        yolo = _yolo_target(pos=(5.0, 5.0), confidence=0.3)
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        correlator.correlate()

        remaining = tracker.get_all()
        assert len(remaining) == 1
        survivor = remaining[0]
        # Confidence should be boosted beyond original
        assert survivor.position_confidence > 0.5

    @pytest.mark.unit
    def test_merged_target_name_includes_secondary_source(self):
        """The surviving target name should reference the secondary source."""
        ble = _ble_target(pos=(5.0, 5.0), confidence=0.6)
        yolo = _yolo_target(pos=(5.0, 5.0), confidence=0.3)
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        correlator.correlate()

        remaining = tracker.get_all()
        assert len(remaining) == 1
        # The primary (higher confidence = ble) should mention secondary source
        assert "yolo" in remaining[0].name.lower()

    @pytest.mark.unit
    def test_correlation_record_stored(self):
        """Correlation records should be retrievable after correlate()."""
        ble = _ble_target(pos=(5.0, 5.0))
        yolo = _yolo_target(pos=(5.5, 5.5))
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        correlator.correlate()

        records = correlator.get_correlations()
        assert len(records) == 1
        assert isinstance(records[0], CorrelationRecord)
        assert records[0].primary_id in (ble.target_id, yolo.target_id)
        assert records[0].secondary_id in (ble.target_id, yolo.target_id)
        assert records[0].primary_id != records[0].secondary_id


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.unit
    def test_empty_tracker(self):
        """No targets means no correlations."""
        tracker = TargetTracker()
        correlator = TargetCorrelator(tracker)
        records = correlator.correlate()
        assert records == []

    @pytest.mark.unit
    def test_single_target(self):
        """A single target cannot be correlated."""
        tracker = _make_tracker_with(_ble_target())
        correlator = TargetCorrelator(tracker)
        records = correlator.correlate()
        assert records == []

    @pytest.mark.unit
    def test_at_exact_radius_boundary(self):
        """Targets at exactly the radius distance should still correlate."""
        ble = _ble_target(pos=(0.0, 0.0))
        yolo = _yolo_target(pos=(5.0, 0.0))  # exactly 5 units away
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 1

    @pytest.mark.unit
    def test_just_beyond_radius_not_correlated(self):
        """Targets just beyond the radius should NOT correlate."""
        ble = _ble_target(pos=(0.0, 0.0))
        yolo = _yolo_target(pos=(5.01, 0.0))  # just beyond 5 units
        tracker = _make_tracker_with(ble, yolo)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 0

    @pytest.mark.unit
    def test_custom_radius(self):
        """Custom radius changes correlation behavior."""
        ble = _ble_target(pos=(0.0, 0.0))
        yolo = _yolo_target(pos=(3.0, 0.0))
        tracker = _make_tracker_with(ble, yolo)

        # With radius=2 they are too far
        correlator = TargetCorrelator(tracker, radius=2.0)
        records = correlator.correlate()
        assert len(records) == 0

    @pytest.mark.unit
    def test_multiple_pairs(self):
        """Multiple distinct pairs can correlate simultaneously."""
        ble1 = _ble_target(tid="ble_aa", pos=(0.0, 0.0))
        yolo1 = _yolo_target(tid="det_person_1", pos=(1.0, 0.0))
        ble2 = _ble_target(tid="ble_bb", pos=(50.0, 50.0))
        yolo2 = _yolo_target(tid="det_person_2", pos=(51.0, 50.0))
        tracker = _make_tracker_with(ble1, yolo1, ble2, yolo2)

        correlator = TargetCorrelator(tracker, radius=5.0)
        records = correlator.correlate()

        assert len(records) == 2
        assert len(tracker.get_all()) == 2


class TestLifecycle:
    """Start/stop lifecycle."""

    @pytest.mark.unit
    def test_start_stop(self):
        """Correlator starts and stops cleanly."""
        tracker = TargetTracker()
        correlator = start_correlator(tracker, interval=0.1)
        assert correlator._running is True

        time.sleep(0.15)
        stop_correlator(correlator)
        assert correlator._running is False
        assert correlator._thread is None

    @pytest.mark.unit
    def test_start_idempotent(self):
        """Calling start() twice doesn't create duplicate threads."""
        tracker = TargetTracker()
        correlator = TargetCorrelator(tracker, interval=0.1)
        correlator.start()
        thread1 = correlator._thread
        correlator.start()
        thread2 = correlator._thread
        assert thread1 is thread2
        correlator.stop()
