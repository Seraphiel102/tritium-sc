# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""CommandHistoryStore — in-memory audit log of commands sent to edge devices.

Tracks every command dispatched to edge devices via MQTT, along with
acknowledgement status (acknowledged, failed, timed out). Used for
operational audit and the fleet command history panel.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger("comms.command_history")

# Commands older than this are expired from memory
_MAX_HISTORY = 500
# Commands without ACK after this many seconds are marked timed_out
_ACK_TIMEOUT_S = 60.0


class CommandHistoryStore:
    """Thread-safe in-memory store for command history."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # command_id -> dict
        self._commands: dict[str, dict] = {}
        # Ordered list of command_ids for history
        self._order: list[str] = []

    def record_sent(
        self,
        device_id: str,
        command: str,
        payload: dict | None = None,
        device_group: str | None = None,
        command_id: str | None = None,
    ) -> str:
        """Record a command being sent to a device.

        Returns the command_id.
        """
        if command_id is None:
            command_id = f"cmd_{uuid.uuid4().hex[:12]}"

        entry = {
            "command_id": command_id,
            "device_id": device_id,
            "device_group": device_group,
            "command": command,
            "payload": payload or {},
            "sent_at": time.time(),
            "result": "pending",
            "acked_at": None,
            "error": None,
        }

        with self._lock:
            self._commands[command_id] = entry
            self._order.append(command_id)
            # Trim oldest
            while len(self._order) > _MAX_HISTORY:
                old_id = self._order.pop(0)
                self._commands.pop(old_id, None)

        logger.debug("Command recorded: %s -> %s (%s)", command, device_id, command_id)
        return command_id

    def record_ack(
        self,
        command_id: str | None = None,
        device_id: str | None = None,
        result: str = "acknowledged",
        error: str | None = None,
    ) -> bool:
        """Record a command acknowledgement from a device.

        Can match by command_id directly, or by device_id (matches most
        recent pending command for that device).
        """
        with self._lock:
            entry = None
            if command_id and command_id in self._commands:
                entry = self._commands[command_id]
            elif device_id:
                # Find most recent pending command for this device
                for cid in reversed(self._order):
                    cmd = self._commands.get(cid)
                    if cmd and cmd["device_id"] == device_id and cmd["result"] == "pending":
                        entry = cmd
                        break

            if entry is None:
                return False

            entry["result"] = result
            entry["acked_at"] = time.time()
            if error:
                entry["error"] = error

        return True

    def check_timeouts(self) -> int:
        """Mark pending commands that have exceeded the ACK timeout.

        Returns the number of commands that timed out.
        """
        now = time.time()
        timed_out = 0
        with self._lock:
            for cmd in self._commands.values():
                if cmd["result"] == "pending" and (now - cmd["sent_at"]) > _ACK_TIMEOUT_S:
                    cmd["result"] = "timed_out"
                    timed_out += 1
        return timed_out

    def get_recent(self, limit: int = 100) -> list[dict]:
        """Get the most recent commands, newest first."""
        self.check_timeouts()
        with self._lock:
            ids = list(reversed(self._order[-limit:]))
            return [dict(self._commands[cid]) for cid in ids if cid in self._commands]

    def get_stats(self) -> dict:
        """Get summary statistics."""
        self.check_timeouts()
        with self._lock:
            total = len(self._commands)
            acked = sum(1 for c in self._commands.values() if c["result"] == "acknowledged")
            failed = sum(1 for c in self._commands.values() if c["result"] == "failed")
            timed_out = sum(1 for c in self._commands.values() if c["result"] == "timed_out")
            pending = sum(1 for c in self._commands.values() if c["result"] == "pending")
            return {
                "total_sent": total,
                "acknowledged": acked,
                "failed": failed,
                "timed_out": timed_out,
                "pending": pending,
            }
