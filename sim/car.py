"""F163 car simulator (contract 6).

Kinematic bicycle model on a closed oval/stadium track at 20 Hz. Supports a
pure-pursuit autopilot (``--mode auto``) and operator-driven ``--mode manual``
(applies the last received control with a 0.5 s safety decay to zero throttle).
Reports IMU readings derived from the motion (longitudinal and centripetal
acceleration, yaw rate) with noise, models battery sag, acknowledges each
control it receives, and can drop telemetry packets (``--loss``) or blank out
sensor readings (``--sensor-fault``) to exercise the loss and sensor-error KPIs.

Run:
    python -m sim.car --mode auto --duration 10
    python -m sim.car --mode manual --server ws://127.0.0.1:8000/ws/car
"""

import argparse
import asyncio
import json
import math
import random
import time
from typing import Optional

import websockets

from .track import (
    build_centerline,
    lookahead_point,
    nearest_index,
    track_length,
)

FIRMWARE = "sim-0.2"

TICK_HZ = 20.0
TICK_DT = 1.0 / TICK_HZ

# Vehicle parameters.
WHEELBASE = 0.25           # meters
MAX_SPEED = 5.0            # m/s at full throttle
MAX_STEER_RAD = math.radians(30.0)
ACCEL_RATE = 4.0           # m/s^2 toward target speed
LOOKAHEAD_PTS = 24         # centerline points ahead for pure pursuit

# Battery model.
BATTERY_FULL_V = 8.4
BATTERY_NOMINAL_V = 7.4
BATTERY_SAG_PER_THROTTLE = 0.8   # volts of sag at full throttle
BATTERY_DRAIN_PER_S = 0.01       # slow steady drain

# Geographic anchor for GPS projection (Bogazici area, matches contract sample).
ANCHOR_LAT = 41.0421
ANCHOR_LON = 29.0093
M_PER_DEG_LAT = 111_320.0

CONTROL_TIMEOUT_S = 0.5
# Fraction of the centreline a car must cover for a line crossing to be a lap.
LAP_MIN_PROGRESS = 0.9


def local_to_gps(x: float, y: float):
    """Project a local planar (x, y) meter offset to lat/lon degrees."""
    lat = ANCHOR_LAT + y / M_PER_DEG_LAT
    m_per_deg_lon = M_PER_DEG_LAT * math.cos(math.radians(ANCHOR_LAT))
    lon = ANCHOR_LON + x / m_per_deg_lon
    return lat, lon


class CarSim:
    def __init__(self, args):
        self.args = args
        self.car_id = args.car_id
        self.mode = args.mode
        self.loss = args.loss

        self.centerline = build_centerline()
        self.track_len = track_length(self.centerline)

        # Start at centerline origin (start/finish), heading along +x.
        self.x, self.y = self.centerline[0]
        self.heading = 0.0          # radians
        self.speed = 0.0            # m/s

        self.seq = 0
        self.battery_charge = BATTERY_FULL_V

        # Lap tracking.
        self.lap_number = 0
        self.lap_start_t: Optional[float] = None
        self.prev_near_i = 0
        # Centreline points covered since the current lap began. A lap only
        # counts once this reaches most of the track (see check_lap).
        self.lap_progress = 0

        # Motion state reported by the IMU.
        self.accel_long = 0.0       # m/s^2, along the car
        self.yaw_rate = 0.0         # rad/s
        self.sensor_fault = getattr(args, "sensor_fault", 0.0)
        # Autopilot pace: 1.0 is the default driver, lower is a slower one.
        self.pace = max(0.2, min(1.15, getattr(args, "pace", 1.0)))

        # Manual control state.
        self.last_control_throttle = 0.0
        self.last_control_steering = 0.0
        self.last_control_at = 0.0

        # Applied actuation (echoed in telemetry).
        self.applied_throttle = 0.0
        self.applied_steering = 0.0

        self._stop = False

    # ---- reset (contract 2) -------------------------------------------
    def reset(self):
        """Put the car back on the start/finish line, stopped.

        The lap in progress is abandoned: the timer re-arms on the next
        start, so a reset can never produce a short lap. Completed laps,
        the sequence counter, and the battery are left alone.
        """
        self.x, self.y = self.centerline[0]
        self.heading = 0.0
        self.speed = 0.0
        self.last_control_throttle = 0.0
        self.last_control_steering = 0.0
        self.last_control_at = 0.0
        self.applied_throttle = 0.0
        self.applied_steering = 0.0
        self.lap_start_t = None
        self.prev_near_i = 0
        self.lap_progress = 0
        self.accel_long = 0.0
        self.yaw_rate = 0.0

    # ---- control input (manual mode) ---------------------------------
    def on_control(self, throttle: float, steering: float):
        self.last_control_throttle = max(-1.0, min(1.0, throttle))
        self.last_control_steering = max(-1.0, min(1.0, steering))
        self.last_control_at = time.monotonic()

    def _compute_actuation(self, now_mono: float):
        """Return (throttle, steering) normalized in [-1, 1]."""
        if self.mode == "auto":
            return self._pure_pursuit()
        # Manual: apply last control with 0.5 s safety decay on throttle.
        if now_mono - self.last_control_at > CONTROL_TIMEOUT_S:
            return 0.0, self.last_control_steering
        return self.last_control_throttle, self.last_control_steering

    def _pure_pursuit(self):
        near_i = nearest_index(self.centerline, self.x, self.y)
        tx, ty = lookahead_point(self.centerline, near_i, LOOKAHEAD_PTS)
        # Angle to lookahead point in vehicle frame.
        dx = tx - self.x
        dy = ty - self.y
        target_ang = math.atan2(dy, dx)
        alpha = _wrap_angle(target_ang - self.heading)
        ld = math.hypot(dx, dy)
        if ld < 1e-6:
            steer_rad = 0.0
        else:
            steer_rad = math.atan2(2.0 * WHEELBASE * math.sin(alpha), ld)
        # Contract 3: negative steering is left. A left bend is a positive
        # (counter-clockwise) wheel angle here, so the sign flips.
        steering = max(-1.0, min(1.0, -steer_rad / MAX_STEER_RAD))
        # Ease throttle in corners.
        throttle = (0.85 - 0.3 * min(1.0, abs(steering))) * self.pace
        return min(1.0, throttle), steering

    # ---- physics ------------------------------------------------------
    def step(self, now_mono: float):
        throttle, steering = self._compute_actuation(now_mono)
        self.applied_throttle = throttle
        self.applied_steering = steering

        target_speed = throttle * MAX_SPEED
        # First-order speed response toward target.
        dv = target_speed - self.speed
        max_dv = ACCEL_RATE * TICK_DT
        if dv > max_dv:
            dv = max_dv
        elif dv < -max_dv:
            dv = -max_dv
        self.speed += dv
        if self.speed < 0:
            self.speed = max(self.speed, -MAX_SPEED)
        self.accel_long = dv / TICK_DT

        # Contract 3: steering < 0 is left, > 0 is right. Heading is measured
        # counter-clockwise, so steering left must increase it.
        steer_rad = -steering * MAX_STEER_RAD

        # Kinematic bicycle update.
        self.x += self.speed * math.cos(self.heading) * TICK_DT
        self.y += self.speed * math.sin(self.heading) * TICK_DT
        if abs(steer_rad) > 1e-9 and abs(self.speed) > 1e-6:
            self.yaw_rate = (self.speed / WHEELBASE) * math.tan(steer_rad)
            self.heading += self.yaw_rate * TICK_DT
        else:
            self.yaw_rate = 0.0
        self.heading = _wrap_angle(self.heading)

        # Battery: steady drain + load-dependent sag.
        self.battery_charge = max(
            6.0, self.battery_charge - BATTERY_DRAIN_PER_S * TICK_DT
        )

    def _battery_voltage(self):
        sag = BATTERY_SAG_PER_THROTTLE * abs(self.applied_throttle)
        v = self.battery_charge - sag + random.gauss(0.0, 0.01)
        return round(v, 3)

    # ---- lap detection ------------------------------------------------
    def check_lap(self, t: float):
        """Detect a completed lap: a forward crossing of start/finish (centerline
        index 0) with a full circuit driven since the previous one.

        Crossing the line is not enough on its own. A car circling on top of
        it, or reversing over it and coming back, crosses it again and again
        without going round, so progress along the centreline is accumulated
        and a lap needs most of the track's length of it.
        """
        near_i = nearest_index(self.centerline, self.x, self.y)
        n = len(self.centerline)
        step = near_i - self.prev_near_i
        if step > n / 2:
            step -= n
        elif step < -n / 2:
            step += n
        self.lap_progress += step
        crossed = (
            self.prev_near_i > n * 0.75 and near_i < n * 0.25
        )
        self.prev_near_i = near_i
        if crossed:
            started = self.lap_start_t
            full_circuit = self.lap_progress >= LAP_MIN_PROGRESS * n
            # Either way the next lap is timed from this crossing.
            self.lap_start_t = t
            self.lap_progress = near_i
            if started is not None and full_circuit:
                self.lap_number += 1
                return self.lap_number, t - started
            return None
        if self.lap_start_t is None and self.speed > 0.1:
            # Arm the timer once the car is moving for the first lap.
            self.lap_start_t = t
            self.lap_progress = 0
        return None

    # ---- telemetry ----------------------------------------------------
    def telemetry(self, t: float) -> dict:
        self.seq += 1
        heading_deg = (math.degrees(self.heading)) % 360.0
        lat, lon = local_to_gps(self.x, self.y)
        # IMU in the car's frame: x forward, y left, z up. Lateral acceleration
        # is the centripetal term v * yaw rate, so it is positive in a left turn.
        ax = self.accel_long + random.gauss(0.0, 0.05)
        ay = self.speed * self.yaw_rate + random.gauss(0.0, 0.05)
        az = 9.81 + random.gauss(0.0, 0.03)
        msg = {
            "type": "telemetry",
            "car_id": self.car_id,
            "seq": self.seq,
            "t": round(t, 3),
            "imu": {
                "ax": round(ax, 4), "ay": round(ay, 4), "az": round(az, 4),
                "gx": round(random.gauss(0.0, 0.01), 4),
                "gy": round(random.gauss(0.0, 0.01), 4),
                "gz": round(self.yaw_rate + random.gauss(0.0, 0.01), 4),
            },
            "gps": {"lat": round(lat, 7), "lon": round(lon, 7)},
            "speed_mps": round(self.speed, 3),
            "heading_deg": round(heading_deg, 2),
            "battery_v": self._battery_voltage(),
            "steering": round(self.applied_steering, 4),
            "throttle": round(self.applied_throttle, 4),
        }
        if self.sensor_fault > 0.0 and random.random() < self.sensor_fault:
            _blank_one_sensor(msg)
        return msg


def _blank_one_sensor(msg: dict) -> None:
    """Report one sensor as having no reading (null), as a dropout would."""
    sensor = random.choice(("gps", "imu", "speed", "battery"))
    if sensor == "gps":
        msg["gps"] = {"lat": None, "lon": None}
    elif sensor == "imu":
        msg["imu"] = {k: None for k in msg["imu"]}
    elif sensor == "speed":
        msg["speed_mps"] = None
    else:
        msg["battery_v"] = None


def _wrap_angle(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


async def _reader(ws, sim: CarSim):
    """Consume server->car messages: control (acknowledged), reset."""
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "control":
                sim.on_control(
                    float(msg.get("throttle", 0.0)),
                    float(msg.get("steering", 0.0)),
                )
                # Acknowledge at once so the server can time the round trip.
                if msg.get("cseq") is not None:
                    await ws.send(json.dumps({"type": "control_ack", "cseq": msg["cseq"]}))
            elif msg.get("type") == "reset":
                sim.reset()
    except Exception:
        pass


async def run(args):
    sim = CarSim(args)
    async with websockets.connect(args.server) as ws:
        # Hello handshake.
        await ws.send(json.dumps({
            "type": "hello",
            "car_id": sim.car_id,
            "fw": FIRMWARE,
            "mode": sim.mode,
        }))
        ack_raw = await ws.recv()
        try:
            ack = json.loads(ack_raw)
            session_id = ack.get("session_id")
        except (json.JSONDecodeError, ValueError):
            session_id = None
        print(f"[sim {sim.car_id}] connected mode={sim.mode} session={session_id}")

        reader_task = asyncio.create_task(_reader(ws, sim))

        start = time.monotonic()
        tick = 0
        try:
            while True:
                now_mono = time.monotonic()
                t = time.time()

                sim.step(now_mono)

                lap = sim.check_lap(t)
                if lap is not None:
                    lap_number, lap_time = lap
                    await ws.send(json.dumps({
                        "type": "lap",
                        "car_id": sim.car_id,
                        "lap_number": lap_number,
                        "lap_time_s": round(lap_time, 3),
                        "t": round(t, 3),
                    }))
                    print(f"[sim {sim.car_id}] lap {lap_number} time={lap_time:.2f}s")

                msg = sim.telemetry(t)
                # Packet loss: still advances seq so the server sees a gap.
                if sim.loss <= 0.0 or random.random() >= sim.loss:
                    await ws.send(json.dumps(msg))

                tick += 1
                if args.duration and (now_mono - start) >= args.duration:
                    break

                # Pace to 20 Hz.
                next_tick = start + tick * TICK_DT
                sleep = next_tick - time.monotonic()
                if sleep > 0:
                    await asyncio.sleep(sleep)
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        print(f"[sim {sim.car_id}] done laps={sim.lap_number} ticks={tick}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="F163 car simulator")
    p.add_argument("--server", default="ws://127.0.0.1:8000/ws/car",
                   help="WS /ws/car URL")
    p.add_argument("--car-id", dest="car_id", default="car-1")
    p.add_argument("--mode", choices=["auto", "manual"], default="auto")
    p.add_argument("--loss", type=float, default=0.0,
                   help="packet drop probability [0..1], e.g. 0.01")
    p.add_argument("--sensor-fault", dest="sensor_fault", type=float, default=0.0,
                   help="probability [0..1] that a frame carries one sensor with no "
                        "reading (null), e.g. 0.02")
    p.add_argument("--pace", type=float, default=1.0,
                   help="autopilot pace, 0.2..1.15 (1.0 = default driver); give two "
                        "simulated cars different values to get a real race")
    p.add_argument("--duration", type=float, default=0.0,
                   help="run duration in seconds (0 = run until interrupted)")
    return p


def main():
    args = build_parser().parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
