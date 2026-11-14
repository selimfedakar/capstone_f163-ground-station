"""WS /ws/car handler: vehicle connection, telemetry, laps (contract 2)."""

import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .db import Database
from .state import AppState, CarConn

log = logging.getLogger("f163.ws_car")


def _flatten_telemetry(msg: Dict[str, Any], session_id: int) -> Dict[str, Any]:
    """Flatten a telemetry message into the DB row schema (contract 5)."""
    imu = msg.get("imu") or {}
    gps = msg.get("gps") or {}
    return {
        "session_id": session_id,
        "seq": msg.get("seq"),
        "t": msg.get("t"),
        "ax": imu.get("ax"), "ay": imu.get("ay"), "az": imu.get("az"),
        "gx": imu.get("gx"), "gy": imu.get("gy"), "gz": imu.get("gz"),
        "lat": gps.get("lat"), "lon": gps.get("lon"),
        "speed_mps": msg.get("speed_mps"),
        "heading_deg": msg.get("heading_deg"),
        "battery_v": msg.get("battery_v"),
        "steering": msg.get("steering"),
        "throttle": msg.get("throttle"),
    }


async def handle_car(ws: WebSocket, state: AppState, db: Database) -> None:
    await ws.accept()
    car: Optional[CarConn] = None
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                log.warning("car: malformed JSON frame ignored: %r", raw[:200])
                continue
            if not isinstance(msg, dict):
                log.warning("car: non-object JSON frame ignored")
                continue

            mtype = msg.get("type")

            if mtype == "hello":
                if car is not None:
                    # Duplicate hello: ignore per contract (exactly once first).
                    log.warning("car %s: duplicate hello ignored", car.car_id)
                    continue
                car_id = str(msg.get("car_id", "unknown"))
                mode = msg.get("mode", "manual")
                if mode not in ("manual", "auto"):
                    mode = "manual"
                session_id = db.create_session(car_id, mode)
                car = CarConn(car_id=car_id, session_id=session_id, mode=mode, ws=ws)
                state.register_car(car)
                await ws.send_text(json.dumps({
                    "type": "hello_ack",
                    "session_id": session_id,
                    "server_time": time.time(),
                }))
                await state.broadcast_ui({
                    "type": "car_connected",
                    "car_id": car_id,
                    "session_id": session_id,
                })
                continue

            if car is None:
                # Anything before hello is ignored.
                log.warning("car: message before hello ignored (type=%r)", mtype)
                continue

            if mtype == "telemetry":
                row = _flatten_telemetry(msg, car.session_id)
                await db.queue_telemetry(row)
                await state.broadcast_ui(msg)
            elif mtype == "lap":
                db.insert_lap(
                    car.session_id,
                    int(msg.get("lap_number", 0)),
                    float(msg.get("lap_time_s", 0.0)),
                    float(msg.get("t", time.time())),
                )
                await state.broadcast_ui(msg)
            else:
                log.warning("car %s: unknown message type %r ignored", car.car_id, mtype)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # defensive: never let one car take down the server
        log.warning("car: handler error: %s", exc)
    finally:
        if car is not None:
            car.connected = False
            state.unregister_car(car.car_id)
            db.end_session(car.session_id)
            await state.broadcast_ui({
                "type": "car_disconnected",
                "car_id": car.car_id,
                "session_id": car.session_id,
            })
