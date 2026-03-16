# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the edge autonomy plugin."""
import sys
from pathlib import Path

_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from edge_autonomy.plugin import EdgeAutonomyPlugin


class TestEdgeAutonomyPlugin:
    def test_plugin_identity(self):
        p = EdgeAutonomyPlugin()
        assert p.plugin_id == "tritium.edge_autonomy"
        assert p.name == "Edge Autonomy"
        assert p.version == "1.0.0"

    def test_receive_decision(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        decision = p.receive_decision({
            "device_id": "dev-001",
            "decision_type": "alert",
            "trigger": "unknown_ble",
            "confidence": 0.7,
            "target_id": "ble_AA:BB:CC",
        })
        assert decision["decision_id"].startswith("auto_")
        assert decision["sc_override"] == "pending"
        assert p._total_received == 1

    def test_auto_confirm_high_confidence(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        decision = p.receive_decision({
            "device_id": "dev-001",
            "confidence": 0.95,
        })
        assert decision["sc_override"] == "confirmed"
        assert p._total_confirmed == 1

    def test_confirm_decision(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        decision = p.receive_decision({
            "device_id": "dev-001",
            "confidence": 0.5,
        })
        result = p.confirm_decision(
            decision["decision_id"],
            reason="Verified by operator",
            confirmed_by="admin",
        )
        assert result["sc_override"] == "confirmed"
        assert result["override_reason"] == "Verified by operator"

    def test_override_decision(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        decision = p.receive_decision({
            "device_id": "dev-001",
            "confidence": 0.5,
        })
        result = p.override_decision(
            decision["decision_id"],
            reason="False positive",
            overridden_by="admin",
            corrective_action="Whitelist device",
        )
        assert result["sc_override"] == "overridden"
        assert result["corrective_action"] == "Whitelist device"

    def test_confirm_nonexistent(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        assert p.confirm_decision("ghost") is None

    def test_list_decisions_filter(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        p.receive_decision({"device_id": "dev-001", "confidence": 0.5})
        p.receive_decision({"device_id": "dev-002", "confidence": 0.5})
        p.receive_decision({"device_id": "dev-001", "confidence": 0.5})

        all_d = p.list_decisions()
        assert len(all_d) == 3

        dev1 = p.list_decisions(device_id="dev-001")
        assert len(dev1) == 2

        pending = p.list_decisions(status="pending")
        assert len(pending) == 3

    def test_device_accuracy_tracking(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")

        d1 = p.receive_decision({"device_id": "dev-001", "confidence": 0.5})
        d2 = p.receive_decision({"device_id": "dev-001", "confidence": 0.5})
        d3 = p.receive_decision({"device_id": "dev-001", "confidence": 0.5})

        p.confirm_decision(d1["decision_id"])
        p.confirm_decision(d2["decision_id"])
        p.override_decision(d3["decision_id"], reason="false positive")

        stats = p.get_stats()
        dev_stats = stats["device_stats"]["dev-001"]
        assert dev_stats["confirmed"] == 2
        assert dev_stats["overridden"] == 1
        assert dev_stats["accuracy"] == pytest.approx(0.667, abs=0.01)

    def test_stats(self):
        p = EdgeAutonomyPlugin()
        p._logger = __import__("logging").getLogger("test")
        p.receive_decision({"device_id": "dev-001", "confidence": 0.5})
        stats = p.get_stats()
        assert stats["total_received"] == 1
        assert stats["pending_review"] == 1
        assert stats["total_stored"] == 1
