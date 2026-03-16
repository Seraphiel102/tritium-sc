# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Indoor-outdoor transition detector.

Detects when a BLE/WiFi target transitions between outdoor (GPS-based
positioning) and indoor (WiFi fingerprint / trilateration only) contexts.

Detection logic:
  1. A target with GPS-derived position that switches to WiFi-only
     trilateration has likely entered a building.
  2. A target with WiFi-only positioning that gains GPS signal has
     likely exited a building.
  3. RSSI pattern changes (stronger indoor APs, weaker outdoor nodes)
     corroborate the transition.

Publishes TransitionEvent via EventBus for downstream analytics,
dossier enrichment, and alert generation.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    pass

# TransitionEvent import — may fail if tritium-lib is not installed
try:
    from tritium_lib.models.transition import TransitionEvent, TransitionType
except ImportError:
    TransitionEvent = None  # type: ignore[assignment,misc]
    TransitionType = None  # type: ignore[assignment,misc]

logger = logging.getLogger("edge-tracker.transition")

# Minimum observations before detecting a transition
MIN_OBSERVATIONS = 3
# Window for considering recent positioning method history (seconds)
HISTORY_WINDOW = 120.0
# Cooldown between transitions for the same target (seconds)
TRANSITION_COOLDOWN = 60.0


@dataclass
class TargetPositioningState:
    """Tracks the positioning method history for a single target."""

    target_id: str
    # Recent positioning observations: (timestamp, method, has_gps, node_count)
    observations: list[tuple[float, str, bool, int]] = field(default_factory=list)
    current_state: str = "unknown"  # "indoor", "outdoor", "unknown"
    last_transition_time: float = 0.0
    max_observations: int = 50

    def add_observation(
        self,
        method: str,
        has_gps: bool,
        node_count: int = 1,
        timestamp: float | None = None,
    ) -> None:
        ts = timestamp or time.time()
        self.observations.append((ts, method, has_gps, node_count))
        if len(self.observations) > self.max_observations:
            self.observations = self.observations[-self.max_observations:]

    def recent_observations(self, window: float = HISTORY_WINDOW) -> list[tuple[float, str, bool, int]]:
        cutoff = time.time() - window
        return [(t, m, g, n) for t, m, g, n in self.observations if t > cutoff]


class IndoorOutdoorDetector:
    """Detects indoor-outdoor transitions for tracked targets.

    Feed target position updates with their positioning method metadata.
    The detector tracks method history and fires TransitionEvents when
    a target's positioning context changes.
    """

    def __init__(self, event_bus: Any = None) -> None:
        self._event_bus = event_bus
        self._lock = threading.Lock()
        self._targets: dict[str, TargetPositioningState] = {}
        self._transition_log: list[dict[str, Any]] = []
        self._max_log = 500

    def update_target(
        self,
        target_id: str,
        position: tuple[float, float] | None = None,
        positioning_method: str = "unknown",
        has_gps: bool = False,
        trilateration: dict[str, Any] | None = None,
        node_count: int = 1,
        node_id: str = "",
    ) -> dict[str, Any] | None:
        """Update a target's positioning state and check for transitions.

        Args:
            target_id: Unique target identifier.
            position: Current position (lat, lng) if available.
            positioning_method: How position was derived
                ("gps", "trilateration", "wifi_fingerprint", "proximity", "unknown").
            has_gps: Whether the position includes GPS data.
            trilateration: Trilateration result dict if available.
            node_count: Number of nodes contributing to position.
            node_id: Reporting edge node.

        Returns:
            TransitionEvent dict if a transition was detected, else None.
        """
        if TransitionEvent is None:
            return None

        now = time.time()

        with self._lock:
            if target_id not in self._targets:
                self._targets[target_id] = TargetPositioningState(target_id=target_id)

            state = self._targets[target_id]

            # Determine effective method
            method = positioning_method
            if trilateration and trilateration.get("confidence", 0) > 0.3:
                method = "trilateration"
            if has_gps:
                method = "gps"

            state.add_observation(method, has_gps, node_count, now)

            # Check for transition
            recent = state.recent_observations()
            if len(recent) < MIN_OBSERVATIONS:
                return None

            # Cooldown check
            if (now - state.last_transition_time) < TRANSITION_COOLDOWN:
                return None

            # Classify current positioning context
            new_context = self._classify_context(recent)
            if new_context == "unknown" or new_context == state.current_state:
                return None

            # Transition detected
            old_state = state.current_state
            state.current_state = new_context
            state.last_transition_time = now

            # Compute confidence based on observation consistency
            confidence = self._compute_confidence(recent, new_context)

            event = TransitionEvent(
                target_id=target_id,
                from_state=old_state,
                to_state=new_context,
                transition_type=TransitionType.INDOOR_OUTDOOR,
                position=position,
                timestamp=now,
                confidence=confidence,
                source="indoor_outdoor_detector",
                node_id=node_id,
                metadata={
                    "positioning_method": method,
                    "has_gps": has_gps,
                    "node_count": node_count,
                    "observation_count": len(recent),
                },
            )

            event_dict = event.to_dict()
            self._transition_log.append(event_dict)
            if len(self._transition_log) > self._max_log:
                self._transition_log = self._transition_log[-self._max_log:]

            # Publish to EventBus
            if self._event_bus is not None:
                self._event_bus.publish("transition:indoor_outdoor", data=event_dict)

            logger.info(
                "Indoor/outdoor transition: %s %s -> %s (conf=%.2f, method=%s)",
                target_id, old_state, new_context, confidence, method,
            )

            return event_dict

    def _classify_context(self, observations: list[tuple[float, str, bool, int]]) -> str:
        """Classify whether recent observations indicate indoor or outdoor.

        Heuristics:
          - GPS present -> outdoor
          - WiFi fingerprint only -> indoor
          - Trilateration with many nodes -> could be either
          - Proximity only (1 node) with no GPS -> likely indoor
        """
        gps_count = sum(1 for _, _, has_gps, _ in observations if has_gps)
        total = len(observations)

        if total == 0:
            return "unknown"

        gps_ratio = gps_count / total

        # Strong GPS presence -> outdoor
        if gps_ratio >= 0.6:
            return "outdoor"

        # Count by method
        method_counts: dict[str, int] = {}
        for _, method, _, _ in observations:
            method_counts[method] = method_counts.get(method, 0) + 1

        wifi_fp = method_counts.get("wifi_fingerprint", 0)
        proximity = method_counts.get("proximity", 0)
        trilat = method_counts.get("trilateration", 0)

        # WiFi fingerprint dominant -> indoor
        indoor_ratio = (wifi_fp + proximity) / total
        if indoor_ratio >= 0.6 and gps_ratio < 0.2:
            return "indoor"

        # Trilateration without GPS -> likely indoor
        if trilat > 0 and gps_ratio < 0.1:
            return "indoor"

        # Mostly GPS -> outdoor
        if gps_ratio >= 0.4:
            return "outdoor"

        return "unknown"

    def _compute_confidence(self, observations: list[tuple[float, str, bool, int]], context: str) -> float:
        """Compute confidence in the transition based on observation consistency."""
        total = len(observations)
        if total == 0:
            return 0.0

        if context == "outdoor":
            matching = sum(1 for _, _, has_gps, _ in observations if has_gps)
        elif context == "indoor":
            matching = sum(
                1 for _, m, g, _ in observations
                if m in ("wifi_fingerprint", "proximity", "trilateration") and not g
            )
        else:
            return 0.5

        ratio = matching / total
        # Scale: 60% match -> 0.5 confidence, 100% match -> 1.0
        return min(1.0, max(0.3, ratio * 1.25))

    def get_target_state(self, target_id: str) -> str:
        """Get current indoor/outdoor state for a target."""
        with self._lock:
            state = self._targets.get(target_id)
            return state.current_state if state else "unknown"

    def get_recent_transitions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent transition events."""
        with self._lock:
            return list(reversed(self._transition_log[-limit:]))

    def get_status(self) -> dict[str, Any]:
        """Return detector status for API."""
        with self._lock:
            indoor = sum(1 for s in self._targets.values() if s.current_state == "indoor")
            outdoor = sum(1 for s in self._targets.values() if s.current_state == "outdoor")
            return {
                "tracked_targets": len(self._targets),
                "indoor_targets": indoor,
                "outdoor_targets": outdoor,
                "total_transitions": len(self._transition_log),
            }

    def prune_stale(self, max_age: float = 600.0) -> int:
        """Remove targets with no recent observations."""
        cutoff = time.time() - max_age
        pruned = 0
        with self._lock:
            stale = [
                tid for tid, state in self._targets.items()
                if not state.observations or state.observations[-1][0] < cutoff
            ]
            for tid in stale:
                del self._targets[tid]
                pruned += 1
        return pruned
