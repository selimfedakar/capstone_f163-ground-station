"""WS /ws/car handler: vehicle connection, telemetry, laps, acks (contract 2)."""

import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from .db import Database
from .laps import LapEvent, LapTracker
from .race import enter_car, finish_race, leave_race
from .state import AppState, CarConn, ServerLap, as_number

log = logging.getLogger("f163.ws_car")

# A car's own lap report and the server's timing of the same lap land within
# a tick of each other; anything further apart is a different event.
LAP_MATCH_WINDOW_S = 1.5


def _flatten_telemetry(msg: Dict[str, Any], session_id: int) -> Dict[str, Any]:
    """Flatten a telemetry message into the DB row schema (contract 5).

    Anything that is not a finite number becomes NULL, which is how a missing
    or broken sensor reading is recorded.
    """
    imu = msg.get("imu") if isinstance(msg.get("imu"), dict) else {}
    gps = msg.get("gps") if isinstance(msg.get("gps"), dict) else {}
    return {
        "session_id": session_id,
        "seq": msg.get("seq"),
        "t": as_number(msg.get("t")),
        "ax": as_number(imu.get("ax")), "ay": as_number(imu.get("ay")), "az": as_number(imu.get("az")),
        "gx": as_number(imu.get("gx")), "gy": as_number(imu.get("gy")), "gz": as_number(imu.get("gz")),
        "lat": as_number(gps.get("lat")), "lon": as_number(gps.get("lon")),
        "speed_mps": as_number(msg.get("speed_mps")),
        "heading_deg": as_number(msg.get("heading_deg")),
        "battery_v": as_number(msg.get("battery_v")),
        "steering": as_number(msg.get("steering")),
        "throttle": as_number(msg.get("throttle")),
    }


async def _emit_server_lap(
    car: CarConn, ev: LapEvent, recv: float, state: AppState, db: Database
) -> None:
    race = state.race
    race_id = race_lap = race_time = None
    if race is not None and car.in_race:
        car.race_lap += 1
        race_id, race_lap = race["id"], car.race_lap
        if car.race_start_t is not None:
            race_time = round(ev.t - car.race_start_t, 3)

    # Did the car announce this same lap a moment ago?
    car_time = None
    pending = car.pending_car_lap
    if pending is not None and abs(pending["t"] - ev.t) <= LAP_MATCH_WINDOW_S:
        car_time = pending["lap_time_s"]
        car.pending_car_lap = None
    car.last_server_lap = ServerLap(ev.lap_number, ev.t, car_time is not None)

    # Millisecond resolution is as fine as 20 Hz positions can honestly give.
    await db.queue_lap(
        car.session_id, ev.lap_number, round(ev.lap_time_s, 3), round(ev.t, 3),
        recv_t=recv, valid=ev.valid, source="server", off_track_s=round(ev.off_track_s, 3),
        car_time_s=car_time, race_id=race_id, race_lap=race_lap,
    )
    await state.broadcast_ui({
        "type": "lap",
        "car_id": car.car_id,
        "lap_number": ev.lap_number,
        "lap_time_s": round(ev.lap_time_s, 3),
        "t": round(ev.t, 3),
        "valid": ev.valid,
        "source": "server",
        "off_track_s": round(ev.off_track_s, 2),
        "race_id": race_id,
        "race_lap": race_lap,
        "race_time_s": race_time,
    })

    if race is not None and race_lap is not None and race["laps_target"] and race_lap >= race["laps_target"]:
        await finish_race(state, db, reason=f"{car.car_id} completed {race_lap} laps")


async def _emit_unconfirmed_car_lap(car: CarConn, state: AppState, db: Database) -> None:
    """Record a lap the car reported that the server's own timing never saw."""
    lap = car.pending_car_lap
    car.pending_car_lap = None
    if lap is None:
        return
    log.warning(
        "car %s: reported lap %s (%.2fs) not confirmed by server timing",
        car.car_id, lap["lap_number"], lap["lap_time_s"],
    )
    await db.queue_lap(
        car.session_id, lap["lap_number"], lap["lap_time_s"], lap["t"],
        recv_t=lap["recv_t"], valid=False, source="car",
    )
    await state.broadcast_ui({
        "type": "lap",
        "car_id": car.car_id,
        "lap_number": lap["lap_number"],
        "lap_time_s": round(lap["lap_time_s"], 3),
        "t": round(lap["t"], 3),
        "valid": False,
        "source": "car",
        "off_track_s": None,
        "race_id": None,
        "race_lap": None,
        "race_time_s": None,
    })


async def flush_pending_controls(car: CarConn, db: Database, older_than_mono: Optional[float] = None) -> None:
    """Log forwarded commands that were never acknowledged."""
    for cseq in [k for k, p in car.pending.items() if older_than_mono is None or p.sent_mono < older_than_mono]:
        p = car.pending.pop(cseq)
        await db.queue_control(
            car.session_id, p.ts, p.throttle, p.steering,
            recv_t=p.recv_t, forwarded=True, ack_rtt_ms=None, ui_rtt_ms=p.ui_rtt_ms,
        )


async def _handle_telemetry(msg: Dict[str, Any], car: CarConn, state: AppState, db: Database) -> None:
    recv = time.time()
    row = _flatten_telemetry(msg, car.session_id)
    seq = row["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int):
        log.warning("car %s: telemetry without an integer seq ignored", car.car_id)
        return
    if row["t"] is None:
        row["t"] = recv
    t = row["t"]
    car.last_t = t
    row["recv_t"] = recv

    if state.race is not None and car.in_race and car.race_start_t is None:
        # Entered the race before its first frame: the race clock starts here.
        car.race_start_t = t
        db.set_race_entry_start(state.race["id"], car.session_id, t)

    event: Optional[LapEvent] = None
    if row["lat"] is not None and row["lon"] is not None:
        x, y = state.track.to_local(row["lat"], row["lon"])
        event, s, off = car.tracker.update(x, y, t, row["speed_mps"])
        row["track_s"] = round(s, 3)
        row["off_track"] = int(off)

    await db.queue_telemetry(row)
    await state.broadcast_ui(msg)

    if event is not None:
        await _emit_server_lap(car, event, recv, state, db)
    pending = car.pending_car_lap
    if pending is not None and t > pending["t"] + LAP_MATCH_WINDOW_S:
        await _emit_unconfirmed_car_lap(car, state, db)


async def _handle_car_lap(msg: Dict[str, Any], car: CarConn, db: Database) -> None:
    """The car's own lap report: kept as a cross-check, never as the result."""
    lap_time = as_number(msg.get("lap_time_s"))
    if lap_time is None:
        return
    t = as_number(msg.get("t"))
    if t is None:
        t = car.last_t if car.last_t is not None else time.time()
    number = msg.get("lap_number")
    number = number if isinstance(number, int) and not isinstance(number, bool) else 0

    last = car.last_server_lap
    if last is not None and not last.has_car_time and abs(last.t - t) <= LAP_MATCH_WINDOW_S:
        last.has_car_time = True
        await db.queue_lap_car_time(car.session_id, last.lap_number, lap_time)
        return
    car.pending_car_lap = {"lap_number": number, "lap_time_s": lap_time, "t": t, "recv_t": time.time()}


async def _handle_control_ack(msg: Dict[str, Any], car: CarConn, db: Database) -> None:
    cseq = msg.get("cseq")
    p = car.pending.pop(cseq, None) if isinstance(cseq, int) else None
    if p is None:
        return
    rtt_ms = (time.monotonic() - p.sent_mono) * 1000.0
    await db.queue_control(
        car.session_id, p.ts, p.throttle, p.steering,
        recv_t=p.recv_t, forwarded=True, ack_rtt_ms=rtt_ms, ui_rtt_ms=p.ui_rtt_ms,
    )
    if p.origin is not None:
        try:
            await p.origin.send_text(json.dumps({
                "type": "control_ack",
                "car_id": car.car_id,
                "ts": p.ts,
                "car_rtt_ms": round(rtt_ms, 2),
            }))
        except Exception:
            pass  # the UI went away; its socket handler cleans up


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
                fw = msg.get("fw")
                fw = str(fw)[:64] if fw is not None else None
                session_id = db.create_session(car_id, mode, fw=fw)
                car = CarConn(
                    car_id=car_id, session_id=session_id, mode=mode, ws=ws,
                    tracker=LapTracker(state.track), fw=fw,
                )
                state.register_car(car)
                await ws.send_text(json.dumps({
                    "type": "hello_ack",
                    "session_id": session_id,
                    "server_time": time.time(),
                }))
                if state.race is not None:
                    # A car that connects mid-race joins it from its first frame.
                    enter_car(state, db, car, time.time())
                    state.race["cars"] = sorted(c.car_id for c in state.cars.values() if c.in_race)
                await state.broadcast_ui({
                    "type": "car_connected",
                    "car_id": car_id,
                    "session_id": session_id,
                    "mode": mode,
                    "fw": fw,
                })
                continue

            if car is None:
                # Anything before hello is ignored.
                log.warning("car: message before hello ignored (type=%r)", mtype)
                continue

            if mtype == "telemetry":
                await _handle_telemetry(msg, car, state, db)
            elif mtype == "lap":
                await _handle_car_lap(msg, car, db)
            elif mtype == "control_ack":
                await _handle_control_ack(msg, car, db)
            else:
                log.warning("car %s: unknown message type %r ignored", car.car_id, mtype)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # defensive: never let one car take down the server
        log.warning("car: handler error: %s", exc)
    finally:
        if car is not None:
            car.connected = False
            try:
                await _emit_unconfirmed_car_lap(car, state, db)
                await flush_pending_controls(car, db)
                leave_race(state, db, car)
                # The session is over: commit its tail now rather than on the
                # next batch tick, so the dashboard has all of it at once.
                await db.flush()
            except Exception as exc:
                log.warning("car %s: cleanup error: %s", car.car_id, exc)
            state.unregister_car(car)
            db.end_session(car.session_id)
            await state.broadcast_ui({
                "type": "car_disconnected",
                "car_id": car.car_id,
                "session_id": car.session_id,
            })
