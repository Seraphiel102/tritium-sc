# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""VideoRecordingManager — records camera feed segments to disk.

Records camera JPEG frames into time-segmented files, indexes them
by timestamp and camera_id, and provides an API for listing and
playing back recorded segments.

Each recording segment is a directory containing sequential JPEG
frames plus a metadata JSON file with timing information.

Directory layout:
    {storage_root}/
        {camera_id}/
            {YYYY-MM-DD}/
                {HH-MM-SS}/
                    meta.json      — segment metadata
                    frame_0000.jpg — first frame
                    frame_0001.jpg — ...

Usage
-----
    mgr = VideoRecordingManager(storage_root="/data/recordings")
    mgr.start_recording("cam_01")
    mgr.add_frame("cam_01", jpeg_bytes)
    mgr.stop_recording("cam_01")
    segments = mgr.list_segments("cam_01")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_SEGMENT_DURATION = 300.0  # 5 minutes per segment
DEFAULT_MAX_FRAMES_PER_SEGMENT = 9000  # ~5 min at 30fps
DEFAULT_MAX_STORAGE_MB = 10000  # 10 GB


@dataclass
class RecordingSegment:
    """Metadata for a single recording segment."""

    segment_id: str
    camera_id: str
    start_time: float
    end_time: float = 0.0
    frame_count: int = 0
    size_bytes: int = 0
    path: str = ""
    status: str = "recording"  # recording, complete, error

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "camera_id": self.camera_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "frame_count": self.frame_count,
            "size_bytes": self.size_bytes,
            "duration_s": self.end_time - self.start_time if self.end_time else 0.0,
            "path": self.path,
            "status": self.status,
        }


@dataclass
class ActiveRecording:
    """State for an in-progress recording."""

    camera_id: str
    segment: RecordingSegment
    segment_dir: Path
    frame_index: int = 0
    started_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class VideoRecordingManager:
    """Manages video recording for multiple camera feeds.

    Thread-safe. Supports concurrent recording from multiple cameras.

    Parameters
    ----------
    storage_root:
        Root directory for all recordings.
    segment_duration:
        Maximum duration (seconds) per segment before auto-rotation.
    max_storage_mb:
        Maximum total storage usage in megabytes.
    """

    def __init__(
        self,
        storage_root: str | Path = "/tmp/tritium_recordings",
        segment_duration: float = DEFAULT_SEGMENT_DURATION,
        max_storage_mb: float = DEFAULT_MAX_STORAGE_MB,
    ) -> None:
        self._storage_root = Path(storage_root)
        self._segment_duration = segment_duration
        self._max_storage_mb = max_storage_mb

        self._lock = threading.Lock()
        self._active: dict[str, ActiveRecording] = {}
        self._segment_index: list[RecordingSegment] = []

        # Create storage root
        self._storage_root.mkdir(parents=True, exist_ok=True)

        # Load existing segment index
        self._scan_existing_segments()

    # -- Recording control -------------------------------------------------

    def start_recording(self, camera_id: str) -> dict:
        """Start recording frames from a camera.

        Returns the segment metadata dict.
        """
        with self._lock:
            if camera_id in self._active:
                return self._active[camera_id].segment.to_dict()

        # Create segment directory
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")
        segment_id = f"{camera_id}_{date_str}_{time_str}"

        segment_dir = self._storage_root / camera_id / date_str / time_str
        segment_dir.mkdir(parents=True, exist_ok=True)

        segment = RecordingSegment(
            segment_id=segment_id,
            camera_id=camera_id,
            start_time=time.time(),
            path=str(segment_dir),
            status="recording",
        )

        recording = ActiveRecording(
            camera_id=camera_id,
            segment=segment,
            segment_dir=segment_dir,
        )

        with self._lock:
            self._active[camera_id] = recording

        logger.info("Started recording: %s -> %s", camera_id, segment_dir)
        return segment.to_dict()

    def stop_recording(self, camera_id: str) -> Optional[dict]:
        """Stop recording for a camera.

        Returns the completed segment metadata, or None if not recording.
        """
        with self._lock:
            recording = self._active.pop(camera_id, None)

        if recording is None:
            return None

        segment = recording.segment
        segment.end_time = time.time()
        segment.status = "complete"

        # Write metadata file
        self._write_segment_meta(recording.segment_dir, segment)

        with self._lock:
            self._segment_index.append(segment)

        logger.info(
            "Stopped recording: %s (%d frames, %.1fs)",
            camera_id,
            segment.frame_count,
            segment.end_time - segment.start_time,
        )
        return segment.to_dict()

    def add_frame(self, camera_id: str, jpeg_data: bytes) -> bool:
        """Add a JPEG frame to the active recording for a camera.

        Returns True if the frame was recorded, False if not recording
        or if the segment rotated.
        """
        with self._lock:
            recording = self._active.get(camera_id)

        if recording is None:
            return False

        with recording.lock:
            # Check if segment needs rotation
            elapsed = time.time() - recording.segment.start_time
            if (
                elapsed >= self._segment_duration
                or recording.frame_index >= DEFAULT_MAX_FRAMES_PER_SEGMENT
            ):
                self._rotate_segment(camera_id)
                with self._lock:
                    recording = self._active.get(camera_id)
                if recording is None:
                    return False

            # Write frame
            frame_path = (
                recording.segment_dir
                / f"frame_{recording.frame_index:04d}.jpg"
            )
            try:
                frame_path.write_bytes(jpeg_data)
                recording.frame_index += 1
                recording.segment.frame_count = recording.frame_index
                recording.segment.size_bytes += len(jpeg_data)
                return True
            except Exception as exc:
                logger.error("Failed to write frame: %s", exc)
                return False

    def is_recording(self, camera_id: str) -> bool:
        """Check if a camera is currently recording."""
        with self._lock:
            return camera_id in self._active

    def get_active_recordings(self) -> list[dict]:
        """Get all active recordings."""
        with self._lock:
            return [r.segment.to_dict() for r in self._active.values()]

    # -- Segment queries ---------------------------------------------------

    def list_segments(
        self,
        camera_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict]:
        """List recording segments, optionally filtered.

        Args:
            camera_id: Filter by camera ID.
            start_time: Only segments starting after this time.
            end_time: Only segments ending before this time.
            limit: Maximum results.
        """
        with self._lock:
            segments = list(self._segment_index)

        # Apply filters
        if camera_id:
            segments = [s for s in segments if s.camera_id == camera_id]
        if start_time is not None:
            segments = [s for s in segments if s.start_time >= start_time]
        if end_time is not None:
            segments = [
                s for s in segments if s.end_time <= end_time or s.end_time == 0
            ]

        # Sort by start_time descending (most recent first)
        segments.sort(key=lambda s: s.start_time, reverse=True)

        return [s.to_dict() for s in segments[:limit]]

    def get_segment(self, segment_id: str) -> Optional[dict]:
        """Get metadata for a specific segment."""
        with self._lock:
            for s in self._segment_index:
                if s.segment_id == segment_id:
                    return s.to_dict()
        return None

    def get_frame(
        self, segment_id: str, frame_index: int
    ) -> Optional[bytes]:
        """Get a specific frame from a segment.

        Returns JPEG bytes or None.
        """
        with self._lock:
            segment = None
            for s in self._segment_index:
                if s.segment_id == segment_id:
                    segment = s
                    break

        if segment is None:
            return None

        frame_path = Path(segment.path) / f"frame_{frame_index:04d}.jpg"
        if frame_path.exists():
            return frame_path.read_bytes()
        return None

    def get_frames_in_range(
        self, camera_id: str, start_time: float, end_time: float
    ) -> list[dict]:
        """Get frame references within a time range.

        Returns list of {segment_id, frame_index, timestamp} dicts.
        """
        segments = self.list_segments(
            camera_id=camera_id, start_time=start_time, end_time=end_time
        )
        frames = []
        for seg in segments:
            if seg["frame_count"] == 0:
                continue
            duration = seg["duration_s"]
            if duration <= 0:
                continue
            fps = seg["frame_count"] / duration
            for i in range(seg["frame_count"]):
                frame_time = seg["start_time"] + (i / fps)
                if start_time <= frame_time <= end_time:
                    frames.append({
                        "segment_id": seg["segment_id"],
                        "frame_index": i,
                        "timestamp": frame_time,
                    })
        return frames

    def delete_segment(self, segment_id: str) -> bool:
        """Delete a recording segment and its files.

        Returns True if deleted.
        """
        with self._lock:
            segment = None
            for i, s in enumerate(self._segment_index):
                if s.segment_id == segment_id:
                    segment = s
                    self._segment_index.pop(i)
                    break

        if segment is None:
            return False

        # Delete files
        seg_path = Path(segment.path)
        if seg_path.exists():
            import shutil
            shutil.rmtree(seg_path, ignore_errors=True)

        return True

    def get_storage_usage(self) -> dict:
        """Get total storage usage statistics."""
        total_bytes = 0
        total_segments = 0
        total_frames = 0
        cameras: set[str] = set()

        with self._lock:
            for s in self._segment_index:
                total_bytes += s.size_bytes
                total_segments += 1
                total_frames += s.frame_count
                cameras.add(s.camera_id)

        return {
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "total_segments": total_segments,
            "total_frames": total_frames,
            "cameras": len(cameras),
            "max_storage_mb": self._max_storage_mb,
            "usage_pct": round(
                total_bytes / (self._max_storage_mb * 1024 * 1024) * 100, 2
            )
            if self._max_storage_mb > 0
            else 0.0,
        }

    # -- Internal ----------------------------------------------------------

    def _rotate_segment(self, camera_id: str) -> None:
        """Complete current segment and start a new one."""
        self.stop_recording(camera_id)
        self.start_recording(camera_id)

    def _write_segment_meta(
        self, segment_dir: Path, segment: RecordingSegment
    ) -> None:
        """Write segment metadata to disk."""
        meta_path = segment_dir / "meta.json"
        try:
            meta_path.write_text(json.dumps(segment.to_dict(), indent=2))
        except Exception as exc:
            logger.error("Failed to write segment meta: %s", exc)

    def _scan_existing_segments(self) -> None:
        """Scan storage root for existing segment directories."""
        if not self._storage_root.exists():
            return

        for camera_dir in self._storage_root.iterdir():
            if not camera_dir.is_dir():
                continue
            camera_id = camera_dir.name
            for date_dir in camera_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                for time_dir in date_dir.iterdir():
                    if not time_dir.is_dir():
                        continue
                    meta_file = time_dir / "meta.json"
                    if meta_file.exists():
                        try:
                            meta = json.loads(meta_file.read_text())
                            segment = RecordingSegment(
                                segment_id=meta.get(
                                    "segment_id",
                                    f"{camera_id}_{date_dir.name}_{time_dir.name}",
                                ),
                                camera_id=meta.get("camera_id", camera_id),
                                start_time=meta.get("start_time", 0.0),
                                end_time=meta.get("end_time", 0.0),
                                frame_count=meta.get("frame_count", 0),
                                size_bytes=meta.get("size_bytes", 0),
                                path=str(time_dir),
                                status=meta.get("status", "complete"),
                            )
                            self._segment_index.append(segment)
                        except Exception as exc:
                            logger.warning(
                                "Failed to load segment meta %s: %s",
                                meta_file,
                                exc,
                            )
