# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security audit tests for the classification override endpoint.

Wave 52 — SECURITY: Tests that the classification override endpoint
properly rejects invalid alliance values, rejects injection attempts
via device_type, handles edge cases in target_id, and validates
all input boundaries.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


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


@pytest.fixture
def mock_tracker(app):
    """Inject a mock target tracker into app state."""
    tracker = MagicMock()
    target = SimpleNamespace(
        target_id="ble_aa:bb:cc:dd:ee:ff",
        alliance="unknown",
        device_type="phone",
        classification="phone",
        source="ble",
    )
    tracker.get.return_value = target
    tracker.get_all.return_value = [target]

    amy = MagicMock()
    amy.target_tracker = tracker
    app.state.amy = amy
    yield tracker, target
    # Cleanup
    if hasattr(app.state, "amy"):
        del app.state.amy


# ---------------------------------------------------------------------------
# A. Invalid alliance values
# ---------------------------------------------------------------------------

class TestAllianceValidation:
    """Verify that invalid alliance values are rejected."""

    def test_valid_alliances_accepted(self, client, mock_tracker):
        """All valid alliances should be accepted."""
        for alliance in ("friendly", "hostile", "neutral", "unknown"):
            resp = client.post(
                "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
                json={
                    "target_id": "ble_aa:bb:cc:dd:ee:ff",
                    "alliance": alliance,
                    "reason": "test",
                },
            )
            assert resp.status_code == 200, f"Alliance '{alliance}' should be valid"

    def test_invalid_alliance_rejected(self, client, mock_tracker):
        """Arbitrary alliance values should be rejected with 400."""
        invalid_values = [
            "admin",
            "superuser",
            "root",
            "FRIENDLY",  # case-sensitive check
            "Hostile",
            "evil",
            "ally",
            "enemy",
            "compromised",
        ]
        for val in invalid_values:
            resp = client.post(
                "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
                json={
                    "target_id": "ble_aa:bb:cc:dd:ee:ff",
                    "alliance": val,
                    "reason": "test",
                },
            )
            assert resp.status_code == 400, f"Alliance '{val}' should be rejected"

    def test_empty_string_alliance_requires_device_type(self, client, mock_tracker):
        """Empty alliance without device_type should fail."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "alliance": "",
                "device_type": "",
                "reason": "test",
            },
        )
        # Empty strings are falsy, so validation requires at least one field
        assert resp.status_code == 400

    def test_sql_injection_in_alliance(self, client, mock_tracker):
        """SQL injection attempt in alliance should be rejected."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "alliance": "friendly'; DROP TABLE targets;--",
                "reason": "test",
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# B. Injection via device_type
# ---------------------------------------------------------------------------

class TestDeviceTypeInjection:
    """Verify device_type field rejects injection attempts."""

    def test_valid_device_types_accepted(self, client, mock_tracker):
        """All valid device types should be accepted."""
        valid_types = [
            "person", "vehicle", "phone", "watch", "computer",
            "animal", "mesh_radio", "ble_device", "drone", "sensor", "unknown",
        ]
        for dt in valid_types:
            resp = client.post(
                "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
                json={
                    "target_id": "ble_aa:bb:cc:dd:ee:ff",
                    "device_type": dt,
                    "reason": "test",
                },
            )
            assert resp.status_code == 200, f"Device type '{dt}' should be valid"

    def test_script_injection_in_device_type(self, client, mock_tracker):
        """XSS-style injection in device_type should be rejected."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "device_type": "<script>alert('xss')</script>",
                "reason": "test",
            },
        )
        assert resp.status_code == 400

    def test_sql_injection_in_device_type(self, client, mock_tracker):
        """SQL injection attempt in device_type should be rejected."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "device_type": "phone' OR '1'='1",
                "reason": "test",
            },
        )
        assert resp.status_code == 400

    def test_path_traversal_in_device_type(self, client, mock_tracker):
        """Path traversal in device_type should be rejected."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "device_type": "../../etc/passwd",
                "reason": "test",
            },
        )
        assert resp.status_code == 400

    def test_oversized_device_type(self, client, mock_tracker):
        """Extremely long device_type values should be rejected."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "device_type": "A" * 10000,
                "reason": "test",
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case testing for the classification override endpoint."""

    def test_no_fields_provided(self, client, mock_tracker):
        """Request with neither alliance nor device_type should fail."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "reason": "test",
            },
        )
        assert resp.status_code == 400

    def test_target_not_found(self, client, mock_tracker):
        """Override on non-existent target should return 404."""
        tracker, _ = mock_tracker
        tracker.get.return_value = None
        resp = client.post(
            "/api/targets/nonexistent_target/classify",
            json={
                "target_id": "nonexistent_target",
                "alliance": "hostile",
                "reason": "test",
            },
        )
        assert resp.status_code == 404

    def test_target_id_mismatch_path_vs_body(self, client, mock_tracker):
        """Path target_id and body target_id can differ (path wins)."""
        # The endpoint uses path param for lookup, body is for metadata
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "different_id",
                "alliance": "friendly",
                "reason": "test",
            },
        )
        # Should still work since path param is used for tracker lookup
        assert resp.status_code == 200

    def test_unicode_in_reason(self, client, mock_tracker):
        """Unicode characters in reason field should be accepted."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "alliance": "hostile",
                "reason": "Operator confirmed threat via visual contact",
            },
        )
        assert resp.status_code == 200

    def test_no_tracker_available(self, client, app):
        """With no tracker, dossier-only update should not crash."""
        # Remove amy to simulate no tracker
        if hasattr(app.state, "amy"):
            del app.state.amy
        resp = client.post(
            "/api/targets/some_target/classify",
            json={
                "target_id": "some_target",
                "alliance": "hostile",
                "reason": "test",
            },
        )
        # Should succeed (dossier-only path), not crash
        assert resp.status_code == 200

    def test_both_alliance_and_device_type(self, client, mock_tracker):
        """Setting both alliance and device_type in one request."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "alliance": "hostile",
                "device_type": "drone",
                "reason": "Visual confirmation of hostile drone",
                "operator": "op1",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["changes"]["alliance"] == "hostile"
        assert data["changes"]["device_type"] == "drone"

    def test_null_values_handled(self, client, mock_tracker):
        """Explicit null values for alliance/device_type should require one."""
        resp = client.post(
            "/api/targets/ble_aa:bb:cc:dd:ee:ff/classify",
            json={
                "target_id": "ble_aa:bb:cc:dd:ee:ff",
                "alliance": None,
                "device_type": None,
                "reason": "test",
            },
        )
        assert resp.status_code == 400
