# -*- coding: utf-8 -*-
"""
web/routers/camera.py
---------------------
MJPEG streaming endpoint: GET /camera/stream

Delivers a multipart/x-mixed-replace stream of JPEG frames captured from
the Pi camera via OpenCV at approximately 10 FPS.  The stream is consumed
directly by an <img> tag in the browser - no JavaScript needed for video.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

import cv2
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

TARGET_FPS = 10
FRAME_INTERVAL = 1.0 / TARGET_FPS


async def _mjpeg_generator() -> AsyncGenerator[bytes, None]:
    """Async generator that yields MJPEG frames from the camera."""
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        # Yield a single error frame and stop.
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n"
        return

    try:
        while True:
            t0 = time.monotonic()

            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(FRAME_INTERVAL)
                continue

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + buf.tobytes()
                + b"\r\n"
            )

            # Throttle to TARGET_FPS
            elapsed = time.monotonic() - t0
            sleep_for = FRAME_INTERVAL - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
    finally:
        cap.release()


@router.get("/camera/stream")
async def camera_stream():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )