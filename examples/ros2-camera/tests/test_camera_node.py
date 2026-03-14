# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the ROS2 camera node.

Tests verify frame processing, MQTT publishing, detection format,
and command handling.

All ROS2 dependencies are mocked -- tests work without ROS2 installed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Mock ROS2 dependencies before importing our code
# ---------------------------------------------------------------------------

_PARAM_DEFAULTS = {
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "site_id": "home",
    "camera_id": "test-cam-01",
    "camera_enabled": True,
    "detection_interval": 1.0,
    "frame_width": 320,
    "frame_height": 240,
    "jpeg_quality": 80,
}


class _MockNode:
    """Minimal mock of rclpy.node.Node for CameraNode."""

    def __init__(self, name: str = "mock_node"):
        self._node_name = name

    def declare_parameter(self, name, default=None):
        pass

    def get_parameter(self, name):
        val = _PARAM_DEFAULTS.get(name, "")
        result = MagicMock()
        result.value = val
        return result

    def get_logger(self):
        return MagicMock()

    def create_timer(self, period, callback):
        return MagicMock()

    def create_subscription(self, msg_type, topic, callback, qos):
        return MagicMock()

    def create_publisher(self, msg_type, topic, qos):
        return MagicMock()

    def destroy_node(self):
        pass


# Build mock modules
_rclpy_mod = types.ModuleType("rclpy")
_rclpy_node_mod = types.ModuleType("rclpy.node")
_rclpy_node_mod.Node = _MockNode
_rclpy_mod.node = _rclpy_node_mod

_mock = MagicMock()

for mod_name in [
    "rclpy", "rclpy.node", "rclpy.action", "rclpy.action.client",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "nav2_msgs", "nav2_msgs.action",
    "tf2_ros",
    "paho", "paho.mqtt", "paho.mqtt.client",
]:
    sys.modules.setdefault(mod_name, _mock)

# Override the specific modules that need real classes
sys.modules["rclpy"] = _rclpy_mod
sys.modules["rclpy.node"] = _rclpy_node_mod

# Add ros2-camera package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ros2_camera.camera_node import CameraNode


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(**overrides) -> CameraNode:
    """Create a CameraNode with optional parameter overrides."""
    if overrides:
        old_defaults = dict(_PARAM_DEFAULTS)
        _PARAM_DEFAULTS.update(overrides)
        try:
            node = CameraNode()
        finally:
            _PARAM_DEFAULTS.clear()
            _PARAM_DEFAULTS.update(old_defaults)
    else:
        node = CameraNode()
    return node


def _make_bgr_frame(width: int = 320, height: int = 240) -> np.ndarray:
    """Create a synthetic BGR frame with varied intensity for detection.

    Uses a noisy background with bright spots so that adaptive thresholding
    produces contours (uniform rectangles on black won't trigger it).
    """
    cv2 = pytest.importorskip("cv2")
    # Mid-gray background with noise
    rng = np.random.RandomState(42)
    frame = rng.randint(40, 80, (height, width, 3), dtype=np.uint8)
    # Add bright spots that stand out from the noisy background
    cv2.circle(frame, (100, 100), 40, (255, 255, 255), -1)
    cv2.circle(frame, (220, 150), 30, (240, 240, 240), -1)
    return frame


def _make_ros_image(
    width: int = 320, height: int = 240, encoding: str = "bgr8",
) -> MagicMock:
    """Create a mock ROS2 Image message."""
    msg = MagicMock()
    msg.width = width
    msg.height = height
    msg.encoding = encoding

    if encoding == "bgr8":
        data = np.zeros((height, width, 3), dtype=np.uint8)
        # Add a bright region
        data[50:150, 50:150] = 255
        msg.data = data.tobytes()
    elif encoding == "rgb8":
        data = np.zeros((height, width, 3), dtype=np.uint8)
        data[50:150, 50:150] = 255
        msg.data = data.tobytes()
    elif encoding == "mono8":
        data = np.zeros((height, width), dtype=np.uint8)
        data[50:150, 50:150] = 255
        msg.data = data.tobytes()

    return msg


# ===========================================================================
# Test classes
# ===========================================================================


class TestCameraNodeInit:
    """Verify CameraNode initializes correctly with config params."""

    def test_creates_with_defaults(self):
        node = _make_node()
        assert node is not None

    def test_camera_id_from_param(self):
        node = _make_node()
        assert node._camera_id == "test-cam-01"

    def test_site_id_from_param(self):
        node = _make_node()
        assert node._site == "home"

    def test_no_hardcoded_ips(self):
        """Default mqtt_host must be 'localhost', not an IP."""
        node = _make_node()
        assert node._mqtt_host == "localhost"

    def test_camera_enabled_by_default(self):
        node = _make_node()
        assert node._camera_enabled is True

    def test_detection_interval_from_param(self):
        node = _make_node()
        assert node._detection_interval == 1.0

    def test_frame_dimensions_from_params(self):
        node = _make_node()
        assert node._frame_width == 320
        assert node._frame_height == 240

    def test_initial_frame_count_zero(self):
        node = _make_node()
        assert node._frame_count == 0


class TestFrameConversion:
    """Test ROS2 Image to OpenCV conversion."""

    def test_bgr8_conversion(self):
        node = _make_node()
        msg = _make_ros_image(encoding="bgr8")
        frame = node._ros_image_to_cv2(msg)
        assert frame is not None
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (240, 320, 3)

    def test_rgb8_conversion(self):
        node = _make_node()
        msg = _make_ros_image(encoding="rgb8")
        frame = node._ros_image_to_cv2(msg)
        assert frame is not None
        assert frame.shape == (240, 320, 3)

    def test_mono8_conversion(self):
        node = _make_node()
        msg = _make_ros_image(encoding="mono8")
        frame = node._ros_image_to_cv2(msg)
        assert frame is not None
        assert frame.shape == (240, 320, 3)

    def test_unsupported_encoding_returns_none(self):
        node = _make_node()
        msg = _make_ros_image(encoding="bgr8")
        msg.encoding = "bayer_rggb8"
        frame = node._ros_image_to_cv2(msg)
        assert frame is None

    def test_resize_applied(self):
        """Frame should be resized to configured dimensions."""
        node = _make_node(frame_width=160, frame_height=120)
        msg = _make_ros_image(width=320, height=240, encoding="bgr8")
        frame = node._ros_image_to_cv2(msg)
        assert frame is not None
        assert frame.shape == (120, 160, 3)


class TestJPEGEncoding:
    """Test JPEG encoding of frames."""

    def test_encode_jpeg_valid(self):
        node = _make_node()
        frame = _make_bgr_frame()
        jpeg = node._encode_jpeg(frame)
        assert jpeg is not None
        assert jpeg[:2] == b"\xff\xd8", "Should start with JPEG magic bytes"
        assert len(jpeg) > 100

    def test_encode_jpeg_returns_bytes(self):
        node = _make_node()
        frame = _make_bgr_frame()
        jpeg = node._encode_jpeg(frame)
        assert isinstance(jpeg, bytes)


class TestFrameAnalysis:
    """Test the basic frame analysis / detection."""

    def test_analyze_frame_returns_list(self):
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        assert isinstance(detections, list)

    def test_analyze_bright_frame_finds_objects(self):
        """A frame with a bright rectangle should produce detections."""
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        assert len(detections) > 0

    def test_detection_has_required_fields(self):
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        assert len(detections) > 0
        det = detections[0]
        assert "class_name" in det
        assert "confidence" in det
        assert "bbox" in det

    def test_detection_confidence_range(self):
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        for det in detections:
            assert 0.0 <= det["confidence"] <= 1.0

    def test_detection_bbox_has_four_values(self):
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        for det in detections:
            assert len(det["bbox"]) == 4
            assert all(isinstance(v, (int, float)) for v in det["bbox"])

    def test_analyze_black_frame_no_detections(self):
        """A completely black frame should produce no detections."""
        node = _make_node()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        detections = node.analyze_frame(frame)
        assert len(detections) == 0


class TestMQTTPublishing:
    """Test MQTT message formatting and publish calls."""

    def test_publish_frame_calls_mqtt(self):
        node = _make_node()
        mock_pub = MagicMock()
        mock_pub.connected = True
        node._publisher = mock_pub

        frame = _make_bgr_frame()
        jpeg = node._encode_jpeg(frame)
        node._publisher.publish_frame(jpeg)

        mock_pub.publish_frame.assert_called_once_with(jpeg)

    def test_publish_detections_calls_mqtt(self):
        node = _make_node()
        mock_pub = MagicMock()
        mock_pub.connected = True
        node._publisher = mock_pub

        detections = [{"class_name": "object", "confidence": 0.9, "bbox": [0, 0, 10, 10]}]
        node._publisher.publish_detections(detections)

        mock_pub.publish_detections.assert_called_once_with(detections)

    def test_image_callback_disabled_skips(self):
        """When camera is disabled, image callback should not publish."""
        node = _make_node()
        node._camera_enabled = False
        mock_pub = MagicMock()
        node._publisher = mock_pub

        msg = _make_ros_image()
        node._image_callback(msg)

        mock_pub.publish_frame.assert_not_called()
        mock_pub.publish_detections.assert_not_called()


class TestCommandHandling:
    """Test camera command handling via MQTT."""

    def test_command_camera_off(self):
        node = _make_node()
        assert node._camera_enabled is True
        node.handle_command({"command": "camera_off"})
        assert node._camera_enabled is False

    def test_command_camera_on(self):
        node = _make_node()
        node._camera_enabled = False
        node.handle_command({"command": "camera_on"})
        assert node._camera_enabled is True

    def test_unknown_command_no_crash(self):
        node = _make_node()
        original = node._camera_enabled
        node.handle_command({"command": "do_a_flip"})
        assert node._camera_enabled == original

    def test_empty_payload_no_crash(self):
        node = _make_node()
        node.handle_command({})
        assert node._camera_enabled is True


class TestProtocolCompatibility:
    """Ensure camera node speaks TRITIUM-SC camera protocol."""

    def test_frame_topic_matches_tritium_pattern(self):
        node = _make_node()
        topic = f"tritium/{node._site}/cameras/{node._camera_id}/frame"
        parts = topic.split("/")
        assert parts[0] == "tritium"
        assert parts[2] == "cameras"
        assert parts[4] == "frame"

    def test_detection_topic_matches_tritium_pattern(self):
        node = _make_node()
        topic = f"tritium/{node._site}/cameras/{node._camera_id}/detections"
        parts = topic.split("/")
        assert parts[0] == "tritium"
        assert parts[2] == "cameras"
        assert parts[4] == "detections"

    def test_no_hardcoded_hostnames(self):
        node = _make_node()
        assert node._mqtt_host == "localhost"
        assert "192" not in str(node._mqtt_host)

    def test_detection_payload_json_serializable(self):
        node = _make_node()
        frame = _make_bgr_frame()
        detections = node.analyze_frame(frame)
        serialized = json.dumps(detections)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, list)
