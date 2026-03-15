# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Sensorium — Amy's L3 AWARENESS layer.

Fuses data from all sensor threads (YOLO, deep vision, audio, motor,
thinking) into a temporal narrative that higher layers can read.

This is a passive data structure — no thread of its own.  Other threads
push events in, and the thinking thread reads the narrative out.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class SceneEvent:
    """A single timestamped event in Amy's awareness."""

    timestamp: float        # monotonic time
    source: str             # "yolo", "deep", "audio", "motor", "thought"
    text: str               # human-readable description
    importance: float = 0.5 # 0.0-1.0
    source_node: str = ""   # which sensor node generated this

    @property
    def age(self) -> float:
        """Seconds since this event."""
        return time.monotonic() - self.timestamp


@dataclass
class MoodSnapshot:
    """A single mood transition record."""

    timestamp: float
    mood: str
    trigger_event: str = ""


# Source display labels for the narrative
_SOURCE_LABELS = {
    "yolo": "Vision",
    "deep": "Observation",
    "audio": "Audio",
    "motor": "Movement",
    "thought": "Thought",
    "ble": "BLE",
    "mesh": "Mesh",
    "rf_anomaly": "RF Anomaly",
}


@dataclass
class BLEDeviceSnapshot:
    """Snapshot of BLE devices from the latest scan."""

    total: int = 0
    known: int = 0
    unknown: int = 0
    devices: list[dict] = field(default_factory=list)
    timestamp: float = 0.0

    @property
    def age(self) -> float:
        if self.timestamp == 0.0:
            return float("inf")
        return time.monotonic() - self.timestamp


@dataclass
class MeshNodeSnapshot:
    """Snapshot of Meshtastic mesh nodes from the latest update."""

    count: int = 0
    nodes: list[dict] = field(default_factory=list)
    timestamp: float = 0.0

    @property
    def age(self) -> float:
        if self.timestamp == 0.0:
            return float("inf")
        return time.monotonic() - self.timestamp


class Sensorium:
    """Sensor fusion layer — maintains a sliding window of scene events.

    Thread-safe: any thread can push events, any thread can read
    the narrative.
    """

    def __init__(self, max_events: int = 30, window_seconds: float = 120.0):
        self._events: deque[SceneEvent] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._window = window_seconds
        self._people_present: bool = False
        self._people_count: int = 0
        self._last_speech_time: float = 0.0
        self._last_silence_push: float = 0.0
        self._mood_history: list[MoodSnapshot] = []
        self._last_mood: str = "neutral"

        # Battlespace summary callback (set by Commander when target tracker exists)
        self._battlespace_fn: callable | None = None

        # BLE and Mesh awareness
        self._ble_snapshot = BLEDeviceSnapshot()
        self._mesh_snapshot = MeshNodeSnapshot()
        self._ble_new_devices: list[dict] = []  # recently appeared devices
        self._ble_known_macs: set[str] = set()  # MACs seen across all scans

        # Environment awareness (from Meshtastic nodes or edge sensors)
        self._environment_readings: dict[str, dict] = {}  # source_id -> latest reading
        self._environment_timestamp: float = 0.0

        # Anomaly baseline awareness
        self._anomaly_alerts: list[dict] = []  # recent anomaly alerts for narrative
        self._anomaly_summary: str = ""        # cached anomaly context string

        # Dimensional mood model: valence (-1..1) and arousal (0..1)
        self._mood_valence: float = 0.0   # negative=unpleasant, positive=pleasant
        self._mood_arousal: float = 0.3   # low=calm, high=excited

    def push(self, source: str, text: str, importance: float = 0.5,
             source_node: str = "") -> None:
        """Add a scene event (called from any thread).

        Deduplicates consecutive identical events from the same source.
        """
        now = time.monotonic()

        # Debounce silence events (at most once per 30 seconds)
        if source == "audio" and "silence" in text.lower():
            if now - self._last_silence_push < 30.0:
                return
            self._last_silence_push = now

        with self._lock:
            # Skip if identical to the most recent event from same source
            if self._events:
                last = self._events[-1]
                if last.source == source and last.text == text and last.age < 5.0:
                    return

            event = SceneEvent(
                timestamp=now,
                source=source,
                text=text,
                importance=importance,
                source_node=source_node,
            )
            self._events.append(event)

            # Track people presence from YOLO events
            if source == "yolo":
                text_lower = text.lower()
                # Specific departure phrases — avoid loose "left" match
                _DEPARTURE_PHRASES = (
                    "left the room", "left the scene", "left the area",
                    "left the frame", "has left", "have left",
                    "everyone left", "all left", "they left",
                    "person departed", "person exited",
                )
                if "person" in text_lower or "people" in text_lower:
                    if any(p in text_lower for p in _DEPARTURE_PHRASES) and "entered" not in text_lower:
                        self._people_present = False
                        self._people_count = 0
                    else:
                        self._people_present = True
                elif "everyone left" in text_lower or "empty" in text_lower:
                    self._people_present = False
                    self._people_count = 0

            # Track speech timing
            if source == "audio" and "said" in text.lower():
                self._last_speech_time = now

            # Update dimensional mood
            self._update_mood_dimensions(source, text)

        # Track mood transitions (outside lock to avoid calling mood under lock)
        current_mood = self.mood
        if current_mood != self._last_mood:
            self._mood_history.append(MoodSnapshot(
                timestamp=now, mood=current_mood, trigger_event=text[:60],
            ))
            if len(self._mood_history) > 10:
                self._mood_history = self._mood_history[-10:]
            self._last_mood = current_mood

    def narrative(self) -> str:
        """Build a temporal narrative for LLM context."""
        now = time.monotonic()
        with self._lock:
            events = [e for e in self._events if e.age < self._window]

        if not events:
            return "No recent observations."

        lines = []
        for event in events:
            age = now - event.timestamp
            if age < 3:
                time_str = "Now"
            elif age < 60:
                time_str = f"{int(age)}s ago"
            elif age < 3600:
                time_str = f"{int(age / 60)}m ago"
            else:
                time_str = f"{int(age / 3600)}h ago"

            lines.append(f"{time_str}: {event.text}")

        return "\n".join(lines)

    def summary(self) -> str:
        """One-line current state for the dashboard."""
        with self._lock:
            if not self._events:
                return "Quiet. No observations yet."

            latest: dict[str, SceneEvent] = {}
            for event in reversed(list(self._events)):
                if event.source not in latest and event.age < self._window:
                    latest[event.source] = event
                if len(latest) >= 4:
                    break

        parts = []
        if "yolo" in latest:
            parts.append(latest["yolo"].text)
        if "deep" in latest:
            parts.append(latest["deep"].text)
        if "audio" in latest:
            parts.append(latest["audio"].text)

        return " | ".join(parts) if parts else "Quiet."

    @property
    def people_present(self) -> bool:
        with self._lock:
            return self._people_present

    @property
    def seconds_since_speech(self) -> float:
        with self._lock:
            if self._last_speech_time == 0:
                return float("inf")
            return time.monotonic() - self._last_speech_time

    def _update_mood_dimensions(self, source: str, text: str) -> None:
        """Nudge valence/arousal based on a new event. Called inside lock."""
        text_lower = text.lower()
        dv, da = 0.0, 0.0

        # Speech / conversation → positive valence, higher arousal
        if "said" in text_lower or "speech" in text_lower:
            dv += 0.15
            da += 0.12

        # People present → mild positive
        if "person" in text_lower or "people" in text_lower:
            if any(p in text_lower for p in ("left", "departed", "exited")):
                dv -= 0.05
                da -= 0.05
            else:
                dv += 0.08
                da += 0.06

        # Entered / appeared → curiosity spike
        if "entered" in text_lower or "appeared" in text_lower:
            dv += 0.10
            da += 0.15

        # Silence / quiet → calming (no valence shift, just lower arousal)
        if "silence" in text_lower or "quiet" in text_lower:
            da -= 0.10

        # Thoughts → mild contemplation
        if source == "thought":
            da -= 0.02

        # BLE new device → curiosity spike
        if source == "ble" and "new" in text_lower:
            dv += 0.05
            da += 0.08

        # Mesh low battery → mild concern
        if source == "mesh" and "low battery" in text_lower:
            dv -= 0.03
            da += 0.05

        # RF anomaly → vigilance
        if source == "rf_anomaly":
            dv -= 0.08
            da += 0.12

        # Apply with natural decay toward baseline (0.0, 0.3)
        self._mood_valence = max(-1.0, min(1.0, self._mood_valence * 0.95 + dv))
        self._mood_arousal = max(0.0, min(1.0, self._mood_arousal * 0.95 + da))

    @property
    def mood(self) -> str:
        """Amy's inferred mood from dimensional valence/arousal model."""
        v = self._mood_valence
        a = self._mood_arousal

        # Check for near-baseline → neutral
        if abs(v) < 0.05 and abs(a - 0.3) < 0.08:
            return "neutral"

        # Map dimensions to named states
        if v > 0.2 and a > 0.6:
            return "excited"
        if v > 0.1 and a > 0.3:
            return "engaged"
        if v > 0.05 and a <= 0.3:
            return "content"
        if v < -0.1 and a > 0.4:
            return "uneasy"
        if v < -0.05 and a <= 0.3:
            return "melancholy"
        if a < 0.15:
            return "calm"
        if a > 0.4:
            return "curious"

        # Fallback: check event-based signals for attentive/contemplative
        with self._lock:
            recent = [e for e in self._events if e.age < 60]
        if recent:
            sources = [e.source for e in recent]
            if self.people_present:
                return "attentive"
            if sources.count("thought") > 2:
                return "contemplative"

        return "neutral"

    @property
    def mood_description(self) -> str:
        """Human-readable mood intensity for LLM context."""
        v = self._mood_valence
        a = self._mood_arousal
        mood_name = self.mood

        # Intensity from distance from baseline
        intensity = (abs(v) + abs(a - 0.3)) / 2.0
        if intensity > 0.3:
            prefix = "strongly"
        elif intensity > 0.12:
            prefix = "mildly"
        else:
            prefix = "slightly"

        return f"{prefix} {mood_name}"

    @property
    def recent_thoughts(self) -> list[str]:
        """Get the last few internal thoughts for the thinking prompt."""
        with self._lock:
            thoughts = [
                e.text for e in self._events
                if e.source == "thought" and e.age < 120
            ]
        return thoughts[-8:]

    # ------------------------------------------------------------------
    # BLE / Mesh awareness
    # ------------------------------------------------------------------

    def update_ble(self, data: dict) -> None:
        """Process a BLE scan update from the event bus.

        Expected *data* keys:
        - ``devices``: list of dicts with ``addr``, ``name``, ``rssi``, ``type``
        - ``count``: total device count
        - ``node_id``: reporting scanner id (optional)
        """
        now = time.monotonic()
        devices = data.get("devices", [])
        count = data.get("count", len(devices))

        known = [d for d in devices if d.get("name")]
        unknown = [d for d in devices if not d.get("name")]

        # Detect newly appeared devices (MACs not seen before)
        current_macs = {d.get("addr", "") for d in devices}
        new_macs = current_macs - self._ble_known_macs
        new_devices = [d for d in devices if d.get("addr") in new_macs and d.get("name")]

        with self._lock:
            self._ble_snapshot = BLEDeviceSnapshot(
                total=count,
                known=len(known),
                unknown=len(unknown),
                devices=devices,
                timestamp=now,
            )
            self._ble_new_devices = new_devices[-5:]  # keep last 5 new
            self._ble_known_macs.update(current_macs)

        # Push a sensorium event for significant changes
        if new_devices:
            names = ", ".join(d.get("name", "?") for d in new_devices[:3])
            extra = f" (+{len(new_devices) - 3} more)" if len(new_devices) > 3 else ""
            self.push("ble", f"New BLE device(s): {names}{extra}", importance=0.6)
        elif count > 0:
            self.push("ble", f"BLE scan: {count} devices ({len(known)} known, {len(unknown)} unknown)", importance=0.3)

    def update_mesh(self, data: dict) -> None:
        """Process a Meshtastic nodes_updated event from the event bus.

        Expected *data* keys:
        - ``nodes``: list of dicts with ``node_id``, ``long_name``, ``short_name``,
          ``battery``, ``snr``, ``position``
        - ``count``: node count
        """
        now = time.monotonic()
        nodes = data.get("nodes", [])
        count = data.get("count", len(nodes))

        with self._lock:
            self._mesh_snapshot = MeshNodeSnapshot(
                count=count,
                nodes=nodes,
                timestamp=now,
            )

        # Push a sensorium event
        if count > 0:
            low_battery = [n for n in nodes if n.get("battery", 100) < 30]
            if low_battery:
                names = ", ".join(n.get("short_name", n.get("node_id", "?")) for n in low_battery[:2])
                self.push("mesh", f"Mesh: {count} nodes online. Low battery: {names}", importance=0.6)
            else:
                self.push("mesh", f"Mesh: {count} nodes online", importance=0.3)

    @property
    def ble_snapshot(self) -> BLEDeviceSnapshot:
        """Current BLE device snapshot (thread-safe read)."""
        with self._lock:
            return self._ble_snapshot

    @property
    def mesh_snapshot(self) -> MeshNodeSnapshot:
        """Current Meshtastic node snapshot (thread-safe read)."""
        with self._lock:
            return self._mesh_snapshot

    def ble_context(self) -> str:
        """Build a BLE awareness string for the thinking prompt."""
        snap = self.ble_snapshot
        if snap.total == 0 or snap.age > 120:
            return ""
        line = f"BLE: {snap.total} devices detected ({snap.known} known, {snap.unknown} unknown)."
        with self._lock:
            new_devs = list(self._ble_new_devices)
        if new_devs:
            names = ", ".join(d.get("name", "?") for d in new_devs[:3])
            line += f" New: {names}."
        return line

    def update_environment(self, data: dict) -> None:
        """Process an environment reading from mesh nodes or edge sensors.

        Expected *data* keys:
        - ``source_id``: node or device ID
        - ``source_name``: human-readable name (optional)
        - ``temperature_c``: temperature in Celsius (optional)
        - ``humidity_pct``: relative humidity 0-100 (optional)
        - ``pressure_hpa``: barometric pressure in hPa (optional)
        - ``air_quality_index``: AQI value (optional)
        - ``light_level_lux``: ambient light in lux (optional)
        """
        source_id = data.get("source_id", "")
        if not source_id:
            return

        now = time.monotonic()
        with self._lock:
            self._environment_readings[source_id] = {
                **data,
                "_timestamp": now,
            }
            self._environment_timestamp = now

        # Build a sensorium event with human-readable environment info
        parts = []
        name = data.get("source_name") or source_id
        temp_c = data.get("temperature_c")
        if temp_c is not None:
            temp_f = temp_c * 9.0 / 5.0 + 32.0
            parts.append(f"{temp_f:.0f}F")
        humidity = data.get("humidity_pct")
        if humidity is not None:
            parts.append(f"{humidity:.0f}% humidity")
        pressure = data.get("pressure_hpa")
        if pressure is not None:
            parts.append(f"{pressure:.0f} hPa")
        aqi = data.get("air_quality_index")
        if aqi is not None:
            parts.append(f"AQI {aqi:.0f}")

        if parts:
            env_str = ", ".join(parts)
            self.push("mesh", f"Mesh node {name} reports {env_str}", importance=0.4)

    def environment_context(self) -> str:
        """Build an environment awareness string for the thinking prompt."""
        now = time.monotonic()
        with self._lock:
            if not self._environment_readings:
                return ""
            # Only show if data is recent (within 5 minutes)
            if now - self._environment_timestamp > 300:
                return ""
            readings = dict(self._environment_readings)

        lines = []
        for source_id, data in readings.items():
            # Skip stale readings (>5 min)
            if now - data.get("_timestamp", 0) > 300:
                continue
            name = data.get("source_name") or source_id
            parts = []
            temp_c = data.get("temperature_c")
            if temp_c is not None:
                temp_f = temp_c * 9.0 / 5.0 + 32.0
                parts.append(f"{temp_f:.0f}F/{temp_c:.1f}C")
            humidity = data.get("humidity_pct")
            if humidity is not None:
                parts.append(f"{humidity:.0f}% humidity")
            pressure = data.get("pressure_hpa")
            if pressure is not None:
                parts.append(f"{pressure:.0f} hPa")
            if parts:
                lines.append(f"  {name}: {', '.join(parts)}")

        if not lines:
            return ""
        return "Environment:\n" + "\n".join(lines)

    def update_anomalies(self, anomalies: list[dict]) -> None:
        """Process anomaly alerts from the AnomalyBaselineCollector.

        Expected *anomalies*: list of dicts with ``metric_name``,
        ``current_value``, ``baseline_mean``, ``baseline_std``,
        ``deviation_sigma``, ``direction``, ``severity``, ``description``.
        """
        if not anomalies:
            return

        with self._lock:
            # Keep last 10 anomalies
            self._anomaly_alerts = (self._anomaly_alerts + anomalies)[-10:]

        # Build narrative-friendly summary
        parts: list[str] = []
        for a in anomalies:
            metric = a.get("metric_name", "unknown")
            direction = a.get("direction", "")
            sigma = a.get("deviation_sigma", 0.0)
            current = a.get("current_value", 0)
            baseline_mean = a.get("baseline_mean", 0)
            severity = a.get("severity", "low")

            # Human-readable metric names
            metric_labels = {
                "ble_device_count": "BLE device count",
                "wifi_network_count": "WiFi network count",
                "rssi_mean": "average RSSI",
                "device_churn_new": "new device arrivals",
                "device_churn_departed": "device departures",
                "total_sightings": "total sightings",
            }
            label = metric_labels.get(metric, metric)

            if metric == "ble_device_count" and direction == "below":
                pct = round((1.0 - current / max(baseline_mean, 1)) * 100)
                parts.append(
                    f"{pct}% fewer BLE devices than normal baseline "
                    f"({int(current)} vs {int(baseline_mean)} avg)"
                )
            elif metric == "ble_device_count" and direction == "above":
                pct = round((current / max(baseline_mean, 1) - 1.0) * 100)
                parts.append(
                    f"{pct}% more BLE devices than normal ({int(current)} vs {int(baseline_mean)} avg)"
                )
            else:
                parts.append(
                    f"{label} is {sigma:.1f} sigma {direction} normal "
                    f"({current:.1f} vs {baseline_mean:.1f})"
                )

        summary = "; ".join(parts)
        with self._lock:
            self._anomaly_summary = summary

        # Push a sensorium event for significant anomalies
        high_count = sum(1 for a in anomalies if a.get("severity") in ("high", "medium"))
        importance = 0.7 if high_count else 0.5
        self.push("rf_anomaly", f"RF anomaly: {summary}", importance=importance)

    def anomaly_context(self) -> str:
        """Build an anomaly awareness string for the thinking prompt."""
        with self._lock:
            summary = self._anomaly_summary
            alerts = list(self._anomaly_alerts)
        if not summary:
            return ""

        # Only show if anomalies are recent (within 30 minutes)
        if alerts:
            latest_ts = max(a.get("timestamp", 0) for a in alerts)
            if latest_ts > 0 and (time.time() - latest_ts) > 1800:
                return ""

        return f"RF ANOMALY ALERT: {summary}"

    def mesh_context(self) -> str:
        """Build a Meshtastic mesh awareness string for the thinking prompt."""
        snap = self.mesh_snapshot
        if snap.count == 0 or snap.age > 120:
            return ""
        parts = [f"Mesh: {snap.count} nodes online."]
        for node in snap.nodes[:5]:
            name = node.get("short_name") or node.get("long_name") or node.get("node_id", "?")
            batt = node.get("battery")
            snr = node.get("snr")
            details = []
            if batt is not None:
                details.append(f"battery {batt:.0f}%")
            if snr is not None:
                details.append(f"SNR {snr:.1f}")
            if details:
                parts.append(f"  {name}: {', '.join(details)}")
        return "\n".join(parts)

    def rich_narrative(self, max_events: int = 15, min_importance: float = 0.3) -> str:
        """Importance-weighted narrative with mood transitions and grouping."""
        now = time.monotonic()
        with self._lock:
            events = [e for e in self._events if e.age < self._window]

        if not events:
            return "No recent observations."

        # Filter by importance
        events = [e for e in events if e.importance >= min_importance]
        if not events:
            return "Quiet period."

        # Score by importance * recency
        scored: list[tuple[float, SceneEvent]] = []
        for e in events:
            recency = max(0.3, 1.0 - e.age / self._window)
            scored.append((e.importance * recency, e))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Take top events, re-sort by time
        top = sorted(scored[:max_events], key=lambda x: x[1].timestamp)

        # Group consecutive same-source events
        lines: list[str] = []
        i = 0
        while i < len(top):
            _, event = top[i]
            # Count consecutive same-source
            group = [event]
            j = i + 1
            while j < len(top) and top[j][1].source == event.source:
                group.append(top[j][1])
                j += 1

            age = now - event.timestamp
            if age < 3:
                time_str = "Now"
            elif age < 60:
                time_str = f"{int(age)}s ago"
            elif age < 3600:
                time_str = f"{int(age / 60)}m ago"
            else:
                time_str = f"{int(age / 3600)}h ago"

            label = _SOURCE_LABELS.get(event.source, event.source.title())
            if len(group) > 2 and all(g.text == group[0].text for g in group):
                duration = group[-1].timestamp - group[0].timestamp
                lines.append(f"{time_str} [{label}]: {group[0].text} (repeated, {duration:.0f}s)")
            else:
                for g in group:
                    g_age = now - g.timestamp
                    if g_age < 3:
                        g_ts = "Now"
                    elif g_age < 60:
                        g_ts = f"{int(g_age)}s ago"
                    else:
                        g_ts = f"{int(g_age / 60)}m ago"
                    g_label = _SOURCE_LABELS.get(g.source, g.source.title())
                    lines.append(f"{g_ts} [{g_label}]: {g.text}")

            i = j

        # Prepend context: mood transitions, people presence, speech timing
        header_lines: list[str] = []
        for ms in self._mood_history[-3:]:
            if ms.timestamp > now - self._window:
                header_lines.append(f"[Mood shift: {ms.mood}]")

        if self._people_present:
            header_lines.append(f"[People present: {self._people_count or 'yes'}]")
        sss = self.seconds_since_speech
        if sss < 30:
            header_lines.append("[Recent speech activity]")
        elif sss < float("inf") and sss < 300:
            header_lines.append(f"[Last speech: {int(sss)}s ago]")

        # BLE / Mesh awareness
        ble_ctx = self.ble_context()
        if ble_ctx:
            header_lines.append(f"[{ble_ctx}]")
        mesh_ctx = self.mesh_context()
        if mesh_ctx:
            # mesh_context may be multiline; wrap each line
            for mline in mesh_ctx.split("\n"):
                header_lines.append(f"[{mline.strip()}]")

        # Environment awareness
        env_ctx = self.environment_context()
        if env_ctx:
            for eline in env_ctx.split("\n"):
                header_lines.append(f"[{eline.strip()}]")

        # Anomaly baseline awareness
        anomaly_ctx = self.anomaly_context()
        if anomaly_ctx:
            header_lines.append(f"[{anomaly_ctx}]")

        # Curiosity: unknown devices worth investigating
        curiosity_ctx = self.curiosity_context()
        if curiosity_ctx:
            for cline in curiosity_ctx.split("\n"):
                header_lines.append(f"[{cline.strip()}]")

        # Battlespace summary from target tracker
        if self._battlespace_fn is not None:
            try:
                bs = self._battlespace_fn()
                if bs:
                    header_lines.append(f"[{bs}]")
            except Exception:
                pass

        return "\n".join(header_lines + lines)

    # ------------------------------------------------------------------
    # Amy curiosity system — proactive investigation of unknown targets
    # ------------------------------------------------------------------

    def curiosity_targets(self, rssi_threshold: int = -70,
                          max_results: int = 3) -> list[dict]:
        """Return unknown BLE devices with strong signal worth investigating.

        Amy should express curiosity about these in her inner monologue
        and suggest investigation. Only returns devices that:
        - Have no name (unknown)
        - Have strong RSSI (above threshold, meaning they're close)
        - Were recently detected (within last 60s)
        """
        snap = self.ble_snapshot
        if snap.total == 0 or snap.age > 60:
            return []

        candidates = []
        for dev in snap.devices:
            name = dev.get("name", "")
            rssi = dev.get("rssi", -100)
            addr = dev.get("addr", "")
            device_type = dev.get("type", "unknown")

            # Only unknown/unnamed devices with strong signal
            if not name and rssi >= rssi_threshold and addr:
                candidates.append({
                    "addr": addr,
                    "rssi": rssi,
                    "device_type": device_type,
                    "signal_strength": "strong" if rssi > -50 else "moderate",
                })

        # Sort by signal strength (strongest first)
        candidates.sort(key=lambda d: d["rssi"], reverse=True)
        return candidates[:max_results]

    def curiosity_context(self) -> str:
        """Build a curiosity prompt for Amy's thinking loop.

        Returns a string Amy can use in her inner monologue to express
        curiosity about nearby unknown devices.
        """
        targets = self.curiosity_targets()
        if not targets:
            return ""

        lines = ["CURIOSITY: Unknown devices detected nearby:"]
        for t in targets:
            addr_short = t["addr"][-8:]  # last 8 chars of MAC
            lines.append(
                f"  - Device {addr_short} ({t['signal_strength']} signal, "
                f"RSSI {t['rssi']}dBm, type: {t['device_type']})"
            )
        lines.append(
            "Consider: What kind of device is this? Is it a phone someone "
            "is carrying? A new IoT device? Should we investigate?"
        )
        return "\n".join(lines)

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)
