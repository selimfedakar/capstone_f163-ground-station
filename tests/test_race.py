"""Races: start, lap-by-lap classification, automatic finish, results, CSV."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from server.app.main import create_app
from server.app.track import default_track

from tests.helpers import drive, frame, wait_for


@pytest.fixture()
def client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with TestClient(create_app(db_path=path)) as c:
        yield c
    if os.path.exists(path):
        os.remove(path)


def _connect(car, car_id, mode="auto"):
    car.send_json({"type": "hello", "car_id": car_id, "fw": "sim-0.2", "mode": mode})
    return car.receive_json()["session_id"]


def _until(ws, predicate, max_msgs=400):
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message never arrived")


def test_cannot_start_a_race_with_no_cars(client):
    r = client.post("/api/races", json={})
    assert r.status_code == 409
    assert "no car" in r.json()["detail"]


def test_race_between_two_cars(client):
    track = default_track()
    L = track.length_m
    with client.websocket_connect("/ws/car") as a, client.websocket_connect("/ws/car") as b:
        sid_a, sid_b = _connect(a, "car-a"), _connect(b, "car-b")
        # Both are sitting somewhere out on the track before the start.
        a.send_json(frame(track, "car-a", 1, 1000.0, 12.0, 0.0))
        b.send_json(frame(track, "car-b", 1, 1000.0, 20.0, 0.0))

        with client.websocket_connect("/ws/ui") as ui:
            ui.send_json({"type": "hello", "client": "web"})
            assert ui.receive_json()["race"] is None

            r = client.post("/api/races", json={"name": "Final", "laps": 2})
            assert r.status_code == 201
            race = r.json()
            assert race["name"] == "Final" and race["laps_target"] == 2
            assert race["cars"] == ["car-a", "car-b"]
            # Every car is sent back to the line.
            assert a.receive_json() == {"type": "reset"}
            assert b.receive_json() == {"type": "reset"}
            started = _until(ui, lambda m: m["type"] == "race")
            assert started["race"]["id"] == race["id"]

            # A second race cannot start while this one runs.
            assert client.post("/api/races", json={}).status_code == 409
            # A UI that connects now is told about it.
            with client.websocket_connect("/ws/ui") as late:
                late.send_json({"type": "hello", "client": "web"})
                assert late.receive_json()["race"]["id"] == race["id"]

            # car-a laps at 8 m/s, car-b at 6 m/s, both from the line.
            seq_a, t_a = drive(a, track, "car-a", 0.0, L + 1.0, speed=8.0, seq=1, t=1000.1)
            lap = _until(ui, lambda m: m["type"] == "lap")
            assert (lap["car_id"], lap["race_id"], lap["race_lap"]) == ("car-a", race["id"], 1)
            # Timed from the flag at t=1000, not from the first frame at 1000.1.
            assert lap["race_time_s"] == pytest.approx(0.1 + L / 8.0, abs=0.02)

            seq_b, t_b = drive(b, track, "car-b", 0.0, L + 1.0, speed=6.0, seq=1, t=1000.1)
            lap = _until(ui, lambda m: m["type"] == "lap")
            assert (lap["car_id"], lap["race_lap"]) == ("car-b", 1)

            # Mid-race standings: same lap, car-a ahead on time.
            live = client.get(f"/api/races/{race['id']}").json()
            assert live["ended_at"] is None
            assert [(x["position"], x["car_id"], x["laps"]) for x in live["results"]] == [
                (1, "car-a", 1), (2, "car-b", 1)]
            assert live["results"][1]["gap_s"] == pytest.approx(L / 6.0 - L / 8.0, abs=0.02)

            # car-a completes lap 2: that is the lap target, so the race ends.
            drive(a, track, "car-a", 1.5, L + 1.0, speed=8.0, seq=seq_a, t=t_a + 0.1)
            finished = _until(ui, lambda m: m["type"] == "race" and m["race"] is None)
            assert finished["finished"]["id"] == race["id"]
            assert "car-a completed 2 laps" in finished["finished"]["reason"]

        result = client.get(f"/api/races/{race['id']}").json()
        assert result["ended_at"] is not None
        first, second = result["results"]
        assert (first["position"], first["car_id"], first["laps"]) == (1, "car-a", 2)
        assert (first["gap_laps"], first["gap_s"]) == (0, 0.0)
        assert first["total_time_s"] == pytest.approx(0.1 + 2 * L / 8.0, abs=0.05)
        # (The fake car's second stint resumes a few cm ahead, hence the tolerance.)
        assert first["best_lap_s"] == pytest.approx(L / 8.0, abs=0.06)
        assert [l["race_lap"] for l in first["lap_times"]] == [1, 2]
        assert (second["position"], second["car_id"], second["laps"]) == (2, "car-b", 1)
        assert (second["gap_laps"], second["gap_s"]) == (1, None)
        assert second["max_speed_mps"] == 6.0
        # Race figures cover the race only, not the wait before the start.
        assert second["distance_m"] == pytest.approx(L + 1.0, abs=1.0)

        # Laps after the flag do not belong to the race.
        drive(b, track, "car-b", 1.5, L + 1.0, speed=6.0, seq=seq_b, t=t_b + 0.1)
        assert wait_for(lambda: len(client.get(f"/api/sessions/{sid_b}/laps").json()) == 2)
        laps_b = client.get(f"/api/sessions/{sid_b}/laps").json()
        assert [l["race_id"] for l in laps_b] == [race["id"], None]
        assert client.get(f"/api/races/{race['id']}").json()["results"][1]["laps"] == 1

        listing = client.get("/api/races").json()
        assert [(x["id"], x["name"], x["cars"]) for x in listing] == [(race["id"], "Final", 2)]

        csv_text = client.get(f"/api/races/{race['id']}/results.csv").text.splitlines()
        assert csv_text[0].startswith("position,car_id,session_id,laps,total_time_s")
        assert csv_text[1].startswith("1,car-a,") and csv_text[2].startswith("2,car-b,")
        assert sid_a != sid_b


def test_operator_finishes_a_race_without_a_lap_target(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as a:
        _connect(a, "car-a")
        a.send_json(frame(track, "car-a", 1, 1000.0, 0.0, 0.0))
        race = client.post("/api/races", json={"reset": False}).json()
        assert race["laps_target"] is None
        assert race["name"].startswith("Race at ")
        assert client.post("/api/races/999/finish").status_code == 409
        done = client.post(f"/api/races/{race['id']}/finish").json()
        assert done["reason"] == "operator" and done["ended_at"] is not None
        assert client.post(f"/api/races/{race['id']}/finish").status_code == 409
        # With no race running, a new one can start.
        assert client.post("/api/races", json={"reset": False}).status_code == 201


def test_a_car_connecting_mid_race_joins_it(client):
    track = default_track()
    with client.websocket_connect("/ws/car") as a:
        _connect(a, "car-a")
        a.send_json(frame(track, "car-a", 1, 1000.0, 0.0, 0.0))
        race = client.post("/api/races", json={"reset": False}).json()
        with client.websocket_connect("/ws/car") as b:
            _connect(b, "car-late")
            drive(b, track, "car-late", 0.0, track.length_m + 1.0, speed=8.0, t=2000.0)
            assert wait_for(lambda: len(client.get(f"/api/races/{race['id']}").json()["results"]) == 2)
            late = next(r for r in client.get(f"/api/races/{race['id']}").json()["results"]
                        if r["car_id"] == "car-late")
            assert late["laps"] == 1
            assert late["total_time_s"] == pytest.approx(track.length_m / 8.0, abs=0.02)


def test_unknown_race_is_404(client):
    assert client.get("/api/races/42").status_code == 404
    assert client.get("/api/races/42/results.csv").status_code == 404
    assert client.get("/api/races").json() == []
