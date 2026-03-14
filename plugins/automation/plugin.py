# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AutomationPlugin — if-then rule engine for event-driven automation.

Subscribes to all EventBus events and evaluates them against user-defined
rules. When a rule matches, its actions execute: publish alerts, send
MQTT commands, tag targets, escalate threats, or emit notifications.

Provides REST API at /api/automation/ for rule CRUD and dry-run testing.
"""

from __future__ import annotations

import json
import logging
import os
import queue as queue_mod
import threading
from pathlib import Path
from typing import Any, Optional

from engine.plugins.base import PluginContext, PluginInterface

from .rules import (
    ActionSpec,
    AutomationRule,
    RuleEngine,
    create_example_rules,
)

log = logging.getLogger("automation")

# Persist rules to data/automation/rules.json
_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "automation"


class AutomationPlugin(PluginInterface):
    """Event-driven automation engine with if-then rules."""

    def __init__(self) -> None:
        self._event_bus: Any = None
        self._app: Any = None
        self._logger: Optional[logging.Logger] = None
        self._ctx: Optional[PluginContext] = None

        self._engine = RuleEngine()
        self._running = False
        self._event_queue: Optional[queue_mod.Queue] = None
        self._event_thread: Optional[threading.Thread] = None

        # Stats
        self._events_processed: int = 0
        self._rules_matched: int = 0

    # -- PluginInterface identity ------------------------------------------

    @property
    def plugin_id(self) -> str:
        return "tritium.automation"

    @property
    def name(self) -> str:
        return "Automation Engine"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> set[str]:
        return {"routes", "background"}

    # -- PluginInterface lifecycle -----------------------------------------

    def configure(self, ctx: PluginContext) -> None:
        self._event_bus = ctx.event_bus
        self._app = ctx.app
        self._ctx = ctx
        self._logger = ctx.logger or log

        # Register action executors that need plugin context
        self._engine.register_executor("alert", self._execute_alert)
        self._engine.register_executor("command", self._execute_command)
        self._engine.register_executor("tag", self._execute_tag)
        self._engine.register_executor("escalate", self._execute_escalate)
        self._engine.register_executor("notify", self._execute_notify)

        # Load persisted rules or seed with examples
        self._load_rules()

        # Register HTTP routes
        self._register_routes()
        self._logger.info("Automation plugin configured (%d rules)", len(self._engine.list_rules()))

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if self._event_bus:
            self._event_queue = self._event_bus.subscribe()
            self._event_thread = threading.Thread(
                target=self._event_drain_loop,
                daemon=True,
                name="automation-events",
            )
            self._event_thread.start()

        self._logger.info("Automation plugin started")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)

        if self._event_bus and self._event_queue:
            self._event_bus.unsubscribe(self._event_queue)

        self._save_rules()
        self._logger.info("Automation plugin stopped")

    @property
    def healthy(self) -> bool:
        return self._running

    # -- Public API --------------------------------------------------------

    @property
    def engine(self) -> RuleEngine:
        """Expose the rule engine for direct access."""
        return self._engine

    def get_stats(self) -> dict:
        """Return plugin statistics."""
        rules = self._engine.list_rules()
        return {
            "events_processed": self._events_processed,
            "rules_matched": self._rules_matched,
            "total_rules": len(rules),
            "enabled_rules": sum(1 for r in rules if r.enabled),
            "disabled_rules": sum(1 for r in rules if not r.enabled),
        }

    # -- Event handling ----------------------------------------------------

    def _event_drain_loop(self) -> None:
        """Drain EventBus queue and evaluate each event."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.5)
                self._events_processed += 1
                results = self._engine.evaluate(event)
                if results:
                    self._rules_matched += len(
                        [r for r in results if r.get("executed")]
                    )
            except queue_mod.Empty:
                pass
            except Exception as exc:
                log.error("Automation event error: %s", exc)

    # -- Action executors --------------------------------------------------

    def _execute_alert(self, action: ActionSpec, event: dict) -> dict:
        """Publish an alert event to the EventBus."""
        if not self._event_bus:
            return {"success": False, "error": "No event bus"}

        alert_data = {
            "severity": action.params.get("severity", "info"),
            "message": action.params.get("message", "Automation alert"),
            "category": action.params.get("category", "automation"),
            "source_event": event.get("type", ""),
            "source": "automation",
        }
        self._event_bus.publish("automation:alert", alert_data)
        return {"success": True, "alert": alert_data}

    def _execute_command(self, action: ActionSpec, event: dict) -> dict:
        """Send an MQTT command to a device via EventBus."""
        if not self._event_bus:
            return {"success": False, "error": "No event bus"}

        device_id = action.params.get("device_id", "")
        command = action.params.get("command", "")
        if not device_id or not command:
            return {
                "success": False,
                "error": "device_id and command required",
            }

        cmd_data = {
            "device_id": device_id,
            "command": command,
            "params": action.params.get("command_params", {}),
            "source": "automation",
        }
        self._event_bus.publish("automation:command", cmd_data)
        return {"success": True, "command": cmd_data}

    def _execute_tag(self, action: ActionSpec, event: dict) -> dict:
        """Add a tag to a target via EventBus."""
        if not self._event_bus:
            return {"success": False, "error": "No event bus"}

        # Use target_id from event data if not specified in params
        data = event.get("data", {})
        target_id = action.params.get(
            "target_id", data.get("target_id", data.get("device_id", ""))
        )
        tag = action.params.get("tag", "")
        if not tag:
            return {"success": False, "error": "tag required"}

        tag_data = {
            "target_id": target_id,
            "tag": tag,
            "reason": action.params.get("reason", ""),
            "source": "automation",
        }
        self._event_bus.publish("automation:tag", tag_data)
        return {"success": True, "tag": tag_data}

    def _execute_escalate(self, action: ActionSpec, event: dict) -> dict:
        """Escalate threat level via EventBus."""
        if not self._event_bus:
            return {"success": False, "error": "No event bus"}

        data = event.get("data", {})
        target_id = action.params.get(
            "target_id", data.get("target_id", data.get("device_id", ""))
        )
        threat_level = action.params.get("threat_level", "suspicious")

        escalation_data = {
            "target_id": target_id,
            "threat_level": threat_level,
            "reason": action.params.get("reason", "Automation rule triggered"),
            "source": "automation",
        }
        self._event_bus.publish("automation:escalation", escalation_data)
        return {"success": True, "escalation": escalation_data}

    def _execute_notify(self, action: ActionSpec, event: dict) -> dict:
        """Publish a notification event."""
        if not self._event_bus:
            return {"success": False, "error": "No event bus"}

        notify_data = {
            "title": action.params.get("title", "Automation Notification"),
            "message": action.params.get("message", ""),
            "level": action.params.get("level", "info"),
            "source": "automation",
        }
        self._event_bus.publish("automation:notification", notify_data)
        return {"success": True, "notification": notify_data}

    # -- Persistence -------------------------------------------------------

    def _load_rules(self) -> None:
        """Load rules from JSON file, or seed with examples."""
        rules_file = _DATA_DIR / "rules.json"
        if rules_file.exists():
            try:
                with open(rules_file) as f:
                    data = json.load(f)
                for rd in data:
                    rule = AutomationRule.from_dict(rd)
                    self._engine.add_rule(rule)
                self._logger.info("Loaded %d rules from %s", len(data), rules_file)
                return
            except Exception as exc:
                self._logger.warning("Failed to load rules: %s", exc)

        # Seed with example rules
        for rule in create_example_rules():
            self._engine.add_rule(rule)
        self._save_rules()
        self._logger.info("Seeded %d example rules", len(self._engine.list_rules()))

    def _save_rules(self) -> None:
        """Persist rules to JSON file."""
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            rules_file = _DATA_DIR / "rules.json"
            data = [r.to_dict() for r in self._engine.list_rules()]
            with open(rules_file, "w") as f:
                json.dump(data, f, indent=2)
            self._logger.debug("Saved %d rules to %s", len(data), rules_file)
        except Exception as exc:
            self._logger.warning("Failed to save rules: %s", exc)

    # -- HTTP routes -------------------------------------------------------

    def _register_routes(self) -> None:
        if not self._app:
            return

        from .routes import create_router
        router = create_router(self)
        self._app.include_router(router)
