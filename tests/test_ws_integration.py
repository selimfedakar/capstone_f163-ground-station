"""WS integration test using FastAPI TestClient.

A fake car connects and drives a lap. A fake UI connects, receives the
broadcasts, and sends a control; the car must receive it. Rows land in a temp DB.
"""

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from server.app.db import Database
from server.app.main import create_app
from server.app.track import default_track

from tests.helpers import drive, wait_for


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(db_path=path)
    with TestClient(app) as c:
        c._db_path = path
        yield c
    if os.path.exists(path):
        os.remove(path)


def _count(client, table, session_id):
    import sqlite3
    conn = sqlite3.connect(client._db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE session_id=?", (session_id,)).fetchone()[0]
    finally:
        conn.close()


def _drain_until(ws, wanted_type, max_msgs=50):
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == wanted_type:
            return msg
    raise AssertionError(f"did not receive message of type {wanted_type}")


def test_full_flow_manual(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "fw": "sim-0.1", "mode": "manual"})
        ack = car.receive_json()
        assert ack["type"] == "hello_ack"
        assert isinstance(ack["session_id"], int)
        session_id = ack["session_id"]

        # UI connects after the car so the state snapshot includes it.
        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            state = ui.receive_json()
            assert state["type"] == "state"
            assert any(c["car_id"] == "car-1" for c in state["cars"])

            # Car drives one full lap; UI receives the telemetry verbatim.
            speed = 8.0
            seq, t = drive(car, track, "car-1", s_from=0.0, s_to=track.length_m + 1.0, speed=speed)
            tel = _drain_until(ui, "telemetry")
            assert tel["car_id"] == "car-1"
            assert tel["seq"] >= 1

            # The server times the lap itself from the reported positions.
            lap = _drain_until(ui, "lap", max_msgs=200)
            assert lap["lap_number"] == 1
            assert lap["source"] == "server"
            assert lap["valid"] is True
            assert lap["lap_time_s"] == pytest.approx(track.length_m / speed, rel=0.01)

            # The car's own report of that lap is kept only as a cross-check.
            car.send_json({
                "type": "lap", "car_id": "car-1", "lap_number": 1,
                "lap_time_s": 4.4, "t": lap["t"] + 0.05,
            })

            # UI sends a control; the car must receive it clamped and forwarded.
            ui.send_json({
                "type": "control", "car_id": "car-1",
                "throttle": 2.0, "steering": -0.25, "ts": 1011.0,
            })
            ctrl = car.receive_json()
            assert ctrl["type"] == "control"
            assert ctrl["throttle"] == 1.0  # clamped from 2.0
            assert ctrl["steering"] == -0.25
            assert isinstance(ctrl["cseq"], int)

            # ping -> pong
            ui.send_json({"type": "ping", "ts": 1234.5})
            pong = _drain_until(ui, "pong")
            assert pong["ts"] == 1234.5
            assert "server_time" in pong

    # After the car disconnects, allow the writer to flush, then check the DB.
    db = Database(client._db_path)
    assert wait_for(lambda: db.get_session(session_id)["ended_at"] is not None)
    assert wait_for(lambda: _count(client, "control_log", session_id) == 1)
    rows = db.get_telemetry(session_id, limit=10_000)
    assert len(rows) == seq
    assert all(r["recv_t"] is not None and r["off_track"] == 0 for r in rows)

    laps = db.get_laps(session_id)
    assert len(laps) == 1
    assert laps[0]["lap_number"] == 1
    assert laps[0]["source"] == "server"
    assert laps[0]["car_time_s"] == 4.4

    # Control was logged, forwarded, and never acknowledged by this fake car.
    import sqlite3
    conn = sqlite3.connect(client._db_path)
    logged = conn.execute(
        "SELECT forwarded, ack_rtt_ms FROM control_log WHERE session_id=?", (session_id,)
    ).fetchall()
    conn.close()
    assert logged == [(1, None)]

    # Session ended on disconnect.
    s = db.get_session(session_id)
    assert s["ended_at"] is not None
    assert s["fw"] == "sim-0.1"


def test_car_lap_without_a_driven_lap_is_not_counted(client):
    """A car announcing a lap it did not drive is recorded, never counted."""
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "fw": "sim-0.1", "mode": "manual"})
        session_id = car.receive_json()["session_id"]
        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            ui.receive_json()
            frame = {
                "type": "telemetry", "car_id": "car-1",
                "imu": {"ax": 0.1, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0},
                "gps": {"lat": 41.0421, "lon": 29.0093},
                "speed_mps": 0.0, "heading_deg": 90.0, "battery_v": 7.4,
                "steering": 0.0, "throttle": 0.0,
            }
            car.send_json({**frame, "seq": 1, "t": 1000.0})
            car.send_json({
                "type": "lap", "car_id": "car-1", "lap_number": 1,
                "lap_time_s": 0.8, "t": 1000.0,
            })
            # Server timing has two seconds to agree; it does not.
            car.send_json({**frame, "seq": 2, "t": 1002.0})
            lap = _drain_until(ui, "lap")
            assert lap["source"] == "car"
            assert lap["valid"] is False

    db = Database(client._db_path)
    assert wait_for(lambda: len(db.get_laps(session_id)) == 1)
    laps = db.get_laps(session_id)
    assert [(l["source"], l["valid"]) for l in laps] == [("car", False)]
    k = db.compute_kpis(session_id)
    assert k["lap_count"] == 0
    assert k["best_lap_s"] is None
    assert k["unconfirmed_car_laps"] == 1


def test_control_unknown_car_ignored(client):
    with client.websocket_connect("/ws/ui") as ui:
        ui.send_json({"type": "hello", "client": "web"})
        ui.receive_json()  # state
        # No car connected: control for unknown car must be ignored (no crash).
        ui.send_json({
            "type": "control", "car_id": "ghost",
            "throttle": 0.5, "steering": 0.0, "ts": 1.0,
        })
        # Verify the UI socket is still alive via ping/pong.
        ui.send_json({"type": "ping", "ts": 7.0})
        pong = ui.receive_json()
        assert pong["type"] == "pong"
        assert pong["ts"] == 7.0


def test_auto_mode_not_forwarded(client):
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-auto", "fw": "sim-0.1", "mode": "auto"})
        ack = car.receive_json()
        session_id = ack["session_id"]
        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            ui.receive_json()
            ui.send_json({
                "type": "control", "car_id": "car-auto",
                "throttle": 0.5, "steering": 0.1, "ts": 1.0,
            })
            # Control is logged but NOT forwarded to an auto car.
            # Confirm via DB after disconnect.
            ui.send_json({"type": "ping", "ts": 1.0})
            assert ui.receive_json()["type"] == "pong"

    assert wait_for(lambda: _count(client, "control_log", session_id) == 1)  # logged, not forwarded


def test_reset_forwarded_in_both_modes(client):
    for mode in ("manual", "auto"):
        car_id = f"car-{mode}"
        with client.websocket_connect("/ws/car") as car:
            car.send_json({"type": "hello", "car_id": car_id, "fw": "sim-0.1", "mode": mode})
            assert car.receive_json()["type"] == "hello_ack"
            with client.websocket_connect("/ws/ui") as ui:
                ui.send_json({"type": "hello", "client": "web"})
                ui.receive_json()
                ui.send_json({"type": "reset", "car_id": car_id})
                assert car.receive_json() == {"type": "reset"}


def test_reset_unknown_car_ignored(client):
    with client.websocket_connect("/ws/ui") as ui:
        ui.send_json({"type": "hello", "client": "web"})
        ui.receive_json()
        ui.send_json({"type": "reset", "car_id": "ghost"})
        # Server must stay healthy.
        ui.send_json({"type": "ping", "ts": 1.0})
        assert ui.receive_json()["type"] == "pong"


def test_malformed_json_ignored(client):
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "mode": "manual"})
        car.receive_json()  # ack
        car.send_text("{not valid json")  # must be ignored, no crash
        # Still alive: send valid telemetry and a lap, then verify lap recorded.
        car.send_json({
            "type": "lap", "car_id": "car-1", "lap_number": 1,
            "lap_time_s": 10.0, "t": 1.0,
        })
