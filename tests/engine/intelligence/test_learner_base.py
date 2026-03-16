# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Verify all learners extend BaseLearner from tritium-lib."""
from __future__ import annotations

import pytest
from tritium_lib.intelligence.base_learner import BaseLearner


class TestLearnerInheritance:
    """All learner implementations must extend BaseLearner."""

    @pytest.mark.unit
    def test_correlation_learner_extends_base(self):
        from engine.intelligence.correlation_learner import CorrelationLearner
        assert issubclass(CorrelationLearner, BaseLearner)

    @pytest.mark.unit
    def test_ble_classification_learner_extends_base(self):
        from engine.intelligence.ble_classification_learner import BLEClassificationLearner
        assert issubclass(BLEClassificationLearner, BaseLearner)

    @pytest.mark.unit
    def test_pattern_learner_extends_base(self):
        from tritium_lib.intelligence.pattern_learning import PatternLearner
        assert issubclass(PatternLearner, BaseLearner)

    @pytest.mark.unit
    def test_correlation_learner_has_name(self):
        from engine.intelligence.correlation_learner import CorrelationLearner
        learner = CorrelationLearner(training_store=None, model_path="")
        assert learner.name == "correlation"

    @pytest.mark.unit
    def test_ble_learner_has_name(self):
        from engine.intelligence.ble_classification_learner import BLEClassificationLearner
        learner = BLEClassificationLearner(model_path="")
        assert learner.name == "ble_classifier"

    @pytest.mark.unit
    def test_correlation_learner_get_stats(self):
        from engine.intelligence.correlation_learner import CorrelationLearner
        learner = CorrelationLearner(training_store=None, model_path="")
        stats = learner.get_stats()
        assert "name" in stats
        assert stats["name"] == "correlation"
        assert "trained" in stats

    @pytest.mark.unit
    def test_ble_learner_get_stats(self):
        from engine.intelligence.ble_classification_learner import BLEClassificationLearner
        learner = BLEClassificationLearner(model_path="")
        stats = learner.get_stats()
        assert "name" in stats
        assert stats["name"] == "ble_classifier"

    @pytest.mark.unit
    def test_correlation_learner_get_status_compat(self):
        """get_status() should still work for backward compat."""
        from engine.intelligence.correlation_learner import CorrelationLearner
        learner = CorrelationLearner(training_store=None, model_path="")
        status = learner.get_status()
        assert "trained" in status
        assert "sklearn_available" in status
        assert "feature_names" in status

    @pytest.mark.unit
    def test_ble_learner_get_status_compat(self):
        """get_status() should still work for backward compat."""
        from engine.intelligence.ble_classification_learner import BLEClassificationLearner
        learner = BLEClassificationLearner(model_path="")
        status = learner.get_status()
        assert "trained" in status
        assert "sklearn_available" in status
        assert "device_types" in status

    @pytest.mark.unit
    def test_all_learners_share_save_load(self):
        """All learners should inherit save/load from BaseLearner."""
        from engine.intelligence.correlation_learner import CorrelationLearner
        from engine.intelligence.ble_classification_learner import BLEClassificationLearner
        from tritium_lib.intelligence.pattern_learning import PatternLearner

        for cls in [CorrelationLearner, BLEClassificationLearner, PatternLearner]:
            assert hasattr(cls, "save")
            assert hasattr(cls, "load")
            # save/load should come from BaseLearner (not overridden as _save_model/_load_model)
            assert not hasattr(cls, "_save_model")
            assert not hasattr(cls, "_load_model")
