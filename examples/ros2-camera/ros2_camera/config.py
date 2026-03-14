# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Configuration for ROS2 camera node.

All settings are overridable via environment variables.
NO hardcoded IPs or hostnames.
"""

from __future__ import annotations

import os


# MQTT broker
MQTT_HOST: str = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT: int = int(os.environ.get("MQTT_PORT", "1883"))

# Identity
CAMERA_ID: str = os.environ.get("CAMERA_ID", "ros2-cam-01")
SITE_ID: str = os.environ.get("MQTT_SITE_ID", "home")

# Detection
DETECTION_INTERVAL: float = float(os.environ.get("DETECTION_INTERVAL", "1.0"))

# Frame settings
FRAME_WIDTH: int = int(os.environ.get("FRAME_WIDTH", "640"))
FRAME_HEIGHT: int = int(os.environ.get("FRAME_HEIGHT", "480"))
JPEG_QUALITY: int = int(os.environ.get("JPEG_QUALITY", "80"))
