"""Shared test helpers: a fake car that drives along the track."""

import time
from typing import Callable, Tuple

from server.app.track import Track


def frame(track: Track, car_id: str, seq: int, t: float, s: float, speed: float, offset: float = 0.0) -> dict:
    """A telemetry frame for a car ``s`` metres round the lap.

    ``offset`` moves it sideways off the centreline (metres, east) to put it
    outside track limits.
    """
    x, y = track.point_at(s)
    lat, lon = track.to_gps(x + offset, y)
    return {
        "type": "telemetry", "car_id": car_id, "seq": seq, "t": round(t, 4),
        "imu": {"ax": 0.2, "ay": 1.0, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.4},
        "gps": {"lat": lat, "lon": lon},
        "speed_mps": speed, "heading_deg": 90.0, "battery_v": 7.4,
        "steering": 0.0, "throttle": 0.5,
    }


def drive(
    car_ws,
    track: Track,
    car_id: str,
    s_from: float,
    s_to: float,
    speed: float = 8.0,
    hz: float = 10.0,
    seq: int = 0,
    t: float = 1000.0,
) -> Tuple[int, float]:
    """Send telemetry for a car driving from ``s_from`` to ``s_to`` metres.

    Returns the last ``(seq, t)`` so a caller can continue the same run.
    """
    dt = 1.0 / hz
    s = s_from
    while s <= s_to:
        seq += 1
        car_ws.send_json(frame(track, car_id, seq, t, s, speed))
        s += speed * dt
        t += dt
    return seq, t - dt


def wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll until ``predicate`` holds. Writes are queued, so a row sent a moment
    ago may not be on disk yet."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()
