# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for fleet map API."""

import pytest
import time
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.fleet_map import router


@pytest.fixture
def mock_fleet_plugin():
    """Create a mock fleet dashboard plugin."""
    plugin = MagicMock()
    plugin.get_devices.return_value = [
        {
            "device_id": "node-001",
            "name": "Front Door",
            "lat": 30.2672,
            "lng": -97.7431,
            "battery": 0.85,
            "group": "perimeter",
            "capabilities": {"ble_scanner": True, "wifi_scanner": True},
            "firmware_version": "1.2.0",
            "uptime_seconds": 86400,
            "ble_count": 12,
            "wifi_count": 8,
            "last_heartbeat": time.time() - 30,
        },
        {
            "device_id": "node-002",
            "name": "Backyard",
            "lat": 30.2680,
            "lng": -97.7440,
            "battery": 0.42,
            "group": "perimeter",
            "capabilities": {"ble_scanner": True, "wifi_scanner": False},
            "firmware_version": "1.2.0",
            "uptime_seconds": 3600,
            "ble_count": 5,
            "wifi_count": 0,
            "last_heartbeat": time.time() - 600,  # offline
        },
    ]
    return plugin


@pytest.fixture
def app_with_fleet(mock_fleet_plugin):
    app = FastAPI()
    app.include_router(router)
    app.state.fleet_dashboard_plugin = mock_fleet_plugin
    app.state.edge_tracker_plugin = None
    return app


@pytest.fixture
def client(app_with_fleet):
    return TestClient(app_with_fleet)


class TestFleetMapDevices:
    """Tests for GET /api/fleet/map/devices."""

    def test_returns_devices(self, client):
        resp = client.get("/api/fleet/map/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["devices"]) == 2

    def test_health_status(self, client):
        resp = client.get("/api/fleet/map/devices")
        data = resp.json()
        devices = {d["device_id"]: d for d in data["devices"]}
        assert devices["node-001"]["health"] == "online"
        assert devices["node-002"]["health"] == "offline"

    def test_group_summary(self, client):
        resp = client.get("/api/fleet/map/devices")
        data = resp.json()
        assert "perimeter" in data["groups"]
        assert data["groups"]["perimeter"] == 2

    def test_online_offline_counts(self, client):
        resp = client.get("/api/fleet/map/devices")
        data = resp.json()
        assert data["online"] == 1
        assert data["offline"] == 1

    def test_no_fleet_plugin(self):
        app = FastAPI()
        app.include_router(router)
        app.state.fleet_dashboard_plugin = None
        client = TestClient(app)

        resp = client.get("/api/fleet/map/devices")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestFleetCoverage:
    """Tests for GET /api/fleet/map/coverage."""

    def test_returns_coverage(self, client):
        resp = client.get("/api/fleet/map/coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert all("lat" in c for c in data["coverage"])
        assert all("radius_m" in c for c in data["coverage"])

    def test_no_fleet_plugin(self):
        app = FastAPI()
        app.include_router(router)
        app.state.fleet_dashboard_plugin = None
        client = TestClient(app)

        resp = client.get("/api/fleet/map/coverage")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
