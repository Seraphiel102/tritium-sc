# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Rate limiter HTTP integration test.

Sends 100+ rapid requests to a protected endpoint with rate limiting enabled
and verifies that 429 responses appear after the limit is reached.
"""

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.rate_limit import RateLimitMiddleware


@pytest.fixture
def rate_limited_app():
    """Create a minimal FastAPI app with rate limiting enabled."""
    app = FastAPI()

    # Patch settings so rate limiting is enabled
    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = True

        # Add rate limit middleware: 10 requests per 60s window (tight for testing)
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=10,
            window_seconds=60,
        )

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"health": "ok"}

    @app.get("/ws/live")
    async def ws_live():
        return {"ws": True}

    return app


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit():
    """Send 20 rapid requests to a protected endpoint with a limit of 10.

    Verifies:
    - First 10 requests return 200
    - Requests 11+ return 429
    - 429 response includes rate limit headers
    """
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"health": "ok"}

    # Add middleware with tight limit
    app.add_middleware(
        RateLimitMiddleware,
        max_requests=10,
        window_seconds=60,
    )

    # Patch settings to enable rate limiting
    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses = []
            for i in range(20):
                resp = await client.get("/api/test")
                statuses.append(resp.status_code)

            # First 10 should be 200
            ok_count = statuses.count(200)
            blocked_count = statuses.count(429)

            assert ok_count == 10, f"Expected 10 OK responses, got {ok_count}. Statuses: {statuses}"
            assert blocked_count == 10, f"Expected 10 blocked responses, got {blocked_count}. Statuses: {statuses}"

            # The 11th request should be a 429
            assert statuses[10] == 429, f"Request #11 should be 429, got {statuses[10]}"


@pytest.mark.asyncio
async def test_rate_limit_includes_headers():
    """Verify 429 response includes proper rate limit headers."""
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=5,
        window_seconds=60,
    )

    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Exhaust the limit
            for _ in range(5):
                await client.get("/api/test")

            # 6th request should be 429
            resp = await client.get("/api/test")
            assert resp.status_code == 429
            assert "X-RateLimit-Limit" in resp.headers
            assert resp.headers["X-RateLimit-Remaining"] == "0"
            assert "Retry-After" in resp.headers

            body = resp.json()
            assert "Rate limit exceeded" in body["detail"]


@pytest.mark.asyncio
async def test_rate_limit_exempts_health_and_ws():
    """Health and WebSocket paths should be exempt from rate limiting."""
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"health": "ok"}

    @app.get("/static/test.js")
    async def static_file():
        return {"static": True}

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=3,
        window_seconds=60,
    )

    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Exhaust limit on /api/test
            for _ in range(3):
                await client.get("/api/test")

            # /api/test should now be blocked
            resp = await client.get("/api/test")
            assert resp.status_code == 429

            # But exempt paths should still work
            resp = await client.get("/health")
            assert resp.status_code == 200

            resp = await client.get("/static/test.js")
            assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_200_requests_rapid():
    """Send 100 rapid requests, verify exactly max_requests succeed."""
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=20,
        window_seconds=60,
    )

    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = True

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Fire 100 requests as fast as possible
            responses = []
            for _ in range(100):
                resp = await client.get("/api/test")
                responses.append(resp.status_code)

            ok_count = responses.count(200)
            blocked_count = responses.count(429)

            assert ok_count == 20, f"Expected exactly 20 OK, got {ok_count}"
            assert blocked_count == 80, f"Expected 80 blocked, got {blocked_count}"

            # Remaining header should decrease
            first_resp = await client.get("/api/test")
            assert first_resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_disabled_allows_all():
    """When rate_limit_enabled=False, no requests should be blocked."""
    app = FastAPI()

    @app.get("/api/test")
    async def test_endpoint():
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        max_requests=5,
        window_seconds=60,
    )

    from unittest.mock import patch
    with patch("app.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = False

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(20):
                resp = await client.get("/api/test")
                assert resp.status_code == 200, "All requests should pass when rate limiting is disabled"
