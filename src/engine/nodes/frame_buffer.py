# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Shared frame buffer for video capture nodes.

Extracted from bcc950.py -- used by BCC950Node and IPCameraNode.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np


class FrameBuffer:
    """Continuously reads frames from VideoCapture into a shared buffer.

    All consumers (MJPEG stream, YOLO, deep think) read from the buffer
    instead of the camera directly.  Uses non-blocking acquire on cap_lock
    so it coexists with MotionVerifier.
    """

    def __init__(self, cap: cv2.VideoCapture, cap_lock: threading.Lock):
        self._cap = cap
        self._cap_lock = cap_lock
        self._frame: np.ndarray | None = None
        self._jpeg: bytes | None = None
        self._frame_time: float = 0.0
        self._frame_id: int = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    @property
    def frame(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    @property
    def frame_id(self) -> int:
        with self._lock:
            return self._frame_id

    @property
    def frame_age(self) -> float:
        with self._lock:
            return time.monotonic() - self._frame_time if self._frame_time > 0 else float("inf")

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._cap_lock.acquire(blocking=False):
                try:
                    ret, frame = self._cap.read()
                finally:
                    self._cap_lock.release()
                if ret and frame is not None:
                    frame = frame.copy()
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    with self._lock:
                        self._frame = frame
                        self._jpeg = buf.tobytes()
                        self._frame_time = time.monotonic()
                        self._frame_id += 1
            time.sleep(0.033)  # ~30 fps


class ReconnectingFrameBuffer:
    """Frame buffer with automatic RTSP reconnection.

    When consecutive read failures exceed the threshold, releases the
    capture and reopens with exponential backoff.

    RTSP probing is non-blocking: ``start()`` launches a background
    thread that performs the initial ``cv2.VideoCapture()`` open, so the
    caller never blocks waiting for an unreachable camera.
    """

    FAILURE_THRESHOLD = 10
    BACKOFF_BASE = 1.0
    BACKOFF_MAX = 30.0
    OPEN_TIMEOUT = 3.0  # seconds — max time for initial RTSP probe

    def __init__(self, url: str):
        self._url = url
        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._jpeg: bytes | None = None
        self._frame_time: float = 0.0
        self._frame_id: int = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._consecutive_failures: int = 0
        self._reconnect_count: int = 0

    def start(self) -> None:
        # Don't block on RTSP probe — the background thread will open
        # the capture as its first action, with reconnect on failure.
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def frame(self) -> np.ndarray | None:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    @property
    def frame_id(self) -> int:
        with self._lock:
            return self._frame_id

    @property
    def frame_age(self) -> float:
        with self._lock:
            return time.monotonic() - self._frame_time if self._frame_time > 0 else float("inf")

    def _run(self) -> None:
        # Initial open without backoff delay — only timeout-guarded
        if self._cap is None and not self._stop.is_set():
            self._cap = self._open_with_timeout(self._url)

        while not self._stop.is_set():
            if self._cap is None or not self._cap.isOpened():
                self._reconnect()
                continue

            ret, frame = self._cap.read()
            if ret and frame is not None:
                self._consecutive_failures = 0
                frame = frame.copy()
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                with self._lock:
                    self._frame = frame
                    self._jpeg = buf.tobytes()
                    self._frame_time = time.monotonic()
                    self._frame_id += 1
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.FAILURE_THRESHOLD:
                    self._reconnect()
                    continue

            time.sleep(0.033)

    def _reconnect(self) -> None:
        """Release and reopen the capture with exponential backoff."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        delay = min(
            self.BACKOFF_BASE * (2 ** self._reconnect_count),
            self.BACKOFF_MAX,
        )
        self._reconnect_count += 1
        self._consecutive_failures = 0

        # Wait with stop check (break into 0.1s increments)
        waited = 0.0
        while waited < delay and not self._stop.is_set():
            time.sleep(min(0.1, delay - waited))
            waited += 0.1

        if not self._stop.is_set():
            self._cap = self._open_with_timeout(self._url)

    def _open_with_timeout(self, url: str) -> cv2.VideoCapture | None:
        """Open a VideoCapture with a timeout to avoid blocking.

        Runs cv2.VideoCapture in a helper thread with a deadline of
        OPEN_TIMEOUT seconds.  Returns the capture if opened in time,
        else None.
        """
        result: list[cv2.VideoCapture | None] = [None]

        def _do_open():
            cap = cv2.VideoCapture(url)
            result[0] = cap

        opener = threading.Thread(target=_do_open, daemon=True, name="rtsp-open")
        opener.start()
        opener.join(timeout=self.OPEN_TIMEOUT)

        if opener.is_alive():
            return None

        cap = result[0]
        if cap is not None and cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap

        if cap is not None:
            cap.release()
        return None
