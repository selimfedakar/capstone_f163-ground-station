"""REST API (contract 4): dashboard reads, CSV export, race control."""

import csv
import io
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .race import RaceError, finish_race, start_race


class RaceStart(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    #: The race ends when the first car completes this many laps.
    laps: Optional[int] = Field(default=None, ge=1, le=500)
    #: Send every car back to the start line first.
    reset: bool = True


def _csv_chunks(header: Sequence[str], chunks: Iterable[List[Sequence[Any]]]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    yield buf.getvalue()
    for rows in chunks:
        buf.seek(0)
        buf.truncate(0)
        writer.writerows(rows)
        yield buf.getvalue()


def _csv_response(filename: str, header: Sequence[str], chunks: Iterable[List[Sequence[Any]]]) -> StreamingResponse:
    return StreamingResponse(
        _csv_chunks(header, chunks),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_RESULT_COLS = (
    "position", "car_id", "session_id", "laps", "total_time_s", "gap_laps", "gap_s",
    "best_lap_s", "avg_lap_s", "last_lap_s", "invalid_laps", "max_speed_mps",
    "avg_moving_speed_mps", "distance_m", "off_track_s", "packet_loss_pct",
    "sensor_error_pct", "latency_p95_ms",
)
_LAP_CSV_COLS = (
    "lap_number", "lap_time_s", "t", "valid", "source", "off_track_s",
    "car_time_s", "race_id", "race_lap",
)


def build_router() -> APIRouter:
    router = APIRouter()

    def _db(request: Request):
        return request.app.state.db

    def _state(request: Request):
        return request.app.state.app_state

    def _require_session(request: Request, session_id: int) -> Dict[str, Any]:
        session = _db(request).get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    @router.get("/api/health")
    async def health():
        return {"status": "ok"}

    @router.get("/api/track")
    async def track(request: Request):
        return _state(request).track.to_dict()

    # ---- sessions --------------------------------------------------------
    @router.get("/api/sessions")
    async def sessions(request: Request):
        return _db(request).list_sessions()

    @router.get("/api/sessions/{session_id}/telemetry")
    async def telemetry(
        request: Request,
        session_id: int,
        from_t: Optional[float] = Query(default=None),
        to_t: Optional[float] = Query(default=None),
        limit: int = Query(default=5000, ge=1, le=1_000_000),
    ):
        _require_session(request, session_id)
        return _db(request).get_telemetry(session_id, from_t=from_t, to_t=to_t, limit=limit)

    @router.get("/api/sessions/{session_id}/telemetry.csv")
    async def telemetry_csv(request: Request, session_id: int):
        session = _require_session(request, session_id)
        db = _db(request)
        return _csv_response(
            f"f163-session-{session_id}-{session['car_id']}-telemetry.csv",
            db.telemetry_columns,
            db.iter_telemetry(session_id),
        )

    @router.get("/api/sessions/{session_id}/laps")
    async def laps(request: Request, session_id: int):
        _require_session(request, session_id)
        return _db(request).get_laps(session_id)

    @router.get("/api/sessions/{session_id}/laps.csv")
    async def laps_csv(request: Request, session_id: int):
        session = _require_session(request, session_id)
        rows = [[lap[c] for c in _LAP_CSV_COLS] for lap in _db(request).get_laps(session_id)]
        return _csv_response(
            f"f163-session-{session_id}-{session['car_id']}-laps.csv", _LAP_CSV_COLS, [rows]
        )

    @router.get("/api/sessions/{session_id}/kpis")
    async def kpis(request: Request, session_id: int):
        result = _db(request).compute_kpis(session_id)
        if result is None:
            raise HTTPException(status_code=404, detail="session not found")
        return result

    # ---- races -----------------------------------------------------------
    @router.get("/api/races")
    async def races(request: Request):
        return _db(request).list_races()

    @router.post("/api/races", status_code=201)
    async def race_start(request: Request, body: RaceStart):
        try:
            return await start_race(
                _state(request), _db(request), name=body.name, laps_target=body.laps, reset=body.reset
            )
        except RaceError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.get("/api/races/{race_id}")
    async def race(request: Request, race_id: int):
        result = _db(request).race_results(race_id)
        if result is None:
            raise HTTPException(status_code=404, detail="race not found")
        return result

    @router.post("/api/races/{race_id}/finish")
    async def race_finish(request: Request, race_id: int):
        state = _state(request)
        if state.race is None or state.race["id"] != race_id:
            raise HTTPException(status_code=409, detail="that race is not running")
        return await finish_race(state, _db(request))

    @router.get("/api/races/{race_id}/results.csv")
    async def race_csv(request: Request, race_id: int):
        result = _db(request).race_results(race_id)
        if result is None:
            raise HTTPException(status_code=404, detail="race not found")
        rows = [[r.get(c) for c in _RESULT_COLS] for r in result["results"]]
        return _csv_response(f"f163-race-{race_id}-results.csv", _RESULT_COLS, [rows])

    return router
