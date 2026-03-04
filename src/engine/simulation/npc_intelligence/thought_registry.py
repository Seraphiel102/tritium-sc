# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ThoughtRegistry — central store for NPC thought bubbles.

Any source (internal AI, external API, Graphlings plugin) can write thoughts.
Thoughts publish to EventBus -> WebSocket bridge -> frontend rendering.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


# Importance levels for thought bubbles.
# Only thoughts at or above IMPORTANCE_BROADCAST_THRESHOLD are sent to clients.
IMPORTANCE_IDLE = "idle"          # Background chatter, not displayed
IMPORTANCE_LOW = "low"            # Minor observations
IMPORTANCE_NORMAL = "normal"      # Standard thoughts
IMPORTANCE_HIGH = "high"          # Notable events (spotted enemy, taking cover)
IMPORTANCE_CRITICAL = "critical"  # Combat, damage, kills, distress

# Numeric ranking for comparison
_IMPORTANCE_RANK = {
    IMPORTANCE_IDLE: 0,
    IMPORTANCE_LOW: 1,
    IMPORTANCE_NORMAL: 2,
    IMPORTANCE_HIGH: 3,
    IMPORTANCE_CRITICAL: 4,
}

# Only broadcast thoughts at or above this level to WebSocket clients.
# Clients can still request any unit's stored thought on click.
IMPORTANCE_BROADCAST_THRESHOLD = IMPORTANCE_HIGH


def importance_rank(level: str) -> int:
    """Return numeric rank for an importance level string."""
    return _IMPORTANCE_RANK.get(level, 2)


@dataclass
class UnitThought:
    """A single thought bubble for a unit."""

    unit_id: str
    text: str
    emotion: str = "neutral"  # neutral, curious, afraid, angry, happy
    importance: str = "normal"  # idle, low, normal, high, critical
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.monotonic)


class ThoughtRegistry:
    """Central store for NPC thought bubbles."""

    def __init__(self, event_bus: Any = None, plugin: Any = None):
        self._event_bus = event_bus
        self._plugin = plugin  # NPCIntelligencePlugin for brain access
        self._thoughts: dict[str, UnitThought] = {}
        self._controllers: dict[str, str] = {}  # unit_id -> controller_id
        self._lock = threading.Lock()
        self._running = False
        self._expiry_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the expiry cleanup thread."""
        if self._running:
            return
        self._running = True
        self._expiry_thread = threading.Thread(
            target=self._expiry_loop, daemon=True, name="thought-expiry"
        )
        self._expiry_thread.start()

    def stop(self) -> None:
        """Stop the expiry cleanup thread."""
        self._running = False
        if self._expiry_thread is not None:
            self._expiry_thread.join(timeout=2.0)
            self._expiry_thread = None

    def set_thought(
        self,
        unit_id: str,
        text: str,
        emotion: str = "neutral",
        duration: float = 5.0,
        importance: str = IMPORTANCE_NORMAL,
    ) -> UnitThought:
        """Set a thought bubble for a unit. No control lock needed.

        Thoughts are always stored locally.  Only thoughts at or above
        ``IMPORTANCE_BROADCAST_THRESHOLD`` are published to EventBus
        (and therefore forwarded to WebSocket clients).
        """
        now = time.monotonic()
        thought = UnitThought(
            unit_id=unit_id,
            text=text,
            emotion=emotion,
            importance=importance,
            expires_at=now + duration,
            created_at=now,
        )
        with self._lock:
            self._thoughts[unit_id] = thought

        # Only broadcast important thoughts to avoid spamming the frontend.
        should_broadcast = (
            importance_rank(importance)
            >= importance_rank(IMPORTANCE_BROADCAST_THRESHOLD)
        )
        if should_broadcast and self._event_bus is not None:
            self._event_bus.publish(
                "npc_thought",
                {
                    "unit_id": unit_id,
                    "text": text,
                    "emotion": emotion,
                    "duration": duration,
                    "importance": importance,
                },
            )
        return thought

    def clear_thought(self, unit_id: str) -> None:
        """Clear a thought bubble."""
        with self._lock:
            self._thoughts.pop(unit_id, None)
        if self._event_bus is not None:
            self._event_bus.publish("npc_thought_clear", {"unit_id": unit_id})

    def get_thought(self, unit_id: str) -> UnitThought | None:
        """Get the current thought for a unit."""
        with self._lock:
            thought = self._thoughts.get(unit_id)
        if thought is not None and time.monotonic() > thought.expires_at:
            self.clear_thought(unit_id)
            return None
        return thought

    def all_thoughts(self) -> dict[str, UnitThought]:
        """Snapshot of all active (non-expired) thoughts."""
        now = time.monotonic()
        with self._lock:
            return {
                uid: t
                for uid, t in self._thoughts.items()
                if t.expires_at > now
            }

    def take_control(self, unit_id: str, controller_id: str) -> bool:
        """Take control of an NPC. Returns False if locked by different controller or unit not found."""
        with self._lock:
            existing = self._controllers.get(unit_id)
            if existing is not None and existing != controller_id:
                return False
            self._controllers[unit_id] = controller_id
        # Bind the brain if plugin available
        if self._plugin is not None:
            brain = self._plugin.get_brain(unit_id)
            if brain is not None:
                brain.bind()
            else:
                # No brain found -- unit doesn't exist
                with self._lock:
                    self._controllers.pop(unit_id, None)
                return False
        return True

    def release_control(self, unit_id: str) -> None:
        """Release control of an NPC."""
        with self._lock:
            self._controllers.pop(unit_id, None)
        if self._plugin is not None:
            brain = self._plugin.get_brain(unit_id)
            if brain is not None:
                brain.unbind()

    def get_controller(self, unit_id: str) -> str | None:
        """Get the controller_id for a unit, or None if uncontrolled."""
        with self._lock:
            return self._controllers.get(unit_id)

    def _expiry_loop(self) -> None:
        """Background thread that clears expired thoughts every 1s."""
        while self._running:
            time.sleep(1.0)
            now = time.monotonic()
            expired: list[str] = []
            with self._lock:
                for uid, t in self._thoughts.items():
                    if t.expires_at <= now:
                        expired.append(uid)
            for uid in expired:
                self.clear_thought(uid)
