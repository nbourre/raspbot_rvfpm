"""
web/routers/ws.py
-----------------
WebSocket endpoint /ws

Handles bidirectional real-time communication:
  Client -> Server : drive commands, servo commands
  Server -> Client : distance sensor readings (pushed by robot_state background task)

Message schemas
---------------
Drive:
  { "type": "drive", "direction": "<direction>", "speed": <int 0-255> }
  direction values: forward | backward | turn_left | turn_right |
                    strafe_left | strafe_right |
                    diagonal_forward_left | diagonal_forward_right |
                    diagonal_backward_left | diagonal_backward_right |
                    stop

Servo:
  { "type": "servo", "axis": "pan" | "tilt", "angle": <int 0-180> }
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


def _handle_drive(data: dict) -> None:
    """Execute a drive command on the motors."""
    if state.robot is None:
        return
    direction = data.get("direction", "stop")
    speed = int(data.get("speed", DEFAULT_SPEED))
    if direction == "stop":
        state.robot.motors.stop()
        return
    method_name = DIRECTION_MAP.get(direction)
    if method_name is None:
        return
    method: Callable = getattr(state.robot.motors, method_name)
    method(speed)


def _handle_servo(data: dict) -> None:
    """Set a servo angle."""
    if state.robot is None:
        return
    axis = data.get("axis")
    angle = int(data.get("angle", 90))
    if axis == "pan":
        state.robot.servos.pan.set_angle(angle)
    elif axis == "tilt":
        state.robot.servos.tilt.set_angle(angle)


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
            elif msg_type == "servo":
                _handle_servo(data)
    except WebSocketDisconnect:
        pass
    finally:
        state.connections.discard(ws)
        # Safety: stop motors when the controlling client disconnects.
        if state.robot is not None:
            state.robot.motors.stop()
