# -*- coding: utf-8 -*-
"""
web/routers/game.py
-------------------
REST endpoints for the Parking Challenge game mode.

Routes
------
GET  /game/state          - current game state snapshot
POST /game/reset          - abort game, return to IDLE
GET  /game/config         - return current config JSON
POST /game/config         - save new config JSON
GET  /game/detect         - grab one camera frame and return all detected circles
GET  /game/leaderboard    - return leaderboard JSON
POST /game/leaderboard    - add an entry to the leaderboard
DELETE /game/leaderboard  - clear entire leaderboard
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from web.game import config as gcfg
from web.game import state as gstate

router = APIRouter(prefix="/game", tags=["game"])

LEADERBOARD_PATH = Path(__file__).parents[2] / "data" / "leaderboard.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_leaderboard() -> list[dict]:
    if LEADERBOARD_PATH.exists():
        try:
            return json.loads(LEADERBOARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_leaderboard(entries: list[dict]) -> None:
    LEADERBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEADERBOARD_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Game state / control
# ---------------------------------------------------------------------------

@router.get("/state")
async def get_game_state():
    return JSONResponse(gstate.get_state())


@router.post("/reset")
async def reset_game():
    gstate.reset()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Live detection test (used by config panel)
# ---------------------------------------------------------------------------

@router.get("/detect")
async def detect_once():
    """Grab one frame from the camera and return all detected circles.

    This endpoint is intended for the configuration panel to let the operator
    verify that the HSV calibration is picking up circles correctly without
    starting a full game session.

    Returns
    -------
    {
        "ok": true,
        "detections": [
            { "color": "red", "cx": 0.51, "cy": 0.49,
              "radius_ratio": 0.22, "cx_px": 320, "cy_px": 240, "radius_px": 140 }
        ]
    }
    """
    import asyncio
    from web.game.detector import detect_circles

    cfg = gcfg.load()

    try:
        import cv2
    except ImportError:
        return JSONResponse({"ok": False, "error": "cv2 not available", "detections": []})

    # Run blocking camera grab in a thread so we don't block the event loop
    def _grab():
        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                return None
            # Discard a couple of stale buffered frames
            for _ in range(3):
                cap.grab()
            ret, frame = cap.read()
            return frame if ret else None
        finally:
            cap.release()

    frame = await asyncio.to_thread(_grab)

    if frame is None:
        return JSONResponse({"ok": False, "error": "Camera not available", "detections": []})

    detections = detect_circles(frame, cfg)
    return JSONResponse({"ok": True, "detections": detections})


# ---------------------------------------------------------------------------
# HSV mask preview (used by config panel binary threshold view)
# ---------------------------------------------------------------------------

@router.get("/mask")
async def mask_preview(color: str = Query(..., description="Color name: red|green|blue|black")):
    """Grab one camera frame and return a JPEG showing the binary HSV mask
    for the requested color (white = matched pixels, black = not matched).

    Used by the config panel so the operator can visually verify HSV tuning.
    """
    import asyncio
    import numpy as np

    cfg = gcfg.load()

    try:
        import cv2
    except ImportError:
        raise HTTPException(status_code=503, detail="cv2 not available")

    color_def = cfg.get("colors", {}).get(color)
    if color_def is None:
        raise HTTPException(status_code=400, detail=f"Unknown color: {color!r}")

    def _grab_and_mask():
        cap = cv2.VideoCapture(0)
        try:
            if not cap.isOpened():
                return None
            for _ in range(3):
                cap.grab()
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
        finally:
            cap.release()

        h, w = frame.shape[:2]
        hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        ranges = color_def.get("ranges", [])
        mask   = np.zeros((h, w), dtype=np.uint8)
        for rng in ranges:
            if len(rng) != 6:
                continue
            lo    = np.array([rng[0], rng[2], rng[4]], dtype=np.uint8)
            hi    = np.array([rng[1], rng[3], rng[5]], dtype=np.uint8)
            mask |= cv2.inRange(hsv, lo, hi)

        # Morphological cleanup (same as detector.py)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)
        mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        # Build a 3-channel BGR image: white mask on original frame (tinted)
        # Left half: original frame | Right half: mask as white-on-black
        # Actually: return a side-by-side composite (original | mask)
        mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        # Colour-tint the mask image with the target colour for clarity
        TINT = {
            "red":   (0,   0,   255),
            "green": (0,   200, 0  ),
            "blue":  (255, 80,  0  ),
            "black": (180, 180, 180),
        }
        tint = TINT.get(color, (255, 255, 255))
        colored_mask = np.zeros_like(frame)
        colored_mask[mask > 0] = tint

        composite = np.hstack([frame, colored_mask])
        _, jpeg = cv2.imencode(".jpg", composite, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return jpeg.tobytes()

    jpeg_bytes = await asyncio.to_thread(_grab_and_mask)

    if jpeg_bytes is None:
        raise HTTPException(status_code=503, detail="Camera not available")

    return Response(content=jpeg_bytes, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_config():
    return JSONResponse(gcfg.load())


@router.post("/config")
async def save_config(body: dict):
    try:
        gcfg.save(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@router.get("/leaderboard")
async def get_leaderboard():
    entries = _load_leaderboard()
    # Sort by elapsed_ms ascending (fastest first)
    entries.sort(key=lambda e: e.get("elapsed_ms", 999_999_999))
    return JSONResponse(entries)


@router.post("/leaderboard")
async def add_leaderboard_entry(body: dict):
    """
    Expected body:
    {
        "name":       "Alice",
        "school":     "CEGEP XYZ",
        "elapsed_ms": 12345,
        "stops":      5,
        "sequence":   ["red", "green", "blue", "black", "red"]
    }
    """
    required = {"name", "school", "elapsed_ms"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing fields: {', '.join(missing)}"
        )
    entries = _load_leaderboard()
    entries.append({
        "name":       str(body["name"])[:64],
        "school":     str(body["school"])[:64],
        "elapsed_ms": int(body["elapsed_ms"]),
        "stops":      int(body.get("stops", 0)),
        "sequence":   list(body.get("sequence", [])),
    })
    entries.sort(key=lambda e: e.get("elapsed_ms", 999_999_999))
    _save_leaderboard(entries)
    return {"ok": True, "rank": entries.index(
        next(e for e in entries
             if e["name"] == str(body["name"])[:64]
             and e["elapsed_ms"] == int(body["elapsed_ms"]))
    ) + 1}


@router.delete("/leaderboard")
async def clear_leaderboard():
    _save_leaderboard([])
    return {"ok": True}
