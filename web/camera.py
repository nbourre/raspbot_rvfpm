# -*- coding: utf-8 -*-
"""
web/camera.py
-------------
Shared camera singleton.

Opens /dev/video0 exactly once and continuously captures frames in a
background thread.  All consumers (MJPEG streamer, game detector, mask
preview) call `get_frame()` to receive the latest BGR numpy array without
ever touching VideoCapture themselves.

Usage
-----
    from web.camera import camera
    frame = camera.get_frame()   # returns np.ndarray (BGR) or None

The background capture loop starts automatically on first use.
Call camera.start() explicitly from the lifespan if you want it up before
the first request.  Call camera.stop() on shutdown.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np


class SharedCamera:
    """Single-instance camera that keeps a rolling latest frame."""

    def __init__(self, index: int = 0, target_fps: int = 15) -> None:
        self._index      = index
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
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="camera-capture")
        self._thread.start()

    def stop(self) -> None:
        """Stop the background capture thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_frame(self) -> Optional[np.ndarray]:
        """Return the most recent captured BGR frame, or None if not ready."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        cap = cv2.VideoCapture(self._index)
        if not cap.isOpened():
            self._running = False
            return

        try:
            while self._running:
                t0  = time.monotonic()
                ret, frame = cap.read()
                if ret and frame is not None:
                    with self._lock:
                        self._frame = frame
                elapsed    = time.monotonic() - t0
                sleep_for  = self._interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)
        finally:
            cap.release()


# Module-level singleton
camera = SharedCamera()
