# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for the target timeline router — /api/targets/{id}/timeline.

Tests with mocked tracker, geofence engine, and enrichment pipeline.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.timeline import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(tracker=None, amy=None, engine=None, geofence=None, enrichment=None, event_log=None):
    """Create FastAPI app with timeline router and optional state."""
    app = FastAPI()
    app.include_router(router)

    if amy is not None:
        app.state.amy = amy
    if engine is not None:
        app.state.simulation_engine = engine
    if geofence is not None:
        app.state.geofence_engine = geofence
    if enrichment is not None:
        app.state.enrichment_pipeline = enrichment
    if event_log is not None:
        app.state.event_log = event_log

    return app


def _mock_target(target_id="t1", alliance="friendly", name="Unit-1", source="simulation"):
    """Create a mock TrackedTarget."""
    t = MagicMock()
    t.target_id = target_id
    t.alliance = alliance
    t.name = name
    t.source = source
    t.asset_type = "rover"
    t.position = (10.0, 20.0)
    t.position_confidence = 0.9
    t.last_seen = 1000.0
    t.to_dict.return_value = {
        "target_id": target_id,
        "alliance": alliance,
        "name": name,
        "source": source,
        "position": {"x": 10.0, "y": 20.0},
    }
    return t


def _mock_tracker(targets=None, trail=None):
    """Create a mock TargetTracker with history."""
    tracker = MagicMock()
    target_map = {t.target_id: t for t in (targets or [])}

    def get_target(tid):
        return target_map.get(tid)

    tracker.get_target = get_target
    tracker.get_all.return_value = targets or []

    history = MagicMock()
    history.get_trail_dicts.return_value = trail or []
    tracker.history = history

    return tracker


def _amy_with_tracker(tracker):
    """Create a mock Amy with a target_tracker."""
    amy = MagicMock()
    amy.target_tracker = tracker
    amy.simulation_engine = None
    return amy


def _mock_geofence_engine(events=None):
    """Create a mock GeofenceEngine."""
    engine = MagicMock()
    engine.get_events.return_value = events or []
    return engine


def _mock_geo_event(event_type="enter", target_id="t1", zone_name="Zone A", timestamp=500.0):
    """Create a mock GeoEvent."""
    e = MagicMock()
    e.event_type = event_type
    e.target_id = target_id
    e.zone_id = "z1"
    e.zone_name = zone_name
    e.zone_type = "restricted"
    e.position = (15.0, 25.0)
    e.timestamp = timestamp
    return e


def _mock_enrichment_pipeline(results=None):
    """Create a mock enrichment pipeline."""
    pipeline = MagicMock()
    pipeline.get_cached.return_value = results
    return pipeline


def _mock_enrichment_result(provider="oui", timestamp=600.0):
    """Create a mock enrichment result."""
    r = MagicMock()
    r.to_dict.return_value = {
        "provider": provider,
        "timestamp": timestamp,
        "summary": "Manufacturer: Acme Corp",
        "result": "Acme Corp",
    }
    return r


# ---------------------------------------------------------------------------
# GET /api/targets/{target_id}/timeline — basic
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetTimeline:
    """GET /api/targets/{id}/timeline — basic timeline retrieval."""

    def test_target_not_found(self):
        """Returns empty events when target does not exist."""
        tracker = _mock_tracker()
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/nonexistent/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_id"] == "nonexistent"
        assert data["events"] == []
        assert "error" in data

    def test_no_tracking(self):
        """Returns error when no tracker available."""
        client = TestClient(_make_app())
        resp = client.get("/api/targets/t1/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []

    def test_with_trail_events(self):
        """Returns sighting events from target history trail."""
        t1 = _mock_target("t1")
        trail = [
            {"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.5},
            {"x": 3.0, "y": 4.0, "timestamp": 200.0, "speed": 1.0},
            {"x": 5.0, "y": 6.0, "timestamp": 300.0, "speed": 0.0},
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        assert data["events"][0]["event_type"] == "sighting"
        assert data["events"][0]["timestamp"] == 100.0
        # Verify sorted ascending
        timestamps = [e["timestamp"] for e in data["events"]]
        assert timestamps == sorted(timestamps)

    def test_with_geofence_events(self):
        """Returns geofence enter/exit events."""
        t1 = _mock_target("t1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)

        geo_events = [
            _mock_geo_event("enter", "t1", "Perimeter", 150.0),
            _mock_geo_event("exit", "t1", "Perimeter", 250.0),
        ]
        geofence = _mock_geofence_engine(events=geo_events)

        client = TestClient(_make_app(amy=amy, geofence=geofence))
        resp = client.get("/api/targets/t1/timeline")
        assert resp.status_code == 200
        data = resp.json()
        geo = [e for e in data["events"] if e["event_type"].startswith("geofence_")]
        assert len(geo) == 2
        assert geo[0]["event_type"] == "geofence_enter"
        assert geo[1]["event_type"] == "geofence_exit"

    def test_with_enrichment_events(self):
        """Returns enrichment result events."""
        t1 = _mock_target("t1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)

        results = [_mock_enrichment_result("oui", 400.0)]
        pipeline = _mock_enrichment_pipeline(results=results)

        client = TestClient(_make_app(amy=amy, enrichment=pipeline))
        resp = client.get("/api/targets/t1/timeline")
        assert resp.status_code == 200
        data = resp.json()
        enrich = [e for e in data["events"] if e["event_type"] == "enrichment"]
        assert len(enrich) == 1
        assert enrich[0]["source"] == "oui"

    def test_yolo_detection_event(self):
        """YOLO-source targets produce a detection event."""
        t1 = _mock_target("det_person_1", source="yolo")
        t1.asset_type = "person"
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)

        client = TestClient(_make_app(amy=amy))
        resp = client.get("/api/targets/det_person_1/timeline")
        assert resp.status_code == 200
        data = resp.json()
        detections = [e for e in data["events"] if e["event_type"] == "detection"]
        assert len(detections) == 1
        assert detections[0]["source"] == "camera"


# ---------------------------------------------------------------------------
# Time range filtering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTimelineTimeRange:
    """GET /api/targets/{id}/timeline?start=&end= — time filtering."""

    def test_start_filter(self):
        """Filters out events before start timestamp."""
        t1 = _mock_target("t1")
        trail = [
            {"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0},
            {"x": 3.0, "y": 4.0, "timestamp": 200.0, "speed": 0.0},
            {"x": 5.0, "y": 6.0, "timestamp": 300.0, "speed": 0.0},
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline?start=200")
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["events"][0]["timestamp"] == 200.0

    def test_end_filter(self):
        """Filters out events after end timestamp."""
        t1 = _mock_target("t1")
        trail = [
            {"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0},
            {"x": 3.0, "y": 4.0, "timestamp": 200.0, "speed": 0.0},
            {"x": 5.0, "y": 6.0, "timestamp": 300.0, "speed": 0.0},
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline?end=200")
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["events"][-1]["timestamp"] == 200.0

    def test_start_and_end_filter(self):
        """Filters to events within time range."""
        t1 = _mock_target("t1")
        trail = [
            {"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0},
            {"x": 3.0, "y": 4.0, "timestamp": 200.0, "speed": 0.0},
            {"x": 5.0, "y": 6.0, "timestamp": 300.0, "speed": 0.0},
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline?start=150&end=250")
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["timestamp"] == 200.0


# ---------------------------------------------------------------------------
# Event type filtering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTimelineEventTypeFilter:
    """GET /api/targets/{id}/timeline?event_types= — type filtering."""

    def test_filter_sighting_only(self):
        """Filter to sighting events only."""
        t1 = _mock_target("t1")
        trail = [{"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0}]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)

        geo_events = [_mock_geo_event("enter", "t1", "Zone A", 150.0)]
        geofence = _mock_geofence_engine(events=geo_events)

        client = TestClient(_make_app(amy=amy, geofence=geofence))
        resp = client.get("/api/targets/t1/timeline?event_types=sighting")
        data = resp.json()
        assert all(e["event_type"] == "sighting" for e in data["events"])

    def test_filter_multiple_types(self):
        """Filter to multiple event types via comma-separated list."""
        t1 = _mock_target("t1")
        trail = [{"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0}]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)

        geo_events = [_mock_geo_event("enter", "t1", "Zone A", 150.0)]
        geofence = _mock_geofence_engine(events=geo_events)

        results = [_mock_enrichment_result("oui", 200.0)]
        pipeline = _mock_enrichment_pipeline(results=results)

        client = TestClient(_make_app(amy=amy, geofence=geofence, enrichment=pipeline))
        resp = client.get("/api/targets/t1/timeline?event_types=sighting,enrichment")
        data = resp.json()
        types = {e["event_type"] for e in data["events"]}
        assert "geofence_enter" not in types
        assert "sighting" in types or "enrichment" in types


# ---------------------------------------------------------------------------
# Aggregation — multiple sources combined
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTimelineAggregation:
    """Timeline correctly aggregates events from multiple sources."""

    def test_mixed_sources_sorted(self):
        """Events from different sources are merged and sorted by timestamp."""
        t1 = _mock_target("t1")
        trail = [
            {"x": 1.0, "y": 2.0, "timestamp": 100.0, "speed": 0.0},
            {"x": 3.0, "y": 4.0, "timestamp": 300.0, "speed": 0.0},
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)

        geo_events = [_mock_geo_event("enter", "t1", "Zone A", 200.0)]
        geofence = _mock_geofence_engine(events=geo_events)

        results = [_mock_enrichment_result("oui", 250.0)]
        pipeline = _mock_enrichment_pipeline(results=results)

        client = TestClient(_make_app(amy=amy, geofence=geofence, enrichment=pipeline))
        resp = client.get("/api/targets/t1/timeline")
        data = resp.json()

        timestamps = [e["timestamp"] for e in data["events"]]
        assert timestamps == sorted(timestamps)
        assert len(data["events"]) >= 4  # 2 sightings + 1 geofence + 1 enrichment

    def test_limit_parameter(self):
        """Limit parameter caps returned events."""
        t1 = _mock_target("t1")
        trail = [
            {"x": float(i), "y": float(i), "timestamp": float(i * 10), "speed": 0.0}
            for i in range(20)
        ]
        tracker = _mock_tracker(targets=[t1], trail=trail)
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline?limit=5")
        data = resp.json()
        assert len(data["events"]) == 5
        # Should be the last 5 events
        assert data["total"] == 20

    def test_target_info_included(self):
        """Response includes target metadata."""
        t1 = _mock_target("t1", name="Alpha-1")
        tracker = _mock_tracker(targets=[t1])
        amy = _amy_with_tracker(tracker)
        client = TestClient(_make_app(amy=amy))

        resp = client.get("/api/targets/t1/timeline")
        data = resp.json()
        assert data["target"]["name"] == "Alpha-1"
        assert data["target_id"] == "t1"


# ---------------------------------------------------------------------------
# Simulation engine fallback
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTimelineSimulationFallback:
    """Timeline works with simulation engine when tracker unavailable."""

    def test_sim_engine_target(self):
        """Can find target from simulation engine."""
        sim_target = MagicMock()
        sim_target.target_id = "sim-1"
        sim_target.to_dict.return_value = {
            "target_id": "sim-1",
            "name": "Sim Unit",
            "position": {"x": 5.0, "y": 10.0},
        }

        engine = MagicMock()
        engine.get_targets.return_value = [sim_target]

        client = TestClient(_make_app(engine=engine))
        resp = client.get("/api/targets/sim-1/timeline")
        data = resp.json()
        assert data["target"]["target_id"] == "sim-1"
        assert data["events"] == []  # no tracker, so no trail events
