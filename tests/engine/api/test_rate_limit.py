# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for rate limiting middleware."""

import pytest


class TestRateLimitEntry:
    def test_import(self):
        from app.rate_limit import RateLimitEntry
        assert RateLimitEntry is not None

    def test_allows_within_limit(self):
        from app.rate_limit import RateLimitEntry
        entry = RateLimitEntry()
        for _ in range(10):
            allowed, remaining = entry.check(10, 60)
            assert allowed

    def test_blocks_over_limit(self):
        from app.rate_limit import RateLimitEntry
        entry = RateLimitEntry()
        for _ in range(10):
            entry.check(10, 60)
        allowed, remaining = entry.check(10, 60)
        assert not allowed
        assert remaining == 0

    def test_remaining_decreases(self):
        from app.rate_limit import RateLimitEntry
        entry = RateLimitEntry()
        _, rem1 = entry.check(5, 60)
        _, rem2 = entry.check(5, 60)
        assert rem2 < rem1


class TestRateLimitMiddleware:
    def test_import(self):
        from app.rate_limit import RateLimitMiddleware
        assert RateLimitMiddleware is not None

    def test_exempt_paths(self):
        from app.rate_limit import EXEMPT_PATHS, EXEMPT_PREFIXES
        assert "/ws/live" in EXEMPT_PATHS
        assert "/health" in EXEMPT_PATHS
        assert any(p.startswith("/static") for p in EXEMPT_PREFIXES)


class TestBackupRouter:
    def test_import(self):
        from app.routers.backup import router
        assert router is not None


class TestMigrations:
    def test_import(self):
        from app.migrations import MigrationManager
        assert MigrationManager is not None

    def test_migration_files_exist(self):
        """Migration files should exist in the migrations package."""
        from pathlib import Path
        migrations_dir = Path(__file__).parent.parent.parent.parent / "src" / "app" / "migrations"
        migration_files = sorted(migrations_dir.glob("0*.py"))
        assert len(migration_files) >= 1, "No migration files found"

    def test_migrator_module(self):
        from app.migrations.migrator import MigrationManager
        assert callable(MigrationManager)
