# -*- coding: utf-8 -*-
"""
web/robot_state.py
------------------
Singleton Robot() instance shared across all FastAPI routers.
The robot is created once at app startup (via FastAPI lifespan) and torn down
on shutdown.  A background asyncio task broadcasts ultrasonic distance readings
to every connected WebSocket client at ~10 Hz.
"""

from __future__ import annotations

import asyncio
from typing import Set

from fastapi import WebSocket

# The single Robot instance - set by lifespan, cleared on shutdown.
robot = None

# All currently connected WebSocket clients.
connections: Set[WebSocket] = set()

# Game module reference (imported lazily to avoid circular imports at module load).
# Accessed as:  import web.robot_state as state; state.game.start()
game = None

# Background sensor task handle.
_sensor_task: asyncio.Task | None = None


async def _broadcast_distance() -> None:
    """Read ultrasonic sensor every 100 ms and push to all WS clients."""
    import json

    while True:
        await asyncio.sleep(0.1)
        if robot is None or not connections:
            continue
        try:
            with robot.ultrasonic:
                value = robot.ultrasonic.read_cm()
            msg = json.dumps({"type": "distance", "value": round(value, 1)})
            dead: Set[WebSocket] = set()
            for ws in list(connections):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            connections.difference_update(dead)
        except Exception:
            # Sensor may not always be available; silently skip.
            pass


def start_background_tasks() -> None:
    """Called from the FastAPI lifespan to launch the sensor broadcast loop."""
    global _sensor_task
    _sensor_task = asyncio.create_task(_broadcast_distance())


def stop_background_tasks() -> None:
    """Called from the FastAPI lifespan on shutdown."""
    if _sensor_task is not None:
        _sensor_task.cancel()