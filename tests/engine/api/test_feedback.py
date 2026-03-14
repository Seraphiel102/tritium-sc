# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the operator feedback endpoint (POST /api/feedback).

Wave 52 — RL/LLM integration: validates that operator feedback
is properly validated, stored, and retrievable via the stats endpoint.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Import the actual app instance."""
    from app.main import app as real_app
    return real_app


@pytest.fixture
def client(app):
    """TestClient that skips lifespan."""
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFeedbackEndpoint:
    """Tests for POST /api/feedback."""

    def test_valid_feedback_accepted(self, client):
        """Valid feedback with all fields should be accepted."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "decision_type": "classification",
                "correct": True,
                "notes": "Confirmed this is a phone",
                "operator": "op1",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["target_id"] == "ble_aa:bb:cc:dd:ee:ff"
        assert data["decision_type"] == "classification"
        assert data["correct"] is True

    def test_valid_decision_types(self, client):
        """All valid decision types should be accepted."""
        for dt in ("correlation", "classification", "threat"):
            resp = client.post(
                "/api/feedback",
                json={
                    "target_id": "test_target",
                    "decision_type": dt,
                    "correct": False,
                },
            )
            assert resp.status_code == 200, f"Decision type '{dt}' should be valid"

    def test_invalid_decision_type_rejected(self, client):
        """Invalid decision type should be rejected with 400."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "test_target",
                "decision_type": "invalid_type",
                "correct": True,
            },
        )
        assert resp.status_code == 400

    def test_missing_target_id_rejected(self, client):
        """Missing target_id should be rejected."""
        resp = client.post(
            "/api/feedback",
            json={
                "decision_type": "classification",
                "correct": True,
            },
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_empty_target_id_rejected(self, client):
        """Empty target_id should be rejected."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "",
                "decision_type": "classification",
                "correct": True,
            },
        )
        assert resp.status_code == 422  # min_length=1

    def test_missing_correct_field_rejected(self, client):
        """Missing 'correct' field should be rejected."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "test_target",
                "decision_type": "classification",
            },
        )
        assert resp.status_code == 422

    def test_feedback_rejection(self, client):
        """Operator can reject a decision (correct=False)."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "decision_type": "correlation",
                "correct": False,
                "notes": "These are different targets, not correlated",
                "operator": "supervisor",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["correct"] is False

    def test_feedback_without_optional_fields(self, client):
        """Feedback with only required fields should work."""
        resp = client.post(
            "/api/feedback",
            json={
                "target_id": "mesh_node_1",
                "decision_type": "threat",
                "correct": True,
            },
        )
        assert resp.status_code == 200


class TestFeedbackStats:
    """Tests for GET /api/feedback/stats."""

    def test_stats_returns_structure(self, client):
        """Stats endpoint should return expected structure."""
        resp = client.get("/api/feedback/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "correlation" in data
        assert "classification" in data
        assert "feedback" in data
        assert "total" in data["correlation"]
        assert "total" in data["feedback"]
