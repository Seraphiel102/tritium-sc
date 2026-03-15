# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""SwarmCoordinationPlugin — manage multi-robot formations and waypoints.

Coordinates groups of robots/drones into tactical formations. Assigns
waypoints per unit, maintains formation geometry, handles unit loss
gracefully by reassigning roles and closing gaps.

Uses SwarmCommand/SwarmFormation/SwarmStatus models from tritium-lib.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("swarm_coordination")

_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "swarm"


class SwarmUnit:
    """Runtime state for a single swarm."""

    def __init__(self, swarm_id: str, name: str = "") -> None:
        self.swarm_id = swarm_id
        self.name = name or f"Swarm-{swarm_id[:8]}"
        self.formation_type: str = "line"
        self.heading: float = 0.0
        self.spacing: float = 5.0
        self.center_x: float = 0.0
        self.center_y: float = 0.0
        self.members: dict[str, dict] = {}  # member_id -> member state
        self.waypoints: list[tuple[float, float]] = []
        self.current_waypoint_idx: int = 0
        self.command: str = "hold"
        self.max_speed: float = 2.0
        self.patrol_loop: bool = True
        self.created_at: float = time.time()

    def add_member(self, member_id: str, device_id: str = "",
                   asset_type: str = "rover", role: str = "support") -> dict:
        """Add a member to the swarm."""
        member = {
            "member_id": member_id,
            "device_id": device_id,
            "asset_type": asset_type,
            "role": role,
            "status": "active",
            "position_x": self.center_x,
            "position_y": self.center_y,
            "heading": self.heading,
            "battery": 1.0,
            "speed": 0.0,
            "last_seen": time.time(),
        }
        self.members[member_id] = member
        return member

    def remove_member(self, member_id: str) -> bool:
        """Remove a member; reassign roles to close gaps."""
        if member_id not in self.members:
            return False
        del self.members[member_id]
        self._reassign_roles()
        return True

    def _reassign_roles(self) -> None:
        """Reassign roles after unit loss to maintain formation integrity."""
        roles = ["lead", "flank_left", "flank_right", "rear", "scout", "support"]
        members = list(self.members.values())
        for i, m in enumerate(members):
            m["role"] = roles[i % len(roles)]

    def compute_formation_offsets(self) -> dict[str, tuple[float, float]]:
        """Compute position offsets for each member based on formation type."""
        member_ids = list(self.members.keys())
        n = len(member_ids)
        if n == 0:
            return {}

        offsets: dict[str, tuple[float, float]] = {}
        rad = math.radians(self.heading)
        cos_h = math.cos(rad)
        sin_h = math.sin(rad)

        if self.formation_type == "line":
            for i, mid in enumerate(member_ids):
                offset = (i - (n - 1) / 2.0) * self.spacing
                ox = -offset * sin_h
                oy = offset * cos_h
                offsets[mid] = (round(ox, 2), round(oy, 2))

        elif self.formation_type == "wedge":
            offsets[member_ids[0]] = (0.0, 0.0)
            for i, mid in enumerate(member_ids[1:], 1):
                side = 1 if i % 2 == 1 else -1
                row = (i + 1) // 2
                ox = -row * self.spacing * cos_h + side * row * self.spacing * sin_h * 0.5
                oy = -row * self.spacing * sin_h - side * row * self.spacing * cos_h * 0.5
                offsets[mid] = (round(ox, 2), round(oy, 2))

        elif self.formation_type == "circle":
            radius = self.spacing * max(1, n) / (2 * math.pi) if n > 1 else 0
            for i, mid in enumerate(member_ids):
                angle = 2 * math.pi * i / n
                ox = radius * math.cos(angle)
                oy = radius * math.sin(angle)
                offsets[mid] = (round(ox, 2), round(oy, 2))

        elif self.formation_type == "diamond":
            positions = [
                (self.spacing, 0),
                (0, -self.spacing),
                (0, self.spacing),
                (-self.spacing, 0),
            ]
            for i, mid in enumerate(member_ids):
                if i < len(positions):
                    fx, fy = positions[i]
                else:
                    fx = -self.spacing * (1 + (i - 3))
                    fy = 0
                ox = fx * cos_h - fy * sin_h
                oy = fx * sin_h + fy * cos_h
                offsets[mid] = (round(ox, 2), round(oy, 2))

        else:
            # Column fallback
            for i, mid in enumerate(member_ids):
                dist = -i * self.spacing
                ox = dist * cos_h
                oy = dist * sin_h
                offsets[mid] = (round(ox, 2), round(oy, 2))

        return offsets

    def tick(self, dt: float = 0.1) -> None:
        """Advance swarm simulation by dt seconds."""
        if self.command == "hold" or not self.members:
            return

        if self.command in ("advance", "patrol") and self.waypoints:
            if self.current_waypoint_idx < len(self.waypoints):
                wx, wy = self.waypoints[self.current_waypoint_idx]
                dx = wx - self.center_x
                dy = wy - self.center_y
                dist = math.sqrt(dx * dx + dy * dy)

                if dist < 1.0:
                    # Reached waypoint
                    self.current_waypoint_idx += 1
                    if self.current_waypoint_idx >= len(self.waypoints):
                        if self.command == "patrol" and self.patrol_loop:
                            self.current_waypoint_idx = 0
                        else:
                            self.command = "hold"
                            return
                else:
                    # Move toward waypoint
                    speed = min(self.max_speed, dist / dt)
                    move = speed * dt
                    self.center_x += (dx / dist) * move
                    self.center_y += (dy / dist) * move
                    self.heading = math.degrees(math.atan2(dy, dx))

        # Update member positions based on formation offsets
        offsets = self.compute_formation_offsets()
        for mid, (ox, oy) in offsets.items():
            if mid in self.members:
                self.members[mid]["position_x"] = self.center_x + ox
                self.members[mid]["position_y"] = self.center_y + oy
                self.members[mid]["heading"] = self.heading

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "swarm_id": self.swarm_id,
            "name": self.name,
            "formation_type": self.formation_type,
            "heading": self.heading,
            "spacing": self.spacing,
            "center_x": self.center_x,
            "center_y": self.center_y,
            "members": list(self.members.values()),
            "member_count": len(self.members),
            "active_members": sum(
                1 for m in self.members.values() if m["status"] == "active"
            ),
            "waypoints": self.waypoints,
            "current_waypoint_idx": self.current_waypoint_idx,
            "command": self.command,
            "max_speed": self.max_speed,
            "patrol_loop": self.patrol_loop,
        }


class SwarmCoordinationPlugin(PluginInterface):
    """Multi-robot swarm coordination engine."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._ctx: Optional[PluginContext] = None
        self._running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._swarms: dict[str, SwarmUnit] = {}
        self._tick_rate: float = 10.0  # Hz

    @property
    def plugin_id(self) -> str:
        return "tritium.swarm_coordination"

    @property
    def name(self) -> str:
        return "Swarm Coordination"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"routes", "background", "ui"}

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._ctx = ctx
        self._logger = ctx.logger or log
        self._load_swarms()
        self._register_routes()
        self._logger.info("Swarm coordination configured (%d swarms)", len(self._swarms))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick_thread = threading.Thread(
            target=self._tick_loop,
            daemon=True,
            name="swarm-tick",
        )
        self._tick_thread.start()
        self._logger.info("Swarm coordination started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._tick_thread and self._tick_thread.is_alive():
            self._tick_thread.join(timeout=2.0)
        self._save_swarms()
        self._logger.info("Swarm coordination stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API --------------------------------------------------------

    def create_swarm(self, name: str = "", formation: str = "line",
                     spacing: float = 5.0) -> SwarmUnit:
        """Create a new swarm unit."""
        swarm_id = str(uuid.uuid4())[:12]
        swarm = SwarmUnit(swarm_id, name)
        swarm.formation_type = formation
        swarm.spacing = spacing
        self._swarms[swarm_id] = swarm
        self._save_swarms()
        if self._event_bus:
            self._event_bus.publish("swarm:created", swarm.to_dict())
        return swarm

    def get_swarm(self, swarm_id: str) -> Optional[SwarmUnit]:
        return self._swarms.get(swarm_id)

    def list_swarms(self) -> list[dict]:
        return [s.to_dict() for s in self._swarms.values()]

    def delete_swarm(self, swarm_id: str) -> bool:
        if swarm_id not in self._swarms:
            return False
        del self._swarms[swarm_id]
        self._save_swarms()
        if self._event_bus:
            self._event_bus.publish("swarm:deleted", {"swarm_id": swarm_id})
        return True

    def issue_command(self, swarm_id: str, command: str,
                      waypoints: Optional[list] = None,
                      formation: Optional[str] = None,
                      spacing: Optional[float] = None,
                      max_speed: Optional[float] = None) -> Optional[dict]:
        """Issue a command to a swarm."""
        swarm = self._swarms.get(swarm_id)
        if swarm is None:
            return None

        swarm.command = command
        if waypoints is not None:
            swarm.waypoints = [(w[0], w[1]) for w in waypoints]
            swarm.current_waypoint_idx = 0
        if formation is not None:
            swarm.formation_type = formation
        if spacing is not None:
            swarm.spacing = spacing
        if max_speed is not None:
            swarm.max_speed = max_speed

        self._save_swarms()
        if self._event_bus:
            self._event_bus.publish("swarm:command", {
                "swarm_id": swarm_id,
                "command": command,
                "formation": swarm.formation_type,
            })
        return swarm.to_dict()

    def get_stats(self) -> dict:
        total_members = sum(len(s.members) for s in self._swarms.values())
        active_members = sum(
            sum(1 for m in s.members.values() if m["status"] == "active")
            for s in self._swarms.values()
        )
        return {
            "total_swarms": len(self._swarms),
            "total_members": total_members,
            "active_members": active_members,
            "formations": {s.swarm_id: s.formation_type for s in self._swarms.values()},
        }

    # -- Tick loop ---------------------------------------------------------

    def _tick_loop(self) -> None:
        dt = 1.0 / self._tick_rate
        while self._running:
            try:
                for swarm in list(self._swarms.values()):
                    swarm.tick(dt)
                time.sleep(dt)
            except Exception as exc:
                log.error("Swarm tick error: %s", exc)

    # -- Persistence -------------------------------------------------------

    def _load_swarms(self) -> None:
        swarms_file = _DATA_DIR / "swarms.json"
        if not swarms_file.exists():
            return
        try:
            with open(swarms_file) as f:
                data = json.load(f)
            for sd in data:
                swarm = SwarmUnit(sd["swarm_id"], sd.get("name", ""))
                swarm.formation_type = sd.get("formation_type", "line")
                swarm.heading = sd.get("heading", 0.0)
                swarm.spacing = sd.get("spacing", 5.0)
                swarm.center_x = sd.get("center_x", 0.0)
                swarm.center_y = sd.get("center_y", 0.0)
                swarm.command = sd.get("command", "hold")
                swarm.waypoints = [tuple(w) for w in sd.get("waypoints", [])]
                swarm.max_speed = sd.get("max_speed", 2.0)
                for md in sd.get("members", []):
                    swarm.members[md["member_id"]] = md
                self._swarms[swarm.swarm_id] = swarm
            self._logger.info("Loaded %d swarms", len(self._swarms))
        except Exception as exc:
            self._logger.warning("Failed to load swarms: %s", exc)

    def _save_swarms(self) -> None:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            swarms_file = _DATA_DIR / "swarms.json"
            data = []
            for s in self._swarms.values():
                d = s.to_dict()
                d["waypoints"] = [list(w) for w in s.waypoints]
                data.append(d)
            with open(swarms_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            self._logger.warning("Failed to save swarms: %s", exc)

    def _register_routes(self) -> None:
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
