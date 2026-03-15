# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DailySummaryGenerator — generate daily activity summaries.

At a configurable time (default midnight), generates a JSON summary of
the day's activity: total unique targets, new targets, departed targets,
highest threat level reached, busiest hour, total sightings by source.

Stores summaries in the TacticalEventStore for historical trend analysis.

Usage::

    generator = DailySummaryGenerator(
        event_store=tactical_store,
        target_tracker=tracker,
        event_bus=bus,
        summary_hour=0,   # midnight
        summary_minute=0,
    )
    generator.start()
    # ... runs daily at configured time
    generator.stop()

    # Manual generation
    summary = generator.generate_summary()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default summary generation time (midnight UTC)
DEFAULT_SUMMARY_HOUR = 0
DEFAULT_SUMMARY_MINUTE = 0


class DailySummaryGenerator:
    """Generates daily activity summaries for trend analysis.

    Thread-safe. Runs a background thread that triggers summary
    generation at the configured time each day.

    Parameters
    ----------
    event_store:
        TacticalEventStore for querying events and storing summaries.
    target_tracker:
        TargetTracker for current target state.
    event_bus:
        EventBus for publishing daily_summary events.
    summary_hour:
        Hour of day (0-23 UTC) to generate the summary.
    summary_minute:
        Minute of hour (0-59) to generate the summary.
    """

    def __init__(
        self,
        event_store=None,
        target_tracker=None,
        event_bus=None,
        summary_hour: int = DEFAULT_SUMMARY_HOUR,
        summary_minute: int = DEFAULT_SUMMARY_MINUTE,
    ) -> None:
        self._event_store = event_store
        self._target_tracker = target_tracker
        self._event_bus = event_bus
        self._summary_hour = summary_hour
        self._summary_minute = summary_minute
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_summary_date: str = ""
        self._summaries: list[dict] = []

    def start(self) -> None:
        """Start the daily summary background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._schedule_loop, daemon=True, name="daily-summary"
        )
        self._thread.start()
        logger.info(
            "DailySummaryGenerator started (scheduled at %02d:%02d UTC)",
            self._summary_hour, self._summary_minute,
        )

    def stop(self) -> None:
        """Stop the daily summary background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("DailySummaryGenerator stopped")

    def _schedule_loop(self) -> None:
        """Background loop checking if it's time to generate a summary."""
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                today_str = now.strftime("%Y-%m-%d")

                if (
                    now.hour == self._summary_hour
                    and now.minute == self._summary_minute
                    and today_str != self._last_summary_date
                ):
                    summary = self.generate_summary()
                    self._last_summary_date = today_str
                    logger.info(
                        "Daily summary generated for %s: %d unique targets",
                        today_str, summary.get("unique_targets", 0),
                    )
            except Exception:
                logger.exception("Daily summary generation error")

            # Check every 30 seconds
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1.0)

    def generate_summary(self, date_str: str | None = None) -> dict:
        """Generate a summary for the given date (default: today).

        Returns a JSON-serializable dict with the day's activity summary.
        """
        now = datetime.now(timezone.utc)
        if date_str is None:
            date_str = now.strftime("%Y-%m-%d")

        # Time range for the day (midnight to midnight UTC)
        day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        day_start_ts = day_start.timestamp()
        day_end_ts = day_start_ts + 86400

        summary: dict[str, Any] = {
            "date": date_str,
            "generated_at": now.isoformat(),
            "unique_targets": 0,
            "new_targets": 0,
            "departed_targets": 0,
            "highest_threat_level": "none",
            "busiest_hour": -1,
            "busiest_hour_count": 0,
            "sightings_by_source": {},
            "total_sightings": 0,
            "total_events": 0,
            "event_counts_by_type": {},
            "hourly_activity": [0] * 24,
            "convoys_detected": 0,
            "alerts_raised": 0,
        }

        # Query events from the store if available
        events = self._query_events(day_start_ts, day_end_ts)
        summary["total_events"] = len(events)

        # Analyze events
        target_ids_seen: set[str] = set()
        new_target_ids: set[str] = set()
        departed_target_ids: set[str] = set()
        sightings_by_source: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        hourly: list[int] = [0] * 24
        threat_levels_seen: list[str] = []
        convoy_count = 0
        alert_count = 0

        for ev in events:
            ev_type = ev.get("event_type", ev.get("type", ""))
            ev_data = ev.get("data", ev)
            ev_ts = ev.get("timestamp", 0)

            event_counts[ev_type] = event_counts.get(ev_type, 0) + 1

            # Hour tracking
            if ev_ts:
                try:
                    hour = datetime.fromtimestamp(ev_ts, tz=timezone.utc).hour
                    hourly[hour] += 1
                except (ValueError, OSError):
                    pass

            # Sighting analysis
            if ev_type in ("target_sighting", "target_detected"):
                tid = ev_data.get("target_id", "")
                source = ev_data.get("source", "unknown")
                if tid:
                    target_ids_seen.add(tid)
                sightings_by_source[source] = sightings_by_source.get(source, 0) + 1

            # New/departed targets
            if ev_type == "target_detected":
                tid = ev_data.get("target_id", "")
                if tid:
                    new_target_ids.add(tid)
            elif ev_type == "target_lost":
                tid = ev_data.get("target_id", "")
                if tid:
                    departed_target_ids.add(tid)

            # Threat tracking
            if ev_type in ("escalation", "escalation_change"):
                level = ev_data.get("level", ev_data.get("threat_level", ""))
                if level:
                    threat_levels_seen.append(level)

            # Convoy tracking
            if ev_type == "convoy_detected":
                convoy_count += 1

            # Alert tracking
            if ev_type in ("alert", "alert_raised"):
                alert_count += 1

        # Find busiest hour
        if hourly:
            max_hour = max(range(24), key=lambda h: hourly[h])
            summary["busiest_hour"] = max_hour
            summary["busiest_hour_count"] = hourly[max_hour]

        # Compute highest threat level
        threat_priority = {
            "critical": 4, "high": 3, "elevated": 2, "moderate": 2,
            "advisory": 1, "low": 1, "none": 0,
        }
        if threat_levels_seen:
            highest = max(threat_levels_seen, key=lambda l: threat_priority.get(l, 0))
            summary["highest_threat_level"] = highest

        # Also check current tracker state
        if self._target_tracker:
            try:
                current_targets = self._target_tracker.get_all_targets()
                if isinstance(current_targets, dict):
                    target_ids_seen.update(current_targets.keys())
                elif isinstance(current_targets, list):
                    for t in current_targets:
                        tid = t.get("target_id", "") if isinstance(t, dict) else getattr(t, "target_id", "")
                        if tid:
                            target_ids_seen.add(tid)
            except Exception:
                pass

        summary["unique_targets"] = len(target_ids_seen)
        summary["new_targets"] = len(new_target_ids)
        summary["departed_targets"] = len(departed_target_ids)
        summary["sightings_by_source"] = sightings_by_source
        summary["total_sightings"] = sum(sightings_by_source.values())
        summary["event_counts_by_type"] = event_counts
        summary["hourly_activity"] = hourly
        summary["convoys_detected"] = convoy_count
        summary["alerts_raised"] = alert_count

        # Store the summary
        with self._lock:
            self._summaries.append(summary)
            # Keep last 90 days
            if len(self._summaries) > 90:
                self._summaries = self._summaries[-90:]

        # Publish to event bus
        self._publish_event("daily_summary", summary)

        # Store in event store
        self._store_summary(summary)

        return summary

    def get_recent_summaries(self, count: int = 30) -> list[dict]:
        """Return the most recent daily summaries."""
        with self._lock:
            return list(self._summaries[-count:])

    def get_summary_for_date(self, date_str: str) -> dict | None:
        """Return the summary for a specific date, if available."""
        with self._lock:
            for s in self._summaries:
                if s["date"] == date_str:
                    return dict(s)
        return None

    def get_trend(self, days: int = 7) -> dict:
        """Return trend analysis over the last N days."""
        with self._lock:
            recent = self._summaries[-days:]

        if not recent:
            return {"days": 0, "avg_targets": 0, "avg_sightings": 0, "trend": "unknown"}

        avg_targets = sum(s.get("unique_targets", 0) for s in recent) / len(recent)
        avg_sightings = sum(s.get("total_sightings", 0) for s in recent) / len(recent)

        # Compute trend direction
        trend = "stable"
        if len(recent) >= 3:
            first_half = recent[:len(recent) // 2]
            second_half = recent[len(recent) // 2:]
            first_avg = sum(s.get("unique_targets", 0) for s in first_half) / len(first_half)
            second_avg = sum(s.get("unique_targets", 0) for s in second_half) / len(second_half)
            if second_avg > first_avg * 1.1:
                trend = "increasing"
            elif second_avg < first_avg * 0.9:
                trend = "decreasing"

        return {
            "days": len(recent),
            "avg_targets": round(avg_targets, 1),
            "avg_sightings": round(avg_sightings, 1),
            "trend": trend,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _query_events(self, start_ts: float, end_ts: float) -> list[dict]:
        """Query events from the event store for a time range."""
        if self._event_store is None:
            return []
        try:
            if hasattr(self._event_store, 'query_time_range'):
                return self._event_store.query_time_range(start=start_ts, end=end_ts)
            elif hasattr(self._event_store, 'query'):
                return self._event_store.query(start_time=start_ts, end_time=end_ts)
        except Exception:
            logger.debug("Failed to query event store")
        return []

    def _publish_event(self, event_type: str, data: dict) -> None:
        """Publish event to EventBus."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(event_type, data)
        except Exception:
            logger.debug("Failed to publish %s event", event_type)

    def _store_summary(self, summary: dict) -> None:
        """Store summary as a tactical event."""
        if self._event_store is None:
            return
        try:
            if hasattr(self._event_store, 'record'):
                self._event_store.record(
                    event_type="daily_summary",
                    data=summary,
                )
        except Exception:
            logger.debug("Failed to store daily summary")
