# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for CommandHistoryStore — command audit log."""

import time

import pytest

from engine.comms.command_history import CommandHistoryStore


def test_record_sent():
    """Commands can be recorded."""
    store = CommandHistoryStore()
    cid = store.record_sent("device-01", "reboot", {"delay": 5})
    assert cid.startswith("cmd_")
    recent = store.get_recent(10)
    assert len(recent) == 1
    assert recent[0]["command"] == "reboot"
    assert recent[0]["device_id"] == "device-01"
    assert recent[0]["result"] == "pending"


def test_record_ack_by_command_id():
    """ACK by command_id updates the command."""
    store = CommandHistoryStore()
    cid = store.record_sent("device-01", "reboot")
    assert store.record_ack(command_id=cid, result="acknowledged")
    recent = store.get_recent(10)
    assert recent[0]["result"] == "acknowledged"
    assert recent[0]["acked_at"] is not None


def test_record_ack_by_device_id():
    """ACK by device_id matches the most recent pending command."""
    store = CommandHistoryStore()
    store.record_sent("device-01", "identify")
    store.record_sent("device-01", "reboot")
    assert store.record_ack(device_id="device-01", result="acknowledged")
    recent = store.get_recent(10)
    # Most recent (reboot) should be acked
    reboot = [c for c in recent if c["command"] == "reboot"][0]
    assert reboot["result"] == "acknowledged"


def test_record_ack_failure():
    """Failed ACK records error."""
    store = CommandHistoryStore()
    cid = store.record_sent("device-01", "ota_url")
    store.record_ack(command_id=cid, result="failed", error="download failed")
    recent = store.get_recent(10)
    assert recent[0]["result"] == "failed"
    assert recent[0]["error"] == "download failed"


def test_get_stats():
    """Stats returns correct counts."""
    store = CommandHistoryStore()
    cid1 = store.record_sent("d1", "reboot")
    cid2 = store.record_sent("d2", "identify")
    store.record_sent("d3", "sleep")
    store.record_ack(command_id=cid1, result="acknowledged")
    store.record_ack(command_id=cid2, result="failed")
    stats = store.get_stats()
    assert stats["total_sent"] == 3
    assert stats["acknowledged"] == 1
    assert stats["failed"] == 1
    assert stats["pending"] == 1


def test_history_capped():
    """History is capped at 500."""
    store = CommandHistoryStore()
    for i in range(550):
        store.record_sent("d1", f"cmd_{i}")
    recent = store.get_recent(1000)
    assert len(recent) == 500


def test_get_recent_newest_first():
    """Recent commands are returned newest first."""
    store = CommandHistoryStore()
    store.record_sent("d1", "first")
    store.record_sent("d1", "second")
    store.record_sent("d1", "third")
    recent = store.get_recent(10)
    assert recent[0]["command"] == "third"
    assert recent[2]["command"] == "first"


def test_custom_command_id():
    """Custom command_id can be provided."""
    store = CommandHistoryStore()
    cid = store.record_sent("d1", "reboot", command_id="my_custom_id")
    assert cid == "my_custom_id"
    assert store.record_ack(command_id="my_custom_id", result="acknowledged")


def test_device_group():
    """Device group is recorded."""
    store = CommandHistoryStore()
    store.record_sent("d1", "reboot", device_group="alpha")
    recent = store.get_recent(10)
    assert recent[0]["device_group"] == "alpha"
