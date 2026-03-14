# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ROS2 Python package setup for TRITIUM-SC camera node."""

import os
from glob import glob
from setuptools import find_packages, setup

package_name = "ros2_camera"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=[
        "setuptools",
        "paho-mqtt>=1.6.0,<2.0.0",
        "opencv-python>=4.0.0",
        "numpy",
    ],
    zip_safe=True,
    maintainer="TRITIUM-SC",
    maintainer_email="dev@tritium-sc.local",
    description="TRITIUM-SC ROS2 camera node: subscribes to /camera/image_raw and publishes detections via MQTT",
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "camera_node = ros2_camera.camera_node:main",
        ],
    },
)
