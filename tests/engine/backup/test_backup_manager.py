# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for BackupManager — export, import, list, schedule."""

import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from engine.backup.backup import BackupManager, MANIFEST_VERSION


@pytest.fixture
def backup_env(tmp_path):
    """Create a realistic backup environment with databases and data files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    backup_dir = tmp_path / "data" / "backups"
    backup_dir.mkdir()
    db_path = tmp_path / "tritium.db"

    # Create a SQLite database with some data
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE targets (id TEXT, name TEXT)")
    conn.execute("INSERT INTO targets VALUES ('t1', 'Alpha')")
    conn.execute("INSERT INTO targets VALUES ('t2', 'Bravo')")
    conn.commit()
    conn.close()

    # Create dossiers database
    dossier_db = data_dir / "dossiers.db"
    conn = sqlite3.connect(str(dossier_db))
    conn.execute("CREATE TABLE dossiers (target_id TEXT, notes TEXT)")
    conn.execute("INSERT INTO dossiers VALUES ('t1', 'Known friendly')")
    conn.commit()
    conn.close()

    # Create Amy memory
    amy_dir = data_dir / "amy"
    amy_dir.mkdir()
    amy_mem = amy_dir / "memory.json"
    amy_mem.write_text(json.dumps({"facts": ["sky is blue"], "mood": "vigilant"}))

    # Create Amy transcripts
    transcript_dir = amy_dir / "transcripts"
    transcript_dir.mkdir()
    (transcript_dir / "2026-03-14.jsonl").write_text('{"role":"amy","text":"Online"}\n')

    # Create config files
    (data_dir / "automation_rules.json").write_text(json.dumps([{"if": "motion", "then": "alert"}]))
    (data_dir / "geofence_zones.json").write_text(json.dumps([{"name": "HQ", "radius": 50}]))

    # Create plugin state
    plugin_dir = data_dir / "plugins"
    plugin_dir.mkdir()
    threat_dir = plugin_dir / "threat_feeds"
    threat_dir.mkdir()
    (threat_dir / "indicators.json").write_text(json.dumps({"bad_macs": ["aa:bb:cc:dd:ee:ff"]}))

    # Create backstories
    bs_dir = data_dir / "backstories"
    bs_dir.mkdir()
    (bs_dir / "index.json").write_text(json.dumps({"default": "patrol"}))

    mgr = BackupManager(
        data_dir=data_dir,
        backup_dir=backup_dir,
        db_path=db_path,
    )
    return mgr, tmp_path, data_dir, db_path


class TestExportState:
    """Test backup export functionality."""

    def test_export_creates_zip(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        assert archive.exists()
        assert archive.suffix == ".zip"
        assert archive.stat().st_size > 0

    def test_export_contains_manifest(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            assert "manifest.json" in zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == MANIFEST_VERSION
            assert "created_at" in manifest
            assert "contents" in manifest

    def test_export_contains_databases(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert "databases/tritium.db" in names
            assert "databases/dossiers.db" in names

    def test_export_database_is_valid_sqlite(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            db_bytes = zf.read("databases/tritium.db")
            # Write to temp and verify it's a valid SQLite db
            tmp_db = tmp_path / "check.db"
            tmp_db.write_bytes(db_bytes)
            conn = sqlite3.connect(str(tmp_db))
            rows = conn.execute("SELECT * FROM targets").fetchall()
            conn.close()
            assert len(rows) == 2
            assert rows[0] == ("t1", "Alpha")

    def test_export_contains_amy_memory(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            mem = json.loads(zf.read("amy/memory.json"))
            assert mem["mood"] == "vigilant"

    def test_export_contains_transcripts(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert any("transcripts" in n for n in names)

    def test_export_contains_configuration(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            config = json.loads(zf.read("config/state.json"))
            assert "automation_rules" in config
            assert "geofence_zones" in config

    def test_export_contains_plugin_state(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert any("plugins/" in n for n in names)

    def test_export_contains_backstories(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert any("backstories/" in n for n in names)

    def test_export_with_label(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state(label="pre-deploy")
        assert "pre-deploy" in archive.name
        with zipfile.ZipFile(archive, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["label"] == "pre-deploy"

    def test_export_no_database(self, tmp_path):
        """Export with missing database should still create archive."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mgr = BackupManager(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups",
            db_path=tmp_path / "nonexistent.db",
        )
        archive = mgr.export_state()
        assert archive.exists()
        with zipfile.ZipFile(archive, "r") as zf:
            assert "manifest.json" in zf.namelist()
            assert "databases/tritium.db" not in zf.namelist()


class TestImportState:
    """Test backup import/restore functionality."""

    def test_round_trip(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()

        # Corrupt the current database
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM targets")
        conn.commit()
        conn.close()

        # Restore
        report = mgr.import_state(archive)
        assert "tritium" in report["restored"]
        assert len(report["errors"]) == 0

        # Verify database is restored
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM targets").fetchall()
        conn.close()
        assert len(rows) == 2

    def test_restore_amy_memory(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()

        # Delete Amy memory
        amy_mem = data_dir / "amy" / "memory.json"
        amy_mem.unlink()
        assert not amy_mem.exists()

        # Restore
        report = mgr.import_state(archive)
        assert "amy_memory" in report["restored"]
        assert amy_mem.exists()
        mem = json.loads(amy_mem.read_text())
        assert mem["mood"] == "vigilant"

    def test_restore_creates_pre_restore_backup(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        archive = mgr.export_state()
        mgr.import_state(archive)

        # Should have a pre_restore directory with original db
        pre_dirs = list((data_dir / "backups").glob("pre_restore_*"))
        assert len(pre_dirs) >= 1

    def test_restore_invalid_archive(self, backup_env, tmp_path):
        mgr, _, _, _ = backup_env
        bad_file = tmp_path / "bad.zip"
        bad_file.write_text("not a zip")
        with pytest.raises(Exception):
            mgr.import_state(bad_file)

    def test_restore_missing_manifest(self, backup_env, tmp_path):
        mgr, _, _, _ = backup_env
        bad_zip = tmp_path / "no_manifest.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("random.txt", "hello")
        with pytest.raises(ValueError, match="missing manifest"):
            mgr.import_state(bad_zip)

    def test_restore_unsupported_version(self, backup_env, tmp_path):
        mgr, _, _, _ = backup_env
        bad_zip = tmp_path / "bad_version.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"version": "99.0"}))
        with pytest.raises(ValueError, match="Unsupported"):
            mgr.import_state(bad_zip)

    def test_restore_file_not_found(self, backup_env, tmp_path):
        mgr, _, _, _ = backup_env
        with pytest.raises(ValueError, match="not found"):
            mgr.import_state(tmp_path / "ghost.zip")

    def test_restore_v1_compat(self, backup_env, tmp_path):
        """v1 backups had the db at root level, not databases/."""
        mgr, _, data_dir, db_path = backup_env
        v1_zip = tmp_path / "v1_backup.zip"
        with zipfile.ZipFile(v1_zip, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"version": "1.0"}))
            # v1 format: db at root
            zf.write(str(db_path), db_path.name)

        # Corrupt current db
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM targets")
        conn.commit()
        conn.close()

        report = mgr.import_state(v1_zip)
        assert "tritium" in report["restored"]


class TestListBackups:
    """Test backup listing."""

    def test_list_empty(self, tmp_path):
        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "backups",
            db_path=tmp_path / "x.db",
        )
        assert mgr.list_backups() == []

    def test_list_after_export(self, backup_env):
        mgr, _, _, _ = backup_env
        mgr.export_state(label="test1")
        mgr.export_state(label="test2")
        backups = mgr.list_backups()
        assert len(backups) == 2
        # Newest first
        assert "test2" in backups[0]["filename"]
        assert "test1" in backups[1]["filename"]

    def test_list_contains_metadata(self, backup_env):
        mgr, _, _, _ = backup_env
        mgr.export_state(label="meta-test")
        backups = mgr.list_backups()
        b = backups[0]
        assert "id" in b
        assert "filename" in b
        assert "size_bytes" in b
        assert "created_at" in b
        assert b["label"] == "meta-test"
        assert b["version"] == MANIFEST_VERSION


class TestGetBackupPath:
    """Test backup path resolution."""

    def test_existing_backup(self, backup_env):
        mgr, _, _, _ = backup_env
        archive = mgr.export_state()
        path = mgr.get_backup_path(archive.stem)
        assert path == archive

    def test_nonexistent_backup(self, backup_env):
        mgr, _, _, _ = backup_env
        assert mgr.get_backup_path("nonexistent") is None


class TestScheduler:
    """Test auto-backup scheduler."""

    def test_schedule_starts_thread(self, backup_env):
        mgr, _, _, _ = backup_env
        assert not mgr.scheduler_active
        mgr.schedule(24)
        assert mgr.scheduler_active
        mgr.stop_schedule()
        assert not mgr.scheduler_active

    def test_schedule_invalid_interval(self, backup_env):
        mgr, _, _, _ = backup_env
        with pytest.raises(ValueError):
            mgr.schedule(0)
        with pytest.raises(ValueError):
            mgr.schedule(-1)

    def test_stop_without_start(self, backup_env):
        mgr, _, _, _ = backup_env
        mgr.stop_schedule()  # Should not raise

    def test_reschedule_replaces(self, backup_env):
        mgr, _, _, _ = backup_env
        mgr.schedule(12)
        assert mgr.scheduler_active
        mgr.schedule(24)
        assert mgr.scheduler_active
        mgr.stop_schedule()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_export_with_special_label_chars(self, backup_env):
        mgr, _, _, _ = backup_env
        archive = mgr.export_state(label="test/backup 2026!")
        assert archive.exists()
        # Special chars should be sanitized
        assert "/" not in archive.stem.split("tritium_backup_")[-1]

    def test_export_creates_backup_dir(self, tmp_path):
        """Backup dir should be auto-created if missing."""
        mgr = BackupManager(
            data_dir=tmp_path / "data",
            backup_dir=tmp_path / "new_backups",
            db_path=tmp_path / "x.db",
        )
        assert (tmp_path / "new_backups").exists()

    def test_kuzu_directory_backup(self, backup_env):
        mgr, tmp_path, data_dir, db_path = backup_env
        # Create fake KuzuDB directory
        kuzu_dir = data_dir / "kuzu"
        kuzu_dir.mkdir()
        (kuzu_dir / "nodes.bin").write_bytes(b"\x00\x01\x02")
        (kuzu_dir / "rels.bin").write_bytes(b"\x03\x04\x05")

        archive = mgr.export_state()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert any("graph/kuzu" in n for n in names)
            manifest = json.loads(zf.read("manifest.json"))
            assert "kuzu_graph" in manifest["contents"]

    def test_prune_old_backups(self, backup_env):
        mgr, _, _, _ = backup_env
        # Create 12 auto backups with unique names directly
        for i in range(12):
            name = f"tritium_backup_20260314_{i:06d}_auto.zip"
            path = mgr.backup_dir / name
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("manifest.json", json.dumps({"version": "2.0"}))
        auto_backups = list(mgr.backup_dir.glob("*_auto.zip"))
        assert len(auto_backups) == 12

        mgr._prune_old_backups(keep=5)
        remaining = list(mgr.backup_dir.glob("*_auto.zip"))
        assert len(remaining) == 5
