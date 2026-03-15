# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tactical event store — wraps tritium-lib EventStore with EventBus integration.

Subscribes to the local EventBus and persists ALL tactical events:
  - target_sighting    — BLE/WiFi/camera/mesh sighting
  - target_correlation — fused target detected
  - geofence_event     — target entered/exited a zone
  - alert              — threat alert raised
  - acoustic_detection — sound classified
  - escalation         — threat level changed
  - command            — operator or Amy command issued
  - state_change       — system state transition
  - briefing           — daily briefing generated

The store wraps :class:`tritium_lib.store.EventStore` and adds:
  1. EventBus auto-subscription — events are persisted as they arrive
  2. Site-scoped recording (site_id from config)
  3. Convenience query helpers used by the analytics API

Usage::

    from engine.tactical.event_store import TacticalEventStore

    store = TacticalEventStore(event_bus, db_path="data/events.db")
    store.start()
    # events now auto-persist from EventBus
    events = store.query_time_range(start=time.time() - 3600)
    store.stop()
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from tritium_lib.store.event_store import EventStore, TacticalEvent

log = logging.getLogger(__name__)

# Event types we subscribe to on the EventBus
_TRACKED_EVENT_TYPES = (
    "target_sighting",
    "target_detected",
    "target_lost",
    "target_correlation",
    "target_updated",
    "geofence_enter",
    "geofence_exit",
    "geofence_event",
    "alert",
    "alert_raised",
    "acoustic_detection",
    "escalation",
    "escalation_change",
    "command",
    "command_sent",
    "state_change",
    "briefing",
    "threat_classified",
    "rf_motion",
    "patrol_event",
    "investigation_event",
)


class TacticalEventStore:
    """Wraps tritium-lib EventStore with EventBus auto-persistence.

    Parameters
    ----------
    event_bus:
        The application EventBus instance (from engine.comms.event_bus).
    db_path:
        Path to the SQLite database file.
    site_id:
        Site identifier for multi-site deployments.
    max_events:
        Maximum events to retain before pruning oldest.
    """

    def __init__(
        self,
        event_bus: Any = None,
        db_path: str | Path = "data/events.db",
        site_id: str = "home",
        max_events: int = 500_000,
    ) -> None:
        self._event_bus = event_bus
        self._site_id = site_id
        self._store = EventStore(db_path=db_path, max_events=max_events)
        self._started = False
        self._subscriptions: list[Any] = []

    @property
    def store(self) -> EventStore:
        """Access the underlying tritium-lib EventStore."""
        return self._store

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Subscribe to EventBus and begin persisting events."""
        if self._started:
            return
        self._started = True

        if self._event_bus is not None:
            for event_type in _TRACKED_EVENT_TYPES:
                try:
                    sub = self._event_bus.subscribe(
                        event_type, self._on_event
                    )
                    self._subscriptions.append((event_type, sub))
                except Exception:
                    # Some event buses don't return subscription handles
                    self._subscriptions.append((event_type, None))

        log.info(
            "TacticalEventStore started (db=%s, subscriptions=%d)",
            self._store._db_path,
            len(self._subscriptions),
        )

    def stop(self) -> None:
        """Unsubscribe and close."""
        if not self._started:
            return
        self._started = False

        if self._event_bus is not None:
            for event_type, sub in self._subscriptions:
                try:
                    if sub is not None:
                        self._event_bus.unsubscribe(event_type, sub)
                except Exception:
                    pass
        self._subscriptions.clear()

        log.info("TacticalEventStore stopped")

    def close(self) -> None:
        """Stop and close the database."""
        self.stop()
        self._store.close()

    # ------------------------------------------------------------------
    # EventBus handler
    # ------------------------------------------------------------------

    def _on_event(self, event_type: str, data: dict | None = None, **kwargs: Any) -> None:
        """Handle an EventBus event by persisting it."""
        if not self._started:
            return

        payload = data if isinstance(data, dict) else {}
        payload.update(kwargs)

        # Extract common fields from the payload
        severity = payload.pop("severity", "info")
        source = payload.pop("source", "")
        target_id = payload.pop("target_id", "")
        operator = payload.pop("operator", "")
        summary = payload.pop("summary", "")
        position_lat = payload.pop("position_lat", None)
        position_lng = payload.pop("position_lng", None)

        # Also check nested position
        if position_lat is None and "lat" in payload:
            position_lat = payload.get("lat")
        if position_lng is None and "lng" in payload:
            position_lng = payload.get("lng")

        try:
            self._store.record(
                event_type,
                severity=severity,
                source=source,
                target_id=target_id,
                operator=operator,
                summary=summary,
                data=payload,
                position_lat=position_lat,
                position_lng=position_lng,
                site_id=self._site_id,
            )
        except Exception as exc:
            log.warning("Failed to persist event %s: %s", event_type, exc)

    # ------------------------------------------------------------------
    # Direct recording (for non-EventBus callers)
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        *,
        severity: str = "info",
        source: str = "",
        target_id: str = "",
        operator: str = "",
        summary: str = "",
        data: Optional[dict] = None,
        position_lat: Optional[float] = None,
        position_lng: Optional[float] = None,
    ) -> str:
        """Record a tactical event directly (bypasses EventBus)."""
        return self._store.record(
            event_type,
            severity=severity,
            source=source,
            target_id=target_id,
            operator=operator,
            summary=summary,
            data=data,
            position_lat=position_lat,
            position_lng=position_lng,
            site_id=self._site_id,
        )

    # ------------------------------------------------------------------
    # Query pass-throughs
    # ------------------------------------------------------------------

    def query_time_range(
        self,
        start: Optional[float] = None,
        end: Optional[float] = None,
        limit: int = 500,
    ) -> list[TacticalEvent]:
        """Query events within a time range."""
        return self._store.query_time_range(start=start, end=end, limit=limit)

    def query_by_type(
        self,
        event_type: str,
        *,
        start: Optional[float] = None,
        end: Optional[float] = None,
        limit: int = 100,
    ) -> list[TacticalEvent]:
        """Query events by type."""
        return self._store.query_by_type(
            event_type, start=start, end=end, limit=limit
        )

    def query_by_target(self, target_id: str, *, limit: int = 100) -> list[TacticalEvent]:
        """Query events by target ID."""
        return self._store.query_by_target(target_id, limit=limit)

    def get_stats(
        self,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> dict:
        """Get aggregate stats for a time period."""
        return self._store.get_stats(start=start, end=end)

    def count(
        self,
        event_type: Optional[str] = None,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> int:
        """Count events matching filters."""
        return self._store.count(event_type=event_type, start=start, end=end)

    def get_hourly_breakdown(
        self,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> dict[int, int]:
        """Get event counts grouped by hour-of-day (0-23).

        Returns dict mapping hour -> count.
        """
        conditions: list[str] = []
        params: list = []

        if start is not None:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        # SQLite: extract hour from unix timestamp
        sql = f"""
            SELECT CAST(strftime('%H', timestamp, 'unixepoch', 'localtime') AS INTEGER) AS hour,
                   COUNT(*) AS cnt
            FROM tactical_events {where}
            GROUP BY hour
            ORDER BY hour
        """

        store = self._store
        with store._lock:
            rows = store._fetchall(sql, tuple(params))

        return {row["hour"]: row["cnt"] for row in rows}

    def get_top_targets(
        self,
        start: Optional[float] = None,
        end: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get the most-seen targets in a time period.

        Returns list of dicts with target_id and sighting_count.
        """
        conditions = ["target_id != ''"]
        params: list = []

        if start is not None:
            conditions.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            conditions.append("timestamp <= ?")
            params.append(end)

        where = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT target_id, COUNT(*) AS cnt
            FROM tactical_events {where}
            GROUP BY target_id
            ORDER BY cnt DESC
            LIMIT ?
        """
        params.append(limit)

        store = self._store
        with store._lock:
            rows = store._fetchall(sql, tuple(params))

        return [{"target_id": row["target_id"], "event_count": row["cnt"]} for row in rows]

    def cleanup(self) -> int:
        """Prune oldest events if over the limit."""
        return self._store.cleanup()
