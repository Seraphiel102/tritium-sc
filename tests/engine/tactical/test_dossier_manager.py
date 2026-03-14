# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for DossierManager — bridges TargetTracker and DossierStore."""

import tempfile
import time

import pytest

from tritium_lib.store.dossiers import DossierStore

from src.engine.comms.event_bus import EventBus
from src.engine.tactical.dossier_manager import DossierManager
from src.engine.tactical.target_tracker import TargetTracker, TrackedTarget


def _make_store(tmp_path=None):
    """Create a temporary DossierStore."""
    if tmp_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return DossierStore(tmp.name)
    return DossierStore(tmp_path / "test_dossiers.db")


def _make_tracker_with(*targets: TrackedTarget) -> TargetTracker:
    """Create a TargetTracker pre-loaded with targets."""
    tracker = TargetTracker()
    with tracker._lock:
        for t in targets:
            tracker._targets[t.target_id] = t
    return tracker


class TestDossierManagerCRUD:
    """Basic create, read, find-or-create operations."""

    @pytest.mark.unit
    def test_find_or_create_creates_new(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("test_target_1", name="Test Target")
        assert did
        dossier = mgr.get_dossier(did)
        assert dossier is not None
        assert dossier["name"] == "Test Target"
        store.close()

    @pytest.mark.unit
    def test_find_or_create_returns_existing(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1", name="Alpha")
        did2 = mgr.find_or_create_for_target("t1", name="Should Not Change")
        assert did1 == did2
        store.close()

    @pytest.mark.unit
    def test_find_or_create_ble_by_mac(self):
        """BLE targets should be found by MAC identifier lookup."""
        store = _make_store()
        mgr = DossierManager(store=store)
        # Create dossier with MAC identifier
        did1 = mgr.find_or_create_for_target(
            "ble_aabbccddeeff",
            name="Phone",
            identifiers={"mac": "AA:BB:CC:DD:EE:FF"},
        )
        # Second lookup with same MAC-based target_id should find it
        did2 = mgr.find_or_create_for_target("ble_aabbccddeeff")
        assert did1 == did2
        store.close()

    @pytest.mark.unit
    def test_get_dossier_for_target(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("target_x", name="X")

        result = mgr.get_dossier_for_target("target_x")
        assert result is not None
        assert result["dossier_id"] == did
        store.close()

    @pytest.mark.unit
    def test_get_dossier_for_unknown_target(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        result = mgr.get_dossier_for_target("nonexistent")
        assert result is None
        store.close()


class TestSignalsAndEnrichments:
    """Adding signals and enrichments through the manager."""

    @pytest.mark.unit
    def test_add_signal(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        sig_id = mgr.add_signal_to_target(
            "t1", source="ble", signal_type="mac_sighting",
            data={"mac": "AA:BB:CC:DD:EE:FF"}, confidence=0.8,
        )
        assert sig_id is not None

        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["signals"]) == 1
        assert dossier["signals"][0]["source"] == "ble"
        store.close()

    @pytest.mark.unit
    def test_add_signal_no_dossier(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        result = mgr.add_signal_to_target("ghost", "ble", "sighting")
        assert result is None
        store.close()

    @pytest.mark.unit
    def test_add_enrichment(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        eid = mgr.add_enrichment_to_target(
            "t1", provider="oui", enrichment_type="manufacturer",
            data={"manufacturer": "Apple"},
        )
        assert eid is not None

        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["enrichments"]) == 1
        assert dossier["enrichments"][0]["provider"] == "oui"
        store.close()


class TestTagsAndNotes:
    """Tag and note management."""

    @pytest.mark.unit
    def test_add_tag(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        assert mgr.add_tag(did, "suspicious") is True
        dossier = mgr.get_dossier(did)
        assert "suspicious" in dossier["tags"]
        store.close()

    @pytest.mark.unit
    def test_add_tag_deduplication(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        mgr.add_tag(did, "ble")
        mgr.add_tag(did, "ble")
        dossier = mgr.get_dossier(did)
        assert dossier["tags"].count("ble") == 1
        store.close()

    @pytest.mark.unit
    def test_add_tag_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        assert mgr.add_tag("fake_id", "tag") is False
        store.close()

    @pytest.mark.unit
    def test_add_note(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did = mgr.find_or_create_for_target("t1")
        assert mgr.add_note(did, "First seen near gate") is True
        dossier = mgr.get_dossier(did)
        assert "First seen near gate" in dossier["notes"]
        store.close()

    @pytest.mark.unit
    def test_add_note_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        assert mgr.add_note("fake_id", "note") is False
        store.close()


class TestMerge:
    """Dossier merge operations."""

    @pytest.mark.unit
    def test_merge_success(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1", name="Alpha", tags=["ble"])
        did2 = mgr.find_or_create_for_target("t2", name="Beta", tags=["yolo"])

        # Add signals to both
        mgr.add_signal_to_target("t1", "ble", "sighting", confidence=0.5)
        mgr.add_signal_to_target("t2", "yolo", "detection", confidence=0.7)

        result = mgr.merge(did1, did2)
        assert result is True

        # Primary should have both signals
        dossier = mgr.get_dossier(did1)
        assert dossier is not None
        assert len(dossier["signals"]) == 2

        # Secondary should be gone
        assert mgr.get_dossier(did2) is None

        # Target t2 should now map to primary dossier
        assert mgr.get_dossier_for_target("t2")["dossier_id"] == did1
        store.close()

    @pytest.mark.unit
    def test_merge_nonexistent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        did1 = mgr.find_or_create_for_target("t1")
        assert mgr.merge(did1, "fake_id") is False
        store.close()


class TestSearch:
    """Full-text search."""

    @pytest.mark.unit
    def test_search_by_name(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1", name="iPhone Pro Max")
        mgr.find_or_create_for_target("t2", name="Android Phone")

        results = mgr.search("iPhone")
        assert len(results) >= 1
        assert any("iPhone" in r.get("name", "") for r in results)
        store.close()

    @pytest.mark.unit
    def test_search_empty_query(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        results = mgr.search("")
        assert results == []
        store.close()


class TestListing:
    """List and pagination."""

    @pytest.mark.unit
    def test_list_dossiers(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        for i in range(5):
            mgr.find_or_create_for_target(f"t{i}", name=f"Target {i}")

        result = mgr.list_dossiers(limit=3)
        assert len(result) == 3
        store.close()

    @pytest.mark.unit
    def test_list_with_offset(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        for i in range(5):
            mgr.find_or_create_for_target(f"t{i}", name=f"Target {i}")

        page1 = mgr.list_dossiers(limit=3, offset=0)
        page2 = mgr.list_dossiers(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

        # No overlap
        ids1 = {d["dossier_id"] for d in page1}
        ids2 = {d["dossier_id"] for d in page2}
        assert ids1.isdisjoint(ids2)
        store.close()

    @pytest.mark.unit
    def test_get_all_active(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1", name="Recent")
        result = mgr.get_all_active_dossiers()
        assert len(result) >= 1
        store.close()


class TestEventHandling:
    """Event-driven dossier creation via EventBus."""

    @pytest.mark.unit
    def test_handle_ble_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_ble_device({
            "mac": "AA:BB:CC:DD:EE:FF",
            "name": "iPhone",
            "rssi": -50,
        })
        dossier = mgr.get_dossier_for_target("ble_aabbccddeeff")
        assert dossier is not None
        assert dossier["name"] == "iPhone"
        assert len(dossier["signals"]) >= 1
        store.close()

    @pytest.mark.unit
    def test_handle_ble_event_no_mac(self):
        """BLE event without MAC should be ignored."""
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_ble_device({"name": "noMAC"})
        assert len(store.get_recent()) == 0
        store.close()

    @pytest.mark.unit
    def test_handle_detection_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_detection({
            "detections": [
                {"class_name": "person", "confidence": 0.85, "target_id": "det_person_1"},
            ],
        })
        dossier = mgr.get_dossier_for_target("det_person_1")
        assert dossier is not None
        assert len(dossier["signals"]) >= 1
        store.close()

    @pytest.mark.unit
    def test_handle_detection_low_confidence_ignored(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr._handle_detection({
            "detections": [
                {"class_name": "person", "confidence": 0.2, "target_id": "det_low"},
            ],
        })
        result = mgr.get_dossier_for_target("det_low")
        assert result is None
        store.close()

    @pytest.mark.unit
    def test_handle_correlation_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        # Pre-create both targets
        mgr.find_or_create_for_target("ble_abc", name="BLE Device")
        mgr.find_or_create_for_target("det_person_1", name="Person")

        mgr._handle_correlation({
            "primary_id": "ble_abc",
            "secondary_id": "det_person_1",
            "confidence": 0.8,
            "reason": "ble+yolo within 3.0 units",
        })

        # Should have merged — only primary dossier remains
        primary = mgr.get_dossier_for_target("ble_abc")
        assert primary is not None
        # Secondary should now point to primary
        secondary = mgr.get_dossier_for_target("det_person_1")
        assert secondary is not None
        assert secondary["dossier_id"] == primary["dossier_id"]
        store.close()

    @pytest.mark.unit
    def test_handle_enrichment_event(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.find_or_create_for_target("t1")
        mgr._handle_enrichment({
            "target_id": "t1",
            "results": [
                {
                    "provider": "oui_lookup",
                    "enrichment_type": "manufacturer",
                    "data": {"manufacturer": "Apple"},
                },
            ],
        })
        dossier = mgr.get_dossier_for_target("t1")
        assert len(dossier["enrichments"]) == 1
        assert dossier["enrichments"][0]["provider"] == "oui_lookup"
        store.close()


class TestLifecycle:
    """Start/stop lifecycle."""

    @pytest.mark.unit
    def test_start_stop_no_event_bus(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.start()
        assert mgr._running is True
        assert mgr._flush_thread is not None
        assert mgr._listener_thread is None  # no event bus
        mgr.stop()
        assert mgr._running is False
        store.close()

    @pytest.mark.unit
    def test_start_stop_with_event_bus(self):
        store = _make_store()
        bus = EventBus()
        mgr = DossierManager(store=store, event_bus=bus, flush_interval=0.5)
        mgr.start()
        assert mgr._running is True
        assert mgr._listener_thread is not None
        assert mgr._flush_thread is not None
        mgr.stop()
        assert mgr._running is False
        store.close()

    @pytest.mark.unit
    def test_start_idempotent(self):
        store = _make_store()
        mgr = DossierManager(store=store)
        mgr.start()
        thread = mgr._flush_thread
        mgr.start()  # should not create new thread
        assert mgr._flush_thread is thread
        mgr.stop()
        store.close()

    @pytest.mark.unit
    def test_event_bus_integration(self):
        """Events published to EventBus should create dossiers."""
        store = _make_store()
        bus = EventBus()
        mgr = DossierManager(store=store, event_bus=bus, flush_interval=60)
        mgr.start()

        # Publish a BLE event
        bus.publish("ble:new_device", {
            "mac": "11:22:33:44:55:66",
            "name": "TestDevice",
            "rssi": -60,
        })

        # Give the listener thread time to process
        time.sleep(0.5)

        dossier = mgr.get_dossier_for_target("ble_112233445566")
        assert dossier is not None
        assert dossier["name"] == "TestDevice"

        mgr.stop()
        store.close()


class TestDossierStoreUpdateJsonField:
    """Tests for the _update_json_field helper on DossierStore."""

    @pytest.mark.unit
    def test_update_tags(self):
        store = _make_store()
        did = store.create_dossier("Test", tags=["initial"])
        store._update_json_field(did, "tags", ["initial", "new_tag"])
        dossier = store.get_dossier(did)
        assert "new_tag" in dossier["tags"]
        store.close()

    @pytest.mark.unit
    def test_update_notes(self):
        store = _make_store()
        did = store.create_dossier("Test")
        store._update_json_field(did, "notes", ["A note"])
        dossier = store.get_dossier(did)
        assert "A note" in dossier["notes"]
        store.close()

    @pytest.mark.unit
    def test_update_invalid_field_raises(self):
        store = _make_store()
        did = store.create_dossier("Test")
        with pytest.raises(ValueError):
            store._update_json_field(did, "name", "evil")
        store.close()

    @pytest.mark.unit
    def test_update_nonexistent_dossier(self):
        store = _make_store()
        result = store._update_json_field("fake_id", "tags", ["x"])
        assert result is False
        store.close()
