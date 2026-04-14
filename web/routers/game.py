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

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

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
