"""Race control: start a race for the connected cars, finish it, classify it.

A race groups cars so they can be compared. Starting one puts every connected
car back on the start line (the simulator obeys ``reset``; real cars are
gridded by hand) and times each car's laps from the same instant. It ends when
the operator finishes it, or when the first car completes the lap target.
"""

import json
import logging
import time
from typing import Any, Dict, Optional

from .db import Database
from .state import AppState, CarConn

log = logging.getLogger("f163.race")


class RaceError(Exception):
    """A race request that cannot be carried out in the current state."""


def _public(race: Dict[str, Any], state: AppState) -> Dict[str, Any]:
    return {
        "id": race["id"],
        "name": race["name"],
        "laps_target": race["laps_target"],
        "started_at": race["started_at"],
        "ended_at": race.get("ended_at"),
        "cars": sorted(c.car_id for c in state.cars.values() if c.in_race),
    }


def enter_car(state: AppState, db: Database, car: CarConn, now: float) -> None:
    """Put a car into the running race, timing its first lap from now."""
    race = state.race
    if race is None:
        return
    car.in_race = True
    car.race_lap = 0
    car.race_start_t = car.last_t
    car.tracker.start_at(car.last_t)
    db.add_race_entry(race["id"], car.session_id, car.car_id, car.last_t, now)


async def start_race(
    state: AppState,
    db: Database,
    name: Optional[str] = None,
    laps_target: Optional[int] = None,
    reset: bool = True,
) -> Dict[str, Any]:
    if state.race is not None:
        raise RaceError("a race is already running; finish it first")
    cars = [c for c in state.cars.values() if c.connected]
    if not cars:
        raise RaceError("no car is connected")

    now = time.time()
    race_id = db.create_race(name or f"Race at {time.strftime('%H:%M', time.localtime(now))}", laps_target, now)
    race = db.get_race(race_id)
    assert race is not None
    state.race = race

    for car in cars:
        if reset:
            try:
                await car.ws.send_text(json.dumps({"type": "reset"}))
            except Exception as exc:
                log.warning("race: could not reset %s: %s", car.car_id, exc)
        enter_car(state, db, car, now)

    public = _public(race, state)
    state.race = {**race, "cars": public["cars"]}
    await state.broadcast_ui({"type": "race", "race": public})
    log.info("race %s started with %d car(s)", race_id, len(cars))
    return public


async def finish_race(state: AppState, db: Database, reason: str = "operator") -> Dict[str, Any]:
    race = state.race
    if race is None:
        raise RaceError("no race is running")
    now = time.time()
    for car in state.cars.values():
        if car.in_race:
            db.set_race_entry_end(race["id"], car.session_id, car.last_t)
            car.in_race = False
    db.finish_race(race["id"], now)
    state.race = None
    finished = {**race, "ended_at": now, "cars": race.get("cars", []), "reason": reason}
    await state.broadcast_ui({"type": "race", "race": None, "finished": finished})
    log.info("race %s finished (%s)", race["id"], reason)
    return finished


def leave_race(state: AppState, db: Database, car: CarConn) -> None:
    """Close a car's race entry when it disconnects mid-race."""
    race = state.race
    if race is None or not car.in_race:
        return
    db.set_race_entry_end(race["id"], car.session_id, car.last_t)
    car.in_race = False
