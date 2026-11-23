"""WS /ws/ui handler: operator UI, control and reset relay, ping/pong (contract 3)."""

import json
import logging
import time
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from .db import Database
from .race import _public
from .state import AppState, PendingControl, as_number, clamp_unit
from .ws_car import flush_pending_controls

log = logging.getLogger("f163.ws_ui")

# A forwarded command with no acknowledgement after this long is logged as lost.
ACK_TIMEOUT_S = 2.0


def state_message(state: AppState) -> Dict[str, Any]:
    return {
        "type": "state",
        "cars": state.car_snapshot(),
        "race": _public(state.race, state) if state.race is not None else None,
    }


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
                await ws.send_text(json.dumps(state_message(state)))
            elif mtype == "ping":
                await ws.send_text(json.dumps({
                    "type": "pong",
                    "ts": msg.get("ts"),
                    "server_time": time.time(),
                }))
            elif mtype == "control":
                await _handle_control(msg, ws, state, db)
            elif mtype == "reset":
                await _handle_reset(msg, state)
            else:
                log.warning("ui: unknown message type %r ignored", mtype)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("ui: handler error: %s", exc)
    finally:
        state.remove_ui(ws)
        # Acks for this UI's commands have nowhere to go now.
        for car in state.cars.values():
            for p in car.pending.values():
                if p.origin is ws:
                    p.origin = None


async def _handle_control(msg: Dict[str, Any], ws: WebSocket, state: AppState, db: Database) -> None:
    car_id = msg.get("car_id")
    car = state.get_car(car_id) if car_id is not None else None
    if car is None:
        # Control for an unknown car is ignored (contract: graceful handling).
        log.warning("ui: control for unknown car %r ignored", car_id)
        return

    recv = time.time()
    now_mono = time.monotonic()
    throttle = clamp_unit(msg.get("throttle"))
    steering = clamp_unit(msg.get("steering"))
    ts = as_number(msg.get("ts"))
    if ts is None:
        ts = recv
    ui_rtt_ms = as_number(msg.get("ui_rtt_ms"))

    await flush_pending_controls(car, db, older_than_mono=now_mono - ACK_TIMEOUT_S)

    # Forward only in manual mode (contract 2); the command is logged either way.
    if car.mode != "manual":
        await db.queue_control(
            car.session_id, ts, throttle, steering,
            recv_t=recv, forwarded=False, ui_rtt_ms=ui_rtt_ms,
        )
        return

    car.cseq += 1
    car.pending[car.cseq] = PendingControl(
        ts=ts, throttle=throttle, steering=steering, recv_t=recv,
        sent_mono=now_mono, ui_rtt_ms=ui_rtt_ms, origin=ws,
    )
    forward = {
        "type": "control",
        "throttle": throttle,
        "steering": steering,
        "ts": ts,
        "cseq": car.cseq,
    }
    try:
        await car.ws.send_text(json.dumps(forward))
    except Exception as exc:
        log.warning("ui: failed to forward control to car %s: %s", car_id, exc)


async def _handle_reset(msg: Dict[str, Any], state: AppState) -> None:
    """Relay a reset request to the addressed car (contract 2, 3).

    Forwarded in both modes: an auto car that has wandered off can be put
    back on the line too. A car is free to ignore it (a real one has to be
    carried back by hand).
    """
    car_id = msg.get("car_id")
    car = state.get_car(car_id) if car_id is not None else None
    if car is None:
        log.warning("ui: reset for unknown car %r ignored", car_id)
        return
    # Whatever lap was in progress is over; the next one starts from the line.
    car.tracker.abandon()
    try:
        await car.ws.send_text(json.dumps({"type": "reset"}))
    except Exception as exc:
        log.warning("ui: failed to forward reset to car %s: %s", car_id, exc)
