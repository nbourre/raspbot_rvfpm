# -*- coding: utf-8 -*-
"""
web/game/state.py
-----------------
Game state machine (FSM) for the Parking Challenge.

States
------
IDLE        : no game running
COUNTDOWN   : RB held 3s, LED blinks white 3x before first target
TARGETING   : player must find and park in front of the target circle
HOLDING     : correct position maintained; waiting hold_duration seconds
FINISHED    : all stops completed

The FSM runs as an asyncio task (game_loop). It reads camera frames,
runs the detector, broadcasts game_state and game_frame WS messages, and
drives the LED bar.

Public interface
----------------
    game.state.start()     -> launch game_loop task (called by WS handler)
    game.state.reset()     -> abort game, return to IDLE
    game.state.get_state() -> dict snapshot of current game state
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# FSM states
# ---------------------------------------------------------------------------

class GamePhase(str, Enum):
    IDLE       = "IDLE"
    COUNTDOWN  = "COUNTDOWN"
    TARGETING  = "TARGETING"
    HOLDING    = "HOLDING"
    FINISHED   = "FINISHED"


# ---------------------------------------------------------------------------
# LED color helpers
# ---------------------------------------------------------------------------

# Map color names to (R, G, B) tuples for the LED bar
_LED_COLORS = {
    "red":   (255,   0,   0),
    "green": (  0, 255,   0),
    "blue":  (  0,   0, 255),
    "black": None,           # special: only end LEDs yellow
    "white": (255, 255, 255),
    "off":   (  0,   0,   0),
}

NUM_LEDS = 14


def _set_leds_solid(robot, color_name: str) -> None:
    """Set all 14 LEDs to a solid color. For 'black' only end LEDs are yellow."""
    try:
        from raspbot import LedColor
        if color_name == "off":
            robot.leds.off_all()
            return
        if color_name == "black":
            robot.leds.off_all()
            # LEDs are 0-indexed; set index 0 and 13 to yellow
            robot.leds.set_single(0,  LedColor.YELLOW)
            robot.leds.set_single(13, LedColor.YELLOW)
            return
        mapping = {
            "red":   LedColor.RED,
            "green": LedColor.GREEN,
            "blue":  LedColor.BLUE,
            "white": LedColor.WHITE,
        }
        led_color = mapping.get(color_name)
        if led_color is not None:
            robot.leds.set_all(led_color)
    except Exception:
        pass


def _set_leds_sequence(robot, colors: list[str]) -> None:
    """Display the completed stop colors on the LED bar.

    Distributes stops evenly across the 14 LEDs. Each segment gets the color
    of one stop. Remaining LEDs are off.
    """
    try:
        from raspbot import LedColor
        mapping = {
            "red":   LedColor.RED,
            "green": LedColor.GREEN,
            "blue":  LedColor.BLUE,
            "black": LedColor.YELLOW,  # represent black as yellow on LEDs
            "white": LedColor.WHITE,
        }
        n = len(colors)
        if n == 0:
            robot.leds.off_all()
            return
        seg = NUM_LEDS // n
        for i, color_name in enumerate(colors):
            led_color = mapping.get(color_name, LedColor.WHITE)
            for j in range(seg):
                idx = i * seg + j
                if idx < NUM_LEDS:
                    robot.leds.set_single(idx, led_color)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Singleton game state
# ---------------------------------------------------------------------------

phase:         GamePhase      = GamePhase.IDLE
stop_index:    int            = 0        # 0-based index of current stop
total_stops:   int            = 5
sequence:      list[str]      = []       # ordered color sequence for this game
completed:     list[str]      = []       # colors successfully parked
overlay_radius: float         = 0.28    # current overlay radius (fraction of width)
start_time:    float | None   = None    # monotonic time when TARGETING began
hold_start:    float | None   = None    # monotonic time when HOLDING began
elapsed_ms:    int            = 0       # total elapsed ms (updated while running)
_task:         asyncio.Task | None = None
_skip_event:   asyncio.Event | None = None   # set to skip current stop


def get_state() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot of the current game state."""
    return {
        "phase":         phase.value,
        "stop_index":    stop_index,
        "total_stops":   total_stops,
        "target_color":  sequence[stop_index] if sequence and stop_index < len(sequence) else None,
        "completed":     list(completed),
        "overlay_radius": overlay_radius,
        "elapsed_ms":    elapsed_ms,
    }


def reset(broadcast: bool = True) -> None:
    """Abort any running game and return to IDLE."""
    global phase, stop_index, sequence, completed, overlay_radius
    global start_time, hold_start, elapsed_ms, _task, _skip_event

    if _task is not None and not _task.done():
        _task.cancel()
        _task = None

    _skip_event = None

    phase         = GamePhase.IDLE
    stop_index    = 0
    sequence      = []
    completed     = []
    overlay_radius = 0.28
    start_time    = None
    hold_start    = None
    elapsed_ms    = 0

    # Turn off LEDs
    import web.robot_state as rs
    if rs.robot is not None:
        try:
            rs.robot.leds.off_all()
        except Exception:
            pass

    # Notify all clients that the game is back to IDLE.
    # reset() may be called from a sync context (WS message handler runs in the
    # event loop thread), so schedule the coroutine as a fire-and-forget task.
    if broadcast:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_broadcast_state())
        except Exception:
            pass


def start() -> None:
    """Launch the game loop as an asyncio background task."""
    global _task, _skip_event
    reset(broadcast=False)   # game_loop will broadcast COUNTDOWN immediately
    _skip_event = asyncio.Event()
    _task = asyncio.create_task(_game_loop())


def skip_stop() -> None:
    """Signal the game loop to skip the current stop (LB button)."""
    if _skip_event is not None and phase in (GamePhase.TARGETING, GamePhase.HOLDING):
        _skip_event.set()


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def _game_loop() -> None:
    """Full game FSM coroutine. Runs until FINISHED or cancelled."""
    import web.robot_state as rs
    from web.game import config as gcfg
    from web.game.detector import detect_circles, best_match

    global phase, stop_index, sequence, completed, overlay_radius
    global start_time, hold_start, elapsed_ms

    cfg = gcfg.load()
    num_stops     = int(cfg.get("num_stops", 5))
    hold_duration = float(cfg.get("hold_duration", 1.0))
    min_ratio     = float(cfg.get("overlay_min_ratio", 0.20))
    max_ratio     = float(cfg.get("overlay_max_ratio", 0.35))
    center_tol    = float(cfg.get("center_tolerance", 0.10))
    radius_tol    = float(cfg.get("radius_tolerance", 0.10))

    colors_pool = ["red", "green", "blue", "black"]
    sequence = []
    for _ in range(num_stops):
        # Pick any color that differs from the last one
        choices = [c for c in colors_pool if c != (sequence[-1] if sequence else None)]
        sequence.append(random.choice(choices))
    total_stops_local = num_stops

    # ------------------------------------------------------------------
    # COUNTDOWN phase
    # ------------------------------------------------------------------
    phase = GamePhase.COUNTDOWN
    await _broadcast_state()

    # Blink white 3x, one blink per second
    if rs.robot is not None:
        for _ in range(3):
            _set_leds_solid(rs.robot, "white")
            await asyncio.sleep(0.5)
            rs.robot.leds.off_all()
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # TARGETING / HOLDING loop
    # ------------------------------------------------------------------
    stop_index = 0
    start_time = time.monotonic()

    from web.camera import camera as _camera

    try:
        while stop_index < num_stops:
            # Pick a random overlay radius for this stop
            overlay_radius = random.uniform(min_ratio, max_ratio)

            phase      = GamePhase.TARGETING
            hold_start = None
            if rs.robot is not None:
                _set_leds_solid(rs.robot, sequence[stop_index])
            await _broadcast_state()

            # Inner loop: wait for correct positioning
            matched_circle: dict | None = None
            skipped = False
            if _skip_event is not None:
                _skip_event.clear()
            while True:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                # Check for LB skip signal
                if _skip_event is not None and _skip_event.is_set():
                    _skip_event.clear()
                    skipped = True
                    break

                # Grab a frame
                detections: list[dict] = []
                frame = _camera.get_frame()
                if frame is not None:
                    detections = detect_circles(frame, cfg)

                target_color = sequence[stop_index]
                circle, quality = best_match(
                    detections, target_color, overlay_radius,
                    center_tol, radius_tol
                )

                matched = circle is not None

                # Compute hold progress
                hold_progress = 0.0
                if matched:
                    if hold_start is None:
                        hold_start = time.monotonic()
                        phase = GamePhase.HOLDING
                    held = time.monotonic() - hold_start
                    hold_progress = min(1.0, held / hold_duration)
                else:
                    if hold_start is not None:
                        # Lost position during hold - reset
                        hold_start = None
                        phase = GamePhase.TARGETING
                        if rs.robot is not None:
                            _set_leds_solid(rs.robot, target_color)

                # Broadcast frame result to all clients
                await _broadcast_frame(detections, matched, hold_progress)

                # Check if hold complete
                if matched and hold_progress >= 1.0:
                    completed.append(target_color)
                    matched_circle = circle
                    break

                await asyncio.sleep(0.05)   # ~20 fps detection rate

            # Stop validated or skipped
            if not skipped:
                # Brief white flash on valid stop
                if rs.robot is not None:
                    _set_leds_solid(rs.robot, "white")
                await asyncio.sleep(0.4)

            stop_index += 1
            await _broadcast_state()

        # ------------------------------------------------------------------
        # FINISHED
        # ------------------------------------------------------------------
        phase      = GamePhase.FINISHED
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        await _broadcast_state()

        # Replay sequence on LED bar (1 second per color)
        if rs.robot is not None:
            for color_name in sequence:
                _set_leds_solid(rs.robot, color_name)
                await asyncio.sleep(1.0)
            rs.robot.leds.off_all()

    except asyncio.CancelledError:
        pass
    finally:
        if rs.robot is not None:
            try:
                rs.robot.leds.off_all()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def _broadcast(msg: dict) -> None:
    """Send a JSON message to all connected WebSocket clients."""
    import web.robot_state as rs
    text = json.dumps(msg)
    dead = set()
    for ws in list(rs.connections):
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    rs.connections.difference_update(dead)


async def _broadcast_state() -> None:
    snap = get_state()
    snap["type"] = "game_state"
    await _broadcast(snap)


async def _broadcast_frame(
    detections: list[dict],
    matched: bool,
    hold_progress: float,
) -> None:
    await _broadcast({
        "type":          "game_frame",
        "detected":      detections,
        "matched":       matched,
        "hold_progress": round(hold_progress, 3),
    })
