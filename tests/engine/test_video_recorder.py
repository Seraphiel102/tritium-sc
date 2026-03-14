# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for the video recording manager."""

import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

import sys

_sc_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_sc_root / "src"))

from engine.media.recorder import (
    VideoRecordingManager,
    RecordingSegment,
    DEFAULT_SEGMENT_DURATION,
)


@pytest.fixture
def tmp_storage(tmp_path):
    """Temporary storage directory."""
    return tmp_path / "recordings"


@pytest.fixture
def mgr(tmp_storage):
    """Create a VideoRecordingManager with temp storage."""
    return VideoRecordingManager(storage_root=str(tmp_storage))


@pytest.fixture
def fake_jpeg():
    """Fake JPEG data (just some bytes)."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


# -- Basic recording tests ------------------------------------------------

class TestRecordingBasics:
    def test_start_recording(self, mgr):
        result = mgr.start_recording("cam_01")
        assert result["camera_id"] == "cam_01"
        assert result["status"] == "recording"
        assert mgr.is_recording("cam_01")

    def test_stop_recording(self, mgr):
        mgr.start_recording("cam_01")
        result = mgr.stop_recording("cam_01")
        assert result is not None
        assert result["status"] == "complete"
        assert not mgr.is_recording("cam_01")

    def test_stop_nonexistent(self, mgr):
        result = mgr.stop_recording("cam_nonexistent")
        assert result is None

    def test_double_start(self, mgr):
        r1 = mgr.start_recording("cam_01")
        r2 = mgr.start_recording("cam_01")
        assert r1["segment_id"] == r2["segment_id"]

    def test_is_recording(self, mgr):
        assert not mgr.is_recording("cam_01")
        mgr.start_recording("cam_01")
        assert mgr.is_recording("cam_01")
        mgr.stop_recording("cam_01")
        assert not mgr.is_recording("cam_01")


# -- Frame recording tests ------------------------------------------------

class TestFrameRecording:
    def test_add_frame(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        assert mgr.add_frame("cam_01", fake_jpeg) is True

    def test_add_frame_no_recording(self, mgr, fake_jpeg):
        assert mgr.add_frame("cam_01", fake_jpeg) is False

    def test_frame_count(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        for _ in range(5):
            mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")
        assert result["frame_count"] == 5

    def test_frame_files_on_disk(self, mgr, fake_jpeg, tmp_storage):
        mgr.start_recording("cam_01")
        for _ in range(3):
            mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        seg_path = Path(result["path"])
        assert (seg_path / "frame_0000.jpg").exists()
        assert (seg_path / "frame_0001.jpg").exists()
        assert (seg_path / "frame_0002.jpg").exists()
        assert (seg_path / "meta.json").exists()

    def test_frame_size_tracking(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")
        assert result["size_bytes"] == len(fake_jpeg)

    def test_multiple_cameras(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.start_recording("cam_02")
        mgr.add_frame("cam_01", fake_jpeg)
        mgr.add_frame("cam_01", fake_jpeg)
        mgr.add_frame("cam_02", fake_jpeg)
        r1 = mgr.stop_recording("cam_01")
        r2 = mgr.stop_recording("cam_02")
        assert r1["frame_count"] == 2
        assert r2["frame_count"] == 1


# -- Segment query tests --------------------------------------------------

class TestSegmentQueries:
    def test_list_segments(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        mgr.stop_recording("cam_01")
        segments = mgr.list_segments()
        assert len(segments) == 1
        assert segments[0]["camera_id"] == "cam_01"

    def test_list_by_camera(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        mgr.stop_recording("cam_01")

        mgr.start_recording("cam_02")
        mgr.add_frame("cam_02", fake_jpeg)
        mgr.stop_recording("cam_02")

        segments = mgr.list_segments(camera_id="cam_01")
        assert len(segments) == 1
        assert segments[0]["camera_id"] == "cam_01"

    def test_get_segment(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        seg = mgr.get_segment(result["segment_id"])
        assert seg is not None
        assert seg["segment_id"] == result["segment_id"]

    def test_get_nonexistent_segment(self, mgr):
        assert mgr.get_segment("nonexistent") is None


# -- Frame retrieval tests -------------------------------------------------

class TestFrameRetrieval:
    def test_get_frame(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        frame = mgr.get_frame(result["segment_id"], 0)
        assert frame == fake_jpeg

    def test_get_frame_out_of_range(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        frame = mgr.get_frame(result["segment_id"], 999)
        assert frame is None

    def test_get_frame_nonexistent_segment(self, mgr):
        frame = mgr.get_frame("nonexistent", 0)
        assert frame is None


# -- Deletion tests --------------------------------------------------------

class TestDeletion:
    def test_delete_segment(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        seg_path = Path(result["path"])
        assert seg_path.exists()

        deleted = mgr.delete_segment(result["segment_id"])
        assert deleted is True
        assert not seg_path.exists()

        segments = mgr.list_segments()
        assert len(segments) == 0

    def test_delete_nonexistent(self, mgr):
        assert mgr.delete_segment("nonexistent") is False


# -- Storage stats tests ---------------------------------------------------

class TestStorageStats:
    def test_initial_stats(self, mgr):
        stats = mgr.get_storage_usage()
        assert stats["total_bytes"] == 0
        assert stats["total_segments"] == 0

    def test_stats_after_recording(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        for _ in range(3):
            mgr.add_frame("cam_01", fake_jpeg)
        mgr.stop_recording("cam_01")

        stats = mgr.get_storage_usage()
        assert stats["total_bytes"] == len(fake_jpeg) * 3
        assert stats["total_segments"] == 1
        assert stats["total_frames"] == 3
        assert stats["cameras"] == 1

    def test_stats_multiple_cameras(self, mgr, fake_jpeg):
        for cam in ["cam_01", "cam_02"]:
            mgr.start_recording(cam)
            mgr.add_frame(cam, fake_jpeg)
            mgr.stop_recording(cam)

        stats = mgr.get_storage_usage()
        assert stats["cameras"] == 2
        assert stats["total_segments"] == 2


# -- Active recordings tests -----------------------------------------------

class TestActiveRecordings:
    def test_get_active(self, mgr):
        assert mgr.get_active_recordings() == []
        mgr.start_recording("cam_01")
        active = mgr.get_active_recordings()
        assert len(active) == 1
        assert active[0]["camera_id"] == "cam_01"

    def test_active_after_stop(self, mgr):
        mgr.start_recording("cam_01")
        mgr.stop_recording("cam_01")
        assert mgr.get_active_recordings() == []


# -- Persistence tests -----------------------------------------------------

class TestPersistence:
    def test_meta_json_written(self, mgr, fake_jpeg):
        mgr.start_recording("cam_01")
        mgr.add_frame("cam_01", fake_jpeg)
        result = mgr.stop_recording("cam_01")

        meta_path = Path(result["path"]) / "meta.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["camera_id"] == "cam_01"
        assert meta["frame_count"] == 1

    def test_reload_segments(self, tmp_storage, fake_jpeg):
        """New manager instance should discover existing segments."""
        mgr1 = VideoRecordingManager(storage_root=str(tmp_storage))
        mgr1.start_recording("cam_01")
        mgr1.add_frame("cam_01", fake_jpeg)
        mgr1.stop_recording("cam_01")

        # Create a new manager on the same storage
        mgr2 = VideoRecordingManager(storage_root=str(tmp_storage))
        segments = mgr2.list_segments()
        assert len(segments) == 1
        assert segments[0]["camera_id"] == "cam_01"


# -- RecordingSegment dataclass tests --------------------------------------

class TestRecordingSegment:
    def test_to_dict(self):
        seg = RecordingSegment(
            segment_id="test_seg",
            camera_id="cam_01",
            start_time=1000.0,
            end_time=1300.0,
            frame_count=100,
            size_bytes=50000,
            path="/tmp/test",
            status="complete",
        )
        d = seg.to_dict()
        assert d["segment_id"] == "test_seg"
        assert d["duration_s"] == 300.0
        assert d["frame_count"] == 100
