"""Unit tests for the SQLite storage layer and KPI computation."""

import os
import tempfile

import pytest

from server.app.db import Database


@pytest.fixture()
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    if os.path.exists(path):
        os.remove(path)


def _tel_row(session_id, seq, t, speed, battery, **extra):
    row = {
        "session_id": session_id, "seq": seq, "t": t,
        "ax": 0.0, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "lat": 41.0, "lon": 29.0,
        "speed_mps": speed, "heading_deg": 90.0, "battery_v": battery,
        "steering": 0.0, "throttle": 0.5,
    }
    row.update(extra)
    return row


def test_session_lifecycle(db):
    sid = db.create_session("car-1", "manual", started_at=100.0)
    assert sid == 1
    sessions = db.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["car_id"] == "car-1"
    assert sessions[0]["mode"] == "manual"
    assert sessions[0]["ended_at"] is None

    db.end_session(sid, ended_at=200.0)
    s = db.get_session(sid)
    assert s["ended_at"] == 200.0


def test_sessions_newest_first(db):
    db.create_session("car-1", "auto", started_at=100.0)
    db.create_session("car-2", "manual", started_at=101.0)
    sessions = db.list_sessions()
    assert [s["id"] for s in sessions] == [2, 1]


def test_telemetry_insert_and_read(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    for i in range(5):
        db.insert_telemetry_row(_tel_row(sid, seq=i + 1, t=float(i), speed=float(i), battery=8.0))
    rows = db.get_telemetry(sid)
    assert len(rows) == 5
    # Ordered by t.
    assert [r["t"] for r in rows] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert rows[0]["az"] == 9.81


def test_telemetry_time_filter_and_limit(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    for i in range(10):
        db.insert_telemetry_row(_tel_row(sid, seq=i + 1, t=float(i), speed=1.0, battery=8.0))
    rows = db.get_telemetry(sid, from_t=3.0, to_t=6.0)
    assert [r["t"] for r in rows] == [3.0, 4.0, 5.0, 6.0]
    rows = db.get_telemetry(sid, limit=2)
    assert len(rows) == 2


def test_laps(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    db.insert_lap(sid, 1, 15.2, 20.0)
    db.insert_lap(sid, 2, 14.8, 35.0)
    laps = db.get_laps(sid)
    assert [l["lap_number"] for l in laps] == [1, 2]
    assert laps[1]["lap_time_s"] == 14.8


def test_kpis_exact_values_no_gaps(db):
    sid = db.create_session("car-1", "auto", started_at=100.0)
    speeds = [1.0, 2.0, 3.0, 4.0, 5.0]
    batteries = [8.0, 7.9, 7.8, 7.7, 7.5]
    for i in range(5):
        db.insert_telemetry_row(
            _tel_row(sid, seq=i + 1, t=100.0 + i, speed=speeds[i], battery=batteries[i])
        )
    db.insert_lap(sid, 1, 15.0, 115.0)
    db.insert_lap(sid, 2, 14.0, 130.0)
    db.insert_lap(sid, 3, 16.0, 146.0)
    db.end_session(sid, ended_at=410.5)

    k = db.compute_kpis(sid)
    assert k["session_id"] == sid
    assert k["lap_count"] == 3
    assert k["best_lap_s"] == 14.0
    assert k["avg_lap_s"] == 15.0
    assert k["max_speed_mps"] == 5.0
    assert k["avg_speed_mps"] == 3.0
    assert k["min_battery_v"] == 7.5
    assert k["telemetry_rows"] == 5
    assert k["seq_gaps"] == 0
    assert k["packet_loss_pct"] == 0.0
    assert k["duration_s"] == 310.5


def test_kpis_seq_gaps_and_packet_loss(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    # seqs: 1,2,4,5,10 -> gaps: (4-2-1)=1, (10-5-1)=4 => 5 missing.
    # span = 10 - 1 + 1 = 10, loss = 5/10 * 100 = 50.0
    seqs = [1, 2, 4, 5, 10]
    for i, s in enumerate(seqs):
        db.insert_telemetry_row(_tel_row(sid, seq=s, t=float(i), speed=1.0, battery=8.0))
    k = db.compute_kpis(sid)
    assert k["telemetry_rows"] == 5
    assert k["seq_gaps"] == 5
    assert k["packet_loss_pct"] == 50.0


def test_kpis_empty_session(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    k = db.compute_kpis(sid)
    assert k["lap_count"] == 0
    assert k["telemetry_rows"] == 0
    assert k["seq_gaps"] == 0
    assert k["packet_loss_pct"] == 0.0
    assert k["best_lap_s"] is None


def test_kpis_missing_session(db):
    assert db.compute_kpis(999) is None


def test_control_log(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    db.insert_control(sid, ts=1.0, throttle=0.5, steering=-0.2)
    import sqlite3
    conn = sqlite3.connect(db.path)
    rows = conn.execute("SELECT ts, throttle, steering FROM control_log").fetchall()
    conn.close()
    assert rows == [(1.0, 0.5, -0.2)]
