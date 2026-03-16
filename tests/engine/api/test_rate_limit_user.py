# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for per-user rate limiting and role-based limits."""

import pytest
from unittest.mock import patch, MagicMock

from app.rate_limit import (
    RateLimitEntry,
    RateLimitMiddleware,
    ROLE_RATE_LIMITS,
    _extract_user_from_request,
)


class TestRoleLimits:
    """Role-based rate limit configuration."""

    def test_admin_unlimited(self):
        assert ROLE_RATE_LIMITS["admin"] is None

    def test_operator_100(self):
        assert ROLE_RATE_LIMITS["operator"] == 100

    def test_observer_30(self):
        assert ROLE_RATE_LIMITS["observer"] == 30


class TestExtractUser:
    """User extraction from request headers."""

    def test_returns_none_when_auth_disabled(self):
        request = MagicMock()
        with patch("app.rate_limit.settings") as mock_settings:
            mock_settings.auth_enabled = False
            result = _extract_user_from_request(request)
            assert result is None

    def test_extracts_api_key_user(self):
        request = MagicMock()
        request.headers.get = lambda key, default=None: {
            "X-API-Key": "trk_test123",
        }.get(key, default)

        with patch("app.rate_limit.settings") as mock_settings:
            mock_settings.auth_enabled = True
            with patch("app.auth._validate_api_key") as mock_validate:
                mock_validate.return_value = {
                    "sub": "apikey:test", "role": "operator",
                }
                result = _extract_user_from_request(request)
                assert result is not None
                assert result["role"] == "operator"

    def test_returns_none_for_invalid_api_key(self):
        request = MagicMock()
        request.headers.get = lambda key, default=None: {
            "X-API-Key": "bad_key",
        }.get(key, default)

        with patch("app.rate_limit.settings") as mock_settings:
            mock_settings.auth_enabled = True
            with patch("app.auth._validate_api_key") as mock_validate:
                mock_validate.return_value = None
                # No Bearer token either
                result = _extract_user_from_request(request)
                assert result is None

    def test_extracts_jwt_user(self):
        request = MagicMock()
        request.headers.get = lambda key, default=None: {
            "Authorization": "Bearer fake.jwt.token",
        }.get(key, default)

        with patch("app.rate_limit.settings") as mock_settings:
            mock_settings.auth_enabled = True
            with patch("app.auth.decode_token") as mock_decode:
                mock_decode.return_value = {"sub": "admin", "role": "admin"}
                result = _extract_user_from_request(request)
                assert result is not None
                assert result["sub"] == "admin"


class TestRateLimitMiddlewareResolve:
    """Rate limit key resolution."""

    def test_resolve_unauthenticated_uses_ip(self):
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=50)
        request = MagicMock()
        request.headers.get = lambda key, default=None: None
        request.client.host = "10.0.0.1"

        with patch("app.rate_limit.settings") as mock_settings:
            mock_settings.auth_enabled = False
            key, limit = middleware._resolve_rate_key(request)
            assert key == "ip:10.0.0.1"
            assert limit == 50

    def test_resolve_admin_unlimited(self):
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=50)
        request = MagicMock()
        request.headers.get = lambda key, default=None: {
            "X-API-Key": "trk_admin_key",
        }.get(key, default)
        request.client.host = "10.0.0.1"

        with patch("app.rate_limit._extract_user_from_request") as mock_extract:
            mock_extract.return_value = {"sub": "admin_user", "role": "admin"}
            key, limit = middleware._resolve_rate_key(request)
            assert key == "user:admin_user"
            assert limit is None  # Unlimited

    def test_resolve_operator_100(self):
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=50)
        request = MagicMock()

        with patch("app.rate_limit._extract_user_from_request") as mock_extract:
            mock_extract.return_value = {"sub": "op1", "role": "operator"}
            key, limit = middleware._resolve_rate_key(request)
            assert key == "user:op1"
            assert limit == 100

    def test_resolve_observer_30(self):
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=50)
        request = MagicMock()

        with patch("app.rate_limit._extract_user_from_request") as mock_extract:
            mock_extract.return_value = {"sub": "obs1", "role": "observer"}
            key, limit = middleware._resolve_rate_key(request)
            assert key == "user:obs1"
            assert limit == 30

    def test_resolve_unknown_role_uses_default(self):
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=50)
        request = MagicMock()

        with patch("app.rate_limit._extract_user_from_request") as mock_extract:
            mock_extract.return_value = {"sub": "user1", "role": "custom_role"}
            key, limit = middleware._resolve_rate_key(request)
            assert key == "user:user1"
            assert limit == 50  # Falls back to default

    def test_different_users_have_separate_counters(self):
        """Two users hitting the same middleware get independent counters."""
        middleware = RateLimitMiddleware(app=MagicMock(), max_requests=2)

        # Simulate entries for two different users
        entry_a = middleware._entries["user:alice"]
        entry_b = middleware._entries["user:bob"]

        # Alice uses 2 requests
        entry_a.check(2, 60)
        entry_a.check(2, 60)

        # Bob should still have capacity
        allowed, remaining = entry_b.check(2, 60)
        assert allowed
        assert remaining == 1
