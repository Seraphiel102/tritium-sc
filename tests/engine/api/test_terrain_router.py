# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for terrain analysis and RF coverage router."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.terrain import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_propagation_basic(client):
    """Basic propagation estimate."""
    resp = client.post("/api/terrain/propagation", json={
        "tx_power_dbm": 0,
        "distance_m": 10,
        "frequency_mhz": 2400,
        "terrain_type": "rural",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["terrain_type"] == "rural"
    assert data["estimated_rssi_dbm"] < 0
    assert data["free_space_loss_db"] > 0


def test_propagation_quality_labels(client):
    """Short distance should give excellent quality."""
    resp = client.post("/api/terrain/propagation", json={
        "tx_power_dbm": 20,
        "distance_m": 1,
        "frequency_mhz": 2400,
        "terrain_type": "water",
    })
    data = resp.json()
    assert data["coverage_quality"] in ("excellent", "good")


def test_propagation_far_distance(client):
    """Far distance should give poor quality."""
    resp = client.post("/api/terrain/propagation", json={
        "tx_power_dbm": 0,
        "distance_m": 10000,
        "frequency_mhz": 2400,
        "terrain_type": "urban",
    })
    data = resp.json()
    assert data["coverage_quality"] in ("poor", "none")


def test_coverage_basic(client):
    """Basic coverage analysis."""
    resp = client.post("/api/terrain/coverage", json={
        "sensor_lat": 37.7749,
        "sensor_lng": -122.4194,
        "range_m": 50,
        "grid_resolution_m": 10,
        "terrain_type": "suburban",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cells"] > 0
    assert 0 <= data["coverage_percent"] <= 100
    assert data["terrain_type"] == "suburban"


def test_coverage_cell_limit(client):
    """Coverage should cap at 10000 cells."""
    resp = client.post("/api/terrain/coverage", json={
        "sensor_lat": 37.7749,
        "sensor_lng": -122.4194,
        "range_m": 5000,
        "grid_resolution_m": 5,
    })
    data = resp.json()
    assert data["total_cells"] <= 10000


def test_los_short_distance(client):
    """Short distance should have LOS."""
    resp = client.post("/api/terrain/los", json={
        "start_lat": 37.7749,
        "start_lng": -122.4194,
        "end_lat": 37.7750,
        "end_lng": -122.4193,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_line_of_sight"] is True
    assert data["distance_m"] > 0


def test_los_long_distance(client):
    """Long distance should be uncertain."""
    resp = client.post("/api/terrain/los", json={
        "start_lat": 37.7749,
        "start_lng": -122.4194,
        "end_lat": 37.8,
        "end_lng": -122.3,
    })
    data = resp.json()
    assert data["distance_m"] > 500
    assert data["has_line_of_sight"] is False


def test_terrain_types(client):
    """List terrain types."""
    resp = client.get("/api/terrain/types")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 9
    types = [t["type"] for t in data]
    assert "urban" in types
    assert "water" in types


def test_propagation_all_terrains(client):
    """All terrain types should work."""
    for terrain in ["urban", "suburban", "rural", "forest", "water",
                    "desert", "mountain", "indoor", "unknown"]:
        resp = client.post("/api/terrain/propagation", json={
            "tx_power_dbm": 0,
            "distance_m": 50,
            "terrain_type": terrain,
        })
        assert resp.status_code == 200
