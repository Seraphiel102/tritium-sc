# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for deployment service management API."""

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """Create a test client with the deployment router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.deployment import router

    app = FastAPI()
    app.include_router(router)
    # Mock app.state
    app.state.settings = None
    return TestClient(app)


class TestListServices:
    def test_returns_services(self, client):
        resp = client.get("/api/deployment/services")
        assert resp.status_code == 200
        data = resp.json()
        assert "services" in data
        assert "total" in data
        assert "running" in data
        assert "installed" in data
        assert isinstance(data["services"], list)
        assert data["total"] >= 1  # At least SC server

    def test_sc_always_running(self, client):
        resp = client.get("/api/deployment/services")
        data = resp.json()
        sc = next((s for s in data["services"] if s["name"] == "sc_server"), None)
        assert sc is not None
        assert sc["state"] == "running"
        assert sc["pid"] is not None

    def test_service_fields(self, client):
        resp = client.get("/api/deployment/services")
        data = resp.json()
        for svc in data["services"]:
            assert "name" in svc
            assert "state" in svc
            assert "display_name" in svc


class TestSystemRequirements:
    def test_returns_requirements(self, client):
        resp = client.get("/api/deployment/requirements")
        assert resp.status_code == 200
        data = resp.json()
        assert "python" in data
        assert "system_packages" in data
        assert "platform" in data
        assert "hostname" in data
        assert data["python"]["required"] == "3.12+"
        assert isinstance(data["python"]["ok"], bool)

    def test_system_packages_dict(self, client):
        resp = client.get("/api/deployment/requirements")
        data = resp.json()
        pkgs = data["system_packages"]
        assert isinstance(pkgs, dict)
        assert "git" in pkgs


class TestServiceStart:
    def test_unknown_service(self, client):
        resp = client.post(
            "/api/deployment/services/start",
            json={"service": "nonexistent"},
        )
        assert resp.status_code == 400

    def test_start_body_required(self, client):
        resp = client.post("/api/deployment/services/start")
        assert resp.status_code == 422  # Validation error


class TestServiceStop:
    def test_cannot_stop_sc(self, client):
        resp = client.post(
            "/api/deployment/services/stop",
            json={"service": "sc_server"},
        )
        assert resp.status_code == 400

    def test_unknown_service(self, client):
        resp = client.post(
            "/api/deployment/services/stop",
            json={"service": "nonexistent"},
        )
        assert resp.status_code == 400
