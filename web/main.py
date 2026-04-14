"""
web/main.py
-----------
FastAPI application entry point.

Run with:
    uvicorn web.main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import web.robot_state as state
from web.routers import ws as ws_router
from web.routers import camera as camera_router
from web.routers import game as game_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the Robot on startup; tear it down on shutdown."""
    import sys
    from raspbot import Robot
    from web.game import state as gstate

    # Make game state module accessible via robot_state
    state.game = gstate

    try:
        state.robot = Robot()
        state.robot.__enter__()
        state.start_background_tasks()
    except Exception:
        if state.robot is not None:
            state.robot.__exit__(*sys.exc_info())
            state.robot = None
        raise
    yield
    # Shutdown
    state.stop_background_tasks()
    gstate.reset()
    state.robot.motors.stop()
    state.robot.leds.off_all()
    state.robot.__exit__(None, None, None)
    state.robot = None


app = FastAPI(title="Raspbot RVFPM Controller", lifespan=lifespan)

# Routers
app.include_router(ws_router.router)
app.include_router(camera_router.router)
app.include_router(game_router.router)

# Static files (HTML / CSS / JS)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")
