# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Amy daily briefing router."""

import pytest
from unittest.mock import patch, MagicMock


class TestAmyBriefing:
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

    def test_get_briefing_returns_200(self, client):
        """GET /api/amy/briefing should return a briefing."""
        resp = client.get("/api/amy/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "briefing_id" in data
        assert "text" in data
        assert "source" in data
        assert data["source"] in ("ollama", "template")

    def test_post_briefing_returns_200(self, client):
        """POST /api/amy/briefing should generate a briefing."""
        resp = client.post("/api/amy/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert len(data["text"]) > 50  # should have content

    def test_briefing_contains_sections(self, client):
        """Template briefing should have key sections."""
        resp = client.post("/api/amy/briefing")
        data = resp.json()
        text = data["text"]
        assert "DAILY BRIEFING" in text

    def test_briefing_has_context_summary(self, client):
        """Briefing should include context summary."""
        resp = client.get("/api/amy/briefing")
        data = resp.json()
        assert "context_summary" in data
        cs = data["context_summary"]
        assert "threat_level" in cs
        assert "total_targets" in cs

    def test_briefing_caching(self, client):
        """Consecutive GET requests should return cached result."""
        resp1 = client.post("/api/amy/briefing")
        resp2 = client.get("/api/amy/briefing")
        assert resp1.json()["briefing_id"] == resp2.json()["briefing_id"]


class TestTemplateBriefing:
    def test_template_with_empty_context(self):
        from app.routers.amy_briefing import _template_briefing
        text = _template_briefing({})
        assert "DAILY BRIEFING" in text
        assert "THREAT ASSESSMENT" in text
        assert "Amy, AI Commander" in text

    def test_template_with_targets(self):
        from app.routers.amy_briefing import _template_briefing
        ctx = {
            "targets": {
                "total": 15,
                "by_alliance": {"friendly": 5, "hostile": 3, "unknown": 7},
            },
        }
        text = _template_briefing(ctx)
        assert "15" in text
        assert "FRIENDLY" in text or "friendly" in text.lower()

    def test_template_with_pod(self):
        from app.routers.amy_briefing import _template_briefing
        ctx = {
            "picture_of_day": {
                "new_targets": 12,
                "total_sightings": 500,
                "correlations": 8,
                "threats": 2,
                "zone_events": 15,
                "threat_level": "YELLOW",
                "sightings_by_source": {"ble": 300, "wifi": 150, "yolo": 50},
            },
        }
        text = _template_briefing(ctx)
        assert "12" in text  # new targets
        assert "YELLOW" in text
