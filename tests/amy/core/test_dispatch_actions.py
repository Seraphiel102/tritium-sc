# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for amy.actions.dispatch — asset selection and dispatch."""

from __future__ import annotations

import math
import pytest

from amy.actions.dispatch import (
    ASSET_CAPABILITIES,
    MIN_DISPATCH_BATTERY,
    MOBILE_ASSET_TYPES,
    DispatchAction,
    dispatch_to_investigate,
    find_nearest_asset,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockTrackedTarget:
    def __init__(
        self,
        target_id: str,
        alliance: str = "friendly",
        position: tuple[float, float] = (0.0, 0.0),
        battery: float = 1.0,
        status: str = "active",
        name: str = "Unit",
        asset_type: str = "rover",
    ):
        self.target_id = target_id
        self.alliance = alliance
        self.position = position
        self.battery = battery
        self.status = status
        self.name = name
        self.asset_type = asset_type


class MockTargetTracker:
    def __init__(self, targets: list | None = None):
        self._targets: list[MockTrackedTarget] = targets or []

    def get_all(self) -> list[MockTrackedTarget]:
        return list(self._targets)

    def get_target(self, target_id: str) -> MockTrackedTarget | None:
        for t in self._targets:
            if t.target_id == target_id:
                return t
        return None

    def get_friendlies(self) -> list[MockTrackedTarget]:
        return [t for t in self._targets if t.alliance == "friendly"]


class MockEventBus:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.published.append((event_type, data or {}))


class MockSimTarget:
    def __init__(self, target_id, name="Unit", asset_type="rover",
                 position=(0, 0), alliance="friendly"):
        self.target_id = target_id
        self.name = name
        self.asset_type = asset_type
        self.position = position
        self.alliance = alliance
        self.waypoints = []
        self._waypoint_index = 0
        self.loop_waypoints = True
        self.status = "idle"


class MockSimEngine:
    def __init__(self, targets=None):
        self._targets = {t.target_id: t for t in (targets or [])}

    def get_target(self, target_id):
        return self._targets.get(target_id)


class MockMQTTBridge:
    def __init__(self):
        self.dispatches: list[tuple[str, float, float]] = []

    def publish_dispatch(self, robot_id, x, y):
        self.dispatches.append((robot_id, x, y))


# ===================================================================
# DispatchAction dataclass
# ===================================================================


class TestDispatchAction:
    @pytest.mark.unit
    def test_to_dict(self):
        action = DispatchAction(
            asset_id="rover-01",
            asset_name="Rover Alpha",
            asset_type="rover",
            target_position=(10.0, 20.0),
            reason="investigate threat",
            priority=4,
        )
        d = action.to_dict()
        assert d["asset_id"] == "rover-01"
        assert d["asset_name"] == "Rover Alpha"
        assert d["target_position"]["x"] == 10.0
        assert d["target_position"]["y"] == 20.0
        assert d["reason"] == "investigate threat"
        assert d["priority"] == 4


# ===================================================================
# find_nearest_asset tests
# ===================================================================


class TestFindNearestAsset:
    @pytest.mark.unit
    def test_returns_nearest_mobile(self):
        targets = [
            MockTrackedTarget("r1", position=(10, 0), asset_type="rover"),
            MockTrackedTarget("r2", position=(5, 0), asset_type="rover"),
            MockTrackedTarget("r3", position=(20, 0), asset_type="rover"),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0))
        assert result is not None
        assert result.target_id == "r2"

    @pytest.mark.unit
    def test_excludes_low_battery(self):
        targets = [
            MockTrackedTarget("r1", position=(1, 0), battery=0.05),
            MockTrackedTarget("r2", position=(10, 0), battery=0.50),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0))
        assert result is not None
        assert result.target_id == "r2"

    @pytest.mark.unit
    def test_excludes_non_active(self):
        targets = [
            MockTrackedTarget("r1", position=(1, 0), status="destroyed"),
            MockTrackedTarget("r2", position=(10, 0), status="active"),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0))
        assert result is not None
        assert result.target_id == "r2"

    @pytest.mark.unit
    def test_excludes_turrets_when_mobile_required(self):
        targets = [
            MockTrackedTarget("t1", position=(1, 0), asset_type="turret"),
            MockTrackedTarget("r1", position=(10, 0), asset_type="rover"),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0), require_mobile=True)
        assert result is not None
        assert result.target_id == "r1"

    @pytest.mark.unit
    def test_includes_turrets_when_not_mobile(self):
        targets = [
            MockTrackedTarget("t1", position=(1, 0), asset_type="turret"),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(
            tracker, (0, 0),
            asset_types={"turret"},
            require_mobile=False,
        )
        assert result is not None
        assert result.target_id == "t1"

    @pytest.mark.unit
    def test_filters_by_asset_type(self):
        targets = [
            MockTrackedTarget("r1", position=(1, 0), asset_type="rover"),
            MockTrackedTarget("d1", position=(5, 0), asset_type="drone"),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0), asset_types={"drone"})
        assert result is not None
        assert result.target_id == "d1"

    @pytest.mark.unit
    def test_excludes_by_id(self):
        targets = [
            MockTrackedTarget("r1", position=(1, 0)),
            MockTrackedTarget("r2", position=(10, 0)),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0), exclude_ids={"r1"})
        assert result is not None
        assert result.target_id == "r2"

    @pytest.mark.unit
    def test_returns_none_when_empty(self):
        tracker = MockTargetTracker([])
        result = find_nearest_asset(tracker, (0, 0))
        assert result is None

    @pytest.mark.unit
    def test_returns_none_when_all_excluded(self):
        targets = [
            MockTrackedTarget("r1", position=(1, 0), battery=0.01),
        ]
        tracker = MockTargetTracker(targets)
        result = find_nearest_asset(tracker, (0, 0))
        assert result is None

    @pytest.mark.unit
    def test_accepts_idle_and_arrived_status(self):
        for status in ("active", "idle", "arrived"):
            targets = [MockTrackedTarget("r1", position=(1, 0), status=status)]
            tracker = MockTargetTracker(targets)
            result = find_nearest_asset(tracker, (0, 0))
            assert result is not None, f"Expected match for status={status}"


# ===================================================================
# dispatch_to_investigate tests
# ===================================================================


class TestDispatchToInvestigate:
    @pytest.mark.unit
    def test_dispatches_via_sim_engine(self):
        sim_target = MockSimTarget("rover-01", position=(0, 0))
        engine = MockSimEngine([sim_target])
        bus = MockEventBus()

        action = dispatch_to_investigate(
            "rover-01", (10.0, 20.0),
            event_bus=bus,
            simulation_engine=engine,
            reason="test dispatch",
        )

        assert action is not None
        assert action.asset_id == "rover-01"
        assert action.target_position == (10.0, 20.0)
        assert sim_target.waypoints == [(10.0, 20.0)]
        assert sim_target.status == "active"
        assert sim_target.loop_waypoints is False

    @pytest.mark.unit
    def test_publishes_to_event_bus(self):
        bus = MockEventBus()
        action = dispatch_to_investigate(
            "rover-01", (10.0, 20.0),
            event_bus=bus,
            reason="test",
        )
        assert action is not None
        assert len(bus.published) == 1
        ev_type, ev_data = bus.published[0]
        assert ev_type == "amy_dispatch"
        assert ev_data["target_id"] == "rover-01"

    @pytest.mark.unit
    def test_publishes_to_mqtt(self):
        mqtt = MockMQTTBridge()
        action = dispatch_to_investigate(
            "rover-01", (10.0, 20.0),
            mqtt_bridge=mqtt,
            reason="test",
        )
        assert action is not None
        assert len(mqtt.dispatches) == 1
        assert mqtt.dispatches[0] == ("rover-01", 10.0, 20.0)

    @pytest.mark.unit
    def test_works_without_engine_or_mqtt(self):
        action = dispatch_to_investigate(
            "rover-01", (5.0, 5.0),
            reason="minimal dispatch",
        )
        assert action is not None
        assert action.reason == "minimal dispatch"


# ===================================================================
# Constants
# ===================================================================


class TestDispatchConstants:
    @pytest.mark.unit
    def test_mobile_types_are_correct(self):
        assert "rover" in MOBILE_ASSET_TYPES
        assert "drone" in MOBILE_ASSET_TYPES
        assert "turret" not in MOBILE_ASSET_TYPES

    @pytest.mark.unit
    def test_capabilities_defined(self):
        assert "camera" in ASSET_CAPABILITIES
        assert "observe" in ASSET_CAPABILITIES["drone"]
        assert "intercept" in ASSET_CAPABILITIES["rover"]
