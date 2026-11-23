"""Shared in-memory state: connected cars, UI clients, the track, the race."""

import asyncio
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from .laps import LapTracker
from .track import Track, default_track


def clamp_unit(value: Any, default: float = 0.0) -> float:
    """Clamp a control value into [-1.0, 1.0] (contract 3)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    if v > 1.0:
        return 1.0
    if v < -1.0:
        return -1.0
    return v


def as_number(value: Any) -> Optional[float]:
    """A finite float, or None for anything that is not a usable reading."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


@dataclass
class PendingControl:
    """A command forwarded to a car and not yet acknowledged."""
    ts: float
    throttle: float
    steering: float
    recv_t: float
    sent_mono: float
    ui_rtt_ms: Optional[float]
    origin: Optional[WebSocket]


@dataclass
class ServerLap:
    lap_number: int
    t: float
    has_car_time: bool


@dataclass
class CarConn:
    car_id: str
    session_id: int
    mode: str
    ws: WebSocket
    tracker: LapTracker
    fw: Optional[str] = None
    connected: bool = True
    #: Car-clock time of its latest telemetry frame.
    last_t: Optional[float] = None
    # Command acknowledgement bookkeeping (contract 2, control_ack).
    cseq: int = 0
    pending: Dict[int, PendingControl] = field(default_factory=dict)
    # Cross-check between the car's own lap reports and the server's timing.
    pending_car_lap: Optional[Dict[str, Any]] = None
    last_server_lap: Optional[ServerLap] = None
    # Race membership.
    in_race: bool = False
    race_lap: int = 0
    race_start_t: Optional[float] = None


@dataclass
class AppState:
    cars: Dict[str, CarConn] = field(default_factory=dict)
    ui_clients: Set[WebSocket] = field(default_factory=set)
    track: Track = field(default_factory=default_track)
    #: The race in progress, as broadcast to UIs, or None.
    race: Optional[Dict[str, Any]] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- car registry -------------------------------------------------
    def register_car(self, car: CarConn) -> None:
        self.cars[car.car_id] = car

    def unregister_car(self, car: CarConn) -> None:
        # Only drop the entry if it is still this connection: a car that
        # reconnects under the same id must not be removed by the old socket.
        if self.cars.get(car.car_id) is car:
            self.cars.pop(car.car_id, None)

    def get_car(self, car_id: str) -> Optional[CarConn]:
        return self.cars.get(car_id)

    def car_snapshot(self) -> List[Dict[str, Any]]:
        return [
            {
                "car_id": c.car_id,
                "session_id": c.session_id,
                "mode": c.mode,
                "connected": c.connected,
                "fw": c.fw,
            }
            for c in self.cars.values()
        ]

    # ---- ui registry --------------------------------------------------
    def add_ui(self, ws: WebSocket) -> None:
        self.ui_clients.add(ws)

    def remove_ui(self, ws: WebSocket) -> None:
        self.ui_clients.discard(ws)

    # ---- broadcasting -------------------------------------------------
    async def broadcast_ui(self, message: Dict[str, Any]) -> None:
        """Send a JSON message to every connected UI client.

        Dead sockets are pruned. Broadcasts are serialized once.
        """
        if not self.ui_clients:
            return
        text = json.dumps(message)
        dead: List[WebSocket] = []
        for ws in list(self.ui_clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.ui_clients.discard(ws)
