# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""MQTT client wrapper for publishing camera frames and detections.

Publishes to TRITIUM-SC camera topics:
    tritium/{site}/cameras/{camera_id}/frame      -- JPEG bytes (QoS 0)
    tritium/{site}/cameras/{camera_id}/detections  -- JSON detection payload (QoS 0)

Subscribes to:
    tritium/{site}/cameras/{camera_id}/command     -- camera on/off commands
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

import paho.mqtt.client as mqtt


class MQTTPublisher:
    """MQTT client for publishing camera data to TRITIUM-SC."""

    def __init__(
        self,
        host: str,
        port: int,
        site_id: str,
        camera_id: str,
        on_command: Callable[[dict], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._site = site_id
        self._camera_id = camera_id
        self._on_command = on_command
        self._connected = False

        client_id = f"ros2-cam-{camera_id}-{int(time.time()) % 10000}"
        self._client = mqtt.Client(client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        """Connect to MQTT broker and start network loop."""
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        """Stop network loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            self._connected = True
            cmd_topic = self._topic("command")
            client.subscribe(cmd_topic, qos=1)

    def _on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        self._connected = False

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        if self._on_command is None:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return
        self._on_command(payload)

    def _topic(self, suffix: str) -> str:
        """Build a TRITIUM-SC camera topic."""
        return f"tritium/{self._site}/cameras/{self._camera_id}/{suffix}"

    def publish_frame(self, jpeg_bytes: bytes) -> None:
        """Publish a JPEG frame to the frame topic (QoS 0)."""
        if not self._connected:
            return
        self._client.publish(self._topic("frame"), jpeg_bytes, qos=0)

    def publish_detections(self, detections: list[dict]) -> None:
        """Publish detection results to the detections topic (QoS 0).

        Args:
            detections: List of detection dicts, each with class_name,
                        confidence, and bbox [x1, y1, x2, y2].
        """
        if not self._connected:
            return
        payload = {
            "camera_id": self._camera_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detections": detections,
        }
        self._client.publish(
            self._topic("detections"), json.dumps(payload), qos=0,
        )

    @property
    def frame_topic(self) -> str:
        return self._topic("frame")

    @property
    def detections_topic(self) -> str:
        return self._topic("detections")

    @property
    def command_topic(self) -> str:
        return self._topic("command")
