# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 launch file for TRITIUM-SC camera node."""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "mqtt_host",
            default_value=os.environ.get("MQTT_HOST", "localhost"),
            description="MQTT broker hostname",
        ),
        DeclareLaunchArgument(
            "mqtt_port",
            default_value=os.environ.get("MQTT_PORT", "1883"),
            description="MQTT broker port",
        ),
        DeclareLaunchArgument(
            "site_id",
            default_value=os.environ.get("MQTT_SITE_ID", "home"),
            description="TRITIUM-SC site identifier",
        ),
        DeclareLaunchArgument(
            "camera_id",
            default_value=os.environ.get("CAMERA_ID", "ros2-cam-01"),
            description="Camera identifier",
        ),
        DeclareLaunchArgument(
            "detection_interval",
            default_value="1.0",
            description="Seconds between detection runs",
        ),
        Node(
            package="ros2_camera",
            executable="camera_node",
            name="tritium_camera",
            parameters=[{
                "mqtt_host": LaunchConfiguration("mqtt_host"),
                "mqtt_port": LaunchConfiguration("mqtt_port"),
                "site_id": LaunchConfiguration("site_id"),
                "camera_id": LaunchConfiguration("camera_id"),
                "detection_interval": LaunchConfiguration("detection_interval"),
            }],
            output="screen",
        ),
    ])
