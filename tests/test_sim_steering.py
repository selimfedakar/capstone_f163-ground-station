"""The simulator must steer the way the contract says: negative is left."""

import argparse
import math
import time

from sim.car import CarSim, TICK_DT


def _sim(mode="manual"):
    return CarSim(argparse.Namespace(car_id="car-t", mode=mode, loss=0.0))


def _drive(sim, steering, ticks=10):
    now = time.monotonic()
    for _ in range(ticks):
        sim.on_control(0.5, steering)
        sim.last_control_at = now
        sim.step(now)
        now += TICK_DT


def test_negative_steering_turns_left():
    sim = _sim()
    _drive(sim, -1.0)
    # Starting along +x, a left turn swings the nose toward +y.
    assert 0.0 < sim.heading < math.pi
    assert sim.yaw_rate > 0.0
    assert sim.y > sim.centerline[0][1]
    # The sideways acceleration the IMU reports is positive in a left turn.
    assert sim.speed * sim.yaw_rate > 0.0


def test_positive_steering_turns_right():
    sim = _sim()
    _drive(sim, 1.0)
    assert -math.pi < sim.heading < 0.0
    assert sim.yaw_rate < 0.0
    assert sim.y < sim.centerline[0][1]


def test_autopilot_reports_left_as_negative():
    """The track runs counter-clockwise, so every bend is a left turn."""
    sim = _sim("auto")
    now = time.monotonic()
    steering = []
    for _ in range(int(12 / TICK_DT)):
        sim.step(now)
        now += TICK_DT
        steering.append(sim.applied_steering)
    assert min(steering) < -0.1
    assert max(steering) < 0.1
