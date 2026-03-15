# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy personality configuration API."""

import pytest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.amy_personality import router


@pytest.fixture
def mock_amy():
    """Create a mock Amy commander."""
    amy = MagicMock()
    amy._personality = None
    amy._aggression = 0.5
    amy._curiosity = 0.5
    amy._verbosity = 0.5
    amy._caution = 0.5
    amy._initiative = 0.5
    amy.event_bus = MagicMock()
    return amy


@pytest.fixture
def app_with_amy(mock_amy):
    app = FastAPI()
    app.include_router(router)
    app.state.amy = mock_amy
    return app


@pytest.fixture
def client(app_with_amy):
    return TestClient(app_with_amy)


class TestGetPersonality:
    """Tests for GET /api/amy/personality."""

    def test_get_returns_defaults(self, client):
        resp = client.get("/api/amy/personality")
        assert resp.status_code == 200
        data = resp.json()
        assert "personality" in data
        assert "presets" in data
        assert len(data["presets"]) >= 5

    def test_get_no_amy(self):
        app = FastAPI()
        app.include_router(router)
        app.state.amy = None
        client = TestClient(app)

        resp = client.get("/api/amy/personality")
        assert resp.status_code == 503


class TestUpdatePersonality:
    """Tests for PUT /api/amy/personality."""

    def test_update_personality(self, client):
        resp = client.put("/api/amy/personality", json={
            "aggression": 0.8,
            "curiosity": 0.3,
            "verbosity": 0.6,
            "caution": 0.4,
            "initiative": 0.7,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "personality" in data

    def test_update_publishes_event(self, client, mock_amy):
        client.put("/api/amy/personality", json={
            "aggression": 0.9,
            "curiosity": 0.1,
            "verbosity": 0.5,
            "caution": 0.5,
            "initiative": 0.5,
        })
        mock_amy.event_bus.publish.assert_called()

    def test_update_validates_range(self, client):
        # Values should be clamped by Pydantic
        resp = client.put("/api/amy/personality", json={
            "aggression": 1.5,  # over max
        })
        assert resp.status_code == 422  # Pydantic validation error

    def test_update_no_amy(self):
        app = FastAPI()
        app.include_router(router)
        app.state.amy = None
        client = TestClient(app)

        resp = client.put("/api/amy/personality", json={"aggression": 0.5})
        assert resp.status_code == 503


class TestPresets:
    """Tests for POST /api/amy/personality/preset."""

    def test_apply_patrol(self, client):
        resp = client.post("/api/amy/personality/preset", json={"preset": "patrol"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["preset"] == "patrol"
        assert "personality" in data

    def test_apply_battle(self, client):
        resp = client.post("/api/amy/personality/preset", json={"preset": "battle"})
        assert resp.status_code == 200

    def test_apply_invalid_preset(self, client):
        resp = client.post("/api/amy/personality/preset", json={"preset": "nonexistent"})
        assert resp.status_code == 400

    def test_apply_no_amy(self):
        app = FastAPI()
        app.include_router(router)
        app.state.amy = None
        client = TestClient(app)

        resp = client.post("/api/amy/personality/preset", json={"preset": "patrol"})
        assert resp.status_code == 503
