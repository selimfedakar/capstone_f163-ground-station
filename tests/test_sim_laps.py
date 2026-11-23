"""Simulator lap counting and IMU model."""

import time

import pytest

from sim.car import CarSim, TICK_DT, build_parser


def _sim(*argv):
    return CarSim(build_parser().parse_args(list(argv)))


def _run(sim, ticks, control=None, t0=1000.0):
    laps = []
    now = time.monotonic()
    for i in range(ticks):
        if control is not None:
            sim.on_control(*control)
            sim.last_control_at = now + i * TICK_DT   # keep the command fresh on the test clock
        sim.step(now + i * TICK_DT)
        lap = sim.check_lap(t0 + i * TICK_DT)
        if lap:
            laps.append(lap)
    return laps


def test_donuts_on_the_start_line_are_not_laps():
    sim = _sim("--mode", "manual")
    laps = _run(sim, 600, control=(0.7, 1.0))   # full lock, 30 seconds
    assert laps == []
    assert sim.lap_number == 0


def test_autopilot_laps_are_counted_and_plausible():
    sim = _sim("--mode", "auto")
    laps = _run(sim, 600)   # 30 seconds
    assert [n for n, _ in laps] == [1, 2, 3]
    for _, lap_time in laps:
        assert lap_time == pytest.approx(sim.track_len / 4.07, rel=0.1)


def test_imu_reports_the_motion_not_just_noise():
    sim = _sim("--mode", "manual")
    # Launch in a straight line: clear forward acceleration, no cornering.
    sim.on_control(1.0, 0.0)
    sim.last_control_at = time.monotonic()
    sim.step(sim.last_control_at)
    ax = [sim.telemetry(1.0)["imu"]["ax"] for _ in range(50)]
    assert sum(ax) / len(ax) == pytest.approx(4.0, abs=0.1)   # ACCEL_RATE

    # Steady left turn at speed (steering < 0, contract 3): lateral
    # acceleration = v * yaw rate, positive.
    sim = _sim("--mode", "manual")
    _run(sim, 60, control=(0.6, -0.5))
    imu = [sim.telemetry(1.0)["imu"] for _ in range(50)]
    ay = sum(i["ay"] for i in imu) / len(imu)
    gz = sum(i["gz"] for i in imu) / len(imu)
    assert ay == pytest.approx(sim.speed * sim.yaw_rate, abs=0.1)
    assert ay > 5.0 and gz > 0


def test_sensor_fault_blanks_readings_at_the_requested_rate():
    sim = _sim("--mode", "auto", "--sensor-fault", "0.5")
    frames = [sim.telemetry(1.0) for _ in range(400)]
    def broken(f):
        return (f["gps"]["lat"] is None or f["imu"]["ax"] is None
                or f["speed_mps"] is None or f["battery_v"] is None)
    assert 150 < sum(broken(f) for f in frames) < 250
    assert not any(broken(_sim("--mode", "auto").telemetry(1.0)) for _ in range(50))
