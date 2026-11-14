"""Shared in-memory state: connected cars, UI clients, broadcasting."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket


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


@dataclass
class CarConn:
    car_id: str
    session_id: int
    mode: str
    ws: WebSocket
    connected: bool = True


@dataclass
class AppState:
    cars: Dict[str, CarConn] = field(default_factory=dict)
    ui_clients: Set[WebSocket] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- car registry -------------------------------------------------
    def register_car(self, car: CarConn) -> None:
        self.cars[car.car_id] = car

    def unregister_car(self, car_id: str) -> None:
        self.cars.pop(car_id, None)

    def get_car(self, car_id: str) -> Optional[CarConn]:
        return self.cars.get(car_id)

    def car_snapshot(self) -> List[Dict[str, Any]]:
        return [
            {
                "car_id": c.car_id,
                "session_id": c.session_id,
                "mode": c.mode,
                "connected": c.connected,
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
