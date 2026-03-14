# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Picture of the Day API."""

import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client with minimal app."""
    from fastapi import FastAPI
    from app.routers.picture_of_day import router

    app = FastAPI()
    app.include_router(router)

    # Set up minimal state
    app.state.amy = None
    app.state.simulation_engine = None
    app.state.correlator = None
    app.state.fleet_bridge = None
    app.state.investigation_store = None

    return TestClient(app)


class TestPictureOfDay:
    def test_endpoint_returns_200(self, client):
        resp = client.get("/api/picture-of-day")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/api/picture-of-day")
        data = resp.json()

        assert "report_date" in data
        assert "generated_at" in data
        assert "period_hours" in data
        assert data["period_hours"] == 24
        assert "new_targets" in data
        assert "correlations" in data
        assert "threats" in data
        assert "zone_events" in data
        assert "investigations_opened" in data
        assert "total_sightings" in data
        assert "sightings_by_source" in data
        assert "top_devices" in data
        assert "threat_level" in data
        assert "uptime_percent" in data

    def test_empty_state_defaults(self, client):
        resp = client.get("/api/picture-of-day")
        data = resp.json()

        assert data["new_targets"] == 0
        assert data["correlations"] == 0
        assert data["threats"] == 0
        assert data["threat_level"] == "GREEN"

    def test_with_simulation_targets(self):
        from fastapi import FastAPI
        from app.routers.picture_of_day import router

        app = FastAPI()
        app.include_router(router)

        # Mock simulation engine with targets
        mock_target = MagicMock()
        mock_target.source = "ble"
        mock_target.target_id = "ble_aa:bb:cc:dd:ee:ff"

        mock_engine = MagicMock()
        mock_engine.get_targets.return_value = [mock_target]

        app.state.amy = None
        app.state.simulation_engine = mock_engine
        app.state.correlator = None
        app.state.fleet_bridge = None
        app.state.investigation_store = None

        client = TestClient(app)
        resp = client.get("/api/picture-of-day")
        data = resp.json()

        assert data["new_targets"] == 1
        assert data["sightings_by_source"]["ble"] == 1


class TestNearbyTargets:
    def test_endpoint_not_found_target(self):
        from fastapi import FastAPI
        from app.routers.nearby_targets import router

        app = FastAPI()
        app.include_router(router)

        app.state.amy = None
        app.state.simulation_engine = None

        client = TestClient(app)
        resp = client.get("/api/targets/nonexistent/nearby")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["error"] == "Target not found"

    def test_endpoint_with_mock_tracker(self):
        from fastapi import FastAPI
        from app.routers.nearby_targets import router

        app = FastAPI()
        app.include_router(router)

        # Create mock targets
        primary = MagicMock()
        primary.target_id = "ble_primary"
        primary.position = (100.0, 200.0)
        primary.last_seen = 1000.0

        nearby_target = MagicMock()
        nearby_target.target_id = "ble_nearby"
        nearby_target.position = (110.0, 205.0)
        nearby_target.last_seen = 1000.0
        nearby_target.to_dict.return_value = {
            "target_id": "ble_nearby",
            "name": "Nearby Phone",
            "asset_type": "phone",
            "alliance": "unknown",
            "source": "ble",
        }

        far_target = MagicMock()
        far_target.target_id = "ble_far"
        far_target.position = (9999.0, 9999.0)
        far_target.last_seen = 1000.0

        mock_tracker = MagicMock()
        mock_tracker.get_target.return_value = primary
        mock_tracker.get_all.return_value = [primary, nearby_target, far_target]
        mock_tracker.history = None

        mock_amy = MagicMock()
        mock_amy.target_tracker = mock_tracker
        mock_amy.simulation_engine = None

        app.state.amy = mock_amy
        app.state.simulation_engine = None

        client = TestClient(app)
        resp = client.get("/api/targets/ble_primary/nearby?radius=50")
        data = resp.json()

        assert resp.status_code == 200
        assert data["count"] == 1
        assert data["nearby"][0]["target_id"] == "ble_nearby"


class TestOllamaHealth:
    def test_endpoint_returns_200(self):
        from fastapi import FastAPI
        from app.routers.ollama_health import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        resp = client.get("/api/health/ollama")
        assert resp.status_code == 200
        data = resp.json()
        assert "local" in data
        assert "overall_status" in data
