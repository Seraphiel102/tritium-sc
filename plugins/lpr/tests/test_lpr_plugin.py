# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for LPR (License Plate Recognition) plugin."""

import sys
from pathlib import Path

import pytest

# Ensure plugin directory is importable
_plugins_dir = str(Path(__file__).resolve().parents[2])
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

from lpr.plugin import LPRPlugin, _generate_plate


class TestLPRPluginIdentity:
    """Plugin identity and interface compliance."""

    def test_plugin_id(self):
        p = LPRPlugin()
        assert p.plugin_id == "tritium.lpr"

    def test_plugin_name(self):
        p = LPRPlugin()
        assert p.name == "License Plate Recognition"

    def test_plugin_version(self):
        p = LPRPlugin()
        assert p.version == "0.1.0"

    def test_capabilities(self):
        p = LPRPlugin()
        caps = p.capabilities
        assert "data_source" in caps
        assert "routes" in caps
        assert "background" in caps


class TestWatchlist:
    """Watchlist management tests."""

    def test_add_plate(self):
        p = LPRPlugin()
        entry = p.add_to_watchlist("ABC-1234", reason="Stolen", priority="high")
        assert entry["plate_number"] == "ABC-1234"
        assert entry["reason"] == "Stolen"
        assert entry["priority"] == "high"

    def test_add_normalizes_case(self):
        p = LPRPlugin()
        p.add_to_watchlist("abc-1234")
        assert p.check_watchlist("ABC-1234") is not None

    def test_remove_plate(self):
        p = LPRPlugin()
        p.add_to_watchlist("ABC-1234")
        assert p.remove_from_watchlist("ABC-1234")
        assert p.check_watchlist("ABC-1234") is None

    def test_remove_nonexistent(self):
        p = LPRPlugin()
        assert not p.remove_from_watchlist("NONE-000")

    def test_get_watchlist(self):
        p = LPRPlugin()
        p.add_to_watchlist("AAA-1111")
        p.add_to_watchlist("BBB-2222")
        wl = p.get_watchlist()
        assert len(wl) == 2
        plates = {e["plate_number"] for e in wl}
        assert "AAA-1111" in plates
        assert "BBB-2222" in plates

    def test_check_watchlist_miss(self):
        p = LPRPlugin()
        assert p.check_watchlist("NOTHERE") is None


class TestDetections:
    """Detection recording and search tests."""

    def test_record_detection(self):
        p = LPRPlugin()
        det = p.record_detection("ABC-1234", camera_id="cam1", confidence=0.95)
        assert det["plate_number"] == "ABC-1234"
        assert det["camera_id"] == "cam1"
        assert det["confidence"] == 0.95
        assert det["watchlist_match"] is False

    def test_watchlist_hit(self):
        p = LPRPlugin()
        p.add_to_watchlist("ABC-1234", reason="Stolen", priority="high")
        det = p.record_detection("abc-1234", camera_id="cam1")
        assert det["watchlist_match"] is True
        assert det["watchlist_reason"] == "Stolen"
        assert det["watchlist_priority"] == "high"

    def test_watchlist_hit_count(self):
        p = LPRPlugin()
        p.add_to_watchlist("ABC-1234")
        p.record_detection("ABC-1234")
        p.record_detection("ABC-1234")
        wl = p.check_watchlist("ABC-1234")
        assert wl["hit_count"] == 2

    def test_recent_detections(self):
        p = LPRPlugin()
        for i in range(10):
            p.record_detection(f"PLT-{i:04d}")
        dets = p.get_recent_detections(count=5)
        assert len(dets) == 5

    def test_search_plates(self):
        p = LPRPlugin()
        p.record_detection("ABC-1234")
        p.record_detection("ABC-5678")
        p.record_detection("XYZ-9999")
        results = p.search_plates("ABC")
        assert len(results) == 2

    def test_search_empty(self):
        p = LPRPlugin()
        results = p.search_plates("NOPE")
        assert len(results) == 0

    def test_stats(self):
        p = LPRPlugin()
        p.add_to_watchlist("ABC-1234")
        p.record_detection("ABC-1234")
        p.record_detection("XYZ-5678")
        stats = p.get_stats()
        assert stats["total_detections"] == 2
        assert stats["watchlist_hits"] == 1
        assert stats["unique_plates"] == 2
        assert stats["watchlist_size"] == 1


class TestPlateGeneration:
    """Synthetic plate number generation."""

    def test_generate_plate_format(self):
        for _ in range(20):
            plate = _generate_plate()
            assert isinstance(plate, str)
            assert len(plate) >= 6
            assert "-" in plate

    def test_generate_plates_diverse(self):
        plates = {_generate_plate() for _ in range(50)}
        # Should generate mostly unique plates
        assert len(plates) >= 30
