# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for backup/restore API endpoints."""

import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("AMY_ENABLED", "false")
os.environ.setdefault("SIMULATION_ENABLED", "false")
os.environ.setdefault("MQTT_ENABLED", "false")
os.environ.setdefault("AUTH_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-key-32-chars-long-ok")


class TestBackupRouter:
    """Test backup API endpoints via router module functions."""

    def test_import_router(self):
        """Verify the backup router can be imported."""
        from app.routers.backup import router
        assert router is not None
        assert router.prefix == "/api/backup"

    def test_get_db_path(self):
        from app.routers.backup import _get_db_path
        path = _get_db_path()
        assert isinstance(path, Path)

    def test_get_manager(self):
        from app.routers.backup import _get_manager
        mgr = _get_manager()
        assert mgr is not None
        assert mgr.backup_dir.name == "backups"

    def test_shared_manager_singleton(self):
        import app.routers.backup as mod
        # Reset global
        mod._manager = None
        m1 = mod._shared_manager()
        m2 = mod._shared_manager()
        assert m1 is m2
        mod._manager = None  # cleanup

    def test_create_backup_request_model(self):
        from app.routers.backup import CreateBackupRequest
        req = CreateBackupRequest(label="nightly")
        assert req.label == "nightly"
        req2 = CreateBackupRequest()
        assert req2.label == ""

    def test_schedule_request_model(self):
        from app.routers.backup import ScheduleRequest
        req = ScheduleRequest(interval_hours=6.0)
        assert req.interval_hours == 6.0


class TestBackupManagerUnit:
    """Unit tests for BackupManager through the router's factory."""

    def test_export_and_list(self, tmp_path):
        from engine.backup.backup import BackupManager

        db_path = tmp_path / "tritium.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()

        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            db_path=db_path,
        )
        (tmp_path / "data").mkdir(exist_ok=True)

        archive = mgr.export_state(label="api-test")
        assert archive.exists()

        backups = mgr.list_backups()
        assert len(backups) == 1
        assert backups[0]["label"] == "api-test"

    def test_download_path_resolution(self, tmp_path):
        from engine.backup.backup import BackupManager

        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            db_path=tmp_path / "x.db",
        )
        assert mgr.get_backup_path("nonexistent") is None

    def test_restore_from_export(self, tmp_path):
        from engine.backup.backup import BackupManager

        db_path = tmp_path / "tritium.db"
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        conn.commit()
        conn.close()

        mgr = BackupManager(data_dir=data_dir, backup_dir=tmp_path / "backups", db_path=db_path)
        archive = mgr.export_state()

        # Destroy original
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM t")
        conn.commit()
        conn.close()

        report = mgr.import_state(archive)
        assert "tritium" in report["restored"]

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT id FROM t").fetchall()
        conn.close()
        assert rows == [(42,)]
