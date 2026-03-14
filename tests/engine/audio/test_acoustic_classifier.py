# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for acoustic event classifier."""

import pytest
from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AcousticEventType,
    AudioFeatures,
)


class TestAcousticEventType:
    def test_enum_values(self):
        assert AcousticEventType.GUNSHOT == "gunshot"
        assert AcousticEventType.VOICE == "voice"
        assert AcousticEventType.VEHICLE == "vehicle"


class TestAudioFeatures:
    def test_defaults(self):
        f = AudioFeatures()
        assert f.rms_energy == 0.0
        assert f.duration_ms == 0


class TestAcousticClassifier:
    def setup_method(self):
        self.classifier = AcousticClassifier()

    def test_gunshot_detection(self):
        """High energy, short duration = gunshot."""
        features = AudioFeatures(
            peak_amplitude=0.95,
            rms_energy=0.9,
            spectral_centroid=1000,
            duration_ms=50,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.GUNSHOT
        assert event.confidence > 0.8

    def test_voice_detection(self):
        """Mid-frequency, moderate energy, sustained = voice."""
        features = AudioFeatures(
            peak_amplitude=0.3,
            rms_energy=0.2,
            spectral_centroid=500,
            duration_ms=2000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.VOICE

    def test_vehicle_detection(self):
        """Low frequency, sustained = vehicle."""
        features = AudioFeatures(
            peak_amplitude=0.4,
            rms_energy=0.3,
            spectral_centroid=200,
            duration_ms=5000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.VEHICLE

    def test_siren_detection(self):
        """Mid-high frequency, sustained, loud = siren."""
        features = AudioFeatures(
            peak_amplitude=0.7,
            rms_energy=0.5,
            spectral_centroid=1200,
            duration_ms=3000,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.SIREN

    def test_glass_break_detection(self):
        """High frequency, high energy, short = glass break."""
        features = AudioFeatures(
            peak_amplitude=0.7,
            rms_energy=0.6,
            spectral_centroid=4000,
            duration_ms=200,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.GLASS_BREAK

    def test_unknown_classification(self):
        """Low energy noise = unknown."""
        features = AudioFeatures(
            peak_amplitude=0.05,
            rms_energy=0.02,
            spectral_centroid=1000,
            duration_ms=100,
        )
        event = self.classifier.classify(features)
        assert event.event_type == AcousticEventType.UNKNOWN

    def test_event_history(self):
        """Events are recorded in history."""
        for i in range(5):
            self.classifier.classify(AudioFeatures(
                peak_amplitude=0.9, duration_ms=50, spectral_centroid=1000,
            ))
        events = self.classifier.get_recent_events()
        assert len(events) == 5

    def test_event_counts(self):
        """Event counts track by type."""
        self.classifier.classify(AudioFeatures(
            peak_amplitude=0.9, duration_ms=50, spectral_centroid=1000,
        ))
        self.classifier.classify(AudioFeatures(
            peak_amplitude=0.2, rms_energy=0.15, spectral_centroid=500, duration_ms=2000,
        ))
        counts = self.classifier.get_event_counts()
        assert "gunshot" in counts
        assert "voice" in counts


class TestAcousticRouter:
    def test_import(self):
        from app.routers.acoustic import router
        assert router is not None
