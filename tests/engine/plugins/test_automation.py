# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the Automation Engine plugin."""

import time

import pytest

from engine.plugins.base import PluginInterface


@pytest.mark.unit
class TestAutomationPlugin:
    """Verify Automation plugin interface and lifecycle."""

    def test_implements_plugin_interface(self):
        from plugins.automation.plugin import AutomationPlugin
        plugin = AutomationPlugin()
        assert isinstance(plugin, PluginInterface)

    def test_plugin_identity(self):
        from plugins.automation.plugin import AutomationPlugin
        plugin = AutomationPlugin()
        assert plugin.plugin_id == "tritium.automation"
        assert plugin.name == "Automation Engine"
        assert plugin.version == "1.0.0"

    def test_capabilities(self):
        from plugins.automation.plugin import AutomationPlugin
        plugin = AutomationPlugin()
        caps = plugin.capabilities
        assert "routes" in caps
        assert "background" in caps

    def test_engine_exposed(self):
        from plugins.automation.plugin import AutomationPlugin
        plugin = AutomationPlugin()
        assert plugin.engine is not None

    def test_stats_empty(self):
        from plugins.automation.plugin import AutomationPlugin
        plugin = AutomationPlugin()
        stats = plugin.get_stats()
        assert stats["events_processed"] == 0
        assert stats["rules_matched"] == 0
        assert stats["total_rules"] == 0


@pytest.mark.unit
class TestTriggerCondition:
    """Verify TriggerCondition evaluation logic."""

    def test_eq_string(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="alliance", operator="eq", value="unknown")
        assert c.evaluate({"alliance": "unknown"}) is True
        assert c.evaluate({"alliance": "friendly"}) is False

    def test_eq_numeric(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="count", operator="eq", value="5")
        assert c.evaluate({"count": 5}) is True
        assert c.evaluate({"count": "5"}) is True

    def test_neq(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="status", operator="neq", value="online")
        assert c.evaluate({"status": "offline"}) is True
        assert c.evaluate({"status": "online"}) is False

    def test_gt(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="seen_count", operator="gt", value=5)
        assert c.evaluate({"seen_count": 10}) is True
        assert c.evaluate({"seen_count": 5}) is False
        assert c.evaluate({"seen_count": 3}) is False

    def test_lt(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="battery", operator="lt", value=20)
        assert c.evaluate({"battery": 15}) is True
        assert c.evaluate({"battery": 25}) is False

    def test_gte(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="rssi", operator="gte", value=-50)
        assert c.evaluate({"rssi": -40}) is True
        assert c.evaluate({"rssi": -50}) is True
        assert c.evaluate({"rssi": -60}) is False

    def test_lte(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="temp", operator="lte", value=100)
        assert c.evaluate({"temp": 100}) is True
        assert c.evaluate({"temp": 101}) is False

    def test_contains(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="name", operator="contains", value="Apple")
        assert c.evaluate({"name": "Apple Watch"}) is True
        assert c.evaluate({"name": "Samsung Galaxy"}) is False

    def test_regex(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="mac", operator="regex", value=r"^AA:BB")
        assert c.evaluate({"mac": "AA:BB:CC:DD:EE:FF"}) is True
        assert c.evaluate({"mac": "11:22:33:44:55:66"}) is False

    def test_exists(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="location", operator="exists")
        assert c.evaluate({"location": {"lat": 0, "lon": 0}}) is True
        assert c.evaluate({"other": "data"}) is False

    def test_missing_field_returns_false(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="nonexistent", operator="eq", value="x")
        assert c.evaluate({"other": "data"}) is False

    def test_dot_notation(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="device.battery", operator="gt", value=50)
        assert c.evaluate({"device": {"battery": 85}}) is True
        assert c.evaluate({"device": {"battery": 30}}) is False

    def test_unknown_operator(self):
        from plugins.automation.rules import TriggerCondition
        c = TriggerCondition(field="x", operator="bogus", value=1)
        assert c.evaluate({"x": 1}) is False


@pytest.mark.unit
class TestAutomationRule:
    """Verify AutomationRule serialization."""

    def test_to_dict_roundtrip(self):
        from plugins.automation.rules import (
            ActionSpec,
            AutomationRule,
            TriggerCondition,
        )
        rule = AutomationRule(
            rule_id="test-1",
            name="Test Rule",
            trigger="ble:new_device",
            conditions=[
                TriggerCondition(field="rssi", operator="gt", value=-50),
            ],
            actions=[
                ActionSpec(action_type="alert", params={"severity": "high"}),
            ],
            enabled=True,
            cooldown_seconds=30.0,
            description="A test rule",
        )
        d = rule.to_dict()
        assert d["rule_id"] == "test-1"
        assert d["name"] == "Test Rule"
        assert d["trigger"] == "ble:new_device"
        assert len(d["conditions"]) == 1
        assert d["conditions"][0]["field"] == "rssi"
        assert len(d["actions"]) == 1
        assert d["actions"][0]["action_type"] == "alert"

        # Roundtrip
        restored = AutomationRule.from_dict(d)
        assert restored.rule_id == rule.rule_id
        assert restored.name == rule.name
        assert restored.trigger == rule.trigger
        assert len(restored.conditions) == 1
        assert restored.conditions[0].operator == "gt"
        assert len(restored.actions) == 1
        assert restored.actions[0].action_type == "alert"

    def test_from_dict_defaults(self):
        from plugins.automation.rules import AutomationRule
        rule = AutomationRule.from_dict({"name": "Minimal"})
        assert rule.name == "Minimal"
        assert rule.trigger == ""
        assert rule.conditions == []
        assert rule.actions == []
        assert rule.enabled is True
        assert rule.cooldown_seconds == 0.0


@pytest.mark.unit
class TestRuleEngine:
    """Verify RuleEngine evaluation and action execution."""

    def _make_engine(self):
        from plugins.automation.rules import RuleEngine
        return RuleEngine()

    def _make_rule(self, **kwargs):
        from plugins.automation.rules import AutomationRule
        defaults = {
            "rule_id": "r1",
            "name": "Test",
            "trigger": "test:event",
            "enabled": True,
        }
        defaults.update(kwargs)
        return AutomationRule(**defaults)

    def test_add_and_list_rules(self):
        engine = self._make_engine()
        r = self._make_rule()
        engine.add_rule(r)
        assert len(engine.list_rules()) == 1
        assert engine.get_rule("r1") is r

    def test_remove_rule(self):
        engine = self._make_engine()
        engine.add_rule(self._make_rule())
        assert engine.remove_rule("r1") is True
        assert engine.remove_rule("r1") is False
        assert len(engine.list_rules()) == 0

    def test_enable_disable_rule(self):
        engine = self._make_engine()
        engine.add_rule(self._make_rule())
        engine.disable_rule("r1")
        assert engine.get_rule("r1").enabled is False
        engine.enable_rule("r1")
        assert engine.get_rule("r1").enabled is True

    def test_clear_rules(self):
        engine = self._make_engine()
        engine.add_rule(self._make_rule(rule_id="a"))
        engine.add_rule(self._make_rule(rule_id="b"))
        count = engine.clear_rules()
        assert count == 2
        assert len(engine.list_rules()) == 0

    def test_evaluate_exact_trigger_match(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            actions=[ActionSpec(action_type="log", params={"message": "hit"})],
        ))
        results = engine.evaluate({"type": "test:event", "data": {}})
        assert len(results) == 1
        assert results[0]["matched"] is True
        assert results[0]["executed"] is True

    def test_evaluate_no_match(self):
        engine = self._make_engine()
        engine.add_rule(self._make_rule())
        results = engine.evaluate({"type": "other:event", "data": {}})
        assert len(results) == 0

    def test_evaluate_wildcard_trigger(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            trigger="test:*",
            actions=[ActionSpec(action_type="log", params={"message": "wild"})],
        ))
        results = engine.evaluate({"type": "test:anything", "data": {}})
        assert len(results) == 1

    def test_evaluate_star_matches_all(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            trigger="*",
            actions=[ActionSpec(action_type="log", params={})],
        ))
        results = engine.evaluate({"type": "any:event", "data": {}})
        assert len(results) == 1

    def test_evaluate_conditions_filter(self):
        from plugins.automation.rules import ActionSpec, TriggerCondition
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            conditions=[TriggerCondition(field="level", operator="gt", value=5)],
            actions=[ActionSpec(action_type="log", params={})],
        ))

        # Passes condition
        results = engine.evaluate({"type": "test:event", "data": {"level": 10}})
        assert len(results) == 1

        # Fails condition
        results = engine.evaluate({"type": "test:event", "data": {"level": 3}})
        assert len(results) == 0

    def test_evaluate_disabled_rule_skipped(self):
        engine = self._make_engine()
        engine.add_rule(self._make_rule(enabled=False))
        results = engine.evaluate({"type": "test:event", "data": {}})
        assert len(results) == 0

    def test_evaluate_cooldown(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            cooldown_seconds=60.0,
            actions=[ActionSpec(action_type="log", params={})],
        ))

        # First fire: executes
        results = engine.evaluate({"type": "test:event", "data": {}})
        assert len(results) == 1
        assert results[0]["executed"] is True

        # Second fire within cooldown: blocked
        results = engine.evaluate({"type": "test:event", "data": {}})
        assert len(results) == 1
        assert results[0]["executed"] is False
        assert "cooldown" in results[0]["reason"]

    def test_evaluate_dry_run(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            actions=[ActionSpec(action_type="alert", params={"severity": "high"})],
        ))

        results = engine.evaluate(
            {"type": "test:event", "data": {}}, dry_run=True
        )
        assert len(results) == 1
        assert results[0]["executed"] is False
        assert results[0]["action_results"][0]["dry_run"] is True

    def test_execute_unknown_action_type(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        engine.add_rule(self._make_rule(
            actions=[ActionSpec(action_type="nonexistent", params={})],
        ))
        results = engine.evaluate({"type": "test:event", "data": {}})
        assert len(results) == 1
        ar = results[0]["action_results"][0]
        assert ar["success"] is False
        assert "No executor" in ar["error"]

    def test_register_custom_executor(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        executed = []

        def my_executor(action, event):
            executed.append(action.params)
            return {"success": True}

        engine.register_executor("custom", my_executor)
        engine.add_rule(self._make_rule(
            actions=[ActionSpec(action_type="custom", params={"key": "val"})],
        ))
        engine.evaluate({"type": "test:event", "data": {}})
        assert len(executed) == 1
        assert executed[0]["key"] == "val"

    def test_fire_count_increments(self):
        from plugins.automation.rules import ActionSpec
        engine = self._make_engine()
        rule = self._make_rule(
            actions=[ActionSpec(action_type="log", params={})],
        )
        engine.add_rule(rule)
        engine.evaluate({"type": "test:event", "data": {}})
        engine.evaluate({"type": "test:event", "data": {}})
        assert rule._fire_count == 2


@pytest.mark.unit
class TestTriggerMatching:
    """Verify trigger pattern matching edge cases."""

    def test_exact_match(self):
        from plugins.automation.rules import _match_trigger
        assert _match_trigger("ble:new_device", "ble:new_device") is True
        assert _match_trigger("ble:new_device", "ble:lost_device") is False

    def test_wildcard_suffix(self):
        from plugins.automation.rules import _match_trigger
        assert _match_trigger("ble:new_device", "ble:*") is True
        assert _match_trigger("wifi:scan", "ble:*") is False

    def test_wildcard_prefix(self):
        from plugins.automation.rules import _match_trigger
        assert _match_trigger("zone:enter", "*:enter") is True
        assert _match_trigger("zone:exit", "*:enter") is False

    def test_star_matches_all(self):
        from plugins.automation.rules import _match_trigger
        assert _match_trigger("anything", "*") is True
        assert _match_trigger("a:b:c", "*") is True

    def test_no_match(self):
        from plugins.automation.rules import _match_trigger
        assert _match_trigger("foo", "bar") is False


@pytest.mark.unit
class TestExampleRules:
    """Verify example rules creation."""

    def test_creates_three_rules(self):
        from plugins.automation.rules import create_example_rules
        rules = create_example_rules()
        assert len(rules) == 3

    def test_example_rules_have_valid_structure(self):
        from plugins.automation.rules import create_example_rules
        for rule in create_example_rules():
            assert rule.rule_id
            assert rule.name
            assert rule.trigger
            assert len(rule.actions) > 0
            assert rule.enabled is True
            assert rule.cooldown_seconds > 0

    def test_example_rules_serializable(self):
        from plugins.automation.rules import AutomationRule, create_example_rules
        for rule in create_example_rules():
            d = rule.to_dict()
            restored = AutomationRule.from_dict(d)
            assert restored.rule_id == rule.rule_id
            assert restored.name == rule.name


@pytest.mark.unit
class TestFieldResolution:
    """Verify dot-notation field resolution."""

    def test_simple_field(self):
        from plugins.automation.rules import _resolve_field
        assert _resolve_field({"x": 1}, "x") == 1

    def test_nested_field(self):
        from plugins.automation.rules import _resolve_field
        data = {"device": {"battery": {"level": 85}}}
        assert _resolve_field(data, "device.battery.level") == 85

    def test_missing_field(self):
        from plugins.automation.rules import _resolve_field
        assert _resolve_field({"x": 1}, "y") is None

    def test_missing_nested(self):
        from plugins.automation.rules import _resolve_field
        assert _resolve_field({"x": 1}, "x.y.z") is None


@pytest.mark.unit
class TestPluginActionExecutors:
    """Verify plugin action executors publish to EventBus."""

    def _make_plugin_with_bus(self):
        from plugins.automation.plugin import AutomationPlugin
        from engine.comms.event_bus import EventBus

        plugin = AutomationPlugin()
        bus = EventBus()
        plugin._event_bus = bus
        plugin._logger = __import__("logging").getLogger("test")
        return plugin, bus

    def test_alert_executor(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()
        q = bus.subscribe()

        action = ActionSpec(
            action_type="alert",
            params={"severity": "critical", "message": "Test alert"},
        )
        result = plugin._execute_alert(action, {"type": "test", "data": {}})
        assert result["success"] is True

        # Check EventBus received the alert
        import queue as queue_mod
        try:
            event = q.get(timeout=1.0)
            assert event["type"] == "automation:alert"
            assert event["data"]["severity"] == "critical"
        except queue_mod.Empty:
            pytest.fail("No event published to EventBus")

    def test_command_executor(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()
        q = bus.subscribe()

        action = ActionSpec(
            action_type="command",
            params={"device_id": "tritium-01", "command": "reboot"},
        )
        result = plugin._execute_command(action, {"type": "test", "data": {}})
        assert result["success"] is True

        import queue as queue_mod
        event = q.get(timeout=1.0)
        assert event["type"] == "automation:command"
        assert event["data"]["device_id"] == "tritium-01"
        assert event["data"]["command"] == "reboot"

    def test_command_executor_missing_params(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()

        action = ActionSpec(action_type="command", params={})
        result = plugin._execute_command(action, {"type": "test", "data": {}})
        assert result["success"] is False

    def test_tag_executor(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()
        q = bus.subscribe()

        action = ActionSpec(
            action_type="tag",
            params={"tag": "frequent", "reason": "seen often"},
        )
        event = {"type": "ble:new_device", "data": {"device_id": "dev-abc"}}
        result = plugin._execute_tag(action, event)
        assert result["success"] is True

        import queue as queue_mod
        msg = q.get(timeout=1.0)
        assert msg["type"] == "automation:tag"
        assert msg["data"]["tag"] == "frequent"
        assert msg["data"]["target_id"] == "dev-abc"

    def test_tag_executor_missing_tag(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()

        action = ActionSpec(action_type="tag", params={})
        result = plugin._execute_tag(action, {"type": "test", "data": {}})
        assert result["success"] is False

    def test_escalate_executor(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()
        q = bus.subscribe()

        action = ActionSpec(
            action_type="escalate",
            params={"threat_level": "hostile", "reason": "threat detected"},
        )
        event = {"type": "ble:suspicious", "data": {"target_id": "tgt-1"}}
        result = plugin._execute_escalate(action, event)
        assert result["success"] is True

        import queue as queue_mod
        msg = q.get(timeout=1.0)
        assert msg["type"] == "automation:escalation"
        assert msg["data"]["threat_level"] == "hostile"

    def test_notify_executor(self):
        from plugins.automation.rules import ActionSpec
        plugin, bus = self._make_plugin_with_bus()
        q = bus.subscribe()

        action = ActionSpec(
            action_type="notify",
            params={"title": "Update", "message": "Something happened"},
        )
        result = plugin._execute_notify(action, {"type": "test", "data": {}})
        assert result["success"] is True

        import queue as queue_mod
        msg = q.get(timeout=1.0)
        assert msg["type"] == "automation:notification"
        assert msg["data"]["title"] == "Update"

    def test_executor_no_event_bus(self):
        from plugins.automation.plugin import AutomationPlugin
        from plugins.automation.rules import ActionSpec
        plugin = AutomationPlugin()
        plugin._logger = __import__("logging").getLogger("test")

        action = ActionSpec(action_type="alert", params={})
        result = plugin._execute_alert(action, {"type": "test", "data": {}})
        assert result["success"] is False


@pytest.mark.unit
class TestRuleExportImport:
    """Verify rule export and import roundtrip."""

    def test_export_format(self):
        from plugins.automation.rules import AutomationRule, create_example_rules

        rules = create_example_rules()
        export_data = [r.to_dict() for r in rules]
        package = {
            "format": "tritium_automation_rules",
            "version": "1.0.0",
            "rule_count": len(rules),
            "rules": export_data,
        }
        assert package["format"] == "tritium_automation_rules"
        assert package["rule_count"] == 3
        assert len(package["rules"]) == 3

    def test_import_roundtrip(self):
        from plugins.automation.rules import AutomationRule, create_example_rules

        # Export
        original_rules = create_example_rules()
        export_data = [r.to_dict() for r in original_rules]

        # Import
        imported = [AutomationRule.from_dict(d) for d in export_data]
        assert len(imported) == len(original_rules)
        for orig, imp in zip(original_rules, imported):
            assert orig.rule_id == imp.rule_id
            assert orig.name == imp.name
            assert orig.trigger == imp.trigger
            assert len(orig.conditions) == len(imp.conditions)
            assert len(orig.actions) == len(imp.actions)

    def test_import_preserves_all_fields(self):
        from plugins.automation.rules import (
            ActionSpec,
            AutomationRule,
            TriggerCondition,
        )
        rule = AutomationRule(
            rule_id="export-test",
            name="Export Test",
            trigger="ble:*",
            conditions=[
                TriggerCondition(field="rssi", operator="gt", value=-60),
                TriggerCondition(field="name", operator="contains", value="Watch"),
            ],
            actions=[
                ActionSpec(action_type="alert", params={"severity": "high"}),
                ActionSpec(action_type="tag", params={"tag": "strong_signal"}),
            ],
            enabled=False,
            cooldown_seconds=45.0,
            description="Test all fields survive export/import",
        )
        d = rule.to_dict()
        restored = AutomationRule.from_dict(d)
        assert restored.rule_id == "export-test"
        assert restored.enabled is False
        assert restored.cooldown_seconds == 45.0
        assert restored.description == "Test all fields survive export/import"
        assert len(restored.conditions) == 2
        assert len(restored.actions) == 2
        assert restored.conditions[1].value == "Watch"
        assert restored.actions[1].params["tag"] == "strong_signal"
