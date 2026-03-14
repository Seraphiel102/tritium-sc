# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 camera node that subscribes to /camera/image_raw and publishes
detections to TRITIUM-SC via MQTT.

Subscribes to ROS2 topics:
    /camera/image_raw  (sensor_msgs/Image) -- raw camera frames

MQTT topics published:
    tritium/{site}/cameras/{id}/frame       -- JPEG bytes (QoS 0)
    tritium/{site}/cameras/{id}/detections  -- JSON detection payload (QoS 0)

MQTT topics subscribed:
    tritium/{site}/cameras/{id}/command     -- camera on/off commands

All configuration via ROS2 parameters -- NO hardcoded IPs or hostnames.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image

from .config import (
    CAMERA_ID,
    DETECTION_INTERVAL,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    JPEG_QUALITY,
    MQTT_HOST,
    MQTT_PORT,
    SITE_ID,
)
from .mqtt_publisher import MQTTPublisher


class CameraNode(Node):
    """ROS2 node that receives camera frames, analyzes them, and publishes
    detections to MQTT."""

    def __init__(self) -> None:
        super().__init__("tritium_camera")

        # Declare ROS2 parameters with env var defaults
        self.declare_parameter("mqtt_host", MQTT_HOST)
        self.declare_parameter("mqtt_port", MQTT_PORT)
        self.declare_parameter("site_id", SITE_ID)
        self.declare_parameter("camera_id", CAMERA_ID)
        self.declare_parameter("camera_enabled", True)
        self.declare_parameter("detection_interval", DETECTION_INTERVAL)
        self.declare_parameter("frame_width", FRAME_WIDTH)
        self.declare_parameter("frame_height", FRAME_HEIGHT)
        self.declare_parameter("jpeg_quality", JPEG_QUALITY)

        # Read parameter values
        self._mqtt_host: str = self.get_parameter("mqtt_host").value
        self._mqtt_port: int = self.get_parameter("mqtt_port").value
        self._site: str = self.get_parameter("site_id").value
        self._camera_id: str = self.get_parameter("camera_id").value
        self._camera_enabled: bool = self.get_parameter("camera_enabled").value
        self._detection_interval: float = self.get_parameter("detection_interval").value
        self._frame_width: int = self.get_parameter("frame_width").value
        self._frame_height: int = self.get_parameter("frame_height").value
        self._jpeg_quality: int = self.get_parameter("jpeg_quality").value

        # State
        self._frame_count: int = 0
        self._last_detection_time: float = 0.0
        self._last_frame: np.ndarray | None = None

        # MQTT publisher
        self._publisher = MQTTPublisher(
            host=self._mqtt_host,
            port=self._mqtt_port,
            site_id=self._site,
            camera_id=self._camera_id,
            on_command=self.handle_command,
        )

        try:
            self._publisher.connect()
            self.get_logger().info(
                f"Camera MQTT connecting to {self._mqtt_host}:{self._mqtt_port}"
            )
        except Exception as e:
            self.get_logger().error(f"Camera MQTT connection failed: {e}")

        # Subscribe to ROS2 camera topic
        self._image_sub = self.create_subscription(
            Image, "/camera/image_raw", self._image_callback, 10,
        )

        self.get_logger().info(
            f"Camera node started: id={self._camera_id}, "
            f"detection_interval={self._detection_interval}s"
        )

    def destroy_node(self) -> None:
        """Clean shutdown."""
        try:
            self._publisher.disconnect()
        except Exception:
            pass
        super().destroy_node()

    # --- ROS2 image callback ---

    def _image_callback(self, msg: Image) -> None:
        """Process incoming camera frame."""
        if not self._camera_enabled:
            return

        frame = self._ros_image_to_cv2(msg)
        if frame is None:
            return

        self._last_frame = frame
        self._frame_count += 1

        # Publish JPEG frame
        jpeg = self._encode_jpeg(frame)
        if jpeg is not None:
            self._publisher.publish_frame(jpeg)

        # Run detection at configured interval
        now = time.time()
        if now - self._last_detection_time >= self._detection_interval:
            self._last_detection_time = now
            detections = self.analyze_frame(frame)
            if detections:
                self._publisher.publish_detections(detections)

    # --- Frame conversion ---

    def _ros_image_to_cv2(self, msg: Image) -> np.ndarray | None:
        """Convert a ROS2 Image message to an OpenCV BGR numpy array.

        Supports bgr8, rgb8, and mono8 encodings.
        """
        try:
            h, w = msg.height, msg.width
            encoding = msg.encoding

            if encoding == "bgr8":
                frame = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w, 3)
            elif encoding == "rgb8":
                rgb = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w, 3)
                frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            elif encoding == "mono8":
                gray = np.frombuffer(msg.data, dtype=np.uint8).reshape(h, w)
                frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            else:
                self.get_logger().debug(f"Unsupported encoding: {encoding}")
                return None

            # Resize if needed
            if (w, h) != (self._frame_width, self._frame_height):
                frame = cv2.resize(frame, (self._frame_width, self._frame_height))

            return frame
        except Exception as e:
            self.get_logger().debug(f"Frame conversion error: {e}")
            return None

    def _encode_jpeg(self, frame: np.ndarray) -> bytes | None:
        """Encode a BGR frame as JPEG bytes."""
        ok, buf = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality],
        )
        if not ok:
            return None
        return buf.tobytes()

    # --- Frame analysis ---

    def analyze_frame(self, frame: np.ndarray) -> list[dict]:
        """Run basic frame analysis to detect regions of interest.

        This is a simple motion/contrast detector for demonstration.
        Replace with YOLO or other model for production use.

        Returns:
            List of detection dicts with class_name, confidence, bbox.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Use adaptive threshold to find bright regions
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, -20,
        )

        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
        )

        detections = []
        min_area = (self._frame_width * self._frame_height) * 0.005

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            confidence = min(1.0, area / (self._frame_width * self._frame_height * 0.1))

            detections.append({
                "class_name": "object",
                "confidence": round(confidence, 2),
                "bbox": [x, y, x + w, y + h],
            })

        return detections

    # --- Command handling ---

    def handle_command(self, payload: dict) -> None:
        """Process an incoming MQTT command.

        Supported commands:
            camera_on  -- enable camera publishing
            camera_off -- disable camera publishing
        """
        command = payload.get("command", "")
        if command == "camera_on":
            self._camera_enabled = True
            self.get_logger().info("Camera enabled")
        elif command == "camera_off":
            self._camera_enabled = False
            self.get_logger().info("Camera disabled")
        else:
            self.get_logger().debug(f"Unknown camera command: {command}")


def main(args=None):
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
