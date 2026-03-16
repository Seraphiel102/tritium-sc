# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for target timeline / biography API."""

import pytest
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.target_timeline import router


@pytest.fixture
def mock_tracker():
    """Create a mock target tracker."""
    tracker = MagicMock()

    # Mock target
    target = MagicMock()
    target.target_id = "ble_AA:BB:CC:DD:EE:FF"
    target.name = "Phone-1"
    target.alliance = "unknown"
    target.asset_type = "phone"
    target.source = "ble"
    target.status = "active"
    target.position = (10.0, 20.0)
    target.heading = 45.0
    target.speed = 1.5
    target.battery = 0.8
    target.last_seen = time.monotonic() - 5.0
    target.effective_confidence = 0.75
    target.threat_score = 0.1
    target.confirming_sources = {"ble", "wifi"}
    target.velocity_suspicious = False
    target.to_dict.return_value = {
        "target_id": "ble_AA:BB:CC:DD:EE:FF",
        "name": "Phone-1",
        "alliance": "unknown",
        "asset_type": "phone",
        "position": {"x": 10.0, "y": 20.0},
        "lat": 30.0,
        "lng": -97.0,
        "source": "ble",
    }

    # Mock history
    history = MagicMock()
    trail_data = [
        (10.0, 20.0, time.monotonic() - 60.0),
        (11.0, 21.0, time.monotonic() - 30.0),
        (12.0, 22.0, time.monotonic() - 5.0),
    ]
    history.get_trail.return_value = trail_data
    history.estimate_speed.return_value = 1.5
    history.estimate_heading.return_value = 45.0

    tracker.history = history
    tracker.get_target.return_value = target
    tracker.get_all.return_value = [target]

    return tracker


@pytest.fixture
def app_with_tracker(mock_tracker):
    """Create a FastAPI app with mock tracker."""
    app = FastAPI()
    app.include_router(router)

    amy = MagicMock()
    amy.target_tracker = mock_tracker
    amy.dossier_store = None
    app.state.amy = amy

    return app


@pytest.fixture
def client(app_with_tracker):
    return TestClient(app_with_tracker)


class TestTargetTimeline:
    """Tests for GET /api/targets/{target_id}/timeline."""

    def test_timeline_returns_data(self, client):
        resp = client.get("/api/targets/ble_AA:BB:CC:DD:EE:FF/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "ble_AA:BB:CC:DD:EE:FF"
        assert data["name"] == "Phone-1"
        assert data["source"] == "ble"
        assert "first_seen" in data
        assert "last_seen" in data
        assert "total_tracked_seconds" in data
        assert "sighting_count" in data
        assert "source_breakdown" in data
        assert "trail" in data
        assert len(data["trail"]) == 3

    def test_timeline_not_found(self, client, mock_tracker):
        mock_tracker.get_target.return_value = None
        resp = client.get("/api/targets/nonexistent/timeline")
        assert resp.status_code == 404

    def test_timeline_source_breakdown(self, client):
        resp = client.get("/api/targets/ble_AA:BB:CC:DD:EE:FF/timeline")
        data = resp.json()
        breakdown = data["source_breakdown"]
        assert "ble" in breakdown


class TestTargetBiography:
    """Tests for GET /api/targets/{target_id}/biography."""

    def test_biography_returns_narrative(self, client):
        resp = client.get("/api/targets/ble_AA:BB:CC:DD:EE:FF/biography")
        assert resp.status_code == 200
        data = resp.json()
        assert "biography" in data
        assert "Phone-1" in data["biography"]
        assert "total_tracked_seconds" in data
        assert "sighting_count" in data

    def test_biography_not_found(self, client, mock_tracker):
        mock_tracker.get_target.return_value = None
        resp = client.get("/api/targets/nonexistent/biography")
        assert resp.status_code == 404

    def test_biography_mentions_sources(self, client):
        resp = client.get("/api/targets/ble_AA:BB:CC:DD:EE:FF/biography")
        data = resp.json()
        # Should mention multi-source confirmation
        assert "sources" in data["biography"].lower() or "confirmed" in data["biography"].lower()


class TestNoTracker:
    """Tests when tracker is not available."""

    def test_timeline_no_tracker(self):
        app = FastAPI()
        app.include_router(router)
        app.state.amy = None
        client = TestClient(app)

        resp = client.get("/api/targets/test/timeline")
        assert resp.status_code == 503

    def test_biography_no_tracker(self):
        app = FastAPI()
        app.include_router(router)
        app.state.amy = None
        client = TestClient(app)

        resp = client.get("/api/targets/test/biography")
        assert resp.status_code == 503
