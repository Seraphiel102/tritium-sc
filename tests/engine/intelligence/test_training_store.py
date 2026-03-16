# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the training data store (RL/ML data collection).

Wave 52 — validates that correlation decisions, classification decisions,
and operator feedback are properly stored and retrievable from SQLite.
"""
from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def store():
    """Create a temporary TrainingStore for testing."""
    from engine.intelligence.training_store import TrainingStore
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_training.db")
        yield TrainingStore(db_path=db_path)


class TestCorrelationLogging:
    """Test correlation decision logging."""

    def test_log_correlation(self, store):
        """Log a correlation decision and retrieve it."""
        row_id = store.log_correlation(
            target_a_id="ble_aa:bb:cc:dd:ee:ff",
            target_b_id="det_person_1",
            features={"proximity": 0.9, "timing": 0.8, "co_occurrence": 3},
            score=0.85,
            decision="merge",
        )
        assert row_id > 0

        data = store.get_correlation_data(limit=10)
        assert len(data) == 1
        assert data[0]["target_a_id"] == "ble_aa:bb:cc:dd:ee:ff"
        assert data[0]["target_b_id"] == "det_person_1"
        assert data[0]["score"] == 0.85
        assert data[0]["decision"] == "merge"
        assert data[0]["features"]["proximity"] == 0.9

    def test_multiple_correlations(self, store):
        """Log multiple correlation decisions."""
        for i in range(5):
            store.log_correlation(
                target_a_id=f"target_a_{i}",
                target_b_id=f"target_b_{i}",
                features={"score": i * 0.2},
                score=i * 0.2,
                decision="related" if i > 2 else "unrelated",
            )

        data = store.get_correlation_data()
        assert len(data) == 5

    def test_update_correlation_outcome(self, store):
        """Update correlation outcome after operator review."""
        row_id = store.log_correlation(
            target_a_id="t1", target_b_id="t2",
            features={}, score=0.7, decision="merge",
        )
        assert store.update_correlation_outcome(row_id, "correct")

        data = store.get_correlation_data(outcome_only=True)
        assert len(data) == 1
        assert data[0]["outcome"] == "correct"

    def test_outcome_only_filter(self, store):
        """Filter to only confirmed outcomes."""
        store.log_correlation("t1", "t2", {}, 0.5, "merge", outcome="correct")
        store.log_correlation("t3", "t4", {}, 0.3, "unrelated")  # no outcome

        confirmed = store.get_correlation_data(outcome_only=True)
        all_data = store.get_correlation_data()
        assert len(confirmed) == 1
        assert len(all_data) == 2


class TestClassificationLogging:
    """Test classification decision logging."""

    def test_log_classification(self, store):
        """Log a classification decision and retrieve it."""
        row_id = store.log_classification(
            target_id="ble_aa:bb:cc:dd:ee:ff",
            features={"rssi": -45, "oui": "Apple", "name": "iPhone"},
            predicted_type="phone",
            confidence=0.92,
            predicted_alliance="friendly",
        )
        assert row_id > 0

        data = store.get_classification_data(limit=10)
        assert len(data) == 1
        assert data[0]["target_id"] == "ble_aa:bb:cc:dd:ee:ff"
        assert data[0]["predicted_type"] == "phone"
        assert data[0]["confidence"] == 0.92
        assert data[0]["features"]["oui"] == "Apple"

    def test_update_classification_correction(self, store):
        """Update classification with operator corrections."""
        row_id = store.log_classification(
            target_id="ble_xx",
            features={"rssi": -70},
            predicted_type="phone",
            confidence=0.5,
        )
        assert store.update_classification_correction(
            row_id, correct_type="watch", correct_alliance="friendly",
        )

        data = store.get_classification_data(corrected_only=True)
        assert len(data) == 1
        assert data[0]["correct_type"] == "watch"
        assert data[0]["correct_alliance"] == "friendly"

    def test_corrected_only_filter(self, store):
        """Filter to only corrected classifications."""
        store.log_classification("t1", {}, "phone", 0.9)
        store.log_classification("t2", {}, "watch", 0.4)
        # Correct one
        data = store.get_classification_data()
        row_id = data[-1]["id"]  # oldest (t1)
        store.update_classification_correction(row_id, correct_type="computer")

        corrected = store.get_classification_data(corrected_only=True)
        assert len(corrected) == 1


class TestFeedbackLogging:
    """Test operator feedback logging."""

    def test_log_feedback(self, store):
        """Log operator feedback and retrieve it."""
        row_id = store.log_feedback(
            target_id="ble_aa:bb:cc:dd:ee:ff",
            decision_type="classification",
            correct=True,
            notes="Confirmed phone",
            operator="op1",
        )
        assert row_id > 0

        data = store.get_feedback()
        assert len(data) == 1
        assert data[0]["target_id"] == "ble_aa:bb:cc:dd:ee:ff"
        assert data[0]["correct"] == 1
        assert data[0]["operator"] == "op1"

    def test_feedback_by_type(self, store):
        """Filter feedback by decision type."""
        store.log_feedback("t1", "classification", True)
        store.log_feedback("t2", "correlation", False)
        store.log_feedback("t3", "classification", True)

        class_feedback = store.get_feedback(decision_type="classification")
        assert len(class_feedback) == 2

        corr_feedback = store.get_feedback(decision_type="correlation")
        assert len(corr_feedback) == 1

    def test_rejection_feedback(self, store):
        """Log a rejection (correct=False)."""
        store.log_feedback("t1", "threat", False, notes="False positive")
        data = store.get_feedback()
        assert data[0]["correct"] == 0


class TestStats:
    """Test training data statistics."""

    def test_empty_stats(self, store):
        """Empty store should return zero counts."""
        stats = store.get_stats()
        assert stats["correlation"]["total"] == 0
        assert stats["classification"]["total"] == 0
        assert stats["feedback"]["total"] == 0
        assert stats["feedback"]["accuracy"] == 0.0

    def test_stats_with_data(self, store):
        """Stats should reflect actual data."""
        store.log_correlation("t1", "t2", {}, 0.5, "merge", outcome="correct")
        store.log_correlation("t3", "t4", {}, 0.3, "unrelated")
        store.log_classification("t1", {}, "phone", 0.9)
        store.log_feedback("t1", "classification", True)
        store.log_feedback("t2", "classification", False)

        stats = store.get_stats()
        assert stats["correlation"]["total"] == 2
        assert stats["correlation"]["confirmed"] == 1
        assert stats["classification"]["total"] == 1
        assert stats["feedback"]["total"] == 2
        assert stats["feedback"]["correct"] == 1
        assert stats["feedback"]["accuracy"] == 0.5
