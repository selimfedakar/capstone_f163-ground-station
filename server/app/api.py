"""REST API (contract 4): dashboard reads."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request


def build_router() -> APIRouter:
    router = APIRouter()

    def _db(request: Request):
        return request.app.state.db

    @router.get("/api/health")
    async def health():
        return {"status": "ok"}

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
        db = _db(request)
        if db.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        return db.get_telemetry(session_id, from_t=from_t, to_t=to_t, limit=limit)

    @router.get("/api/sessions/{session_id}/laps")
    async def laps(request: Request, session_id: int):
        db = _db(request)
        if db.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        return db.get_laps(session_id)

    @router.get("/api/sessions/{session_id}/kpis")
    async def kpis(request: Request, session_id: int):
        db = _db(request)
        result = db.compute_kpis(session_id)
        if result is None:
            raise HTTPException(status_code=404, detail="session not found")
        return result

    return router
