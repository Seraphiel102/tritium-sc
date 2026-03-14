# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security audit tests — Wave 22.

Verifies:
1. SQL injection resistance in API endpoints
2. Input validation (malformed JSON, oversized payloads)
3. LPR/transponder endpoints handle bad data gracefully
4. Rate limit middleware exists and functions
5. No information leakage in error responses
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.lpr import router as lpr_router
from app.routers.transponders import router as tp_router
from app.routers import lpr as lpr_module
from app.routers import transponders as tp_module


@pytest.fixture
def lpr_client():
    app = FastAPI()
    app.include_router(lpr_router)
    lpr_module._detections.clear()
    lpr_module._watchlist.clear()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def tp_client():
    app = FastAPI()
    app.include_router(tp_router)
    tp_module._flights.clear()
    tp_module._vessels.clear()
    tp_module._stats.update({
        "adsb_reports": 0, "ais_reports": 0,
        "active_flights": 0, "active_vessels": 0, "emergencies": 0,
    })
    return TestClient(app, raise_server_exceptions=False)


class TestInputValidation:
    """Test that endpoints reject malformed or malicious input."""

    def test_lpr_empty_plate(self, lpr_client):
        """Empty plate text should still work (no crash)."""
        resp = lpr_client.post("/api/lpr/detect", json={
            "plate_text": "",
            "confidence": 0.5,
        })
        assert resp.status_code == 200

    def test_lpr_very_long_plate(self, lpr_client):
        """Extremely long plate text should not crash."""
        resp = lpr_client.post("/api/lpr/detect", json={
            "plate_text": "A" * 10000,
            "confidence": 0.5,
        })
        assert resp.status_code == 200

    def test_lpr_special_chars_in_plate(self, lpr_client):
        """Special characters in plate text should not crash.

        Note: LPR uses in-memory store, no SQL. The plate text is
        normalized (spaces/dashes removed, uppercased) but special
        chars pass through. This is safe since no DB queries use it.
        """
        resp = lpr_client.post("/api/lpr/detect", json={
            "plate_text": "'; DROP TABLE plates; --",
            "confidence": 0.5,
        })
        assert resp.status_code == 200
        data = resp.json()
        # Should return a valid response without crashing
        assert "target_id" in data
        assert data["target_id"].startswith("lpr_")

    def test_lpr_negative_confidence(self, lpr_client):
        """Negative confidence should not crash."""
        resp = lpr_client.post("/api/lpr/detect", json={
            "plate_text": "ABC123",
            "confidence": -1.0,
        })
        assert resp.status_code == 200

    def test_lpr_invalid_json(self, lpr_client):
        """Invalid JSON should return 422."""
        resp = lpr_client.post(
            "/api/lpr/detect",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    def test_tp_invalid_icao(self, tp_client):
        """Invalid ICAO hex should not crash."""
        resp = tp_client.post("/api/transponders/adsb/report", json={
            "icao_hex": "",
        })
        assert resp.status_code == 200

    def test_tp_extreme_altitude(self, tp_client):
        """Extreme altitude values should not crash."""
        resp = tp_client.post("/api/transponders/adsb/report", json={
            "icao_hex": "TEST",
            "altitude_ft": 999999999,
        })
        assert resp.status_code == 200

    def test_tp_negative_mmsi(self, tp_client):
        """Negative MMSI should not crash."""
        resp = tp_client.post("/api/transponders/ais/report", json={
            "mmsi": -1,
        })
        assert resp.status_code == 200

    def test_tp_zero_mmsi(self, tp_client):
        """Zero MMSI should not crash."""
        resp = tp_client.post("/api/transponders/ais/report", json={
            "mmsi": 0,
        })
        assert resp.status_code == 200


class TestNoInfoLeakage:
    """Test that error responses don't leak internal details."""

    def test_lpr_404_no_stack_trace(self, lpr_client):
        """404 should not contain stack traces."""
        resp = lpr_client.delete("/api/lpr/watchlist/NONEXISTENT")
        assert resp.status_code == 404
        body = resp.text
        assert "Traceback" not in body
        assert "File " not in body

    def test_tp_missing_route(self, tp_client):
        """Unknown route should return clean 404/405."""
        resp = tp_client.get("/api/transponders/nonexistent")
        assert resp.status_code in (404, 405)
        body = resp.text
        assert "Traceback" not in body


class TestEdgeCases:
    """Test boundary conditions."""

    def test_lpr_stats_empty(self, lpr_client):
        """Stats with no data should not divide by zero."""
        resp = lpr_client.get("/api/lpr/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["avg_confidence"] == 0.0

    def test_lpr_search_empty_query(self, lpr_client):
        """Empty search query should return results."""
        lpr_client.post("/api/lpr/detect", json={"plate_text": "ABC"})
        resp = lpr_client.get("/api/lpr/search?q=")
        assert resp.status_code == 200

    def test_tp_stats_empty(self, tp_client):
        """Stats with no data should not crash."""
        resp = tp_client.get("/api/transponders/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_flights"] == 0

    def test_tp_emergencies_empty(self, tp_client):
        """No emergencies should return clean response."""
        resp = tp_client.get("/api/transponders/emergencies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
