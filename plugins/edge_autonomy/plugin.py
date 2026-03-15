# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""EdgeAutonomyPlugin — processes autonomous decisions from edge devices.

When edge devices detect high-threat conditions locally (unknown BLE in
restricted zone, motion detected, acoustic event), they autonomously
publish alerts via MQTT. This plugin receives those decisions, logs them,
validates them, and allows SC operators to confirm or override.

MQTT topic: tritium/{device_id}/alert/autonomous
"""
from __future__ import annotations

import json
import logging
import os
import queue as queue_mod
import threading
import time
from pathlib import Path
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

log = logging.getLogger("edge_autonomy")

_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "edge_autonomy"


class EdgeAutonomyPlugin(PluginInterface):
    """Processes and manages autonomous decisions from edge devices."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._ctx: Optional[PluginContext] = None
        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

        # Decision storage: decision_id -> decision dict
        self._decisions: dict[str, dict] = {}
        # Per-device accuracy tracking
        self._device_stats: dict[str, dict] = {}

        # Stats
        self._total_received: int = 0
        self._total_confirmed: int = 0
        self._total_overridden: int = 0

    @property
    def plugin_id(self) -> str:
        return "tritium.edge_autonomy"

    @property
    def name(self) -> str:
        return "Edge Autonomy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"routes", "background"}

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._ctx = ctx
        self._logger = ctx.logger or log
        self._load_decisions()
        self._register_routes()
        self._logger.info("Edge autonomy configured (%d decisions)", len(self._decisions))

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="edge-autonomy-events",
            )
            self._event_thread.start()

        self._logger.info("Edge autonomy started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._save_decisions()
        self._logger.info("Edge autonomy stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API --------------------------------------------------------

    def receive_decision(self, decision: dict) -> dict:
        """Process an autonomous decision from an edge device."""
        decision_id = decision.get("decision_id", f"auto_{int(time.time()*1000)}_{self._total_received}")
        decision["decision_id"] = decision_id
        decision.setdefault("sc_override", "pending")
        decision.setdefault("created_at", time.time())
        decision.setdefault("confidence", 0.5)

        self._decisions[decision_id] = decision
        self._total_received += 1

        # Track per-device stats
        device_id = decision.get("device_id", "unknown")
        if device_id not in self._device_stats:
            self._device_stats[device_id] = {
                "total": 0, "confirmed": 0, "overridden": 0,
                "accuracy": 0.0,
            }
        self._device_stats[device_id]["total"] += 1

        # Auto-validate high-confidence decisions
        if decision.get("confidence", 0) >= 0.9:
            decision["sc_override"] = "confirmed"
            decision["override_reason"] = "auto-confirmed (confidence >= 0.9)"
            self._total_confirmed += 1
            self._device_stats[device_id]["confirmed"] += 1

        self._save_decisions()

        if self._event_bus:
            self._event_bus.publish("edge_autonomy:decision_received", decision)

        return decision

    def confirm_decision(self, decision_id: str, reason: str = "",
                         confirmed_by: str = "") -> Optional[dict]:
        """SC confirms an edge decision was correct."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            return None

        decision["sc_override"] = "confirmed"
        decision["override_reason"] = reason
        decision["override_by"] = confirmed_by
        decision["override_at"] = time.time()
        self._total_confirmed += 1

        device_id = decision.get("device_id", "unknown")
        if device_id in self._device_stats:
            self._device_stats[device_id]["confirmed"] += 1
            self._update_device_accuracy(device_id)

        self._save_decisions()

        if self._event_bus:
            self._event_bus.publish("edge_autonomy:decision_confirmed", decision)

        return decision

    def override_decision(self, decision_id: str, reason: str = "",
                          overridden_by: str = "",
                          corrective_action: str = "") -> Optional[dict]:
        """SC overrides an edge decision — it was incorrect."""
        decision = self._decisions.get(decision_id)
        if decision is None:
            return None

        decision["sc_override"] = "overridden"
        decision["override_reason"] = reason
        decision["override_by"] = overridden_by
        decision["override_at"] = time.time()
        decision["corrective_action"] = corrective_action
        self._total_overridden += 1

        device_id = decision.get("device_id", "unknown")
        if device_id in self._device_stats:
            self._device_stats[device_id]["overridden"] += 1
            self._update_device_accuracy(device_id)

        self._save_decisions()

        if self._event_bus:
            self._event_bus.publish("edge_autonomy:decision_overridden", decision)

        return decision

    def list_decisions(self, device_id: Optional[str] = None,
                       status: Optional[str] = None,
                       limit: int = 100) -> list[dict]:
        """List decisions with optional filters."""
        decisions = list(self._decisions.values())
        if device_id:
            decisions = [d for d in decisions if d.get("device_id") == device_id]
        if status:
            decisions = [d for d in decisions if d.get("sc_override") == status]
        decisions.sort(key=lambda d: d.get("created_at", 0), reverse=True)
        return decisions[:limit]

    def get_stats(self) -> dict:
        pending = sum(
            1 for d in self._decisions.values()
            if d.get("sc_override") == "pending"
        )
        return {
            "total_received": self._total_received,
            "total_confirmed": self._total_confirmed,
            "total_overridden": self._total_overridden,
            "pending_review": pending,
            "total_stored": len(self._decisions),
            "device_stats": self._device_stats,
        }

    def _update_device_accuracy(self, device_id: str) -> None:
        stats = self._device_stats.get(device_id)
        if stats is None:
            return
        reviewed = stats["confirmed"] + stats["overridden"]
        if reviewed > 0:
            stats["accuracy"] = round(stats["confirmed"] / reviewed, 3)

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                event_type = event.get("type", "")
                # Listen for edge autonomous decisions coming via MQTT bridge
                if event_type in (
                    "mqtt:edge_autonomous_alert",
                    "edge:autonomous_decision",
                ):
                    self.receive_decision(event.get("data", event))
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Edge autonomy event error: %s", exc)

    # -- Persistence -------------------------------------------------------

    def _load_decisions(self) -> None:
        decisions_file = _DATA_DIR / "decisions.json"
        if not decisions_file.exists():
            return
        try:
            with open(decisions_file) as f:
                data = json.load(f)
            self._decisions = {d["decision_id"]: d for d in data.get("decisions", [])}
            self._device_stats = data.get("device_stats", {})
            self._total_received = data.get("total_received", len(self._decisions))
            self._total_confirmed = data.get("total_confirmed", 0)
            self._total_overridden = data.get("total_overridden", 0)
            self._logger.info("Loaded %d decisions", len(self._decisions))
        except Exception as exc:
            self._logger.warning("Failed to load decisions: %s", exc)

    def _save_decisions(self) -> None:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            decisions_file = _DATA_DIR / "decisions.json"
            data = {
                "decisions": list(self._decisions.values()),
                "device_stats": self._device_stats,
                "total_received": self._total_received,
                "total_confirmed": self._total_confirmed,
                "total_overridden": self._total_overridden,
            }
            with open(decisions_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            self._logger.warning("Failed to save decisions: %s", exc)

    def _register_routes(self) -> None:
        if not self._app:
            return
        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
