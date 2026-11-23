"""Simulator reset: back on the line, stopped, lap in progress abandoned."""

import time

from sim.car import build_parser, CarSim


def _sim(mode="manual"):
    return CarSim(build_parser().parse_args(["--mode", mode]))


def test_reset_returns_to_start_line_stopped():
    sim = _sim()
    start = (sim.x, sim.y)
    sim.on_control(1.0, 0.6)
    now = time.monotonic()
    for i in range(40):
        sim.on_control(1.0, 0.6)
        # Keep the command fresh on the test's clock (0.5 s safety decay).
        sim.last_control_at = now + i * 0.05
        sim.step(now + i * 0.05)
        sim.check_lap(1000.0 + i * 0.05)
    assert (sim.x, sim.y) != start
    assert sim.speed > 0
    seq_before, laps_before, charge_before = sim.seq, sim.lap_number, sim.battery_charge

    sim.reset()

    assert (sim.x, sim.y) == start
    assert sim.heading == 0.0
    assert sim.speed == 0.0
    assert sim.applied_throttle == 0.0 and sim.applied_steering == 0.0
    assert sim.lap_start_t is None
    # Session bookkeeping survives a reset.
    assert (sim.seq, sim.lap_number, sim.battery_charge) == (seq_before, laps_before, charge_before)


def test_reset_stops_a_car_still_holding_throttle():
    sim = _sim()
    sim.on_control(1.0, 0.0)
    sim.reset()
    sim.step(time.monotonic())
    assert sim.speed == 0.0
