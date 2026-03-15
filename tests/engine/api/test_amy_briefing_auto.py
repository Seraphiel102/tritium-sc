# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy morning briefing auto-trigger and config endpoints."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.amy_briefing import (
    router,
    _morning_briefing_enabled,
    _morning_briefing_hour,
    start_morning_briefing,
    stop_morning_briefing,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """App with amy briefing router."""
    app = FastAPI()
    app.include_router(router)
    # Need app.state for the briefing context
    app.state.amy = None
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

class TestBriefingConfig:
    def test_get_config(self, client):
        resp = client.get("/api/amy/briefing/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "hour" in data
        assert isinstance(data["hour"], int)

    def test_set_config_hour(self, client):
        resp = client.post(
            "/api/amy/briefing/config",
            json={"hour": 6},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hour"] == 6

    def test_set_config_enabled(self, client):
        resp = client.post(
            "/api/amy/briefing/config",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

        # Re-enable
        resp = client.post(
            "/api/amy/briefing/config",
            json={"enabled": True},
        )
        assert resp.json()["enabled"] is True

    def test_set_config_clamps_hour(self, client):
        resp = client.post(
            "/api/amy/briefing/config",
            json={"hour": 25},
        )
        data = resp.json()
        assert data["hour"] == 23

        resp = client.post(
            "/api/amy/briefing/config",
            json={"hour": -1},
        )
        data = resp.json()
        assert data["hour"] == 0


# ---------------------------------------------------------------------------
# Briefing generation
# ---------------------------------------------------------------------------

class TestBriefingGeneration:
    def test_post_briefing(self, client):
        resp = client.post("/api/amy/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "briefing_id" in data
        assert "text" in data
        assert len(data["text"]) > 0
        assert data["source"] in ("template", "ollama")

    def test_get_briefing_returns_cached(self, client):
        # Generate first
        client.post("/api/amy/briefing")
        # Get should return cached
        resp = client.get("/api/amy/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "briefing_id" in data

    def test_briefing_has_context_summary(self, client):
        resp = client.post("/api/amy/briefing")
        data = resp.json()
        assert "context_summary" in data
        assert "threat_level" in data["context_summary"]


# ---------------------------------------------------------------------------
# Morning briefing lifecycle
# ---------------------------------------------------------------------------

class TestMorningBriefingLifecycle:
    def test_start_stop(self):
        """start and stop should not crash."""
        # Can't easily test the async loop, but can verify the functions exist
        # and don't crash when called outside an event loop
        stop_morning_briefing()  # should be safe even if not started
