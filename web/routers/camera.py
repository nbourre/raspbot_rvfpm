# -*- coding: utf-8 -*-
"""
web/routers/camera.py
---------------------
MJPEG streaming endpoint: GET /camera/stream

Delivers a multipart/x-mixed-replace stream of JPEG frames at approximately
10 FPS.  Frames are read from the shared camera singleton (web.camera) so
that /dev/video0 is opened only once regardless of how many consumers exist.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator

import cv2
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from web.camera import camera

router = APIRouter()

TARGET_FPS      = 10
FRAME_INTERVAL  = 1.0 / TARGET_FPS


async def _mjpeg_generator() -> AsyncGenerator[bytes, None]:
    """Async generator that yields MJPEG frames from the shared camera."""
    while True:
        t0 = time.monotonic()

        frame = await asyncio.to_thread(camera.get_frame)
        if frame is None:
            await asyncio.sleep(FRAME_INTERVAL)
            continue

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            await asyncio.sleep(FRAME_INTERVAL)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )

        elapsed   = time.monotonic() - t0
        sleep_for = FRAME_INTERVAL - elapsed
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


@router.get("/camera/stream")
async def camera_stream():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
