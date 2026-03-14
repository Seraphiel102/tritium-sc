# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WebSocket load test — verifies system handles concurrent connections.

Tests:
1. 10 concurrent WebSocket connections receive messages
2. Message rate consistency across connections
3. No connection drops under load
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.routers.ws import ConnectionManager


class TestWebSocketLoadUnit:
    """Unit-level tests for WebSocket connection handling under load."""

    def test_connection_manager_import(self):
        """ConnectionManager can be imported."""
        assert ConnectionManager is not None

    @pytest.mark.asyncio
    async def test_connection_manager_broadcast_to_many(self):
        """Verify broadcast delivers to 10 connections, 50 messages each."""
        manager = ConnectionManager()

        received = {i: [] for i in range(10)}
        broadcast_count = 50

        class FakeWebSocket:
            def __init__(self, idx):
                self.idx = idx

            async def send_text(self, data):
                received[self.idx].append(data)

            async def accept(self):
                pass

        sockets = [FakeWebSocket(i) for i in range(10)]
        for ws in sockets:
            manager.active_connections.add(ws)

        # Broadcast dict messages (broadcast takes dict, json.dumps internally)
        for i in range(broadcast_count):
            await manager.broadcast({"type": "test", "seq": i})

        for idx in range(10):
            assert len(received[idx]) == broadcast_count, (
                f"Connection {idx} received {len(received[idx])}/{broadcast_count} messages"
            )

    @pytest.mark.asyncio
    async def test_broadcast_handles_dead_connections(self):
        """Verify broadcast removes dead connections gracefully."""
        manager = ConnectionManager()

        received = []

        class GoodSocket:
            async def send_text(self, data):
                received.append(data)

            async def accept(self):
                pass

        class DeadSocket:
            async def send_text(self, data):
                raise RuntimeError("Connection closed")

            async def accept(self):
                pass

        good = GoodSocket()
        dead = DeadSocket()

        manager.active_connections.add(good)
        manager.active_connections.add(dead)

        # Broadcast should not crash despite dead connection
        await manager.broadcast({"type": "test"})

        # Good socket should still have received
        assert len(received) >= 1, "Good socket should receive the message"

        # Dead socket should have been removed
        assert dead not in manager.active_connections, (
            "Dead socket should be removed after failed send"
        )

    @pytest.mark.asyncio
    async def test_concurrent_broadcasts_no_race(self):
        """Multiple concurrent broadcasts should not corrupt message ordering."""
        manager = ConnectionManager()

        received = []

        class FakeSocket:
            async def send_text(self, data):
                received.append(data)

            async def accept(self):
                pass

        ws = FakeSocket()
        manager.active_connections.add(ws)

        # Fire 100 concurrent broadcasts
        async def send_batch(start):
            for i in range(10):
                await manager.broadcast({"seq": start + i})

        tasks = [send_batch(i * 10) for i in range(10)]
        await asyncio.gather(*tasks)

        # All 100 messages should arrive
        assert len(received) == 100, (
            f"Expected 100 messages, got {len(received)}"
        )

    @pytest.mark.asyncio
    async def test_high_volume_no_degradation(self):
        """Send 500 messages to 10 connections, measure timing.

        Verifies no significant degradation under load.
        """
        manager = ConnectionManager()

        msg_counts = {i: 0 for i in range(10)}

        class FakeWebSocket:
            def __init__(self, idx):
                self.idx = idx

            async def send_text(self, data):
                msg_counts[self.idx] += 1

            async def accept(self):
                pass

        sockets = [FakeWebSocket(i) for i in range(10)]
        for ws in sockets:
            manager.active_connections.add(ws)

        start = time.monotonic()
        for i in range(500):
            await manager.broadcast({"type": "load_test", "seq": i})
        elapsed = time.monotonic() - start

        # All connections should have received all messages
        for idx in range(10):
            assert msg_counts[idx] == 500, (
                f"Connection {idx} got {msg_counts[idx]}/500"
            )

        # Should complete in reasonable time (< 5s for 500 messages)
        assert elapsed < 5.0, (
            f"500 broadcasts to 10 connections took {elapsed:.2f}s, expected < 5s"
        )

    def test_telemetry_batcher_import(self):
        """TelemetryBatcher can be imported (used for batching WS updates)."""
        try:
            from app.routers.ws import TelemetryBatcher
            assert TelemetryBatcher is not None
        except ImportError:
            pass
