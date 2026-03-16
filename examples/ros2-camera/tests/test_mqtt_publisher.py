# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the MQTT publisher wrapper.

Tests verify topic formatting, payload structure, and connect/disconnect
behavior. All MQTT dependencies are mocked.
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Mock paho.mqtt before importing
# ---------------------------------------------------------------------------
_mock_paho = MagicMock()
sys.modules.setdefault("paho", _mock_paho)
sys.modules.setdefault("paho.mqtt", _mock_paho.mqtt)
sys.modules.setdefault("paho.mqtt.client", _mock_paho.mqtt.client)

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros2_camera.mqtt_publisher import MQTTPublisher


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_publisher(
    site_id: str = "home",
    camera_id: str = "test-cam-01",
    on_command=None,
) -> MQTTPublisher:
    """Create a MQTTPublisher with mock MQTT client."""
    pub = MQTTPublisher(
        host="localhost",
        port=1883,
        site_id=site_id,
        camera_id=camera_id,
        on_command=on_command,
    )
    return pub


# ===========================================================================
# Test classes
# ===========================================================================


class TestTopicFormatting:
    """Verify MQTT topics follow TRITIUM-SC camera protocol."""

    def test_frame_topic(self):
        pub = _make_publisher()
        assert pub.frame_topic == "tritium/home/cameras/test-cam-01/frame"

    def test_detections_topic(self):
        pub = _make_publisher()
        assert pub.detections_topic == "tritium/home/cameras/test-cam-01/detections"

    def test_command_topic(self):
        pub = _make_publisher()
        assert pub.command_topic == "tritium/home/cameras/test-cam-01/command"

    def test_custom_site_id(self):
        pub = _make_publisher(site_id="backyard")
        assert pub.frame_topic == "tritium/backyard/cameras/test-cam-01/frame"

    def test_custom_camera_id(self):
        pub = _make_publisher(camera_id="roof-cam")
        assert pub.frame_topic == "tritium/home/cameras/roof-cam/frame"

    def test_topic_structure(self):
        """All topics must follow tritium/{site}/cameras/{id}/{suffix}."""
        pub = _make_publisher(site_id="lab", camera_id="cam-42")
        for topic in [pub.frame_topic, pub.detections_topic, pub.command_topic]:
            parts = topic.split("/")
            assert parts[0] == "tritium"
            assert parts[1] == "lab"
            assert parts[2] == "cameras"
            assert parts[3] == "cam-42"


class TestPublishFrame:
    """Test JPEG frame publishing."""

    def test_publish_frame_when_connected(self):
        pub = _make_publisher()
        pub._connected = True
        mock_client = MagicMock()
        pub._client = mock_client

        jpeg = b"\xff\xd8fake-jpeg-data"
        pub.publish_frame(jpeg)

        mock_client.publish.assert_called_once()
        args = mock_client.publish.call_args
        assert args[0][0] == "tritium/home/cameras/test-cam-01/frame"
        assert args[0][1] == jpeg
        assert args[1]["qos"] == 0 or args[0][2] == 0

    def test_publish_frame_skipped_when_disconnected(self):
        pub = _make_publisher()
        pub._connected = False
        mock_client = MagicMock()
        pub._client = mock_client

        pub.publish_frame(b"\xff\xd8data")
        mock_client.publish.assert_not_called()


class TestPublishDetections:
    """Test detection payload publishing."""

    def test_publish_detections_format(self):
        pub = _make_publisher()
        pub._connected = True
        mock_client = MagicMock()
        pub._client = mock_client

        detections = [
            {"class_name": "person", "confidence": 0.92, "bbox": [10, 20, 100, 200]},
        ]
        pub.publish_detections(detections)

        mock_client.publish.assert_called_once()
        args = mock_client.publish.call_args
        topic = args[0][0]
        assert topic == "tritium/home/cameras/test-cam-01/detections"

        payload = json.loads(args[0][1])
        assert payload["camera_id"] == "test-cam-01"
        assert "timestamp" in payload
        assert isinstance(payload["detections"], list)
        assert len(payload["detections"]) == 1
        assert payload["detections"][0]["class_name"] == "person"

    def test_publish_detections_skipped_when_disconnected(self):
        pub = _make_publisher()
        pub._connected = False
        mock_client = MagicMock()
        pub._client = mock_client

        pub.publish_detections([{"class_name": "car", "confidence": 0.8, "bbox": [0, 0, 10, 10]}])
        mock_client.publish.assert_not_called()

    def test_publish_empty_detections(self):
        pub = _make_publisher()
        pub._connected = True
        mock_client = MagicMock()
        pub._client = mock_client

        pub.publish_detections([])

        mock_client.publish.assert_called_once()
        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["detections"] == []

    def test_detection_payload_has_camera_id(self):
        pub = _make_publisher(camera_id="my-cam")
        pub._connected = True
        mock_client = MagicMock()
        pub._client = mock_client

        pub.publish_detections([])

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert payload["camera_id"] == "my-cam"

    def test_detection_payload_has_timestamp(self):
        pub = _make_publisher()
        pub._connected = True
        mock_client = MagicMock()
        pub._client = mock_client

        pub.publish_detections([])

        payload = json.loads(mock_client.publish.call_args[0][1])
        assert "timestamp" in payload
        assert "T" in payload["timestamp"]  # ISO format


class TestCommandCallback:
    """Test MQTT command subscription and callback."""

    def test_on_command_called(self):
        handler = MagicMock()
        pub = _make_publisher(on_command=handler)

        # Simulate incoming message
        mock_msg = MagicMock()
        mock_msg.payload = json.dumps({"command": "camera_off"}).encode("utf-8")
        pub._on_message(None, None, mock_msg)

        handler.assert_called_once_with({"command": "camera_off"})

    def test_on_command_not_called_for_bad_json(self):
        handler = MagicMock()
        pub = _make_publisher(on_command=handler)

        mock_msg = MagicMock()
        mock_msg.payload = b"not-json"
        pub._on_message(None, None, mock_msg)

        handler.assert_not_called()

    def test_no_callback_no_crash(self):
        """If on_command is None, messages should be silently ignored."""
        pub = _make_publisher(on_command=None)
        mock_msg = MagicMock()
        mock_msg.payload = json.dumps({"command": "test"}).encode("utf-8")
        pub._on_message(None, None, mock_msg)  # Should not raise


class TestConnectDisconnect:
    """Test connection state tracking."""

    def test_initial_state_disconnected(self):
        pub = _make_publisher()
        assert pub.connected is False

    def test_on_connect_sets_connected(self):
        pub = _make_publisher()
        pub._on_connect(MagicMock(), None, None, 0)
        assert pub.connected is True

    def test_on_connect_failed_stays_disconnected(self):
        pub = _make_publisher()
        pub._on_connect(MagicMock(), None, None, 5)
        assert pub.connected is False

    def test_on_disconnect_clears_connected(self):
        pub = _make_publisher()
        pub._connected = True
        pub._on_disconnect(None, None, 0)
        assert pub.connected is False

    def test_on_connect_subscribes_to_command_topic(self):
        pub = _make_publisher()
        mock_client = MagicMock()
        pub._on_connect(mock_client, None, None, 0)
        mock_client.subscribe.assert_called_once_with(
            "tritium/home/cameras/test-cam-01/command", qos=1,
        )
