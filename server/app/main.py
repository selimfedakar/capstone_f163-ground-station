"""F163 ground station server entrypoint (FastAPI + uvicorn)."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket

from .api import build_router
from .db import DEFAULT_DB_PATH, Database
from .state import AppState
from .track import load_track
from .ws_car import handle_car
from .ws_ui import handle_ui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(db_path: str = None) -> FastAPI:
    db_path = db_path or os.environ.get("F163_DB_PATH", DEFAULT_DB_PATH)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(db_path)
        # Nothing can be running before the first connection: close whatever
        # a previous run left open so it does not show as live for ever.
        db.close_orphans()
        await db.start()
        app.state.db = db
        app.state.app_state = AppState(track=load_track())
        try:
            yield
        finally:
            await db.stop()

    app = FastAPI(title="F163 Ground Station", version="1.1", lifespan=lifespan)
    app.include_router(build_router())

    @app.websocket("/ws/car")
    async def ws_car(ws: WebSocket):
        await handle_car(ws, ws.app.state.app_state, ws.app.state.db)

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket):
        await handle_ui(ws, ws.app.state.app_state, ws.app.state.db)

    return app


app = create_app()
