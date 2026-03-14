# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""FastAPI routes for the Automation Engine plugin.

CRUD for rules plus a dry-run test endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .plugin import AutomationPlugin

from .rules import ActionSpec, AutomationRule, TriggerCondition


# -- Request/Response models -----------------------------------------------


class ConditionModel(BaseModel):
    field: str
    operator: str
    value: object = None


class ActionModel(BaseModel):
    action_type: str
    params: dict = Field(default_factory=dict)


class RuleCreateRequest(BaseModel):
    name: str
    trigger: str
    conditions: list[ConditionModel] = Field(default_factory=list)
    actions: list[ActionModel] = Field(default_factory=list)
    enabled: bool = True
    cooldown_seconds: float = 0.0
    description: str = ""


class RuleUpdateRequest(BaseModel):
    name: str | None = None
    trigger: str | None = None
    conditions: list[ConditionModel] | None = None
    actions: list[ActionModel] | None = None
    enabled: bool | None = None
    cooldown_seconds: float | None = None
    description: str | None = None


class TestRunRequest(BaseModel):
    event_type: str
    data: dict = Field(default_factory=dict)


# -- Router factory --------------------------------------------------------


def create_router(plugin: AutomationPlugin) -> APIRouter:
    """Build and return the automation engine APIRouter."""

    router = APIRouter(prefix="/api/automation", tags=["automation"])

    @router.get("/rules")
    async def list_rules():
        """List all automation rules."""
        rules = plugin.engine.list_rules()
        return {
            "rules": [r.to_dict() for r in rules],
            "count": len(rules),
        }

    @router.get("/rules/{rule_id}")
    async def get_rule(rule_id: str):
        """Get a single rule by ID."""
        rule = plugin.engine.get_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"rule": rule.to_dict()}

    @router.post("/rules", status_code=201)
    async def create_rule(req: RuleCreateRequest):
        """Create a new automation rule."""
        conditions = [
            TriggerCondition(field=c.field, operator=c.operator, value=c.value)
            for c in req.conditions
        ]
        actions = [
            ActionSpec(action_type=a.action_type, params=a.params)
            for a in req.actions
        ]
        rule = AutomationRule(
            name=req.name,
            trigger=req.trigger,
            conditions=conditions,
            actions=actions,
            enabled=req.enabled,
            cooldown_seconds=req.cooldown_seconds,
            description=req.description,
        )
        rule = plugin.engine.add_rule(rule)
        plugin._save_rules()
        return {"rule": rule.to_dict()}

    @router.put("/rules/{rule_id}")
    async def update_rule(rule_id: str, req: RuleUpdateRequest):
        """Update an existing rule."""
        rule = plugin.engine.get_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")

        if req.name is not None:
            rule.name = req.name
        if req.trigger is not None:
            rule.trigger = req.trigger
        if req.conditions is not None:
            rule.conditions = [
                TriggerCondition(field=c.field, operator=c.operator, value=c.value)
                for c in req.conditions
            ]
        if req.actions is not None:
            rule.actions = [
                ActionSpec(action_type=a.action_type, params=a.params)
                for a in req.actions
            ]
        if req.enabled is not None:
            rule.enabled = req.enabled
        if req.cooldown_seconds is not None:
            rule.cooldown_seconds = req.cooldown_seconds
        if req.description is not None:
            rule.description = req.description

        plugin._save_rules()
        return {"rule": rule.to_dict()}

    @router.delete("/rules/{rule_id}")
    async def delete_rule(rule_id: str):
        """Delete a rule by ID."""
        removed = plugin.engine.remove_rule(rule_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Rule not found")
        plugin._save_rules()
        return {"deleted": True, "rule_id": rule_id}

    @router.post("/rules/{rule_id}/enable")
    async def enable_rule(rule_id: str):
        """Enable a rule."""
        found = plugin.engine.enable_rule(rule_id)
        if not found:
            raise HTTPException(status_code=404, detail="Rule not found")
        plugin._save_rules()
        return {"rule_id": rule_id, "enabled": True}

    @router.post("/rules/{rule_id}/disable")
    async def disable_rule(rule_id: str):
        """Disable a rule."""
        found = plugin.engine.disable_rule(rule_id)
        if not found:
            raise HTTPException(status_code=404, detail="Rule not found")
        plugin._save_rules()
        return {"rule_id": rule_id, "enabled": False}

    @router.post("/rules/{rule_id}/test")
    async def test_rule(rule_id: str, req: TestRunRequest):
        """Dry-run a specific rule against a test event.

        Does NOT execute actions — only reports what would happen.
        """
        rule = plugin.engine.get_rule(rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")

        event = {"type": req.event_type, "data": req.data}
        results = plugin.engine.evaluate(event, dry_run=True)

        # Filter results to just this rule
        rule_result = next(
            (r for r in results if r["rule_id"] == rule_id), None
        )
        if rule_result is None:
            return {
                "rule_id": rule_id,
                "matched": False,
                "reason": "Event did not match trigger or conditions",
            }
        return rule_result

    @router.post("/test")
    async def test_all_rules(req: TestRunRequest):
        """Dry-run all rules against a test event."""
        event = {"type": req.event_type, "data": req.data}
        results = plugin.engine.evaluate(event, dry_run=True)
        return {"results": results, "matched_count": len(results)}

    @router.get("/stats")
    async def get_stats():
        """Get automation engine statistics."""
        return plugin.get_stats()

    return router
