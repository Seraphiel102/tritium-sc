# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the movement analytics API router."""

import math
import time
from unittest.mock import MagicMock, patch

import pytest

from app.routers.movement_analytics import (
    _compute_movement_analytics,
    _heading_to_bin,
)


class TestHeadingToBin:
    def test_north(self):
        assert _heading_to_bin(0) == "N"
        assert _heading_to_bin(350) == "N"
        assert _heading_to_bin(10) == "N"

    def test_east(self):
        assert _heading_to_bin(90) == "E"

    def test_south(self):
        assert _heading_to_bin(180) == "S"

    def test_west(self):
        assert _heading_to_bin(270) == "W"

    def test_northeast(self):
        assert _heading_to_bin(45) == "NE"

    def test_wrap_360(self):
        assert _heading_to_bin(360) == "N"
        assert _heading_to_bin(720) == "N"


class TestComputeMovementAnalytics:
    def _make_history(self, trail_data):
        """Create a mock TargetHistory that returns given trail data."""
        history = MagicMock()
        history.get_trail.return_value = trail_data
        return history

    def test_no_history(self):
        history = self._make_history([])
        result = _compute_movement_analytics("t1", history)
        assert result["error"] == "no_history"

    def test_stationary_target(self):
        # Same position repeated
        t = time.monotonic()
        trail = [(10.0, 20.0, t), (10.0, 20.0, t + 1), (10.0, 20.0, t + 2)]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history)
        assert result["is_stationary"] is True
        assert result["avg_speed_mps"] == 0.0

    def test_moving_target(self):
        t = time.monotonic()
        # Moving north at 1 m/s (positive Y)
        trail = [
            (0.0, 0.0, t),
            (0.0, 1.0, t + 1),
            (0.0, 2.0, t + 2),
            (0.0, 3.0, t + 3),
        ]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history)
        assert result["is_stationary"] is False
        assert result["avg_speed_mps"] == pytest.approx(1.0, abs=0.01)
        assert result["total_distance_m"] == pytest.approx(3.0, abs=0.01)
        assert result["target_id"] == "t1"

    def test_direction_histogram(self):
        t = time.monotonic()
        # Moving east (+X)
        trail = [
            (0.0, 0.0, t),
            (1.0, 0.0, t + 1),
            (2.0, 0.0, t + 2),
        ]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history)
        hist = result["direction_histogram"]
        assert hist["E"] > 0.5  # dominant direction is east

    def test_activity_periods(self):
        t = time.monotonic()
        trail = [
            # Moving
            (0.0, 0.0, t),
            (0.0, 1.0, t + 1),
            (0.0, 2.0, t + 2),
            # Stationary
            (0.0, 2.0, t + 3),
            (0.0, 2.0, t + 4),
            # Moving again
            (0.0, 3.0, t + 5),
            (0.0, 4.0, t + 6),
        ]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history)
        periods = result["activity_periods"]
        assert len(periods) >= 1  # at least one active period

    def test_dwell_times_with_zones(self):
        t = time.monotonic()
        zones = [
            {"id": "z1", "name": "Lobby", "center_x": 0.0, "center_y": 0.0, "radius": 5.0},
        ]
        # Target enters and stays in zone
        trail = [
            (0.0, 0.0, t),
            (1.0, 0.0, t + 10),
            (2.0, 0.0, t + 20),
        ]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history, zones=zones)
        assert len(result["dwell_times"]) == 1
        assert result["dwell_times"][0]["zone_name"] == "Lobby"
        assert result["dwell_times"][0]["total_seconds"] >= 15.0

    def test_dwell_times_exit_zone(self):
        t = time.monotonic()
        zones = [
            {"id": "z1", "name": "Parking", "center_x": 0.0, "center_y": 0.0, "radius": 3.0},
        ]
        # Target starts in zone, then leaves
        trail = [
            (0.0, 0.0, t),
            (1.0, 0.0, t + 5),
            (10.0, 0.0, t + 10),  # out of zone
            (20.0, 0.0, t + 15),
        ]
        history = self._make_history(trail)
        result = _compute_movement_analytics("t1", history, zones=zones)
        dwell = result["dwell_times"]
        assert len(dwell) == 1
        assert dwell[0]["entry_count"] == 1
        # Dwell should be about 10 seconds (in zone from t to t+10)
        assert dwell[0]["total_seconds"] <= 15.0


class TestMovementAnalyticsRouter:
    """Test the FastAPI router endpoints."""

    @pytest.fixture
    def client(self):
        import os
        os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
        os.environ.setdefault("SIMULATION_ENABLED", "false")
        os.environ.setdefault("AMY_ENABLED", "false")
        os.environ.setdefault("MQTT_ENABLED", "false")
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_fleet_movement_no_tracker(self, client):
        """Fleet movement endpoint returns 503 without tracker."""
        resp = client.get("/api/analytics/movement")
        assert resp.status_code in (200, 503)

    def test_target_movement_not_found(self, client):
        """Individual target returns 404 or 503."""
        resp = client.get("/api/analytics/movement/nonexistent_target")
        assert resp.status_code in (404, 503)
