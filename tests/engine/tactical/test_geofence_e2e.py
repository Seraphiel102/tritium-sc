# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""End-to-end geofence polygon test — draw → save → engine → events fire."""

import pytest
from engine.tactical.geofence import GeofenceEngine, GeoZone, point_in_polygon


class MockEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_type, data=None):
        self.events.append({"type": event_type, "data": data})


class TestGeofenceE2E:
    """Verify the full geofence flow: create zone, check targets, detect events."""

    def test_polygon_zone_enter_exit(self):
        """Simulate: draw polygon → save → engine checks target → enter/exit detected."""
        bus = MockEventBus()
        engine = GeofenceEngine(event_bus=bus)

        # 1. Draw polygon (simulated frontend action)
        polygon = [
            (10.0, 10.0),
            (10.0, 20.0),
            (20.0, 20.0),
            (20.0, 10.0),
        ]

        # 2. Save zone via API-equivalent action
        zone = GeoZone(
            zone_id="test-zone-1",
            name="Test Restricted Area",
            polygon=polygon,
            zone_type="restricted",
            alert_on_enter=True,
            alert_on_exit=True,
        )
        engine.add_zone(zone)
        assert len(engine.list_zones()) == 1

        # 3. Target starts outside zone
        events = engine.check("ble_aabbccddee", (5.0, 5.0))
        enter_events = [e for e in events if e.event_type == "enter"]
        assert len(enter_events) == 0

        # 4. Target enters zone
        events = engine.check("ble_aabbccddee", (15.0, 15.0))
        enter_events = [e for e in events if e.event_type == "enter"]
        assert len(enter_events) == 1
        assert enter_events[0].zone_id == "test-zone-1"
        assert enter_events[0].zone_name == "Test Restricted Area"

        # Verify EventBus received the enter event
        bus_enters = [e for e in bus.events if e["type"] == "geofence:enter"]
        assert len(bus_enters) == 1
        assert bus_enters[0]["data"]["target_id"] == "ble_aabbccddee"

        # 5. Target stays inside — should get "inside" events, no new "enter"
        events = engine.check("ble_aabbccddee", (12.0, 12.0))
        inside_events = [e for e in events if e.event_type == "inside"]
        assert len(inside_events) == 1
        new_enters = [e for e in events if e.event_type == "enter"]
        assert len(new_enters) == 0

        # 6. Target exits zone
        events = engine.check("ble_aabbccddee", (25.0, 25.0))
        exit_events = [e for e in events if e.event_type == "exit"]
        assert len(exit_events) == 1

        bus_exits = [e for e in bus.events if e["type"] == "geofence:exit"]
        assert len(bus_exits) == 1

    def test_point_in_polygon(self):
        """Basic point-in-polygon ray-casting test."""
        square = [(0, 0), (0, 10), (10, 10), (10, 0)]
        assert point_in_polygon(5, 5, square) is True
        assert point_in_polygon(15, 15, square) is False
        assert point_in_polygon(-1, -1, square) is False

    def test_complex_polygon(self):
        """Test with an L-shaped polygon."""
        l_shape = [
            (0, 0), (0, 20), (10, 20), (10, 10), (20, 10), (20, 0),
        ]
        # Inside the L
        assert point_in_polygon(5, 15, l_shape) is True
        assert point_in_polygon(15, 5, l_shape) is True
        # Outside the L (inside the notch)
        assert point_in_polygon(15, 15, l_shape) is False

    def test_zone_crud(self):
        """Test zone create, list, delete."""
        engine = GeofenceEngine()
        z = GeoZone(
            zone_id="z1",
            name="Zone One",
            polygon=[(0, 0), (0, 10), (10, 10), (10, 0)],
        )
        engine.add_zone(z)
        assert len(engine.list_zones()) == 1

        got = engine.get_zone("z1")
        assert got is not None
        assert got.name == "Zone One"

        engine.remove_zone("z1")
        assert len(engine.list_zones()) == 0

    def test_event_log(self):
        """Test that events are logged and retrievable."""
        engine = GeofenceEngine()
        engine.add_zone(GeoZone(
            zone_id="z1", name="Z1",
            polygon=[(0, 0), (0, 10), (10, 10), (10, 0)],
        ))

        # Enter
        engine.check("t1", (5, 5))
        # Exit
        engine.check("t1", (20, 20))

        all_events = engine.get_events()
        assert len(all_events) == 2

        enter_events = engine.get_events(event_type="enter")
        assert len(enter_events) == 1

        exit_events = engine.get_events(event_type="exit")
        assert len(exit_events) == 1

    def test_multiple_zones(self):
        """Target can be in multiple zones simultaneously."""
        engine = GeofenceEngine()
        engine.add_zone(GeoZone(
            zone_id="z1", name="Zone A",
            polygon=[(0, 0), (0, 20), (20, 20), (20, 0)],
        ))
        engine.add_zone(GeoZone(
            zone_id="z2", name="Zone B",
            polygon=[(10, 10), (10, 30), (30, 30), (30, 10)],
        ))

        # Position (15, 15) is inside both zones
        events = engine.check("t1", (15, 15))
        enter_events = [e for e in events if e.event_type == "enter"]
        assert len(enter_events) == 2

        zones = engine.get_target_zones("t1")
        assert "z1" in zones
        assert "z2" in zones

    def test_disabled_zone_ignored(self):
        """Disabled zones should not trigger events."""
        engine = GeofenceEngine()
        z = GeoZone(
            zone_id="z1", name="Disabled",
            polygon=[(0, 0), (0, 10), (10, 10), (10, 0)],
            enabled=False,
        )
        engine.add_zone(z)
        events = engine.check("t1", (5, 5))
        enter_events = [e for e in events if e.event_type == "enter"]
        assert len(enter_events) == 0
