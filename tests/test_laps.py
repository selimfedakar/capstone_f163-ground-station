"""Server-side lap timing (server/app/laps.py)."""

import math

import pytest

from server.app.laps import LapTracker
from server.app.track import default_track


def run(tracker, track, s_from, s_to, speed=4.0, hz=20.0, t=100.0, dy=0.0):
    """Drive along the centreline; returns (lap events, end time).

    ``dy`` shifts the car north of the centreline, in metres (negative on the
    bottom straight is the outside of the track).
    """
    dt = 1.0 / hz
    laps = []
    s = s_from
    step = speed * dt
    while (s <= s_to) if step > 0 else (s >= s_to):
        x, y = track.point_at(s)
        ev, _, _ = tracker.update(x, y + dy, t, abs(speed))
        if ev:
            laps.append(ev)
        s += step
        t += dt
    return laps, t


def test_a_driven_lap_is_timed_to_the_millisecond():
    track = default_track()
    tracker = LapTracker(track)
    speed = 4.0
    laps, _ = run(tracker, track, 0.0, track.length_m + 1.0, speed=speed)
    assert [l.lap_number for l in laps] == [1]
    # 20 Hz samples are 50 ms apart; interpolating the crossing does far better.
    assert laps[0].lap_time_s == pytest.approx(track.length_m / speed, abs=0.002)
    assert laps[0].valid is True
    assert laps[0].off_track_s == 0.0


def test_consecutive_laps_each_take_one_lap():
    track = default_track()
    tracker = LapTracker(track)
    laps, _ = run(tracker, track, 0.0, 3 * track.length_m + 1.0, speed=5.0)
    assert [l.lap_number for l in laps] == [1, 2, 3]
    for lap in laps:
        assert lap.lap_time_s == pytest.approx(track.length_m / 5.0, abs=0.002)
    # Lap times add up: each lap starts where the last one ended.
    assert laps[2].t - laps[0].t == pytest.approx(2 * track.length_m / 5.0, abs=0.002)


def test_circling_on_the_start_line_is_not_a_lap():
    """The bug this module exists for: 0.8 s 'laps' from donuts on the line."""
    track = default_track()
    tracker = LapTracker(track)
    cx, cy, r = -4.0, -2.57, 0.43   # full-lock circle starting on the line
    t = 100.0
    laps = []
    for i in range(600):
        a = -math.pi / 2 + i * 0.4
        ev, _, _ = tracker.update(cx + r * math.cos(a), cy + r * math.sin(a), t, 3.4)
        if ev:
            laps.append(ev)
        t += 0.05
    assert laps == []
    assert tracker.lap_number == 0


def test_reversing_over_the_line_and_back_is_not_a_lap():
    track = default_track()
    length = track.length_m
    tracker = LapTracker(track)
    laps, t = run(tracker, track, 0.0, length + 2.0, speed=4.0)
    assert [l.lap_number for l in laps] == [1]
    # Back over the line, then forward over it again: the line is crossed
    # going forward a second time with no lap driven in between.
    back, t = run(tracker, track, length + 2.0, length - 3.0, speed=-4.0, t=t)
    again, t = run(tracker, track, length - 3.0, length + 2.0, speed=4.0, t=t)
    assert back == [] and again == []
    assert tracker.lap_number == 1
    # The next real lap is timed from that last crossing.
    laps, _ = run(tracker, track, length + 2.0, 2 * length + 1.0, speed=4.0, t=t)
    assert [l.lap_number for l in laps] == [2]
    assert laps[0].lap_time_s == pytest.approx(length / 4.0, abs=0.06)


def test_a_lap_started_mid_track_counts_from_the_first_crossing():
    track = default_track()
    tracker = LapTracker(track)
    laps, _ = run(tracker, track, 10.0, 2 * track.length_m + 1.0, speed=4.0)
    assert [l.lap_number for l in laps] == [1]
    assert laps[0].lap_time_s == pytest.approx(track.length_m / 4.0, abs=0.002)


def test_running_wide_invalidates_the_lap_time_but_still_counts_the_lap():
    track = default_track()
    tracker = LapTracker(track)
    laps, t = run(tracker, track, 0.0, 2.0, speed=4.0)
    # 1.2 m outside the bottom straight for 4 m: off the 1.6 m wide surface.
    wide, t = run(tracker, track, 2.0, 6.0, speed=4.0, t=t, dy=-1.2)
    rest, _ = run(tracker, track, 6.0, track.length_m + 1.0, speed=4.0, t=t)
    laps = laps + wide + rest
    assert [l.lap_number for l in laps] == [1]
    assert laps[0].valid is False
    assert laps[0].off_track_s == pytest.approx(1.0, abs=0.11)


def test_a_brief_touch_of_the_edge_does_not_invalidate_the_lap():
    track = default_track()
    tracker = LapTracker(track)
    laps, t = run(tracker, track, 0.0, 2.0, speed=4.0)
    wide, t = run(tracker, track, 2.0, 2.4, speed=4.0, t=t, dy=-1.2)   # about 0.1 s
    rest, _ = run(tracker, track, 2.4, track.length_m + 1.0, speed=4.0, t=t)
    laps = laps + wide + rest
    assert [l.valid for l in laps] == [True]


def test_teleport_abandons_the_lap_in_progress():
    """A reset mid-lap must not be credited as driving the rest of the lap."""
    track = default_track()
    tracker = LapTracker(track)
    _, t = run(tracker, track, 0.0, 20.0, speed=4.0)
    # Car is picked up and put back on the line, then drives off again.
    laps, t = run(tracker, track, 0.0, 5.0, speed=4.0, t=t)
    assert laps == []
    # A whole lap from here does count, timed from when it moved off the line.
    laps, _ = run(tracker, track, 5.0, track.length_m + 1.0, speed=4.0, t=t)
    assert [l.lap_number for l in laps] == [1]
    assert laps[0].lap_time_s == pytest.approx(track.length_m / 4.0, abs=0.06)


def test_abandon_is_what_a_reset_calls():
    track = default_track()
    tracker = LapTracker(track)
    _, t = run(tracker, track, 0.0, 30.0, speed=4.0)
    tracker.abandon()
    laps, _ = run(tracker, track, 30.0, track.length_m + 2.0, speed=4.0, t=t)
    assert laps == []   # crossing the line only restarts the clock


def test_race_start_times_lap_one_from_the_flag_not_from_moving_off():
    track = default_track()
    tracker = LapTracker(track)
    # Car is somewhere out on the track when the race is started at t=200.
    _, t = run(tracker, track, 12.0, 15.0, speed=4.0, t=199.0)
    tracker.start_at(200.0)
    # It is reset to the line (a jump, inside the grace period) and sits for 2 s.
    for i in range(40):
        x, y = track.point_at(0.0)
        tracker.update(x, y, 200.05 + i * 0.05, 0.0)
    laps, _ = run(tracker, track, 0.0, track.length_m + 1.0, speed=4.0, t=202.05)
    assert [l.lap_number for l in laps] == [1]
    # 2.05 s on the grid + the lap itself.
    assert laps[0].lap_time_s == pytest.approx(2.05 + track.length_m / 4.0, abs=0.06)


def test_race_start_from_behind_the_line_still_counts_from_the_flag():
    track = default_track()
    tracker = LapTracker(track)
    tracker.start_at(None)   # flag falls at the next sample
    # Gridded 1 m behind the line; it crosses the line at once, then laps.
    laps, _ = run(tracker, track, track.length_m - 1.0, 2 * track.length_m + 1.0, speed=4.0, t=300.0)
    assert [l.lap_number for l in laps] == [1]
    assert laps[0].lap_time_s == pytest.approx((track.length_m + 1.0) / 4.0, abs=0.06)


def test_clock_going_backwards_does_not_crash_or_count():
    track = default_track()
    tracker = LapTracker(track)
    x, y = track.point_at(1.0)
    tracker.update(x, y, 100.0, 4.0)
    ev, _, _ = tracker.update(x, y, 99.0, 4.0)
    assert ev is None
