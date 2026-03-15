# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the historical analytics API router."""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.history_analytics import router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_no_store():
    """App without event store configured."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client_no_store(app_no_store):
    return TestClient(app_no_store)


@pytest.fixture
def app_with_store():
    """App with a mock event store."""
    from engine.tactical.event_store import TacticalEventStore

    app = FastAPI()
    app.include_router(router)

    store = TacticalEventStore(db_path=":memory:", site_id="test")
    # Populate with test data
    store.record("target_sighting", target_id="t1", source="ble")
    store.record("target_sighting", target_id="t2", source="wifi")
    store.record("alert", target_id="t1", severity="warning")
    store.record("target_correlation", target_id="t1", source="correlator")
    store.record("geofence_enter", target_id="t2")

    app.state.tactical_event_store = store
    return app


@pytest.fixture
def client_with_store(app_with_store):
    return TestClient(app_with_store)


# ---------------------------------------------------------------------------
# Tests — no store
# ---------------------------------------------------------------------------

class TestHistoryAnalyticsNoStore:
    def test_returns_empty_without_store(self, client_no_store):
        resp = client_no_store.get("/api/analytics/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 0
        assert data["source"] == "no_store"

    def test_accepts_hours_param(self, client_no_store):
        resp = client_no_store.get("/api/analytics/history?hours=24")
        assert resp.status_code == 200

    def test_accepts_start_end(self, client_no_store):
        now = time.time()
        resp = client_no_store.get(
            f"/api/analytics/history?start={now - 3600}&end={now}"
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests — with store
# ---------------------------------------------------------------------------

class TestHistoryAnalyticsWithStore:
    def test_returns_stats(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 5

    def test_events_by_type(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert "target_sighting" in data["events_by_type"]
        assert data["events_by_type"]["target_sighting"] == 2

    def test_target_activity(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert "target_activity" in data
        assert data["target_activity"]["sightings"] == 2
        assert data["target_activity"]["alerts"] == 1

    def test_correlation_stats(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert "correlation_stats" in data
        assert data["correlation_stats"]["total_correlations"] == 1

    def test_top_targets(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert len(data["top_targets"]) > 0

    def test_busiest_hours(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert isinstance(data["busiest_hours"], dict)

    def test_time_range(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history")
        data = resp.json()
        assert "time_range" in data
        assert data["time_range"]["end"] is not None

    def test_hours_param(self, client_with_store):
        resp = client_with_store.get("/api/analytics/history?hours=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 5  # all within last hour
