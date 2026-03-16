# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for API key scoping — read-only, full, admin access levels."""

import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.auth import (
    APIKeyStore,
    _check_api_key_scope,
    READ_ONLY_METHODS,
)


class TestAPIKeyStoreScopes:
    """API key creation with scopes."""

    def test_create_key_default_scope_is_full(self):
        store = APIKeyStore()
        result = store.create_key(name="test")
        assert result["scope"] == "full"

    def test_create_key_read_only_scope(self):
        store = APIKeyStore()
        result = store.create_key(name="reader", scope="read-only")
        assert result["scope"] == "read-only"

    def test_create_key_admin_scope(self):
        store = APIKeyStore()
        result = store.create_key(name="super", scope="admin")
        assert result["scope"] == "admin"

    def test_create_key_invalid_scope_defaults_to_full(self):
        store = APIKeyStore()
        result = store.create_key(name="bad", scope="invalid_scope")
        assert result["scope"] == "full"

    def test_validate_returns_scope(self):
        store = APIKeyStore()
        result = store.create_key(name="scoped", scope="read-only")
        api_key = result["api_key"]
        user = store.validate(api_key)
        assert user is not None
        assert user["scope"] == "read-only"

    def test_validate_full_scope(self):
        store = APIKeyStore()
        result = store.create_key(name="full_key", scope="full")
        user = store.validate(result["api_key"])
        assert user["scope"] == "full"

    def test_validate_admin_scope(self):
        store = APIKeyStore()
        result = store.create_key(name="admin_key", scope="admin")
        user = store.validate(result["api_key"])
        assert user["scope"] == "admin"

    def test_scope_persists_after_rotation(self):
        store = APIKeyStore()
        result = store.create_key(name="rotated", scope="read-only")
        key_id = result["key_id"]
        new_result = store.rotate_key(key_id)
        assert new_result is not None
        # Validate new key
        user = store.validate(new_result["api_key"])
        assert user is not None
        assert user["scope"] == "read-only"

    def test_scope_in_list_keys(self):
        store = APIKeyStore()
        store.create_key(name="k1", scope="read-only")
        store.create_key(name="k2", scope="admin")
        keys = store.list_keys()
        scopes = {k["name"]: k["scope"] for k in keys}
        assert scopes["k1"] == "read-only"
        assert scopes["k2"] == "admin"


class TestCheckAPIKeyScope:
    """Scope enforcement logic."""

    def test_full_scope_allows_all_methods(self):
        user = {"scope": "full"}
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            request = MagicMock()
            request.method = method
            # Should not raise
            _check_api_key_scope(user, request)

    def test_admin_scope_allows_all_methods(self):
        user = {"scope": "admin"}
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            request = MagicMock()
            request.method = method
            _check_api_key_scope(user, request)

    def test_no_scope_allows_all(self):
        """Backward compatibility: user dict without scope field."""
        user = {"sub": "legacy_key"}
        request = MagicMock()
        request.method = "DELETE"
        _check_api_key_scope(user, request)

    def test_read_only_allows_get(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "GET"
        _check_api_key_scope(user, request)

    def test_read_only_allows_head(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "HEAD"
        _check_api_key_scope(user, request)

    def test_read_only_allows_options(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "OPTIONS"
        _check_api_key_scope(user, request)

    def test_read_only_blocks_post(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "POST"
        with pytest.raises(HTTPException) as exc_info:
            _check_api_key_scope(user, request)
        assert exc_info.value.status_code == 403
        assert "read-only" in str(exc_info.value.detail)

    def test_read_only_blocks_delete(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "DELETE"
        with pytest.raises(HTTPException) as exc_info:
            _check_api_key_scope(user, request)
        assert exc_info.value.status_code == 403

    def test_read_only_blocks_put(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "PUT"
        with pytest.raises(HTTPException) as exc_info:
            _check_api_key_scope(user, request)
        assert exc_info.value.status_code == 403

    def test_read_only_blocks_patch(self):
        user = {"scope": "read-only"}
        request = MagicMock()
        request.method = "PATCH"
        with pytest.raises(HTTPException) as exc_info:
            _check_api_key_scope(user, request)
        assert exc_info.value.status_code == 403


class TestReadOnlyMethods:
    """READ_ONLY_METHODS constant."""

    def test_contains_get(self):
        assert "GET" in READ_ONLY_METHODS

    def test_contains_head(self):
        assert "HEAD" in READ_ONLY_METHODS

    def test_contains_options(self):
        assert "OPTIONS" in READ_ONLY_METHODS

    def test_does_not_contain_post(self):
        assert "POST" not in READ_ONLY_METHODS
