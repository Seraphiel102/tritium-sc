# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Threat Feeds plugin — feeds, routes, and plugin lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Ensure plugins/ is importable
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from threat_feeds.feeds import (
    ThreatFeedManager,
    ThreatIndicator,
    INDICATOR_TYPES,
    SEED_INDICATORS,
    seed_default_indicators,
)
from threat_feeds.plugin import ThreatFeedPlugin


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEventBus:
    """Minimal EventBus mock."""

    def __init__(self):
        self.published: list[tuple[str, dict]] = []
        self._subscribers: list[queue.Queue] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.published.append((event_type, data or {}))
        msg = {"type": event_type}
        if data is not None:
            msg["data"] = data
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def subscribe(self, _filter=None) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory for the manager."""
    return str(tmp_path / "threat_feeds")


@pytest.fixture
def manager(tmp_data_dir):
    """Fresh ThreatFeedManager with empty store."""
    return ThreatFeedManager(data_dir=tmp_data_dir)


@pytest.fixture
def seeded_manager(manager):
    """ThreatFeedManager pre-loaded with seed indicators."""
    seed_default_indicators(manager)
    return manager


# ===========================================================================
# ThreatIndicator dataclass
# ===========================================================================


class TestThreatIndicator:
    """Tests for the ThreatIndicator dataclass."""

    def test_create_indicator(self):
        ind = ThreatIndicator(
            indicator_type="mac",
            value="DE:AD:BE:EF:00:01",
            threat_level="hostile",
            source="test",
            description="test indicator",
        )
        assert ind.indicator_type == "mac"
        assert ind.value == "DE:AD:BE:EF:00:01"
        assert ind.threat_level == "hostile"

    def test_to_dict(self):
        ind = ThreatIndicator(indicator_type="ssid", value="EvilNet")
        d = ind.to_dict()
        assert d["indicator_type"] == "ssid"
        assert d["value"] == "EvilNet"
        assert "first_seen" in d
        assert "last_seen" in d

    def test_from_dict(self):
        d = {
            "indicator_type": "ip",
            "value": "10.0.0.1",
            "threat_level": "hostile",
            "source": "test",
            "description": "bad ip",
        }
        ind = ThreatIndicator.from_dict(d)
        assert ind.indicator_type == "ip"
        assert ind.value == "10.0.0.1"
        assert ind.threat_level == "hostile"

    def test_from_dict_ignores_extra_keys(self):
        d = {
            "indicator_type": "mac",
            "value": "AA:BB:CC:DD:EE:FF",
            "extra_key": "ignored",
        }
        ind = ThreatIndicator.from_dict(d)
        assert ind.indicator_type == "mac"
        assert not hasattr(ind, "extra_key")

    def test_match_key(self):
        ind = ThreatIndicator(indicator_type="mac", value="aa:bb:cc:dd:ee:ff")
        assert ind.match_key() == "mac:AA:BB:CC:DD:EE:FF"

    def test_match_key_case_insensitive(self):
        ind1 = ThreatIndicator(indicator_type="ssid", value="EvilNet")
        ind2 = ThreatIndicator(indicator_type="ssid", value="EVILNET")
        assert ind1.match_key() == ind2.match_key()


# ===========================================================================
# ThreatFeedManager — CRUD
# ===========================================================================


class TestThreatFeedManagerCRUD:
    """Tests for ThreatFeedManager add/remove/check/get_all."""

    def test_add_and_check(self, manager):
        ind = ThreatIndicator(
            indicator_type="mac",
            value="DE:AD:BE:EF:00:01",
            threat_level="hostile",
        )
        manager.add_indicator(ind)
        result = manager.check("mac", "DE:AD:BE:EF:00:01")
        assert result is not None
        assert result.threat_level == "hostile"

    def test_check_case_insensitive(self, manager):
        ind = ThreatIndicator(indicator_type="mac", value="AA:BB:CC:DD:EE:FF")
        manager.add_indicator(ind)
        # Check with lowercase
        result = manager.check("mac", "aa:bb:cc:dd:ee:ff")
        assert result is not None

    def test_check_miss(self, manager):
        result = manager.check("mac", "00:00:00:00:00:00")
        assert result is None

    def test_check_mac_convenience(self, manager):
        ind = ThreatIndicator(indicator_type="mac", value="DE:AD:BE:EF:00:01")
        manager.add_indicator(ind)
        assert manager.check_mac("DE:AD:BE:EF:00:01") is not None

    def test_check_ssid_convenience(self, manager):
        ind = ThreatIndicator(indicator_type="ssid", value="EvilNet")
        manager.add_indicator(ind)
        assert manager.check_ssid("EvilNet") is not None
        assert manager.check_ssid("GoodNet") is None

    def test_check_ip_convenience(self, manager):
        ind = ThreatIndicator(indicator_type="ip", value="10.0.0.1")
        manager.add_indicator(ind)
        assert manager.check_ip("10.0.0.1") is not None

    def test_remove_indicator(self, manager):
        ind = ThreatIndicator(indicator_type="mac", value="DE:AD:BE:EF:00:01")
        manager.add_indicator(ind)
        assert manager.remove_indicator("mac", "DE:AD:BE:EF:00:01") is True
        assert manager.check_mac("DE:AD:BE:EF:00:01") is None

    def test_remove_nonexistent(self, manager):
        assert manager.remove_indicator("mac", "00:00:00:00:00:00") is False

    def test_get_all(self, manager):
        manager.add_indicator(ThreatIndicator(indicator_type="mac", value="AA:AA:AA:AA:AA:AA"))
        manager.add_indicator(ThreatIndicator(indicator_type="ssid", value="BadNet"))
        manager.add_indicator(ThreatIndicator(indicator_type="ip", value="1.2.3.4"))
        assert len(manager.get_all()) == 3

    def test_get_all_filtered(self, manager):
        manager.add_indicator(ThreatIndicator(indicator_type="mac", value="AA:AA:AA:AA:AA:AA"))
        manager.add_indicator(ThreatIndicator(indicator_type="ssid", value="BadNet"))
        macs = manager.get_all(indicator_type="mac")
        assert len(macs) == 1
        assert macs[0].indicator_type == "mac"

    def test_count(self, manager):
        assert manager.count == 0
        manager.add_indicator(ThreatIndicator(indicator_type="mac", value="AA:AA:AA:AA:AA:AA"))
        assert manager.count == 1

    def test_invalid_type_raises(self, manager):
        ind = ThreatIndicator(indicator_type="invalid_type", value="test")
        with pytest.raises(ValueError, match="Invalid indicator_type"):
            manager.add_indicator(ind)

    def test_update_preserves_first_seen(self, manager):
        ind1 = ThreatIndicator(
            indicator_type="mac",
            value="AA:BB:CC:DD:EE:FF",
            first_seen=1000.0,
        )
        manager.add_indicator(ind1)
        ind2 = ThreatIndicator(
            indicator_type="mac",
            value="AA:BB:CC:DD:EE:FF",
            threat_level="hostile",
        )
        manager.add_indicator(ind2)
        result = manager.check_mac("AA:BB:CC:DD:EE:FF")
        assert result.first_seen == 1000.0
        assert result.threat_level == "hostile"


# ===========================================================================
# ThreatFeedManager — Persistence
# ===========================================================================


class TestThreatFeedManagerPersistence:
    """Tests for JSON persistence."""

    def test_persist_and_reload(self, tmp_data_dir):
        mgr1 = ThreatFeedManager(data_dir=tmp_data_dir)
        mgr1.add_indicator(ThreatIndicator(
            indicator_type="mac", value="DE:AD:BE:EF:00:01",
            threat_level="hostile", source="test",
        ))
        assert mgr1.count == 1

        # Create new manager from same directory — should load persisted data
        mgr2 = ThreatFeedManager(data_dir=tmp_data_dir)
        assert mgr2.count == 1
        assert mgr2.check_mac("DE:AD:BE:EF:00:01") is not None

    def test_file_created(self, tmp_data_dir):
        mgr = ThreatFeedManager(data_dir=tmp_data_dir)
        mgr.add_indicator(ThreatIndicator(indicator_type="mac", value="AA:BB:CC:DD:EE:FF"))
        path = os.path.join(tmp_data_dir, "indicators.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1


# ===========================================================================
# ThreatFeedManager — Bulk Import
# ===========================================================================


class TestThreatFeedManagerImport:
    """Tests for bulk import from JSON/CSV."""

    def test_import_json_file(self, manager, tmp_path):
        data = [
            {"indicator_type": "mac", "value": "11:22:33:44:55:66",
             "threat_level": "hostile", "source": "test"},
            {"indicator_type": "ssid", "value": "BadSSID",
             "threat_level": "suspicious", "source": "test"},
        ]
        file_path = str(tmp_path / "indicators.json")
        with open(file_path, "w") as f:
            json.dump(data, f)

        count = manager.load_indicators(file_path)
        assert count == 2
        assert manager.check_mac("11:22:33:44:55:66") is not None
        assert manager.check_ssid("BadSSID") is not None

    def test_import_csv_file(self, manager, tmp_path):
        csv_content = (
            "indicator_type,value,threat_level,source,description\n"
            "mac,AA:BB:CC:DD:EE:FF,hostile,test,bad mac\n"
            "ssid,EvilWifi,suspicious,test,evil wifi\n"
        )
        file_path = str(tmp_path / "indicators.csv")
        with open(file_path, "w") as f:
            f.write(csv_content)

        count = manager.load_indicators(file_path)
        assert count == 2

    def test_import_json_content(self, manager):
        content = json.dumps([
            {"indicator_type": "ip", "value": "10.0.0.1",
             "threat_level": "hostile"},
        ])
        count = manager.load_indicators_from_content(content, format="json")
        assert count == 1
        assert manager.check_ip("10.0.0.1") is not None

    def test_import_csv_content(self, manager):
        content = (
            "indicator_type,value,threat_level,source,description\n"
            "mac,FF:FF:FF:FF:FF:FF,hostile,test,broadcast mac\n"
        )
        count = manager.load_indicators_from_content(content, format="csv")
        assert count == 1

    def test_import_missing_file(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.load_indicators("/nonexistent/file.json")

    def test_import_skips_invalid(self, manager):
        content = json.dumps([
            {"indicator_type": "mac", "value": "AA:BB:CC:DD:EE:FF"},
            {"indicator_type": "invalid", "value": "skip_me"},
            {"indicator_type": "ssid", "value": "GoodEntry"},
        ])
        count = manager.load_indicators_from_content(content)
        assert count == 2  # invalid one skipped


# ===========================================================================
# Seed indicators
# ===========================================================================


class TestSeedIndicators:
    """Tests for seed data."""

    def test_seed_count(self):
        assert len(SEED_INDICATORS) == 10

    def test_seed_types(self):
        types = {s["indicator_type"] for s in SEED_INDICATORS}
        assert "mac" in types
        assert "ssid" in types

    def test_seed_default_indicators(self, manager):
        count = seed_default_indicators(manager)
        assert count == 10
        assert manager.count == 10

    def test_seed_idempotent(self, manager):
        seed_default_indicators(manager)
        count2 = seed_default_indicators(manager)
        assert count2 == 0  # All already present
        assert manager.count == 10


# ===========================================================================
# Enrichment provider
# ===========================================================================


class TestEnrichmentProvider:
    """Tests for the enrichment pipeline integration."""

    @pytest.mark.asyncio
    async def test_enrichment_match_mac(self, seeded_manager):
        result = await seeded_manager.enrichment_provider(
            "target_1", {"mac": "DE:AD:BE:EF:00:01"}
        )
        assert result is not None
        assert result.provider == "threat_feed"
        assert result.enrichment_type == "threat_match"
        assert result.data["threat_level"] == "hostile"

    @pytest.mark.asyncio
    async def test_enrichment_match_ssid(self, seeded_manager):
        result = await seeded_manager.enrichment_provider(
            "target_2", {"ssid": "FreeWiFi-EVIL"}
        )
        assert result is not None
        assert result.data["indicator_type"] == "ssid"

    @pytest.mark.asyncio
    async def test_enrichment_no_match(self, seeded_manager):
        result = await seeded_manager.enrichment_provider(
            "target_3", {"mac": "00:00:00:00:00:00"}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_enrichment_empty_identifiers(self, seeded_manager):
        result = await seeded_manager.enrichment_provider("target_4", {})
        assert result is None


# ===========================================================================
# ThreatFeedPlugin lifecycle
# ===========================================================================


class TestThreatFeedPlugin:
    """Tests for plugin configure/start/stop cycle."""

    def test_plugin_identity(self):
        plugin = ThreatFeedPlugin()
        assert plugin.plugin_id == "tritium.threat-feeds"
        assert plugin.name == "Threat Feeds"
        assert plugin.version == "1.0.0"
        assert "routes" in plugin.capabilities
        assert "data_source" in plugin.capabilities

    def test_plugin_configure_and_start(self, tmp_path):
        from engine.plugins.base import PluginContext

        plugin = ThreatFeedPlugin()
        bus = MockEventBus()

        ctx = PluginContext(
            event_bus=bus,
            target_tracker=None,
            simulation_engine=None,
            settings={},
            app=None,  # No FastAPI app in tests
            logger=None,
            plugin_manager=None,
        )

        # Override data dir via monkeypatch of os.getcwd
        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            plugin.configure(ctx)
            assert plugin.manager is not None
            assert plugin.manager.count == 10  # seeded

            plugin.start()
            assert plugin.healthy is True

            plugin.stop()
            assert plugin.healthy is False
        finally:
            os.chdir(original_cwd)

    def test_plugin_event_check_ble(self, tmp_path):
        """Plugin detects threat indicator match in BLE event."""
        from engine.plugins.base import PluginContext

        plugin = ThreatFeedPlugin()
        bus = MockEventBus()

        ctx = PluginContext(
            event_bus=bus,
            target_tracker=None,
            simulation_engine=None,
            settings={},
            app=None,
            logger=None,
            plugin_manager=None,
        )

        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            plugin.configure(ctx)
            plugin.start()

            # Simulate a BLE event with a known-bad MAC
            event = {
                "type": "ble:new_device",
                "data": {
                    "devices": [{"mac": "DE:AD:BE:EF:00:01", "name": "Evil"}],
                },
            }
            plugin._handle_event(event)

            # Check that an alert was published
            alerts = [
                (t, d) for t, d in bus.published
                if t == "threat:indicator_match"
            ]
            assert len(alerts) == 1
            alert_data = alerts[0][1]
            assert alert_data["indicator"]["threat_level"] == "hostile"
        finally:
            os.chdir(original_cwd)

    def test_plugin_event_check_wifi(self, tmp_path):
        """Plugin detects threat indicator match in WiFi event."""
        from engine.plugins.base import PluginContext

        plugin = ThreatFeedPlugin()
        bus = MockEventBus()

        ctx = PluginContext(
            event_bus=bus,
            target_tracker=None,
            simulation_engine=None,
            settings={},
            app=None,
            logger=None,
            plugin_manager=None,
        )

        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            plugin.configure(ctx)
            plugin.start()

            event = {
                "type": "edge:wifi_update",
                "data": {
                    "networks": [{"ssid": "WiFi-Pineapple", "bssid": "AA:BB:CC:DD:EE:FF"}],
                },
            }
            plugin._handle_event(event)

            alerts = [
                (t, d) for t, d in bus.published
                if t == "threat:indicator_match"
            ]
            assert len(alerts) == 1
        finally:
            os.chdir(original_cwd)

    def test_plugin_no_alert_on_clean_device(self, tmp_path):
        """No alert for devices not in the threat feed."""
        from engine.plugins.base import PluginContext

        plugin = ThreatFeedPlugin()
        bus = MockEventBus()

        ctx = PluginContext(
            event_bus=bus,
            target_tracker=None,
            simulation_engine=None,
            settings={},
            app=None,
            logger=None,
            plugin_manager=None,
        )

        original_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            plugin.configure(ctx)

            event = {
                "type": "ble:new_device",
                "data": {
                    "devices": [{"mac": "00:11:22:33:44:55", "name": "Good"}],
                },
            }
            plugin._handle_event(event)

            alerts = [
                (t, d) for t, d in bus.published
                if t == "threat:indicator_match"
            ]
            assert len(alerts) == 0
        finally:
            os.chdir(original_cwd)


# ===========================================================================
# Routes (unit-level via TestClient)
# ===========================================================================


class TestThreatFeedRoutes:
    """Tests for the /api/threats/* REST endpoints."""

    @pytest.fixture
    def client(self, tmp_data_dir):
        """FastAPI TestClient with threat feed routes mounted."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from threat_feeds.routes import create_router

        mgr = ThreatFeedManager(data_dir=tmp_data_dir)
        seed_default_indicators(mgr)

        app = FastAPI()
        router = create_router(mgr)
        app.include_router(router)
        return TestClient(app)

    def test_list_all(self, client):
        resp = client.get("/api/threats/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 10

    def test_list_filtered(self, client):
        resp = client.get("/api/threats/?indicator_type=mac")
        assert resp.status_code == 200
        data = resp.json()
        assert all(i["indicator_type"] == "mac" for i in data["indicators"])

    def test_list_invalid_type(self, client):
        resp = client.get("/api/threats/?indicator_type=bogus")
        assert resp.status_code == 400

    def test_add_indicator(self, client):
        resp = client.post("/api/threats/", json={
            "indicator_type": "ip",
            "value": "192.168.1.100",
            "threat_level": "hostile",
            "source": "test",
            "description": "test ip",
        })
        assert resp.status_code == 200
        assert resp.json()["added"] is True

    def test_add_invalid_type(self, client):
        resp = client.post("/api/threats/", json={
            "indicator_type": "bogus",
            "value": "test",
        })
        assert resp.status_code == 400

    def test_remove_indicator(self, client):
        resp = client.delete("/api/threats/mac/DE:AD:BE:EF:00:01")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

    def test_remove_nonexistent(self, client):
        resp = client.delete("/api/threats/mac/00:00:00:00:00:00")
        assert resp.status_code == 404

    def test_check_match(self, client):
        resp = client.post("/api/threats/check", json={
            "indicator_type": "mac",
            "value": "DE:AD:BE:EF:00:01",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["match"] is True
        assert data["indicator"]["threat_level"] == "hostile"

    def test_check_no_match(self, client):
        resp = client.post("/api/threats/check", json={
            "indicator_type": "mac",
            "value": "00:00:00:00:00:00",
        })
        assert resp.status_code == 200
        assert resp.json()["match"] is False

    def test_check_invalid_type(self, client):
        resp = client.post("/api/threats/check", json={
            "indicator_type": "bogus",
            "value": "test",
        })
        assert resp.status_code == 400

    def test_import_json(self, client):
        content = json.dumps([
            {"indicator_type": "ip", "value": "1.2.3.4", "threat_level": "hostile"},
        ])
        resp = client.post("/api/threats/import", json={
            "content": content,
            "format": "json",
        })
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1

    def test_import_csv(self, client):
        csv_content = (
            "indicator_type,value,threat_level,source,description\n"
            "mac,FF:FF:FF:FF:FF:FF,hostile,test,broadcast\n"
        )
        resp = client.post("/api/threats/import", json={
            "content": csv_content,
            "format": "csv",
        })
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1

    def test_stats(self, client):
        resp = client.get("/api/threats/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert "by_type" in data
        assert "by_level" in data
        assert "by_source" in data
