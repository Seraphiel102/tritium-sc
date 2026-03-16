# TRITIUM-SC ROS2 Camera Node

A ROS2 camera node that subscribes to `/camera/image_raw`, runs basic frame
analysis, and publishes detections to TRITIUM-SC via MQTT. Deploy on any
ROS2-capable device with a camera to feed video and detections into Amy's
perception system.

## Prerequisites

- **ROS2 Humble** (or later)
- **Python 3.10+**
- **paho-mqtt** (`pip install paho-mqtt>=1.6.0,<2.0.0`)
- **opencv-python** (`pip install opencv-python>=4.0.0`)
- **MQTT broker** (Mosquitto) reachable from both this node and TRITIUM-SC

## Build

```bash
# From your ROS2 workspace src/ directory
cd ~/ros2_ws/src
ln -s /path/to/tritium-sc/examples/ros2-camera ros2_camera

# Build
cd ~/ros2_ws
colcon build --packages-select ros2_camera
source install/setup.bash
```

## Run

```bash
# Default configuration
ros2 launch ros2_camera camera.launch.py

# Custom MQTT broker
ros2 launch ros2_camera camera.launch.py mqtt_host:=my-server

# Custom camera ID and site
ros2 launch ros2_camera camera.launch.py camera_id:=front-cam site_id:=backyard

# Via environment variables
export MQTT_HOST=my-server
export CAMERA_ID=roof-cam
ros2 launch ros2_camera camera.launch.py
```

### Parameter File

Override defaults in `config/camera_params.yaml`:

```yaml
tritium_camera:
  ros__parameters:
    mqtt_host: "localhost"
    mqtt_port: 1883
    site_id: "home"
    camera_id: "ros2-cam-01"
    camera_enabled: true
    detection_interval: 1.0
    frame_width: 640
    frame_height: 480
    jpeg_quality: 80
```

## Architecture

```
    ROS2 Camera Driver          TRITIUM-SC Camera Node          MQTT Broker
    (v4l2_camera, etc.)         (this package)
         |                           |                              |
    /camera/image_raw ------>  CameraNode                           |
                               |  _ros_image_to_cv2()              |
                               |  analyze_frame()                  |
                               |  _encode_jpeg()                   |
                               |       |                            |
                               +-- MQTTPublisher -------> cameras/{id}/frame
                                       |               > cameras/{id}/detections
                                       |               < cameras/{id}/command
                                                            |
                                                       TRITIUM-SC Server
                                                       (camera_feeds plugin)
```

## MQTT Topic Reference

All topics follow the TRITIUM-SC camera protocol. The `{site}` and
`{camera_id}` segments are configurable.

### Published by Camera

| Topic | QoS | Content |
|-------|-----|---------|
| `tritium/{site}/cameras/{id}/frame` | 0 | JPEG bytes |
| `tritium/{site}/cameras/{id}/detections` | 0 | JSON detection payload |

### Subscribed by Camera

| Topic | QoS | Content |
|-------|-----|---------|
| `tritium/{site}/cameras/{id}/command` | 1 | `camera_on`, `camera_off` |

### Detection Payload

```json
{
  "camera_id": "ros2-cam-01",
  "timestamp": "2026-03-13T12:00:00+00:00",
  "detections": [
    {
      "class_name": "object",
      "confidence": 0.85,
      "bbox": [50, 50, 150, 150]
    }
  ]
}
```

## Frame Analysis

The default `analyze_frame()` uses adaptive thresholding to detect bright
regions in the frame. This is a simple demonstration detector. For production
use, replace it with YOLO or another trained model.

Supported image encodings: `bgr8`, `rgb8`, `mono8`.

## Testing

Tests work WITHOUT ROS2 installed (all ROS2 imports are mocked):

```bash
# From tritium-sc root
.venv/bin/python3 -m pytest examples/ros2-camera/tests/ -v

# Or from the ros2-camera directory
cd examples/ros2-camera
python -m pytest tests/ -v
```

## Differences from ros2-robot Camera

| Feature | `ros2-robot` camera | `ros2-camera` (this) |
|---------|---------------------|----------------------|
| Input | Synthetic renderer | Real ROS2 `/camera/image_raw` |
| Detection | Synthetic targets | OpenCV adaptive threshold |
| Dependencies | video_gen renderers | Only OpenCV + numpy |
| Standalone | Part of robot package | Independent package |
| MQTT protocol | Identical | Identical |

Both publish to the same MQTT topics. TRITIUM-SC treats them identically.
