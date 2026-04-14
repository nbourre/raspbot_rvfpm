# -*- coding: utf-8 -*-
"""
web/routers/ws.py
-----------------
WebSocket endpoint /ws

Handles bidirectional real-time communication:
  Client -> Server : drive commands, servo commands, game control
  Server -> Client : distance sensor readings, game state/frame updates

Message schemas
---------------
Drive (discrete, used by d-pad / keyboard):
  { "type": "drive", "direction": "<direction>", "speed": <int 0-255> }
  direction values: forward | backward | turn_left | turn_right |
                    strafe_left | strafe_right |
                    diagonal_forward_left | diagonal_forward_right |
                    diagonal_backward_left | diagonal_backward_right |
                    stop

Drive raw (used by gamepad cartesian mixing):
  { "type": "drive_raw", "l1": <int -255..255>, "l2": <int -255..255>,
                          "r1": <int -255..255>, "r2": <int -255..255> }
  Sets each motor individually with a signed speed.

Servo:
  { "type": "servo", "axis": "pan" | "tilt", "angle": <int 0-180> }

Game control:
  { "type": "game_start" }   - start the parking challenge game
  { "type": "game_reset" }   - abort game, return to IDLE
"""

from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import web.robot_state as state

router = APIRouter()

# Default driving speed when the client doesn't specify one.
DEFAULT_SPEED = 150

# Map direction strings to Motor method names.
DIRECTION_MAP: dict[str, str] = {
    "forward":                  "forward",
    "backward":                 "backward",
    "turn_left":                "turn_left",
    "turn_right":               "turn_right",
    "strafe_left":              "strafe_left",
    "strafe_right":             "strafe_right",
    "diagonal_forward_left":    "diagonal_forward_left",
    "diagonal_forward_right":   "diagonal_forward_right",
    "diagonal_backward_left":   "diagonal_backward_left",
    "diagonal_backward_right":  "diagonal_backward_right",
}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _handle_drive(data: dict) -> None:
    """Execute a discrete drive command on the motors."""
    if state.robot is None:
        return
    direction = data.get("direction", "stop")
    try:
        speed = int(data.get("speed", DEFAULT_SPEED))
    except (ValueError, TypeError):
        speed = DEFAULT_SPEED
    if direction == "stop":
        state.robot.motors.stop()
        return
    method_name = DIRECTION_MAP.get(direction)
    if method_name is None:
        return
    method: Callable = getattr(state.robot.motors, method_name)
    method(speed)


def _handle_drive_raw(data: dict) -> None:
    """Set each motor individually (signed speed -255..255).

    Used by the gamepad cartesian mixing algorithm.
    Motors: L1 = front-left, L2 = rear-left, R1 = front-right, R2 = rear-right.
    """
    if state.robot is None:
        return
    from raspbot import MotorId
    try:
        l1 = _clamp(int(data.get("l1", 0)), -255, 255)
        l2 = _clamp(int(data.get("l2", 0)), -255, 255)
        r1 = _clamp(int(data.get("r1", 0)), -255, 255)
        r2 = _clamp(int(data.get("r2", 0)), -255, 255)
    except (ValueError, TypeError):
        return
    state.robot.motors.drive(MotorId.L1, l1)
    state.robot.motors.drive(MotorId.L2, l2)
    state.robot.motors.drive(MotorId.R1, r1)
    state.robot.motors.drive(MotorId.R2, r2)


def _handle_servo(data: dict) -> None:
    """Set a servo angle."""
    if state.robot is None:
        return
    axis = data.get("axis")
    try:
        angle = int(data.get("angle", 90))
    except (ValueError, TypeError):
        angle = 90
    if axis == "pan":
        state.robot.servos.pan.set_angle(angle)
    elif axis == "tilt":
        state.robot.servos.tilt.set_angle(angle)


def _handle_game_start() -> None:
    """Launch the parking challenge game."""
    if state.game is not None:
        state.game.start()


def _handle_game_reset() -> None:
    """Abort any running game and return to IDLE."""
    if state.game is not None:
        state.game.reset()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    state.connections.add(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")
            if msg_type == "drive":
                _handle_drive(data)
            elif msg_type == "drive_raw":
                _handle_drive_raw(data)
            elif msg_type == "servo":
                _handle_servo(data)
            elif msg_type == "game_start":
                _handle_game_start()
            elif msg_type == "game_reset":
                _handle_game_reset()
    except WebSocketDisconnect:
        pass
    finally:
        state.connections.discard(ws)
        # Safety: stop motors when the controlling client disconnects.
        if state.robot is not None:
            state.robot.motors.stop()
