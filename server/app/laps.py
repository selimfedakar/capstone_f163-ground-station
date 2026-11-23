"""Server-side lap timing.

The ground station times laps itself from the positions a car reports, the way
a trackside timing loop would, instead of trusting whatever lap times the car
announces. A lap counts only when the car crosses the start/finish line going
forward having actually driven round the track since it last did.

All times here are on the car's own clock (the ``t`` of its telemetry), so a
lap time is the difference of two readings of one clock and is not affected by
network delay. The crossing instant is interpolated between the two samples
either side of the line, which matters at 20 Hz: uninterpolated, every lap
time would be a multiple of 50 ms.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from .track import Track

# A lap needs at least this fraction of the track length in forward progress.
MIN_PROGRESS_FRACTION = 0.9
# Off-track time tolerated before a lap's time is marked invalid.
OFF_TRACK_TOLERANCE_S = 0.25
# Faster than any RC car here; a bigger jump between samples is a teleport
# (a reset, or a car carried back by hand), not driving.
MAX_PLAUSIBLE_SPEED_MPS = 15.0
MIN_JUMP_M = 1.0
# The car counts as moving, and so starts its first lap, above this speed.
MOVING_SPEED_MPS = 0.1
# After a race start the cars are reset to the line; ignore that jump.
START_GRACE_S = 1.5


@dataclass
class LapEvent:
    lap_number: int
    lap_time_s: float
    #: Car-clock time of the crossing that completed the lap.
    t: float
    #: False when the car spent too long outside track limits on this lap.
    valid: bool
    off_track_s: float


class LapTracker:
    def __init__(self, track: Track):
        self.track = track
        self.lap_number = 0
        self._seg: Optional[int] = None
        self._prev_s: Optional[float] = None
        self._prev_t: Optional[float] = None
        self._lap_start_t: Optional[float] = None
        self._progress = 0.0
        self._off_s = 0.0
        self._start_pending = False
        self._hold_start = False
        self._grace_until: Optional[float] = None

    # ---- external events ----------------------------------------------
    def abandon(self) -> None:
        """Drop the lap in progress (the car was reset or moved by hand)."""
        self._lap_start_t = None
        self._progress = 0.0
        self._off_s = 0.0
        self._prev_s = None
        self._seg = None
        self._hold_start = False

    def start_at(self, t: Optional[float]) -> None:
        """Start timing lap 1 from ``t`` (a race start).

        ``t`` is the car-clock time of the green flag; ``None`` means "the
        next sample". Unlike a normal lap, this one is timed from the flag
        even if the car has to cross the line to begin it.
        """
        self.abandon()
        self._hold_start = True
        if t is None:
            self._start_pending = True
        else:
            self._lap_start_t = t
            self._grace_until = t + START_GRACE_S

    # ---- per-sample update ----------------------------------------------
    def update(
        self, x: float, y: float, t: float, speed: Optional[float]
    ) -> Tuple[Optional[LapEvent], float, bool]:
        """Feed one position sample.

        Returns ``(lap, s, off_track)``: a ``LapEvent`` if this sample
        completed a lap, the car's distance along the lap in metres, and
        whether it is outside track limits.
        """
        track = self.track
        length = track.length_m
        s, dist, self._seg = track.locate(x, y, self._seg)
        off = track.is_off_track(dist)

        if self._start_pending:
            self._start_pending = False
            self._lap_start_t = t
            self._grace_until = t + START_GRACE_S

        if self._prev_s is None or self._prev_t is None or t <= self._prev_t:
            self._prev_s, self._prev_t = s, t
            self._arm_if_moving(t, speed)
            return None, s, off

        dt = t - self._prev_t
        ds = s - self._prev_s
        if ds > length / 2:
            ds -= length
        elif ds < -length / 2:
            ds += length

        if abs(ds) > max(MIN_JUMP_M, MAX_PLAUSIBLE_SPEED_MPS * dt):
            in_grace = self._grace_until is not None and t <= self._grace_until
            if in_grace:
                self._progress = 0.0
                self._off_s = 0.0
            else:
                lap_number = self.lap_number
                self.abandon()
                self.lap_number = lap_number
                self._seg = None
            self._prev_s, self._prev_t = s, t
            return None, s, off

        event: Optional[LapEvent] = None
        crossed_forward = ds > 0 and self._prev_s + ds >= length
        self._progress += ds
        if off:
            self._off_s += dt

        if self._lap_start_t is None:
            self._arm_if_moving(t, speed)
        elif crossed_forward:
            f = (length - self._prev_s) / ds
            t_cross = self._prev_t + f * dt
            if self._progress >= MIN_PROGRESS_FRACTION * length:
                self.lap_number += 1
                event = LapEvent(
                    lap_number=self.lap_number,
                    lap_time_s=t_cross - self._lap_start_t,
                    t=t_cross,
                    valid=self._off_s <= OFF_TRACK_TOLERANCE_S,
                    off_track_s=self._off_s,
                )
                self._lap_start_t = t_cross
                self._hold_start = False
            elif not self._hold_start:
                # Crossed the line without a lap behind it: time from here.
                self._lap_start_t = t_cross
            self._hold_start = False
            self._progress = self._prev_s + ds - length
            self._off_s = dt * (1 - f) if off else 0.0

        self._prev_s, self._prev_t = s, t
        return event, s, off

    def _arm_if_moving(self, t: float, speed: Optional[float]) -> None:
        if self._lap_start_t is None and speed is not None and abs(speed) > MOVING_SPEED_MPS:
            self._lap_start_t = t
            self._progress = 0.0
            self._off_s = 0.0
