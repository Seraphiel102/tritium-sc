# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for GET /api/events/unified endpoint."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.unified_events import router


@pytest.fixture
def bare_app():
    """Minimal app with no event sources."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def bare_client(bare_app):
    return TestClient(bare_app, raise_server_exceptions=False)


@pytest.fixture
def events_app():
    """App with simulated event sources."""
    app = FastAPI()
    app.include_router(router)

    # Simulate event bus with history
    now = time.time()
    app.state.event_bus = SimpleNamespace(
        history=[
            {"event_type": "target_created", "timestamp": now - 10, "target_id": "ble_aa"},
            {"event_type": "target_updated", "timestamp": now - 5, "target_id": "ble_bb"},
        ],
    )
    app.state.amy = None
    return app


@pytest.fixture
def events_client(events_app):
    return TestClient(events_app, raise_server_exceptions=False)


class TestUnifiedEventsEndpoint:
    """Tests for /api/events/unified."""

    @pytest.mark.unit
    def test_unified_returns_200(self, bare_client):
        resp = bare_client.get("/api/events/unified")
        assert resp.status_code == 200

    @pytest.mark.unit
    def test_unified_returns_events_list(self, bare_client):
        data = bare_client.get("/api/events/unified").json()
        assert "events" in data
        assert isinstance(data["events"], list)

    @pytest.mark.unit
    def test_unified_returns_total(self, bare_client):
        data = bare_client.get("/api/events/unified").json()
        assert "total" in data
        assert data["total"] == len(data["events"])

    @pytest.mark.unit
    def test_unified_returns_sources(self, bare_client):
        data = bare_client.get("/api/events/unified").json()
        assert "sources" in data
        assert isinstance(data["sources"], dict)

    @pytest.mark.unit
    def test_unified_with_event_bus(self, events_client):
        data = events_client.get("/api/events/unified").json()
        assert data["total"] >= 2
        # Should have tactical source
        assert "tactical" in data["sources"]

    @pytest.mark.unit
    def test_unified_limit_param(self, events_client):
        data = events_client.get("/api/events/unified?limit=1").json()
        assert len(data["events"]) <= 1

    @pytest.mark.unit
    def test_unified_source_filter(self, events_client):
        data = events_client.get("/api/events/unified?source=tactical").json()
        for e in data["events"]:
            assert e["source"] == "tactical"

    @pytest.mark.unit
    def test_unified_since_filter(self, events_client):
        future_ts = time.time() + 1000
        data = events_client.get(f"/api/events/unified?since={future_ts}").json()
        assert data["total"] == 0

    @pytest.mark.unit
    def test_unified_events_sorted_newest_first(self, events_client):
        data = events_client.get("/api/events/unified").json()
        events = data["events"]
        if len(events) >= 2:
            assert events[0]["timestamp"] >= events[1]["timestamp"]

    @pytest.mark.unit
    def test_unified_event_structure(self, events_client):
        data = events_client.get("/api/events/unified").json()
        for e in data["events"]:
            assert "source" in e
            assert "type" in e
            assert "timestamp" in e
            assert "data" in e
