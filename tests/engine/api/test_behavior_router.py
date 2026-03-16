# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the behavioral pattern recognition router."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.behavior import router
from app.routers import behavior as beh_module


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    beh_module._patterns.clear()
    beh_module._anomalies.clear()
    beh_module._correlations.clear()
    return TestClient(app, raise_server_exceptions=False)


def test_report_pattern(client):
    resp = client.post("/api/behavior/pattern", json={
        "target_id": "ble_aa:bb:cc",
        "behavior_type": "loitering",
        "confidence": 0.8,
        "center_lat": 37.77,
        "center_lng": -122.42,
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "recorded"


def test_get_patterns(client):
    client.post("/api/behavior/pattern", json={
        "target_id": "t1", "behavior_type": "loitering",
    })
    client.post("/api/behavior/pattern", json={
        "target_id": "t2", "behavior_type": "patrol",
    })
    resp = client.get("/api/behavior/patterns")
    assert len(resp.json()) == 2


def test_filter_patterns_by_target(client):
    client.post("/api/behavior/pattern", json={"target_id": "t1", "behavior_type": "loitering"})
    client.post("/api/behavior/pattern", json={"target_id": "t2", "behavior_type": "patrol"})
    resp = client.get("/api/behavior/patterns?target_id=t1")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["target_id"] == "t1"


def test_filter_patterns_by_type(client):
    client.post("/api/behavior/pattern", json={"target_id": "t1", "behavior_type": "loitering"})
    client.post("/api/behavior/pattern", json={"target_id": "t2", "behavior_type": "patrol"})
    resp = client.get("/api/behavior/patterns?behavior_type=patrol")
    assert len(resp.json()) == 1


def test_report_anomaly(client):
    resp = client.post("/api/behavior/anomaly", json={
        "target_id": "ble_xx",
        "anomaly_type": "new_device",
        "severity": "low",
        "description": "First sighting",
    })
    assert resp.status_code == 200
    assert resp.json()["severity"] == "low"


def test_get_anomalies(client):
    client.post("/api/behavior/anomaly", json={
        "target_id": "t1", "anomaly_type": "new_device", "severity": "low",
    })
    client.post("/api/behavior/anomaly", json={
        "target_id": "t2", "anomaly_type": "unusual_time", "severity": "medium",
    })
    resp = client.get("/api/behavior/anomalies")
    assert len(resp.json()) == 2


def test_filter_anomalies_by_severity(client):
    client.post("/api/behavior/anomaly", json={"target_id": "t1", "severity": "low"})
    client.post("/api/behavior/anomaly", json={"target_id": "t2", "severity": "high"})
    resp = client.get("/api/behavior/anomalies?severity=high")
    assert len(resp.json()) == 1


def test_correlate_high_score(client):
    resp = client.post("/api/behavior/correlate", json={
        "target_a": "ble_phone",
        "target_b": "det_person_0",
        "temporal_overlap": 0.9,
        "spatial_proximity_m": 2.0,
        "co_movement_score": 0.8,
        "source_a": "ble",
        "source_b": "camera",
    })
    data = resp.json()
    assert data["score"] > 0.7
    assert data["should_fuse"] is True
    assert "cross-sensor" in " ".join(data["reasons"])


def test_correlate_low_score(client):
    resp = client.post("/api/behavior/correlate", json={
        "target_a": "ble_a",
        "target_b": "ble_b",
        "temporal_overlap": 0.1,
        "spatial_proximity_m": 200,
        "co_movement_score": 0.0,
    })
    data = resp.json()
    assert data["score"] < 0.3
    assert data["should_fuse"] is False


def test_stats_empty(client):
    resp = client.get("/api/behavior/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_patterns"] == 0
    assert data["total_anomalies"] == 0


def test_stats_populated(client):
    client.post("/api/behavior/pattern", json={"target_id": "t1", "behavior_type": "loitering"})
    client.post("/api/behavior/anomaly", json={"target_id": "t1", "severity": "high"})
    client.post("/api/behavior/correlate", json={
        "target_a": "a", "target_b": "b",
        "temporal_overlap": 0.9, "spatial_proximity_m": 1, "co_movement_score": 0.9,
    })

    resp = client.get("/api/behavior/stats")
    data = resp.json()
    assert data["total_patterns"] == 1
    assert data["total_anomalies"] == 1
    assert data["total_correlations"] == 1
    assert data["high_score_correlations"] == 1
