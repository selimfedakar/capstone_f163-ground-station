"""WS /ws/ui handler: operator UI, control relay, ping/pong (contract 3)."""

import json
import logging
import time
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from .db import Database
from .state import AppState, clamp_unit

log = logging.getLogger("f163.ws_ui")


async def handle_ui(ws: WebSocket, state: AppState, db: Database) -> None:
    await ws.accept()
    state.add_ui(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                log.warning("ui: malformed JSON frame ignored: %r", raw[:200])
                continue
            if not isinstance(msg, dict):
                log.warning("ui: non-object JSON frame ignored")
                continue

            mtype = msg.get("type")

            if mtype == "hello":
                await ws.send_text(json.dumps({
                    "type": "state",
                    "cars": state.car_snapshot(),
                }))
            elif mtype == "ping":
                await ws.send_text(json.dumps({
                    "type": "pong",
                    "ts": msg.get("ts"),
                    "server_time": time.time(),
                }))
            elif mtype == "control":
                await _handle_control(msg, state, db)
            else:
                log.warning("ui: unknown message type %r ignored", mtype)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ui: handler error: %s", exc)
    finally:
        state.remove_ui(ws)


async def _handle_control(msg: Dict[str, Any], state: AppState, db: Database) -> None:
    car_id = msg.get("car_id")
    car = state.get_car(car_id) if car_id is not None else None
    if car is None:
        # Control for an unknown car is ignored (contract: graceful handling).
        log.warning("ui: control for unknown car %r ignored", car_id)
        return

    throttle = clamp_unit(msg.get("throttle"))
    steering = clamp_unit(msg.get("steering"))
    ts = msg.get("ts")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        ts = time.time()

    # Always log the operator command.
    db.insert_control(car.session_id, ts, throttle, steering)

    # Forward only in manual mode (contract 2: control forwarded only in manual).
    if car.mode != "manual":
        return

    forward = {
        "type": "control",
        "throttle": throttle,
        "steering": steering,
        "ts": ts,
    }
    try:
        await car.ws.send_text(json.dumps(forward))
    except Exception as exc:
        log.warning("ui: failed to forward control to car %s: %s", car_id, exc)
