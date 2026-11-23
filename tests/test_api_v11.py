"""REST and WebSocket additions in contract v1.1."""

import csv
import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from server.app.db import Database
from server.app.main import create_app
from server.app.track import default_track

from tests.helpers import drive, frame, wait_for


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with TestClient(create_app(db_path=path)) as c:
        c._db_path = path
        yield c
    if os.path.exists(path):
        os.remove(path)


def test_track_endpoint_describes_the_track(client):
    body = client.get("/api/track").json()
    track = default_track()
    assert body["width_m"] == track.width_m
    assert body["length_m"] == pytest.approx(track.length_m, abs=1e-3)
    assert body["anchor"] == {"lat": track.anchor_lat, "lon": track.anchor_lon}
    assert len(body["centerline"]) == len(track.centerline)
    assert body["centerline"][0] == [-4.0, -3.0]   # start/finish line


def test_track_can_be_replaced_from_a_file(tmp_path, monkeypatch):
    spec = tmp_path / "t.json"
    spec.write_text('{"name": "Square", "anchor": {"lat": 1, "lon": 2}, "width_m": 2,'
                    ' "centerline": [[0,0],[10,0],[10,10],[0,10]]}')
    monkeypatch.setenv("F163_TRACK", str(spec))
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with TestClient(create_app(db_path=path)) as c:
            assert c.get("/api/track").json()["name"] == "Square"
    finally:
        os.remove(path)


def test_control_is_acknowledged_and_timed(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "fw": "sim-0.2", "mode": "manual"})
        session_id = car.receive_json()["session_id"]
        car.send_json(frame(track, "car-1", 1, 1000.0, 0.0, 0.0))
        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            ui.receive_json()
            for ts in (10.0, 11.0):
                ui.send_json({"type": "control", "car_id": "car-1", "throttle": 0.5,
                              "steering": 0.1, "ts": ts, "ui_rtt_ms": 8.0})
            first, second = car.receive_json(), car.receive_json()
            assert (first["cseq"], second["cseq"]) == (1, 2)
            # The car acknowledges only the second one.
            car.send_json({"type": "control_ack", "cseq": 2})
            ack = ui.receive_json()
            assert ack["type"] == "control_ack"
            assert (ack["car_id"], ack["ts"]) == ("car-1", 11.0)
            assert 0.0 <= ack["car_rtt_ms"] < 1000.0
            # An ack for something never sent is ignored.
            car.send_json({"type": "control_ack", "cseq": 99})
            ui.send_json({"type": "ping", "ts": 1.0})
            assert ui.receive_json()["type"] == "pong"

    db = Database(client._db_path)
    assert wait_for(lambda: db.compute_kpis(session_id)["controls_sent"] == 2)
    k = db.compute_kpis(session_id)
    assert (k["controls_acked"], k["controls_lost"]) == (1, 1)
    assert k["control_rtt_p95_ms"] is not None
    # One-way estimate = (UI<->server 8 ms + server<->car round trip) / 2.
    assert k["latency_p95_ms"] == pytest.approx((8.0 + k["control_rtt_p95_ms"]) / 2, abs=0.01)


def test_broken_sensor_readings_are_stored_as_missing_and_counted(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "fw": "sim-0.2", "mode": "auto"})
        session_id = car.receive_json()["session_id"]
        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            ui.receive_json()
            good = frame(track, "car-1", 1, 1000.0, 1.0, 4.0)
            no_gps = {**frame(track, "car-1", 2, 1000.1, 1.4, 4.0), "gps": {"lat": None, "lon": None}}
            junk = {**frame(track, "car-1", 3, 1000.2, 1.8, 4.0), "battery_v": "full", "imu": "n/a"}
            no_seq = {**frame(track, "car-1", 4, 1000.3, 2.2, 4.0), "seq": None}
            for f in (good, no_gps, junk, no_seq):
                car.send_json(f)
            # Frames reach the UI exactly as the car sent them.
            assert ui.receive_json()["seq"] == 1
            assert ui.receive_json()["gps"] == {"lat": None, "lon": None}
            assert ui.receive_json()["battery_v"] == "full"

    db = Database(client._db_path)
    assert wait_for(lambda: len(db.get_telemetry(session_id)) == 3)   # the frame without seq is dropped
    rows = db.get_telemetry(session_id)
    assert rows[1]["lat"] is None and rows[1]["off_track"] is None
    assert rows[2]["battery_v"] is None and rows[2]["ax"] is None
    k = db.compute_kpis(session_id)
    assert k["sensor_errors"] == {"gps": 1, "imu": 1, "speed": 0, "heading": 0, "battery": 1}
    assert k["sensor_error_rows"] == 2


def test_csv_exports(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as car:
        car.send_json({"type": "hello", "car_id": "car-1", "fw": "sim-0.2", "mode": "auto"})
        session_id = car.receive_json()["session_id"]
        seq, _ = drive(car, track, "car-1", 0.0, track.length_m + 1.0, speed=8.0)

    assert wait_for(lambda: client.get(f"/api/sessions/{session_id}/kpis").json()["telemetry_rows"] == seq)
    r = client.get(f"/api/sessions/{session_id}/telemetry.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert f"session-{session_id}-car-1-telemetry.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == seq
    assert rows[0]["seq"] == "1" and rows[0]["speed_mps"] == "8.0" and rows[0]["off_track"] == "0"
    assert float(rows[-1]["track_s"]) == pytest.approx(1.0, abs=0.9)   # just past the line again

    laps = list(csv.DictReader(io.StringIO(client.get(f"/api/sessions/{session_id}/laps.csv").text)))
    assert [(l["lap_number"], l["source"], l["valid"]) for l in laps] == [("1", "server", "True")]

    assert client.get("/api/sessions/999/telemetry.csv").status_code == 404
    assert client.get("/api/sessions/999/laps.csv").status_code == 404


def test_car_connected_carries_mode_and_firmware(client):
    with client.websocket_connect("/ws/ui") as ui:
        ui.send_json({"type": "hello", "client": "web"})
        ui.receive_json()
        with client.websocket_connect("/ws/car") as car:
            car.send_json({"type": "hello", "car_id": "car-9", "fw": "sim-0.2", "mode": "auto"})
            car.receive_json()
            msg = ui.receive_json()
            assert (msg["type"], msg["mode"], msg["fw"]) == ("car_connected", "auto", "sim-0.2")
            ui.send_json({"type": "hello", "client": "web"})
            state = ui.receive_json()
            assert state["cars"][0]["fw"] == "sim-0.2"


def test_reconnecting_under_the_same_id_keeps_the_new_connection(client):
    """The old socket closing must not unregister the car that replaced it."""
    with client.websocket_connect("/ws/ui") as ui:
        ui.send_json({"type": "hello", "client": "web"})
        ui.receive_json()
        with client.websocket_connect("/ws/car") as new:
            with client.websocket_connect("/ws/car") as old:
                old.send_json({"type": "hello", "car_id": "car-1", "mode": "manual"})
                old.receive_json()
                new.send_json({"type": "hello", "car_id": "car-1", "mode": "manual"})
                new.receive_json()
            # `old` is closed now; a command must still reach `new`.
            for _ in range(3):
                assert ui.receive_json()["type"] in ("car_connected", "car_disconnected")
            ui.send_json({"type": "control", "car_id": "car-1", "throttle": 0.3, "steering": 0.0, "ts": 1.0})
            assert new.receive_json()["type"] == "control"
