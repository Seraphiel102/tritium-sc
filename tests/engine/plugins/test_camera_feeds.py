# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Camera Feeds plugin."""

import numpy as np
import pytest

from engine.plugins.base import PluginInterface


@pytest.mark.unit
class TestCameraFeedsPlugin:
    """Verify CameraFeedsPlugin interface and source management."""

    def test_implements_plugin_interface(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_identity(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        assert plugin.plugin_id == "tritium.camera-feeds"
        assert plugin.name == "Camera Feeds"
        assert plugin.version == "1.0.0"

    def test_capabilities(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        caps = plugin.capabilities
        assert "data_source" in caps
        assert "routes" in caps
        assert "ui" in caps
        assert "bridge" in caps

    def test_register_and_list_sources(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(
            source_id="test-1",
            source_type="synthetic",
            extra={"scene_type": "bird_eye"},
        )
        source = plugin.register_source(config)
        assert source.source_id == "test-1"
        assert source.source_type == "synthetic"

        sources = plugin.list_sources()
        assert len(sources) == 1
        assert sources[0]["source_id"] == "test-1"

    def test_register_duplicate_raises(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(source_id="dup", source_type="synthetic")
        plugin.register_source(config)
        with pytest.raises(ValueError, match="already exists"):
            plugin.register_source(config)

    def test_register_unknown_type_raises(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(source_id="bad", source_type="hologram")
        with pytest.raises(ValueError, match="Unknown source type"):
            plugin.register_source(config)

    def test_remove_source(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(source_id="rm-1", source_type="synthetic")
        plugin.register_source(config)
        assert len(plugin.list_sources()) == 1
        plugin.remove_source("rm-1")
        assert len(plugin.list_sources()) == 0

    def test_remove_missing_raises(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        with pytest.raises(KeyError, match="not found"):
            plugin.remove_source("ghost")

    def test_get_source(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(source_id="get-1", source_type="mqtt")
        plugin.register_source(config)
        source = plugin.get_source("get-1")
        assert source is not None
        assert source.source_type == "mqtt"
        assert plugin.get_source("nope") is None

    def test_get_frame_missing_raises(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        with pytest.raises(KeyError, match="not found"):
            plugin.get_frame("missing")

    def test_start_stop(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        plugin = CameraFeedsPlugin()
        assert not plugin.healthy
        plugin.start()
        assert plugin.healthy
        plugin.stop()
        assert not plugin.healthy

    def test_auto_start_on_register_when_running(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        plugin._running = True
        config = CameraSourceConfig(source_id="auto", source_type="mqtt")
        source = plugin.register_source(config)
        assert source.is_running


@pytest.mark.unit
class TestCameraSourceBase:
    """Test CameraSourceBase and concrete implementations."""

    def test_source_types_registry(self):
        from plugins.camera_feeds.sources import SOURCE_TYPES
        assert "synthetic" in SOURCE_TYPES
        assert "mqtt" in SOURCE_TYPES
        assert "rtsp" in SOURCE_TYPES
        assert "mjpeg" in SOURCE_TYPES
        assert "usb" in SOURCE_TYPES

    def test_mqtt_source_on_frame(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(
            source_id="mqtt-test", source_type="mqtt",
            uri="tritium/test/camera",
        )
        source = MQTTSource(config)
        source.start()
        assert source.is_running
        assert source.get_frame() is None  # no frames yet

        # Simulate a JPEG frame arriving
        fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        fake_frame[50, 50] = [255, 0, 0]
        import cv2
        _, jpeg = cv2.imencode(".jpg", fake_frame)
        source.on_frame(jpeg.tobytes())

        frame = source.get_frame()
        assert frame is not None
        assert frame.shape[0] == 100
        assert frame.shape[1] == 100

        source.stop()
        assert not source.is_running

    def test_mqtt_source_ignores_frames_when_stopped(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(source_id="mqtt-stop", source_type="mqtt")
        source = MQTTSource(config)
        # Don't start — frames should be ignored
        fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
        import cv2
        _, jpeg = cv2.imencode(".jpg", fake_frame)
        source.on_frame(jpeg.tobytes())
        assert source.get_frame() is None

    def test_source_to_dict(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(
            source_id="dict-test", source_type="mqtt",
            name="Test Camera", width=320, height=240, fps=5,
        )
        source = MQTTSource(config)
        d = source.to_dict()
        assert d["source_id"] == "dict-test"
        assert d["source_type"] == "mqtt"
        assert d["name"] == "Test Camera"
        assert d["width"] == 320
        assert d["height"] == 240
        assert d["fps"] == 5
        assert d["running"] is False
        assert d["frame_count"] == 0
        assert "created_at" in d

    def test_get_snapshot_returns_jpeg(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(source_id="snap", source_type="mqtt")
        source = MQTTSource(config)
        source.start()

        # No frame yet
        assert source.get_snapshot() is None

        # Feed a frame
        fake = np.zeros((50, 50, 3), dtype=np.uint8)
        import cv2
        _, jpeg = cv2.imencode(".jpg", fake)
        source.on_frame(jpeg.tobytes())

        snap = source.get_snapshot()
        assert snap is not None
        assert snap[:2] == b"\xff\xd8"  # JPEG magic bytes
        source.stop()

    def test_synthetic_source_no_renderer_returns_none(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, SyntheticSource
        config = CameraSourceConfig(
            source_id="syn-nr", source_type="synthetic",
        )
        source = SyntheticSource(config)
        # Don't start (renderer won't load) — get_frame returns None
        assert source.get_frame() is None


@pytest.mark.unit
class TestCameraSourceLifecycle:
    """Test source start/stop lifecycle and frame generation."""

    def test_source_start_stop_idempotent(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(source_id="idem", source_type="mqtt")
        source = MQTTSource(config)
        source.start()
        source.start()  # double start should be safe
        assert source.is_running
        source.stop()
        source.stop()  # double stop should be safe
        assert not source.is_running

    def test_synthetic_source_start_stop(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, SyntheticSource
        config = CameraSourceConfig(
            source_id="syn-lc", source_type="synthetic",
            extra={"scene_type": "bird_eye"},
        )
        source = SyntheticSource(config)
        assert not source.is_running
        source.start()
        assert source.is_running
        source.stop()
        assert not source.is_running

    def test_synthetic_source_get_frame_returns_ndarray(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, SyntheticSource
        config = CameraSourceConfig(
            source_id="syn-frame", source_type="synthetic",
            width=320, height=240,
            extra={"scene_type": "bird_eye"},
        )
        source = SyntheticSource(config)
        source.start()
        frame = source.get_frame()
        # Renderer may or may not be available in test env
        if frame is not None:
            assert isinstance(frame, np.ndarray)
            assert frame.shape[1] == 320
            assert frame.shape[0] == 240

    def test_synthetic_source_increments_frame_count(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, SyntheticSource
        config = CameraSourceConfig(
            source_id="syn-cnt", source_type="synthetic",
            extra={"scene_type": "bird_eye"},
        )
        source = SyntheticSource(config)
        source.start()
        frame1 = source.get_frame()
        if frame1 is not None:
            assert source._frame_count == 1
            source.get_frame()
            assert source._frame_count == 2

    def test_mqtt_source_frame_count_increments(self):
        import cv2
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(source_id="cnt", source_type="mqtt")
        source = MQTTSource(config)
        source.start()
        fake = np.zeros((10, 10, 3), dtype=np.uint8)
        _, jpeg = cv2.imencode(".jpg", fake)
        source.on_frame(jpeg.tobytes())
        source.on_frame(jpeg.tobytes())
        assert source._frame_count == 2

    def test_mqtt_source_corrupt_jpeg_handled(self):
        from plugins.camera_feeds.sources import CameraSourceConfig, MQTTSource
        config = CameraSourceConfig(source_id="corrupt", source_type="mqtt")
        source = MQTTSource(config)
        source.start()
        # Feed garbage bytes — should not crash
        source.on_frame(b"not-a-jpeg")
        assert source.get_frame() is None

    def test_plugin_start_starts_registered_sources(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        config = CameraSourceConfig(source_id="pre", source_type="mqtt")
        source = plugin.register_source(config)
        assert not source.is_running
        plugin.start()
        assert source.is_running
        plugin.stop()
        assert not source.is_running

    def test_plugin_stop_stops_all_sources(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        for i in range(3):
            plugin.register_source(
                CameraSourceConfig(source_id=f"s{i}", source_type="mqtt")
            )
        plugin.start()
        for s in plugin._sources.values():
            assert s.is_running
        plugin.stop()
        for s in plugin._sources.values():
            assert not s.is_running

    def test_remove_source_stops_it(self):
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.sources import CameraSourceConfig
        plugin = CameraFeedsPlugin()
        plugin.start()
        config = CameraSourceConfig(source_id="rm-stop", source_type="mqtt")
        source = plugin.register_source(config)
        assert source.is_running
        plugin.remove_source("rm-stop")
        assert not source.is_running


@pytest.mark.unit
class TestCameraFeedsRoutes:
    """Test route response patterns using TestClient."""

    def test_list_sources_empty(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        resp = client.get("/api/camera-feeds/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []
        assert data["count"] == 0

    def test_add_source_via_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        resp = client.post("/api/camera-feeds/sources", json={
            "source_id": "test-route",
            "source_type": "mqtt",
            "name": "Route Camera",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["source_id"] == "test-route"
        assert data["name"] == "Route Camera"

    def test_add_duplicate_source_returns_409(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        body = {"source_id": "dup-route", "source_type": "mqtt"}
        client.post("/api/camera-feeds/sources", json=body)
        resp = client.post("/api/camera-feeds/sources", json=body)
        assert resp.status_code == 409

    def test_get_source_not_found_returns_404(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        resp = client.get("/api/camera-feeds/sources/nonexistent")
        assert resp.status_code == 404

    def test_delete_source_via_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        client.post("/api/camera-feeds/sources", json={
            "source_id": "del-me", "source_type": "mqtt",
        })
        resp = client.delete("/api/camera-feeds/sources/del-me")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    def test_delete_missing_returns_404(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        resp = client.delete("/api/camera-feeds/sources/ghost")
        assert resp.status_code == 404

    def test_snapshot_no_frame_returns_503(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        client.post("/api/camera-feeds/sources", json={
            "source_id": "no-frame", "source_type": "mqtt",
        })
        resp = client.get("/api/camera-feeds/sources/no-frame/snapshot")
        assert resp.status_code == 503

    def test_list_source_types(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from plugins.camera_feeds.plugin import CameraFeedsPlugin
        from plugins.camera_feeds.routes import create_router

        app = FastAPI()
        plugin = CameraFeedsPlugin()
        app.include_router(create_router(plugin))
        client = TestClient(app)

        resp = client.get("/api/camera-feeds/sources/types")
        assert resp.status_code == 200
        types = resp.json()["types"]
        assert "synthetic" in types
        assert "mqtt" in types


@pytest.mark.unit
class TestCameraFeedsLoader:
    """Test the loader shim."""

    def test_loader_imports(self):
        from plugins.camera_feeds_loader import CameraFeedsPlugin
        assert CameraFeedsPlugin is not None
        plugin = CameraFeedsPlugin()
        assert plugin.plugin_id == "tritium.camera-feeds"
