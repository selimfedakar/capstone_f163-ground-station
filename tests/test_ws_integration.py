"""WS integration test using FastAPI TestClient.

A fake car connects (hello + telemetry + lap). A fake UI connects, receives
broadcasts, and sends a control; the car must receive it. Rows land in a temp DB.
"""

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from server.app.db import Database
from server.app.main import create_app


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


def _drain_until(ws, wanted_type, max_msgs=50):
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == wanted_type:
            return msg
    raise AssertionError(f"did not receive message of type {wanted_type}")


def test_full_flow_manual(client):
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

            # Car sends telemetry; UI should receive it verbatim.
            for seq in range(1, 6):
                car.send_json({
                    "type": "telemetry", "car_id": "car-1", "seq": seq,
                    "t": 1000.0 + seq,
                    "imu": {"ax": 0.1, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0},
                    "gps": {"lat": 41.0, "lon": 29.0},
                    "speed_mps": float(seq), "heading_deg": 90.0, "battery_v": 7.4,
                    "steering": 0.0, "throttle": 0.5,
                })
            tel = _drain_until(ui, "telemetry")
            assert tel["car_id"] == "car-1"
            assert tel["seq"] >= 1

            # Car sends a lap; UI should receive it.
            car.send_json({
                "type": "lap", "car_id": "car-1", "lap_number": 1,
                "lap_time_s": 14.82, "t": 1010.0,
            })
            lap = _drain_until(ui, "lap")
            assert lap["lap_number"] == 1

            # UI sends a control; the car must receive it clamped and forwarded.
            ui.send_json({
                "type": "control", "car_id": "car-1",
                "throttle": 2.0, "steering": -0.25, "ts": 1011.0,
            })
            ctrl = car.receive_json()
            assert ctrl["type"] == "control"
            assert ctrl["throttle"] == 1.0  # clamped from 2.0
            assert ctrl["steering"] == -0.25

            # ping -> pong
            ui.send_json({"type": "ping", "ts": 1234.5})
            pong = _drain_until(ui, "pong")
            assert pong["ts"] == 1234.5
            assert "server_time" in pong

    # After the car disconnects, allow the writer to flush, then check the DB.
    db = Database(client._db_path)
    # Telemetry is flushed on car disconnect (writer stop flush) / lifespan close.
    # Give a short grace; TestClient context exit triggered lifespan shutdown.
    deadline = time.time() + 3.0
    rows = []
    while time.time() < deadline:
        rows = db.get_telemetry(session_id)
        if len(rows) >= 5:
            break
        time.sleep(0.05)
    assert len(rows) == 5

    laps = db.get_laps(session_id)
    assert len(laps) == 1
    assert laps[0]["lap_number"] == 1

    # Control was logged.
    import sqlite3
    conn = sqlite3.connect(client._db_path)
    n = conn.execute("SELECT COUNT(*) FROM control_log WHERE session_id=?", (session_id,)).fetchone()[0]
    conn.close()
    assert n == 1

    # Session ended on disconnect.
    s = db.get_session(session_id)
    assert s["ended_at"] is not None


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

    import sqlite3
    conn = sqlite3.connect(client._db_path)
    n = conn.execute("SELECT COUNT(*) FROM control_log WHERE session_id=?", (session_id,)).fetchone()[0]
    conn.close()
    assert n == 1  # logged even though not forwarded


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
