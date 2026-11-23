"""KPIs added in contract v1.1: distance, track limits, sensors, IMU, latency."""

import os
import sqlite3
import tempfile

import pytest

from server.app.db import Database, percentile


@pytest.fixture()
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    if os.path.exists(path):
        os.remove(path)


def _row(sid, seq, **over):
    row = {
        "session_id": sid, "seq": seq, "t": 100.0 + seq * 0.1, "recv_t": 500.0 + seq * 0.1,
        "ax": 0.0, "ay": 0.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "lat": 41.0421, "lon": 29.0093,
        "speed_mps": 0.0, "heading_deg": 90.0, "battery_v": 7.4,
        "steering": 0.0, "throttle": 0.0, "off_track": 0, "track_s": 0.0,
    }
    row.update(over)
    return row


def _session_standing_then_driving(db):
    """10 frames stationary, then 20 frames at 5 m/s, the last 10 off the track."""
    sid = db.create_session("car-1", "manual", started_at=500.0, fw="sim-0.2")
    for seq in range(1, 11):
        db.insert_telemetry_row(_row(sid, seq))
    for seq in range(11, 31):
        db.insert_telemetry_row(_row(sid, seq, speed_mps=5.0, off_track=int(seq > 20)))
    return sid


def test_distance_and_moving_average_ignore_time_spent_standing(db):
    sid = _session_standing_then_driving(db)
    k = db.compute_kpis(sid)
    assert k["distance_m"] == pytest.approx(10.0)          # 20 samples x 5 m/s x 0.1 s
    assert k["moving_time_s"] == pytest.approx(2.0)
    assert k["avg_moving_speed_mps"] == pytest.approx(5.0)
    # The plain average still counts the standing start, as it always did.
    assert k["avg_speed_mps"] == pytest.approx(3.33, abs=0.01)


def test_off_track_time_and_share(db):
    sid = _session_standing_then_driving(db)
    k = db.compute_kpis(sid)
    assert k["off_track_s"] == pytest.approx(1.0)
    # Share of the time spent driving (2.0 s), not of the whole session.
    assert k["off_track_pct"] == pytest.approx(50.0, abs=0.01)


def test_a_car_parked_off_the_track_adds_no_off_track_time(db):
    sid = _session_standing_then_driving(db)
    for seq in range(31, 131):                     # 10 s stopped outside the limits
        db.insert_telemetry_row(_row(sid, seq, off_track=1))
    k = db.compute_kpis(sid)
    assert k["off_track_s"] == pytest.approx(1.0)
    assert k["off_track_pct"] == pytest.approx(50.0, abs=0.01)


def test_off_track_is_unknown_when_position_was_never_checked(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    for seq in range(1, 6):
        db.insert_telemetry_row(_row(sid, seq, off_track=None, track_s=None))
    k = db.compute_kpis(sid)
    assert k["off_track_s"] is None and k["off_track_pct"] is None


def test_a_telemetry_dropout_is_not_integrated_over(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    db.insert_telemetry_row(_row(sid, 1, t=100.0, speed_mps=5.0))
    db.insert_telemetry_row(_row(sid, 2, t=100.1, speed_mps=5.0))
    db.insert_telemetry_row(_row(sid, 3, t=130.0, speed_mps=5.0))   # 30 s of silence
    k = db.compute_kpis(sid)
    assert k["distance_m"] == pytest.approx(0.5)   # only the 0.1 s step counts


def test_sensor_errors_are_counted_per_sensor_and_per_frame(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    for seq in range(1, 21):
        db.insert_telemetry_row(_row(sid, seq, speed_mps=3.0))
    db.insert_telemetry_row(_row(sid, 21, lat=None, lon=None))
    db.insert_telemetry_row(_row(sid, 22, lat=95.0))                 # not a latitude
    db.insert_telemetry_row(_row(sid, 23, battery_v=None))
    db.insert_telemetry_row(_row(sid, 24, ax=None, speed_mps=99.0))  # two sensors, one frame
    db.insert_telemetry_row(_row(sid, 25, heading_deg=400.0))
    k = db.compute_kpis(sid)
    assert k["sensor_errors"] == {"gps": 2, "imu": 1, "speed": 1, "heading": 1, "battery": 1}
    assert k["sensor_error_rows"] == 5
    assert k["sensor_error_pct"] == pytest.approx(100 * 5 / 25)
    # Bad readings do not leak into the other figures.
    assert k["max_speed_mps"] == 3.0
    assert k["min_battery_v"] == 7.4
    # Sensor errors are not packet loss: every frame arrived.
    assert k["packet_loss_pct"] == 0.0


def test_acceleration_extremes_come_from_the_imu(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    for seq, (ax, ay) in enumerate([(3.0, 1.0), (-6.0, -4.0), (1.0, 2.5), (500.0, 0.0)], start=1):
        db.insert_telemetry_row(_row(sid, seq, ax=ax, ay=ay))
    k = db.compute_kpis(sid)
    assert k["max_accel_mps2"] == 3.0       # the 500 is a broken reading, not a launch
    assert k["max_brake_mps2"] == 6.0
    assert k["max_lateral_mps2"] == 4.0


def test_telemetry_rate_and_longest_silence_use_server_receive_time(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    recv = [500.0, 500.1, 500.2, 500.3, 500.9, 501.0]
    for seq, r in enumerate(recv, start=1):
        db.insert_telemetry_row(_row(sid, seq, recv_t=r))
    k = db.compute_kpis(sid)
    assert k["telemetry_rate_hz"] == pytest.approx(5 / 1.0)
    assert k["max_gap_s"] == pytest.approx(0.6)


def test_command_latency_percentiles(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    for i in range(1, 11):   # acknowledged after 10, 20, ... 100 ms
        db.insert_control(sid, float(i), 0.5, 0.0, recv_t=float(i), forwarded=True,
                          ack_rtt_ms=10.0 * i, ui_rtt_ms=20.0)
    db.insert_control(sid, 11.0, 0.5, 0.0, recv_t=11.0, forwarded=True)    # lost
    db.insert_control(sid, 12.0, 0.5, 0.0, recv_t=12.0, forwarded=True)    # lost
    db.insert_control(sid, 13.0, 0.5, 0.0, recv_t=13.0, forwarded=False)   # car was in auto
    k = db.compute_kpis(sid)
    assert (k["controls_sent"], k["controls_acked"], k["controls_lost"]) == (13, 10, 2)
    assert (k["control_rtt_p50_ms"], k["control_rtt_p95_ms"]) == (50.0, 100.0)
    # One-way UI -> car estimate: half the UI<->server and server<->car round trips.
    assert (k["latency_p50_ms"], k["latency_p95_ms"]) == (35.0, 60.0)


def test_a_car_that_never_acknowledges_is_not_reported_as_lossy(db):
    sid = db.create_session("car-1", "manual", started_at=0.0)
    for i in range(5):
        db.insert_control(sid, float(i), 0.5, 0.0, recv_t=float(i), forwarded=True)
    k = db.compute_kpis(sid)
    assert k["controls_sent"] == 5
    assert k["controls_lost"] is None
    assert k["latency_p95_ms"] is None


def test_percentile_is_nearest_rank():
    assert percentile([], 95) is None
    assert percentile([7.0], 95) == 7.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0


def test_invalid_laps_count_as_laps_but_not_as_best_or_average(db):
    sid = db.create_session("car-1", "auto", started_at=0.0)
    db.insert_lap(sid, 1, 9.0, 109.0)
    db.insert_lap(sid, 2, 6.0, 115.0, valid=False, off_track_s=2.0)   # cut the corner
    db.insert_lap(sid, 3, 8.0, 123.0)
    db.insert_lap(sid, 1, 0.8, 124.0, valid=False, source="car")      # unconfirmed report
    k = db.compute_kpis(sid)
    assert k["lap_count"] == 3
    assert k["invalid_laps"] == 1
    assert k["unconfirmed_car_laps"] == 1
    assert k["best_lap_s"] == 8.0
    assert k["avg_lap_s"] == 8.5


def test_kpis_over_a_time_window(db):
    sid = _session_standing_then_driving(db)
    db.insert_lap(sid, 1, 2.0, 101.5)
    db.insert_lap(sid, 2, 1.0, 102.5)
    # Only the driving part: frames 11..30 are at t = 101.1 .. 103.0.
    k = db.compute_kpis(sid, t_from=101.1, t_to=103.0)
    assert k["telemetry_rows"] == 20
    assert k["avg_speed_mps"] == 5.0
    assert k["distance_m"] == pytest.approx(9.5)   # 19 steps inside the window
    assert k["lap_count"] == 2
    assert k["duration_s"] == pytest.approx(1.9)


def test_a_v1_database_is_upgraded_in_place():
    """Opening an old data/f163.db must keep its sessions readable."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, car_id TEXT NOT NULL,
          mode TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL);
        CREATE TABLE telemetry (session_id INTEGER NOT NULL REFERENCES sessions(id),
          seq INTEGER NOT NULL, t REAL NOT NULL, ax REAL, ay REAL, az REAL, gx REAL, gy REAL,
          gz REAL, lat REAL, lon REAL, speed_mps REAL, heading_deg REAL, battery_v REAL,
          steering REAL, throttle REAL);
        CREATE INDEX idx_telemetry_session_t ON telemetry(session_id, t);
        CREATE TABLE laps (session_id INTEGER NOT NULL REFERENCES sessions(id),
          lap_number INTEGER NOT NULL, lap_time_s REAL NOT NULL, t REAL NOT NULL);
        CREATE TABLE control_log (session_id INTEGER NOT NULL REFERENCES sessions(id),
          ts REAL NOT NULL, throttle REAL NOT NULL, steering REAL NOT NULL);
        INSERT INTO sessions (car_id, mode, started_at, ended_at) VALUES ('car-1', 'auto', 100, 120);
        INSERT INTO telemetry VALUES (1, 1, 100.0, 0,0,9.81,0,0,0, 41.0, 29.0, 4.0, 90, 7.4, 0, 0.8);
        INSERT INTO telemetry VALUES (1, 2, 100.1, 0,0,9.81,0,0,0, 41.0, 29.0, 4.0, 90, 7.3, 0, 0.8);
        INSERT INTO laps VALUES (1, 1, 8.55, 108.55);
        INSERT INTO laps VALUES (1, 2, 8.75, 117.30);
        INSERT INTO control_log VALUES (1, 100.0, 0.5, 0.0);
    """)
    conn.commit()
    conn.close()
    try:
        db = Database(path)
        assert db.get_session(1)["fw"] is None
        laps = db.get_laps(1)
        assert [(l["lap_number"], l["source"], l["valid"]) for l in laps] == [(1, None, None), (2, None, None)]
        k = db.compute_kpis(1)
        # Laps recorded before the server timed them are still the session's laps.
        assert (k["lap_count"], k["best_lap_s"], k["avg_lap_s"]) == (2, 8.55, 8.65)
        assert k["max_speed_mps"] == 4.0 and k["distance_m"] == pytest.approx(0.4)
        assert k["off_track_s"] is None and k["telemetry_rate_hz"] is None
        assert k["controls_sent"] == 1 and k["controls_lost"] is None
        # And it takes new-style rows.
        db.insert_lap(1, 3, 8.4, 125.7, valid=True, off_track_s=0.0)
        assert db.compute_kpis(1)["best_lap_s"] == 8.4
        # Opening it a second time changes nothing.
        Database(path)
        assert len(Database(path).get_laps(1)) == 3
    finally:
        os.remove(path)


def test_sessions_left_open_by_a_crash_are_closed_at_startup(db):
    live = db.create_session("car-1", "auto", started_at=100.0)
    db.insert_telemetry_row(_row(live, 1, recv_t=150.0))
    db.insert_telemetry_row(_row(live, 2, recv_t=163.5))
    empty = db.create_session("car-2", "auto", started_at=200.0)
    done = db.create_session("car-3", "auto", started_at=300.0)
    db.end_session(done, ended_at=310.0)
    race = db.create_race("Crashed race", None, 140.0)
    db.add_race_entry(race, live, "car-1", 100.0, 140.0)

    db.close_orphans()

    assert db.get_session(live)["ended_at"] == 163.5     # its last frame
    assert db.get_session(empty)["ended_at"] == 200.0    # nothing ever arrived
    assert db.get_session(done)["ended_at"] == 310.0     # untouched
    assert db.get_race(race)["ended_at"] == 163.5
