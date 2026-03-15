# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the swarm coordination plugin."""
import sys
from pathlib import Path

# Ensure plugins dir is on path
_plugins_dir = str(Path(__file__).resolve().parent.parent.parent / "plugins")
if _plugins_dir not in sys.path:
    sys.path.insert(0, _plugins_dir)

import pytest
from swarm_coordination.plugin import SwarmUnit, SwarmCoordinationPlugin


class TestSwarmUnit:
    def test_create(self):
        s = SwarmUnit("test-001", "Alpha")
        assert s.swarm_id == "test-001"
        assert s.name == "Alpha"
        assert s.formation_type == "line"
        assert s.command == "hold"

    def test_add_member(self):
        s = SwarmUnit("test-001")
        m = s.add_member("m1", "dev-001", "rover", "lead")
        assert m["member_id"] == "m1"
        assert m["device_id"] == "dev-001"
        assert m["status"] == "active"
        assert len(s.members) == 1

    def test_remove_member(self):
        s = SwarmUnit("test-001")
        s.add_member("m1", "dev-001")
        s.add_member("m2", "dev-002")
        assert len(s.members) == 2
        result = s.remove_member("m1")
        assert result is True
        assert len(s.members) == 1
        assert "m2" in s.members

    def test_remove_nonexistent_member(self):
        s = SwarmUnit("test-001")
        assert s.remove_member("ghost") is False

    def test_compute_formation_offsets_line(self):
        s = SwarmUnit("test-001")
        s.formation_type = "line"
        s.spacing = 5.0
        s.heading = 0.0
        s.add_member("m1")
        s.add_member("m2")
        s.add_member("m3")
        offsets = s.compute_formation_offsets()
        assert len(offsets) == 3
        # Middle unit should be at center
        assert offsets["m2"] == (0.0, 0.0)

    def test_compute_formation_offsets_circle(self):
        s = SwarmUnit("test-001")
        s.formation_type = "circle"
        s.spacing = 5.0
        for i in range(4):
            s.add_member(f"m{i}")
        offsets = s.compute_formation_offsets()
        assert len(offsets) == 4

    def test_compute_formation_offsets_diamond(self):
        s = SwarmUnit("test-001")
        s.formation_type = "diamond"
        s.spacing = 5.0
        for i in range(4):
            s.add_member(f"m{i}")
        offsets = s.compute_formation_offsets()
        assert len(offsets) == 4

    def test_compute_formation_offsets_wedge(self):
        s = SwarmUnit("test-001")
        s.formation_type = "wedge"
        s.spacing = 5.0
        for i in range(5):
            s.add_member(f"m{i}")
        offsets = s.compute_formation_offsets()
        assert len(offsets) == 5
        # Lead at origin
        assert offsets["m0"] == (0.0, 0.0)

    def test_compute_formation_offsets_empty(self):
        s = SwarmUnit("test-001")
        offsets = s.compute_formation_offsets()
        assert len(offsets) == 0

    def test_tick_hold(self):
        s = SwarmUnit("test-001")
        s.add_member("m1")
        s.command = "hold"
        s.center_x = 10.0
        s.center_y = 20.0
        s.tick(0.1)
        # Position should not change on hold
        assert s.center_x == 10.0
        assert s.center_y == 20.0

    def test_tick_advance_to_waypoint(self):
        s = SwarmUnit("test-001")
        s.add_member("m1")
        s.command = "advance"
        s.center_x = 0.0
        s.center_y = 0.0
        s.waypoints = [(100.0, 0.0)]
        s.max_speed = 10.0
        s.tick(1.0)
        # Should have moved toward waypoint
        assert s.center_x > 0.0

    def test_tick_patrol_loops(self):
        s = SwarmUnit("test-001")
        s.add_member("m1")
        s.command = "patrol"
        s.patrol_loop = True
        s.waypoints = [(1.0, 0.0), (2.0, 0.0)]
        s.center_x = 0.5
        s.center_y = 0.0
        s.max_speed = 100.0
        # Tick until reaching first waypoint
        for _ in range(100):
            s.tick(0.1)
        # Should have advanced through waypoints
        assert s.command == "patrol"

    def test_to_dict(self):
        s = SwarmUnit("test-001", "Bravo")
        s.add_member("m1", "dev-001", "drone", "lead")
        d = s.to_dict()
        assert d["swarm_id"] == "test-001"
        assert d["name"] == "Bravo"
        assert d["member_count"] == 1
        assert d["active_members"] == 1
        assert len(d["members"]) == 1
        assert d["members"][0]["asset_type"] == "drone"


class TestSwarmCoordinationPlugin:
    def test_plugin_identity(self):
        p = SwarmCoordinationPlugin()
        assert p.plugin_id == "tritium.swarm_coordination"
        assert p.name == "Swarm Coordination"
        assert p.version == "1.0.0"
        assert "routes" in p.capabilities
        assert "background" in p.capabilities
