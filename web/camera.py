# -*- coding: utf-8 -*-
"""
web/camera.py
-------------
Shared camera singleton.

Opens the Pi camera exactly once in a background thread and continuously
buffers the latest frame.  All consumers (MJPEG streamer, game detector,
mask preview) call get_frame() without ever touching VideoCapture themselves.

Device selection
----------------
Tries /dev/video0 then /dev/video1 with the V4L2 backend.  If the first
open fails it retries every 2 s so that a transient lock (e.g. another
process releasing the device) is recovered automatically.

Usage
-----
    from web.camera import camera
    frame = camera.get_frame()   # np.ndarray (BGR) or None if not yet ready
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Devices to try in order
_CANDIDATES = [
    (0, cv2.CAP_V4L2),
    (1, cv2.CAP_V4L2),
    (0, cv2.CAP_ANY),
]


def _open_camera() -> Optional[cv2.VideoCapture]:
    """Try each candidate until one opens successfully."""
    for index, backend in _CANDIDATES:
        try:
            cap = cv2.VideoCapture(index, backend)
            if cap.isOpened():
                log.info("Camera opened: index=%d backend=%d", index, backend)
                return cap
            cap.release()
        except Exception as exc:
            log.debug("VideoCapture(%d, %d) raised: %s", index, backend, exc)
    return None


class SharedCamera:
    """Single-instance camera that keeps a rolling latest frame."""

    def __init__(self, target_fps: int = 15) -> None:
        self._interval   = 1.0 / target_fps
        self._lock       = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._thread: Optional[threading.Thread] = None
        self._running    = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background capture thread (idempotent)."""
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True, name="camera-capture"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background capture thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Return the most recent captured BGR frame, or None if not ready.

        Auto-starts the capture thread on first call so the camera works
        even if start() was never called explicitly.
        """
        if not self._running:
            self.start()
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        cap: Optional[cv2.VideoCapture] = None

        while self._running:
            # (Re)open the camera if needed
            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                    cap = None
                cap = _open_camera()
                if cap is None:
                    log.warning("Camera not available, retrying in 2 s...")
                    time.sleep(2.0)
                    continue

            t0 = time.monotonic()
            ret, frame = cap.read()
            if ret and frame is not None:
                with self._lock:
                    self._frame = frame
            else:
                # Read failed — device may have gone away
                log.warning("cap.read() failed, reopening camera...")
                cap.release()
                cap = None
                time.sleep(0.5)
                continue

            elapsed   = time.monotonic() - t0
            sleep_for = self._interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

        if cap is not None:
            cap.release()


# Module-level singleton
camera = SharedCamera()
