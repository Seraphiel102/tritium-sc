# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AgentBridge — HTTP client to the Graphling home server.

Provides deploy/recall/think/heartbeat/experience operations against
the Graphling server's deployment REST API. All methods are synchronous
(called from the plugin's background thread) and handle errors gracefully.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from httpx import ConnectError as _ConnectError
from httpx import TimeoutException as _TimeoutException

from .config import GraphlingsConfig

log = logging.getLogger(__name__)


class AgentBridge:
    """HTTP client connecting the tritium-sc plugin to the Graphling home server."""

    def __init__(self, config: GraphlingsConfig) -> None:
        self._base_url = config.server_url.rstrip("/")
        self._timeout = config.server_timeout
        self._dry_run = config.dry_run

    # ── Deploy / Recall ──────────────────────────────────────────

    def deploy(self, soul_id: str, config: dict) -> Optional[dict]:
        """Deploy a graphling to this service.

        Returns the deployment record dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "deployment_id": f"dry_{soul_id}", "status": "deployed"}
        return self._post(
            "/deployment/deploy",
            json={"soul_id": soul_id, "config": config},
        )

    def recall(self, soul_id: str, reason: str = "manual") -> Optional[dict]:
        """Recall a deployed graphling.

        Returns recall result dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "status": "recalled", "reason": reason}
        return self._post(
            f"/deployment/{soul_id}/recall",
            json={"reason": reason},
        )

    # ── Batch Deploy / Recall ────────────────────────────────────

    def batch_deploy(self, config: dict) -> Optional[dict]:
        """Deploy a batch of graphlings.

        POST /deployment/deploy-batch
        Returns the batch result dict, or None on error.
        """
        if self._dry_run:
            return {"status": "deployed", "count": len(config.get("souls", []))}
        return self._post("/deployment/deploy-batch", json=config)

    def batch_recall(self, service_name: str, reason: str) -> Optional[dict]:
        """Recall all graphlings for a service.

        POST /deployment/recall-batch
        Returns recall result dict, or None on error.
        """
        if self._dry_run:
            return {"status": "recalled", "reason": reason}
        return self._post(
            "/deployment/recall-batch",
            json={"service_name": service_name, "reason": reason},
        )

    # ── Think ────────────────────────────────────────────────────

    def think(
        self,
        soul_id: str,
        perception: dict,
        current_state: str,
        available_actions: list[str],
        urgency: float,
        preferred_layer: Optional[int] = None,
    ) -> Optional[dict]:
        """Ask the graphling to make a decision.

        Returns ThinkResponse dict (thought, action, emotion, layer, model, confidence),
        or None on timeout/error.
        """
        if self._dry_run:
            return self._dry_run_think(soul_id, perception, current_state, available_actions, urgency)
        body: dict[str, Any] = {
            "perception": perception,
            "current_state": current_state,
            "available_actions": available_actions,
            "urgency": urgency,
        }
        if preferred_layer is not None:
            body["preferred_layer"] = preferred_layer

        return self._post(f"/deployment/{soul_id}/think", json=body)

    # ── Heartbeat ────────────────────────────────────────────────

    def heartbeat(self, soul_id: str) -> Optional[dict]:
        """Send heartbeat to keep deployment alive.

        Returns heartbeat response dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "status": "alive"}
        return self._post(f"/deployment/{soul_id}/heartbeat", json={})

    # ── Experience ───────────────────────────────────────────────

    def record_experiences(self, soul_id: str, experiences: list[dict]) -> int:
        """Record a batch of experiences.

        Returns the number of experiences recorded (0 on error).
        """
        if self._dry_run:
            return len(experiences)
        result = self._post(
            f"/deployment/{soul_id}/experience",
            json={"experiences": experiences},
        )
        if result is None:
            return 0
        return result.get("recorded", 0)

    # ── Feedback (RL loop) ────────────────────────────────────────

    def feedback(
        self,
        soul_id: str,
        action: str,
        success: bool,
        outcome: str = "",
    ) -> Optional[dict]:
        """Report action success/failure to close the RL reinforcement loop.

        The server uses this to update Thompson Sampling arms and adjust
        future model selection for this graphling.

        Returns server response dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "status": "ok"}
        return self._post(
            f"/deployment/{soul_id}/feedback",
            json={"action": action, "success": success, "outcome": outcome},
        )

    # ── Pending Actions (server autonomy) ──────────────────────

    def get_pending_actions(self, soul_id: str) -> list[dict]:
        """Poll server-generated autonomous actions.

        The server's tickDeployedAutonomous() generates proactive goals
        and actions. External apps poll this to discover what the graphling
        wants to do on its own initiative.

        Returns list of action dicts (empty on error).
        """
        if self._dry_run:
            return []
        result = self._get(f"/deployment/{soul_id}/pending-actions")
        if result is None:
            return []
        return result.get("actions", [])

    # ── World Model ────────────────────────────────────────────

    def report_entity(self, soul_id: str, entity: dict) -> Optional[dict]:
        """Report a perceived entity to update the graphling's mental model.

        Builds persistent world knowledge that persists across think cycles,
        allowing the graphling to remember entities it has seen before.

        Returns server response dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "status": "ok"}
        return self._post(f"/deployment/{soul_id}/world/entity", json=entity)

    # ── Mood ───────────────────────────────────────────────────

    def get_mood(self, soul_id: str) -> Optional[dict]:
        """Get the graphling's current emotional state.

        Returns mood dict (happiness, stress, engagement, confidence),
        or None on error. Use for adaptive behavior and auto-recall.
        """
        if self._dry_run:
            return {"happiness": 0.7, "stress": 0.2, "engagement": 0.6, "confidence": 0.5}
        return self._get(f"/deployment/{soul_id}/mood")

    # ── Objectives ─────────────────────────────────────────────

    def set_objective(self, soul_id: str, objective: dict) -> Optional[dict]:
        """Set a goal for the graphling to pursue autonomously.

        Game events can drive objectives (e.g., "protect village" when
        enemies approach). The server's autonomous tick will work toward it.

        Returns created objective dict, or None on error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "objective": objective, "status": "set"}
        return self._post(f"/deployment/{soul_id}/objectives", json=objective)

    # ── Status ───────────────────────────────────────────────────

    def get_status(self, soul_id: str) -> Optional[dict]:
        """Get deployment status for a soul.

        Returns deployment record dict, or None if not found/error.
        """
        if self._dry_run:
            return {"soul_id": soul_id, "status": "deployed", "deployment_id": f"dry_{soul_id}"}
        return self._get(f"/deployment/{soul_id}")

    def list_active(self) -> list[dict]:
        """List all active deployments.

        Returns list of deployment records (empty on error).
        """
        if self._dry_run:
            return []
        result = self._get("/deployment/active")
        if result is None:
            return []
        return result.get("deployments", [])

    # ── Dry-run stub responses ─────────────────────────────────

    def _dry_run_think(
        self,
        soul_id: str,
        perception: dict,
        current_state: str,
        available_actions: list[str],
        urgency: float,
    ) -> dict:
        """Generate a stub think response for dry-run mode.

        Urgency-aware: high urgency triggers defensive behavior,
        low urgency triggers exploration/social behavior.
        """
        danger = perception.get("danger_level", urgency)

        if danger > 0.7 and "flee" in available_actions:
            return {
                "thought": f"Danger detected (level {danger:.1f})! I need to get to safety immediately.",
                "action": 'flee("away_from_danger")',
                "emotion": "fearful",
                "layer": 2,
                "model_used": "dry_run",
                "confidence": 0.9,
            }
        elif danger > 0.4:
            action = "observe" if "observe" in available_actions else available_actions[0] if available_actions else "say"
            return {
                "thought": f"Something feels tense. I should stay alert and {action}.",
                "action": f'{action}("staying_alert")',
                "emotion": "cautious",
                "layer": 3,
                "model_used": "dry_run",
                "confidence": 0.7,
            }
        else:
            # Peaceful — pick a social or exploratory action
            if "say" in available_actions:
                return {
                    "thought": "Things are calm. I feel content and want to connect with others.",
                    "action": 'say("Hello! What a beautiful day.")',
                    "emotion": "happy",
                    "layer": 3,
                    "model_used": "dry_run",
                    "confidence": 0.8,
                }
            action = available_actions[0] if available_actions else "observe"
            return {
                "thought": f"Peaceful moment. I'll {action} and enjoy the surroundings.",
                "action": f'{action}("exploring")',
                "emotion": "content",
                "layer": 3,
                "model_used": "dry_run",
                "confidence": 0.8,
            }

    # ── HTTP helpers ─────────────────────────────────────────────

    def _post(self, path: str, json: dict) -> Optional[dict]:
        """POST to the Graphling server. Returns parsed JSON or None."""
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.post(url, json=json, timeout=self._timeout)
            if resp.is_success:
                return resp.json()
            log.warning("POST %s returned %d", path, resp.status_code)
            return None
        except _TimeoutException:
            log.warning("POST %s timed out", path)
            return None
        except _ConnectError:
            log.warning("POST %s connection refused", path)
            return None
        except Exception as e:
            log.warning("POST %s failed: %s", path, e)
            return None

    def _get(self, path: str) -> Optional[dict]:
        """GET from the Graphling server. Returns parsed JSON or None."""
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.get(url, timeout=self._timeout)
            if resp.is_success:
                return resp.json()
            log.warning("GET %s returned %d", path, resp.status_code)
            return None
        except _TimeoutException:
            log.warning("GET %s timed out", path)
            return None
        except _ConnectError:
            log.warning("GET %s connection refused", path)
            return None
        except Exception as e:
            log.warning("GET %s failed: %s", path, e)
            return None
