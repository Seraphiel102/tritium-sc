# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Acoustic event classifier for the Tritium sensing pipeline.

Classifies audio events into categories like gunshot, voice, vehicle,
animal, glass break, etc. Uses a simple energy/frequency-based approach
for initial detection, with optional ML model for refinement.

This module is designed to process audio from:
- Edge devices with microphones (ESP32 I2S + MQTT)
- IP cameras with audio channels
- Dedicated acoustic sensors

Integration:
- Receives audio data via MQTT on `tritium/{site}/audio/{device}/raw`
- Publishes classified events to `tritium/{site}/audio/{device}/event`
- Events feed into the TargetTracker for sensor fusion
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from loguru import logger


class AcousticEventType(str, Enum):
    """Types of acoustic events that can be classified."""

    GUNSHOT = "gunshot"
    VOICE = "voice"
    VEHICLE = "vehicle"
    ANIMAL = "animal"
    GLASS_BREAK = "glass_break"
    EXPLOSION = "explosion"
    SIREN = "siren"
    ALARM = "alarm"
    FOOTSTEPS = "footsteps"
    MACHINERY = "machinery"
    MUSIC = "music"
    UNKNOWN = "unknown"


@dataclass
class AcousticEvent:
    """A classified acoustic event."""

    event_type: AcousticEventType
    confidence: float  # 0.0 - 1.0
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    peak_frequency_hz: float = 0.0
    peak_amplitude_db: float = 0.0
    device_id: str = ""
    location: Optional[tuple[float, float]] = None  # lat, lng


@dataclass
class AudioFeatures:
    """Extracted features from an audio segment."""

    rms_energy: float = 0.0
    peak_amplitude: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    duration_ms: int = 0


class AcousticClassifier:
    """Rule-based acoustic event classifier.

    Uses audio features (energy, frequency distribution, duration) to classify
    sounds. Designed to run without ML dependencies — just numpy-level math.
    """

    # Classification thresholds (tuned empirically)
    GUNSHOT_ENERGY_THRESHOLD = 0.8
    GUNSHOT_DURATION_MAX_MS = 200
    VOICE_CENTROID_MIN_HZ = 85
    VOICE_CENTROID_MAX_HZ = 3000
    VEHICLE_CENTROID_MAX_HZ = 500
    SIREN_CENTROID_MIN_HZ = 600
    SIREN_CENTROID_MAX_HZ = 2000

    def __init__(self) -> None:
        self._event_history: list[AcousticEvent] = []
        self._max_history = 1000

    def classify(self, features: AudioFeatures) -> AcousticEvent:
        """Classify an audio segment based on its features.

        Returns an AcousticEvent with the most likely classification.
        """
        # Gunshot: very high energy, very short duration
        if (features.peak_amplitude > self.GUNSHOT_ENERGY_THRESHOLD
                and features.duration_ms < self.GUNSHOT_DURATION_MAX_MS):
            event = AcousticEvent(
                event_type=AcousticEventType.GUNSHOT,
                confidence=min(0.95, features.peak_amplitude),
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Siren: sustained, mid-high frequency
        if (self.SIREN_CENTROID_MIN_HZ < features.spectral_centroid < self.SIREN_CENTROID_MAX_HZ
                and features.duration_ms > 1000
                and features.rms_energy > 0.3):
            event = AcousticEvent(
                event_type=AcousticEventType.SIREN,
                confidence=0.7,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Vehicle: low frequency, sustained (check before voice — overlapping range)
        if (features.spectral_centroid < self.VEHICLE_CENTROID_MAX_HZ
                and features.duration_ms > 500
                and features.rms_energy > 0.2):
            event = AcousticEvent(
                event_type=AcousticEventType.VEHICLE,
                confidence=0.5,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Voice: mid-range frequency, moderate energy
        if (self.VOICE_CENTROID_MIN_HZ < features.spectral_centroid < self.VOICE_CENTROID_MAX_HZ
                and features.rms_energy > 0.1
                and features.duration_ms > 200):
            event = AcousticEvent(
                event_type=AcousticEventType.VOICE,
                confidence=0.6,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Glass break: high energy, short, high frequency
        if (features.spectral_centroid > 2000
                and features.peak_amplitude > 0.6
                and features.duration_ms < 500):
            event = AcousticEvent(
                event_type=AcousticEventType.GLASS_BREAK,
                confidence=0.55,
                duration_ms=features.duration_ms,
                peak_frequency_hz=features.spectral_centroid,
                peak_amplitude_db=features.peak_amplitude,
            )
            self._record(event)
            return event

        # Unknown
        event = AcousticEvent(
            event_type=AcousticEventType.UNKNOWN,
            confidence=0.3,
            duration_ms=features.duration_ms,
            peak_frequency_hz=features.spectral_centroid,
            peak_amplitude_db=features.peak_amplitude,
        )
        self._record(event)
        return event

    def get_recent_events(self, count: int = 50) -> list[AcousticEvent]:
        """Get the most recent classified events."""
        return self._event_history[-count:]

    def get_event_counts(self) -> dict[str, int]:
        """Get count of each event type in history."""
        counts: dict[str, int] = {}
        for event in self._event_history:
            t = event.event_type.value
            counts[t] = counts.get(t, 0) + 1
        return counts

    def _record(self, event: AcousticEvent) -> None:
        """Record event in history, trimming if needed."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
