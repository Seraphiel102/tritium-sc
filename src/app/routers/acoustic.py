# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Acoustic classification API endpoints.

Provides event classification results, sensor management, and
acoustic event history for the tactical map.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from engine.audio.acoustic_classifier import (
    AcousticClassifier,
    AcousticEventType,
    AudioFeatures,
)

router = APIRouter(prefix="/api/acoustic", tags=["acoustic"])

# Singleton classifier instance
_classifier = AcousticClassifier()


class ClassifyRequest(BaseModel):
    """Request to classify audio features."""

    rms_energy: float = 0.0
    peak_amplitude: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_bandwidth: float = 0.0
    duration_ms: int = 0
    device_id: str = ""


class AcousticEventResponse(BaseModel):
    """Response with classified acoustic event."""

    event_type: str
    confidence: float
    timestamp: float
    duration_ms: int
    peak_frequency_hz: float
    peak_amplitude_db: float
    device_id: str


@router.post("/classify", response_model=AcousticEventResponse)
async def classify_audio(request: ClassifyRequest):
    """Classify audio features into an acoustic event type."""
    features = AudioFeatures(
        rms_energy=request.rms_energy,
        peak_amplitude=request.peak_amplitude,
        zero_crossing_rate=request.zero_crossing_rate,
        spectral_centroid=request.spectral_centroid,
        spectral_bandwidth=request.spectral_bandwidth,
        duration_ms=request.duration_ms,
    )
    event = _classifier.classify(features)
    event.device_id = request.device_id

    return AcousticEventResponse(
        event_type=event.event_type.value,
        confidence=event.confidence,
        timestamp=event.timestamp,
        duration_ms=event.duration_ms,
        peak_frequency_hz=event.peak_frequency_hz,
        peak_amplitude_db=event.peak_amplitude_db,
        device_id=event.device_id,
    )


@router.get("/events")
async def get_events(count: int = 50):
    """Get recent acoustic events."""
    events = _classifier.get_recent_events(count)
    return [
        {
            "event_type": e.event_type.value,
            "confidence": e.confidence,
            "timestamp": e.timestamp,
            "duration_ms": e.duration_ms,
            "peak_frequency_hz": e.peak_frequency_hz,
            "device_id": e.device_id,
        }
        for e in events
    ]


@router.get("/stats")
async def get_stats():
    """Get acoustic event statistics."""
    return {
        "event_counts": _classifier.get_event_counts(),
        "event_types": [e.value for e in AcousticEventType],
        "total_events": len(_classifier.get_recent_events(10000)),
    }
