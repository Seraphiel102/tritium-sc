# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SDRMonitorPlugin — rtl_433 MQTT integration for ISM band device tracking.

Subscribes to the MQTT topic that rtl_433 publishes to when run with:
    rtl_433 -F mqtt://localhost:1883,events=rtl_433/events

Incoming JSON messages represent decoded ISM band transmissions —
weather stations, tire pressure sensors (TPMS), doorbell buttons,
car key fobs, soil moisture probes, and hundreds of other 433/868/915 MHz
devices.

Each unique device gets a TrackedTarget so it appears on the tactical map.
Signal history, frequency activity, and per-type statistics are stored
for the API layer.

MQTT topics:
    IN:  rtl_433/events  (configurable via settings)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("sdr_monitor")

# Defaults
DEFAULT_MQTT_TOPIC = "rtl_433/events"
DEFAULT_DEVICE_TTL = 600.0          # seconds before a device is considered stale
MAX_DEVICE_HISTORY = 5000
MAX_SIGNAL_HISTORY = 2000
DEFAULT_POLL_INTERVAL = 10.0        # cleanup loop interval


class ISMDevice:
    """A detected ISM band device from rtl_433."""

    __slots__ = (
        "device_id",
        "model",
        "protocol",
        "device_type",
        "frequency_mhz",
        "rssi_db",
        "snr_db",
        "first_seen",
        "last_seen",
        "message_count",
        "metadata",
    )

    def __init__(
        self,
        device_id: str,
        model: str = "unknown",
        protocol: str = "",
        device_type: str = "ism_device",
        frequency_mhz: float = 0.0,
        rssi_db: float = 0.0,
        snr_db: float = 0.0,
    ) -> None:
        self.device_id = device_id
        self.model = model
        self.protocol = protocol
        self.device_type = device_type
        self.frequency_mhz = frequency_mhz
        self.rssi_db = rssi_db
        self.snr_db = snr_db
        now = time.time()
        self.first_seen = now
        self.last_seen = now
        self.message_count = 1
        self.metadata: dict[str, Any] = {}

    def update(
        self,
        rssi_db: float = 0.0,
        snr_db: float = 0.0,
        frequency_mhz: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> None:
        """Update device with a new observation."""
        self.last_seen = time.time()
        self.message_count += 1
        if rssi_db != 0.0:
            self.rssi_db = rssi_db
        if snr_db != 0.0:
            self.snr_db = snr_db
        if frequency_mhz != 0.0:
            self.frequency_mhz = frequency_mhz
        if metadata:
            self.metadata.update(metadata)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "model": self.model,
            "protocol": self.protocol,
            "device_type": self.device_type,
            "frequency_mhz": self.frequency_mhz,
            "rssi_db": self.rssi_db,
            "snr_db": self.snr_db,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "message_count": self.message_count,
            "metadata": dict(self.metadata),
        }


# -- Device type classification from rtl_433 model names --------------------

_DEVICE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "weather_station": ["weather", "acurite", "oregon", "lacrosse", "bresser", "fineoffset", "fine-offset", "ambient"],
    "tire_pressure": ["tpms", "tire", "tyre"],
    "doorbell": ["doorbell", "door-bell", "chime"],
    "car_key_fob": ["keyfob", "key-fob", "car-key", "remote"],
    "soil_moisture": ["soil", "moisture"],
    "smoke_detector": ["smoke", "fire"],
    "garage_door": ["garage"],
    "thermostat": ["thermostat", "heat", "hvac"],
    "power_meter": ["power", "energy", "meter", "current-cost"],
    "water_meter": ["water-meter"],
    "gas_meter": ["gas-meter"],
    "lightning": ["lightning"],
    "pool_thermometer": ["pool"],
}


def classify_device_type(model: str) -> str:
    """Classify an rtl_433 model string into a device type category."""
    model_lower = model.lower()
    for dtype, keywords in _DEVICE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in model_lower:
                return dtype
    return "ism_device"


def build_device_id(msg: dict) -> str:
    """Build a unique device ID from an rtl_433 JSON message.

    rtl_433 messages typically include 'model' and 'id' fields. Some also
    include 'channel' or 'subtype' for disambiguation.
    """
    model = msg.get("model", "unknown")
    dev_id = msg.get("id", "")
    channel = msg.get("channel", "")
    parts = ["sdr", model.replace(" ", "_")]
    if dev_id != "":
        parts.append(str(dev_id))
    if channel != "":
        parts.append(f"ch{channel}")
    return "_".join(parts).lower()


class SDRMonitorPlugin(PluginInterface):
    """Monitors rtl_433 MQTT output and tracks ISM band devices."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._tracker: Any = None
        self._app: Any = None
        self._mqtt_bridge: Any = None
        self._logger: logging.Logger = log

        self._running = False
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None

        # Config
        self._mqtt_topic: str = DEFAULT_MQTT_TOPIC
        self._device_ttl: float = DEFAULT_DEVICE_TTL
        self._poll_interval: float = DEFAULT_POLL_INTERVAL

        # State
        self._devices: dict[str, ISMDevice] = {}
        self._signal_history: list[dict] = []
        self._frequency_activity: dict[float, int] = {}

        # Stats
        self._stats = {
            "messages_received": 0,
            "devices_detected": 0,
            "devices_active": 0,
            "targets_created": 0,
            "messages_by_type": {},
        }

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.sdr_monitor"

    @property
    def name(self) -> str:
        return "SDR Monitor — rtl_433 ISM Band Tracker"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"data_source", "routes", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._tracker = ctx.target_tracker
        self._app = ctx.app
        self._logger = ctx.logger or log

        settings = ctx.settings or {}
        if "mqtt_topic" in settings:
            self._mqtt_topic = str(settings["mqtt_topic"])
        if "device_ttl" in settings:
            self._device_ttl = float(settings["device_ttl"])
        if "poll_interval" in settings:
            self._poll_interval = float(settings["poll_interval"])

        # Subscribe to MQTT if bridge is available
        self._subscribe_mqtt(ctx)

        # Register API routes
        self._register_routes()

        self._logger.info(
            "SDR Monitor configured (topic=%s, ttl=%.0fs)",
            self._mqtt_topic,
            self._device_ttl,
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="sdr-monitor-cleanup",
        )
        self._cleanup_thread.start()
        self._logger.info("SDR Monitor started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=3.0)

        self._logger.info("SDR Monitor stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- MQTT subscription -------------------------------------------------

    def _subscribe_mqtt(self, ctx: PluginContext) -> None:
        """Subscribe to the rtl_433 MQTT topic via the system MQTT bridge."""
        mqtt_bridge = getattr(ctx, "mqtt_bridge", None)
        if mqtt_bridge is None and hasattr(ctx, "app") and ctx.app:
            mqtt_bridge = getattr(ctx.app.state, "mqtt_bridge", None)

        if mqtt_bridge is None:
            self._logger.info(
                "No MQTT bridge available — rtl_433 messages will be "
                "accepted via EventBus (type=rtl_433:message) or API"
            )
            return

        self._mqtt_bridge = mqtt_bridge
        try:
            mqtt_bridge.subscribe(self._mqtt_topic, self._on_mqtt_message)
            self._logger.info(
                "Subscribed to MQTT topic: %s", self._mqtt_topic
            )
        except Exception as exc:
            self._logger.warning(
                "Could not subscribe to MQTT topic %s: %s",
                self._mqtt_topic,
                exc,
            )

    def _on_mqtt_message(self, topic: str, payload: bytes | str) -> None:
        """Handle an incoming rtl_433 MQTT message."""
        try:
            data = json.loads(payload) if isinstance(payload, (bytes, str)) else payload
            self.ingest_message(data)
        except (json.JSONDecodeError, TypeError) as exc:
            self._logger.debug("Invalid rtl_433 JSON: %s", exc)

    # -- Public API --------------------------------------------------------

    def ingest_message(self, msg: dict) -> dict:
        """Parse and ingest an rtl_433 JSON message.

        Returns the processed device dict.
        """
        device_id = build_device_id(msg)
        model = msg.get("model", "unknown")
        protocol = msg.get("protocol", model)
        frequency_mhz = float(msg.get("freq", msg.get("frequency", 0.0)))
        rssi_db = float(msg.get("rssi", msg.get("rssi_db", 0.0)))
        snr_db = float(msg.get("snr", msg.get("snr_db", 0.0)))
        device_type = classify_device_type(model)

        # Extract metadata (everything that isn't a core field)
        core_keys = {"model", "id", "channel", "protocol", "freq", "frequency",
                      "rssi", "rssi_db", "snr", "snr_db", "time", "subtype"}
        metadata = {k: v for k, v in msg.items() if k not in core_keys}

        with self._lock:
            self._stats["messages_received"] += 1

            # Track frequency activity
            if frequency_mhz > 0:
                rounded = round(frequency_mhz, 2)
                self._frequency_activity[rounded] = (
                    self._frequency_activity.get(rounded, 0) + 1
                )

            # Track message count by device type
            type_counts = self._stats["messages_by_type"]
            type_counts[device_type] = type_counts.get(device_type, 0) + 1

            # Update or create device
            if device_id in self._devices:
                dev = self._devices[device_id]
                dev.update(
                    rssi_db=rssi_db,
                    snr_db=snr_db,
                    frequency_mhz=frequency_mhz,
                    metadata=metadata,
                )
            else:
                dev = ISMDevice(
                    device_id=device_id,
                    model=model,
                    protocol=protocol,
                    device_type=device_type,
                    frequency_mhz=frequency_mhz,
                    rssi_db=rssi_db,
                    snr_db=snr_db,
                )
                dev.metadata = metadata
                self._devices[device_id] = dev
                self._stats["devices_detected"] += 1

            # Record in signal history
            signal_record = {
                "device_id": device_id,
                "model": model,
                "device_type": device_type,
                "frequency_mhz": frequency_mhz,
                "rssi_db": rssi_db,
                "snr_db": snr_db,
                "timestamp": time.time(),
                "metadata": metadata,
            }
            self._signal_history.append(signal_record)
            if len(self._signal_history) > MAX_SIGNAL_HISTORY:
                self._signal_history = self._signal_history[-MAX_SIGNAL_HISTORY:]

            device_dict = dev.to_dict()

        # Publish to EventBus
        if self._event_bus:
            self._event_bus.publish("sdr_monitor:device", data=device_dict)

        # Create/update TrackedTarget
        self._update_target(dev)

        return device_dict

    def get_devices(self) -> list[dict]:
        """Return all detected ISM devices."""
        with self._lock:
            return [d.to_dict() for d in self._devices.values()]

    def get_spectrum(self) -> dict:
        """Return frequency activity summary."""
        with self._lock:
            return {
                "frequency_activity": dict(self._frequency_activity),
                "total_frequencies": len(self._frequency_activity),
            }

    def get_stats(self) -> dict:
        """Return detection statistics."""
        with self._lock:
            return {
                **self._stats,
                "devices_active": len(self._devices),
                "signal_history_size": len(self._signal_history),
                "running": self._running,
                "mqtt_topic": self._mqtt_topic,
            }

    def get_signals(self, limit: int = 50) -> list[dict]:
        """Return recent signal history."""
        with self._lock:
            return list(self._signal_history[-limit:])

    # -- Target tracking ---------------------------------------------------

    def _update_target(self, dev: ISMDevice) -> None:
        """Create or update a TrackedTarget for the ISM device."""
        if self._tracker is None:
            return

        try:
            from engine.tactical.target_tracker import TrackedTarget

            with self._tracker._lock:
                if dev.device_id in self._tracker._targets:
                    t = self._tracker._targets[dev.device_id]
                    t.last_seen = time.monotonic()
                    t.status = f"{dev.device_type}:{dev.model}"
                else:
                    self._tracker._targets[dev.device_id] = TrackedTarget(
                        target_id=dev.device_id,
                        name=f"ISM: {dev.model}",
                        alliance="unknown",
                        asset_type=dev.device_type,
                        position=(0.0, 0.0),
                        last_seen=time.monotonic(),
                        source="sdr_monitor",
                        position_source="rf_proximity",
                        position_confidence=0.1,
                        status=f"{dev.device_type}:{dev.model}",
                    )
                    with self._lock:
                        self._stats["targets_created"] += 1
        except Exception as exc:
            self._logger.error("Failed to create SDR target: %s", exc)

    # -- Cleanup loop (remove stale devices) --------------------------------

    def _cleanup_loop(self) -> None:
        """Background loop: remove devices not seen within TTL."""
        while self._running:
            try:
                now = time.time()
                expired = []

                with self._lock:
                    for did, dev in self._devices.items():
                        if (now - dev.last_seen) > self._device_ttl:
                            expired.append(did)
                    for did in expired:
                        del self._devices[did]

                # Remove from tracker
                if self._tracker and expired:
                    try:
                        with self._tracker._lock:
                            for did in expired:
                                self._tracker._targets.pop(did, None)
                    except Exception:
                        pass

            except Exception as exc:
                self._logger.error("SDR Monitor cleanup error: %s", exc)

            # Sleep in small increments for responsive shutdown
            deadline = time.monotonic() + self._poll_interval
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    # -- Routes ------------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router

        router = create_router(self)
        self._app.include_router(router)

    # -- EventBus handler (alternative to MQTT) ----------------------------

    def handle_event(self, event: dict) -> None:
        """Process EventBus events for rtl_433 data.

        Used when rtl_433 data arrives via EventBus instead of MQTT.
        """
        event_type = event.get("type", event.get("event_type", ""))
        data = event.get("data", {})

        if event_type == "rtl_433:message":
            self.ingest_message(data)
