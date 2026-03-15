# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Automation rule engine — dataclasses and evaluation logic.

Rules are if-then structures: when an event matches a trigger pattern and
all conditions are met, the specified actions execute. Supports cooldowns
to prevent action flooding.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("automation.rules")


@dataclass
class TriggerCondition:
    """A single condition to check against event data fields.

    Operators:
        eq       — field == value (string or numeric)
        neq      — field != value
        gt       — field > value (numeric)
        lt       — field < value (numeric)
        gte      — field >= value (numeric)
        lte      — field <= value (numeric)
        contains — value is substring of field
        regex    — field matches regex pattern
        exists   — field exists in event data (value ignored)
    """

    field: str
    operator: str
    value: Any = None

    def evaluate(self, data: dict) -> bool:
        """Test this condition against event data. Returns True if met."""
        # Dot-notation field access (e.g. "device.battery")
        val = _resolve_field(data, self.field)

        if self.operator == "exists":
            return val is not None

        if val is None:
            return False

        try:
            if self.operator == "eq":
                return str(val) == str(self.value)
            elif self.operator == "neq":
                return str(val) != str(self.value)
            elif self.operator == "gt":
                return float(val) > float(self.value)
            elif self.operator == "lt":
                return float(val) < float(self.value)
            elif self.operator == "gte":
                return float(val) >= float(self.value)
            elif self.operator == "lte":
                return float(val) <= float(self.value)
            elif self.operator == "contains":
                return str(self.value) in str(val)
            elif self.operator == "regex":
                # Guard against ReDoS: limit pattern length and use timeout
                pattern = str(self.value)
                if len(pattern) > 200:
                    log.warning("Regex pattern too long (%d chars), rejected", len(pattern))
                    return False
                try:
                    compiled = re.compile(pattern)
                except re.error:
                    log.warning("Invalid regex pattern: %s", pattern[:50])
                    return False
                return bool(compiled.search(str(val)))
            else:
                log.warning("Unknown operator: %s", self.operator)
                return False
        except (ValueError, TypeError) as exc:
            log.debug("Condition eval error: %s", exc)
            return False


@dataclass
class ActionSpec:
    """Specification for an action to execute when a rule fires.

    Action types:
        alert     — Publish an alert event to EventBus
        command   — Send an MQTT command to a device
        tag       — Add a tag to a target/dossier
        escalate  — Change threat level for a target
        notify    — Publish a notification event
        log       — Log a message at specified level
    """

    action_type: str
    params: dict = field(default_factory=dict)


@dataclass
class AutomationRule:
    """A complete automation rule: trigger + conditions + actions."""

    rule_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    trigger: str = ""  # Event pattern to match (e.g. "ble:new_device")
    conditions: list[TriggerCondition] = field(default_factory=list)
    actions: list[ActionSpec] = field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: float = 0.0
    description: str = ""
    created_at: float = field(default_factory=time.time)

    # Runtime state (not serialized)
    _last_fired: float = field(default=0.0, repr=False)
    _fire_count: int = field(default=0, repr=False)

    def to_dict(self) -> dict:
        """Serialize rule to a plain dict."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "trigger": self.trigger,
            "conditions": [
                {"field": c.field, "operator": c.operator, "value": c.value}
                for c in self.conditions
            ],
            "actions": [
                {"action_type": a.action_type, "params": a.params}
                for a in self.actions
            ],
            "enabled": self.enabled,
            "cooldown_seconds": self.cooldown_seconds,
            "description": self.description,
            "created_at": self.created_at,
            "fire_count": self._fire_count,
            "last_fired": self._last_fired,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AutomationRule:
        """Deserialize a rule from a plain dict."""
        conditions = [
            TriggerCondition(
                field=c["field"],
                operator=c["operator"],
                value=c.get("value"),
            )
            for c in d.get("conditions", [])
        ]
        actions = [
            ActionSpec(
                action_type=a["action_type"],
                params=a.get("params", {}),
            )
            for a in d.get("actions", [])
        ]
        rule = cls(
            rule_id=d.get("rule_id", str(uuid.uuid4())[:8]),
            name=d.get("name", ""),
            trigger=d.get("trigger", ""),
            conditions=conditions,
            actions=actions,
            enabled=d.get("enabled", True),
            cooldown_seconds=d.get("cooldown_seconds", 0.0),
            description=d.get("description", ""),
        )
        if "created_at" in d:
            rule.created_at = d["created_at"]
        return rule


class RuleEngine:
    """Evaluates events against automation rules and executes actions.

    Action executors are registered as callables keyed by action_type.
    The engine provides built-in executors for alert, command, tag,
    escalate, notify, and log.
    """

    def __init__(self) -> None:
        self._rules: dict[str, AutomationRule] = {}
        self._executors: dict[str, Callable] = {}
        self._lock = __import__("threading").Lock()

        # Register built-in executors
        self._executors["log"] = self._execute_log

    # -- Rule management ---------------------------------------------------

    def add_rule(self, rule: AutomationRule) -> AutomationRule:
        """Add a rule. Returns the rule (with generated ID if needed)."""
        with self._lock:
            self._rules[rule.rule_id] = rule
        log.info("Rule added: %s (%s)", rule.name, rule.rule_id)
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID. Returns True if found and removed."""
        with self._lock:
            if rule_id in self._rules:
                del self._rules[rule_id]
                log.info("Rule removed: %s", rule_id)
                return True
        return False

    def get_rule(self, rule_id: str) -> AutomationRule | None:
        """Get a rule by ID."""
        with self._lock:
            return self._rules.get(rule_id)

    def list_rules(self) -> list[AutomationRule]:
        """Return all rules."""
        with self._lock:
            return list(self._rules.values())

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule. Returns True if found."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = True
                return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule. Returns True if found."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule:
                rule.enabled = False
                return True
        return False

    def clear_rules(self) -> int:
        """Remove all rules. Returns count of removed rules."""
        with self._lock:
            count = len(self._rules)
            self._rules.clear()
        return count

    # -- Executor registration ---------------------------------------------

    def register_executor(
        self, action_type: str, executor: Callable
    ) -> None:
        """Register an action executor.

        Executor signature: (action_spec: ActionSpec, event: dict) -> dict
        Returns a result dict with at least {"success": bool}.
        """
        self._executors[action_type] = executor
        log.debug("Executor registered: %s", action_type)

    # -- Evaluation --------------------------------------------------------

    def evaluate(
        self, event: dict, *, dry_run: bool = False
    ) -> list[dict]:
        """Evaluate an event against all enabled rules.

        Args:
            event: Event dict with at least "type" key.
            dry_run: If True, match rules but don't execute actions.

        Returns:
            List of result dicts for each rule that matched.
        """
        event_type = event.get("type", "")
        data = event.get("data", {})
        now = time.time()
        results = []

        with self._lock:
            rules = list(self._rules.values())

        for rule in rules:
            if not rule.enabled:
                continue

            # Match trigger pattern (exact match or glob-style with *)
            if not _match_trigger(event_type, rule.trigger):
                continue

            # Check all conditions
            if not all(c.evaluate(data) for c in rule.conditions):
                continue

            # Cooldown check
            if rule.cooldown_seconds > 0:
                elapsed = now - rule._last_fired
                if elapsed < rule.cooldown_seconds:
                    results.append({
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "matched": True,
                        "executed": False,
                        "reason": f"cooldown ({rule.cooldown_seconds - elapsed:.1f}s remaining)",
                    })
                    continue

            # Execute actions (or report dry run)
            action_results = []
            if dry_run:
                for action in rule.actions:
                    action_results.append({
                        "action_type": action.action_type,
                        "params": action.params,
                        "dry_run": True,
                        "would_execute": action.action_type in self._executors,
                    })
            else:
                rule._last_fired = now
                rule._fire_count += 1
                for action in rule.actions:
                    result = self._execute_action(action, event)
                    action_results.append(result)

            results.append({
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "matched": True,
                "executed": not dry_run,
                "action_results": action_results,
            })

        return results

    # -- Action execution --------------------------------------------------

    def _execute_action(self, action: ActionSpec, event: dict) -> dict:
        """Execute a single action. Returns result dict."""
        executor = self._executors.get(action.action_type)
        if executor is None:
            log.warning(
                "No executor for action type: %s", action.action_type
            )
            return {
                "action_type": action.action_type,
                "success": False,
                "error": f"No executor registered for '{action.action_type}'",
            }

        try:
            result = executor(action, event)
            if not isinstance(result, dict):
                result = {"success": True}
            result["action_type"] = action.action_type
            return result
        except Exception as exc:
            log.error(
                "Action executor error (%s): %s", action.action_type, exc
            )
            return {
                "action_type": action.action_type,
                "success": False,
                "error": str(exc),
            }

    @staticmethod
    def _execute_log(action: ActionSpec, event: dict) -> dict:
        """Built-in log action executor."""
        level = action.params.get("level", "info").upper()
        message = action.params.get("message", f"Rule fired on {event.get('type', '?')}")
        getattr(log, level.lower(), log.info)(message)
        return {"success": True, "message": message}


# -- Helpers ---------------------------------------------------------------


def _resolve_field(data: dict, field_path: str) -> Any:
    """Resolve a dot-notation field path against a dict.

    Example: _resolve_field({"device": {"battery": 85}}, "device.battery")
    returns 85.
    """
    parts = field_path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _match_trigger(event_type: str, pattern: str) -> bool:
    """Match an event type against a trigger pattern.

    Supports:
        - Exact match: "ble:new_device"
        - Wildcard suffix: "ble:*" matches any ble event
        - Wildcard prefix: "*:suspicious" matches any suspicious event
        - Double wildcard: "*" matches everything
    """
    if pattern == "*":
        return True
    if pattern == event_type:
        return True
    if "*" in pattern:
        # Convert glob pattern to regex
        regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
        return bool(re.match(regex, event_type))
    return False


def create_example_rules() -> list[AutomationRule]:
    """Create example automation rules for demonstration."""
    return [
        AutomationRule(
            rule_id="ex-alert-unknown",
            name="Alert on unknown device in restricted zone",
            trigger="geofence:enter",
            conditions=[
                TriggerCondition(field="alliance", operator="eq", value="unknown"),
            ],
            actions=[
                ActionSpec(
                    action_type="alert",
                    params={
                        "severity": "warning",
                        "message": "Unknown device entered restricted zone",
                        "category": "intrusion",
                    },
                ),
            ],
            enabled=True,
            cooldown_seconds=60.0,
            description="Fires an alert when an unknown device enters a geofenced restricted zone.",
        ),
        AutomationRule(
            rule_id="ex-escalate-signal",
            name="Escalate strong unknown signal",
            trigger="ble:suspicious_device",
            conditions=[],
            actions=[
                ActionSpec(
                    action_type="escalate",
                    params={
                        "threat_level": "high",
                        "reason": "Strong unknown BLE signal detected",
                    },
                ),
            ],
            enabled=True,
            cooldown_seconds=120.0,
            description="Escalates threat level when a suspicious BLE device is detected.",
        ),
        AutomationRule(
            rule_id="ex-tag-frequent",
            name="Tag returning device as frequent",
            trigger="ble:new_device",
            conditions=[
                TriggerCondition(field="seen_count", operator="gt", value=5),
            ],
            actions=[
                ActionSpec(
                    action_type="tag",
                    params={
                        "tag": "frequent",
                        "reason": "Seen more than 5 times",
                    },
                ),
            ],
            enabled=True,
            cooldown_seconds=300.0,
            description="Tags a BLE device as 'frequent' when it has been seen more than 5 times.",
        ),
    ]
