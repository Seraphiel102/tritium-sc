# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TargetCorrelator — fuses detections from different sensors into composite targets.

The key insight: a camera sees a "person" at position X, and a BLE scanner
sees a phone MAC at position Y nearby.  These are likely the same physical
entity and should be fused into one target with higher confidence and
combined attributes.

Correlation criteria (all must be met):
  1. Spatial proximity — targets within a configurable radius (default 5 units)
  2. Temporal proximity — both seen within the last 30s
  3. Source diversity — targets come from different sensor types (e.g. "ble" vs "yolo")

When correlated, the secondary target is merged into the primary (the one
with higher confidence), producing a composite target with boosted confidence
and combined attributes.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from .target_tracker import TargetTracker, TrackedTarget


@dataclass
class CorrelationRecord:
    """Record of a successful correlation between two targets."""

    primary_id: str
    secondary_id: str
    confidence: float
    reason: str
    timestamp: float = field(default_factory=time.monotonic)


class TargetCorrelator:
    """Fuses detections from different sensors into composite targets.

    Runs a periodic loop that examines all tracked targets, finds pairs
    that are likely the same physical entity, and merges them.
    """

    def __init__(
        self,
        tracker: TargetTracker,
        *,
        radius: float = 5.0,
        max_age: float = 30.0,
        interval: float = 5.0,
    ) -> None:
        """
        Args:
            tracker: The TargetTracker to read/write targets from.
            radius: Maximum distance between targets to consider correlation.
            max_age: Maximum age (seconds) for a target to be eligible.
            interval: How often the correlation loop runs (seconds).
        """
        self.tracker = tracker
        self.radius = radius
        self.max_age = max_age
        self.interval = interval

        self._correlations: list[CorrelationRecord] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def correlate(self) -> list[CorrelationRecord]:
        """Run one correlation pass over all tracked targets.

        Returns a list of new CorrelationRecords for pairs that were fused.
        """
        targets = self.tracker.get_all()
        now = time.monotonic()

        # Filter to recent targets only
        recent = [t for t in targets if (now - t.last_seen) <= self.max_age]

        new_correlations: list[CorrelationRecord] = []
        consumed: set[str] = set()

        # Sort by confidence descending — higher-confidence targets become primary
        recent.sort(key=lambda t: t.position_confidence, reverse=True)

        for i, primary in enumerate(recent):
            if primary.target_id in consumed:
                continue
            for secondary in recent[i + 1 :]:
                if secondary.target_id in consumed:
                    continue

                # Source diversity — don't fuse same-sensor detections
                if primary.source == secondary.source:
                    continue

                # Spatial proximity
                dx = primary.position[0] - secondary.position[0]
                dy = primary.position[1] - secondary.position[1]
                dist = math.hypot(dx, dy)
                if dist > self.radius:
                    continue

                # Both passed — correlate
                confidence = self._compute_confidence(primary, secondary, dist)
                reason = (
                    f"{primary.source}+{secondary.source} within {dist:.1f} units"
                )

                record = CorrelationRecord(
                    primary_id=primary.target_id,
                    secondary_id=secondary.target_id,
                    confidence=confidence,
                    reason=reason,
                )
                new_correlations.append(record)
                consumed.add(secondary.target_id)

                # Merge secondary into primary
                self._merge(primary, secondary)

                # Remove the secondary from the tracker
                self.tracker.remove(secondary.target_id)

        with self._lock:
            self._correlations.extend(new_correlations)

        return new_correlations

    def get_correlations(self) -> list[CorrelationRecord]:
        """Return all correlation records."""
        with self._lock:
            return list(self._correlations)

    def _compute_confidence(
        self, primary: TrackedTarget, secondary: TrackedTarget, dist: float
    ) -> float:
        """Compute correlation confidence from distance and individual confidences.

        Closer targets and higher individual confidences yield higher
        correlation confidence.
        """
        # Distance factor: 1.0 at dist=0, 0.0 at dist=radius
        dist_factor = max(0.0, 1.0 - (dist / self.radius))

        # Average of individual position confidences
        avg_conf = (primary.position_confidence + secondary.position_confidence) / 2.0

        # Weighted combination
        return min(1.0, 0.6 * dist_factor + 0.4 * avg_conf)

    def _merge(self, primary: TrackedTarget, secondary: TrackedTarget) -> None:
        """Merge secondary target attributes into primary."""
        # Boost confidence
        primary.position_confidence = min(
            1.0,
            primary.position_confidence + secondary.position_confidence * 0.5,
        )

        # Update last_seen to the most recent
        primary.last_seen = max(primary.last_seen, secondary.last_seen)

        # Append source info to name if not already composite
        if secondary.source not in primary.name:
            primary.name = f"{primary.name} [{secondary.source}]"

        # If primary has low-quality position but secondary is better, use secondary
        if secondary.position_confidence > primary.position_confidence:
            primary.position = secondary.position
            primary.position_source = secondary.position_source

    def _loop(self) -> None:
        """Background correlation loop."""
        while self._running:
            self.correlate()
            time.sleep(self.interval)

    def start(self) -> None:
        """Start the periodic correlation loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="correlator", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the periodic correlation loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
            self._thread = None


def start_correlator(tracker: TargetTracker, **kwargs) -> TargetCorrelator:
    """Create and start a TargetCorrelator.

    Args:
        tracker: The TargetTracker instance to correlate against.
        **kwargs: Passed to TargetCorrelator constructor (radius, max_age, interval).

    Returns:
        The running TargetCorrelator instance.
    """
    correlator = TargetCorrelator(tracker, **kwargs)
    correlator.start()
    return correlator


def stop_correlator(correlator: TargetCorrelator) -> None:
    """Stop a running TargetCorrelator."""
    correlator.stop()
