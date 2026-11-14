"""SQLite storage layer for the F163 ground station.

The storage layer is deliberately isolated (contract 7) so it can be swapped
later. A single background writer task owns the write connection and flushes
telemetry inserts in batches (every 50 rows or 1 s, whichever comes first,
per contract 5). Reads use short-lived connections.
"""

import asyncio
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL
);
CREATE TABLE IF NOT EXISTS telemetry (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t REAL NOT NULL,
  ax REAL, ay REAL, az REAL, gx REAL, gy REAL, gz REAL,
  lat REAL, lon REAL,
  speed_mps REAL, heading_deg REAL, battery_v REAL,
  steering REAL, throttle REAL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_session_t ON telemetry(session_id, t);
CREATE TABLE IF NOT EXISTS laps (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  lap_number INTEGER NOT NULL,
  lap_time_s REAL NOT NULL,
  t REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS control_log (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  ts REAL NOT NULL,
  throttle REAL NOT NULL,
  steering REAL NOT NULL
);
"""

DEFAULT_DB_PATH = os.path.join("data", "f163.db")

BATCH_SIZE = 50
BATCH_INTERVAL_S = 1.0

_TELEMETRY_COLS = (
    "session_id", "seq", "t",
    "ax", "ay", "az", "gx", "gy", "gz",
    "lat", "lon",
    "speed_mps", "heading_deg", "battery_v",
    "steering", "throttle",
)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: str) -> None:
    """Create the schema if it does not already exist."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


class Database:
    """Async-facing SQLite wrapper with a single batched writer task.

    Synchronous helpers (used in tests and by read endpoints) operate on their
    own connections. The writer coroutine owns the only long-lived write
    connection to keep SQLite single-writer semantics clean.
    """

    def __init__(self, path: str = DEFAULT_DB_PATH):
        self.path = path
        init_db(path)
        self._queue: "asyncio.Queue[tuple]" = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        self._running = False

    # ---- lifecycle ----------------------------------------------------
    async def start(self) -> None:
        if self._writer_task is None:
            self._running = True
            self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        self._running = False
        if self._writer_task is not None:
            await self._queue.put(("__stop__", None))
            await self._writer_task
            self._writer_task = None

    # ---- session helpers (synchronous, short-lived connection) --------
    def create_session(self, car_id: str, mode: str, started_at: Optional[float] = None) -> int:
        if started_at is None:
            started_at = time.time()
        conn = _connect(self.path)
        try:
            cur = conn.execute(
                "INSERT INTO sessions (car_id, mode, started_at, ended_at) VALUES (?, ?, ?, NULL)",
                (car_id, mode, started_at),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def end_session(self, session_id: int, ended_at: Optional[float] = None) -> None:
        if ended_at is None:
            ended_at = time.time()
        conn = _connect(self.path)
        try:
            conn.execute(
                "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (ended_at, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_lap(self, session_id: int, lap_number: int, lap_time_s: float, t: float) -> None:
        conn = _connect(self.path)
        try:
            conn.execute(
                "INSERT INTO laps (session_id, lap_number, lap_time_s, t) VALUES (?, ?, ?, ?)",
                (session_id, lap_number, lap_time_s, t),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_control(self, session_id: int, ts: float, throttle: float, steering: float) -> None:
        conn = _connect(self.path)
        try:
            conn.execute(
                "INSERT INTO control_log (session_id, ts, throttle, steering) VALUES (?, ?, ?, ?)",
                (session_id, ts, throttle, steering),
            )
            conn.commit()
        finally:
            conn.close()

    def insert_telemetry_row(self, row: Dict[str, Any]) -> None:
        """Synchronous single-row telemetry insert (used by tests)."""
        conn = _connect(self.path)
        try:
            self._insert_telemetry_many(conn, [row])
            conn.commit()
        finally:
            conn.close()

    # ---- telemetry writer ---------------------------------------------
    async def queue_telemetry(self, row: Dict[str, Any]) -> None:
        await self._queue.put(("telemetry", row))

    def _insert_telemetry_many(self, conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
        values = [tuple(r.get(col) for col in _TELEMETRY_COLS) for r in rows]
        placeholders = ", ".join(["?"] * len(_TELEMETRY_COLS))
        cols = ", ".join(_TELEMETRY_COLS)
        conn.executemany(
            f"INSERT INTO telemetry ({cols}) VALUES ({placeholders})",
            values,
        )

    async def _writer_loop(self) -> None:
        conn = _connect(self.path)
        buffer: List[Dict[str, Any]] = []
        last_flush = time.monotonic()

        def flush():
            nonlocal buffer, last_flush
            if buffer:
                self._insert_telemetry_many(conn, buffer)
                conn.commit()
                buffer = []
            last_flush = time.monotonic()

        try:
            while True:
                timeout = BATCH_INTERVAL_S
                try:
                    kind, payload = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    flush()
                    continue

                if kind == "__stop__":
                    flush()
                    break
                if kind == "telemetry":
                    buffer.append(payload)
                    if len(buffer) >= BATCH_SIZE:
                        flush()
                    elif time.monotonic() - last_flush >= BATCH_INTERVAL_S:
                        flush()
        finally:
            flush()
            conn.close()

    # ---- read helpers --------------------------------------------------
    def list_sessions(self) -> List[Dict[str, Any]]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT id, car_id, started_at, ended_at, mode FROM sessions ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT id, car_id, started_at, ended_at, mode FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_telemetry(
        self,
        session_id: int,
        from_t: Optional[float] = None,
        to_t: Optional[float] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        conn = _connect(self.path)
        try:
            query = f"SELECT {', '.join(_TELEMETRY_COLS)} FROM telemetry WHERE session_id = ?"
            params: List[Any] = [session_id]
            if from_t is not None:
                query += " AND t >= ?"
                params.append(from_t)
            if to_t is not None:
                query += " AND t <= ?"
                params.append(to_t)
            query += " ORDER BY t LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_laps(self, session_id: int) -> List[Dict[str, Any]]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT lap_number, lap_time_s, t FROM laps WHERE session_id = ? ORDER BY lap_number",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def compute_kpis(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Compute all KPIs from contract 4 purely in SQL.

        seq_gaps = sum over telemetry (ordered by seq) of max(0, delta - 1),
        i.e. the total number of missing sequence numbers within the session.
        packet_loss_pct = seq_gaps / expected * 100, where expected is the span
        of sequence numbers (max - min + 1).
        """
        conn = _connect(self.path)
        try:
            session = conn.execute(
                "SELECT id, started_at, ended_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session is None:
                return None

            lap_stats = conn.execute(
                """
                SELECT COUNT(*) AS lap_count,
                       MIN(lap_time_s) AS best_lap_s,
                       AVG(lap_time_s) AS avg_lap_s
                FROM laps WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            tel_stats = conn.execute(
                """
                SELECT COUNT(*) AS telemetry_rows,
                       MAX(speed_mps) AS max_speed_mps,
                       AVG(speed_mps) AS avg_speed_mps,
                       MIN(battery_v) AS min_battery_v,
                       MIN(seq) AS min_seq,
                       MAX(seq) AS max_seq,
                       MIN(t) AS min_t,
                       MAX(t) AS max_t
                FROM telemetry WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            # seq_gaps via window: sum of (seq - prev_seq - 1) over positive gaps.
            gaps_row = conn.execute(
                """
                SELECT COALESCE(SUM(gap), 0) AS seq_gaps FROM (
                    SELECT seq - LAG(seq) OVER (ORDER BY seq) - 1 AS gap
                    FROM telemetry WHERE session_id = ?
                ) WHERE gap > 0
                """,
                (session_id,),
            ).fetchone()
            seq_gaps = int(gaps_row["seq_gaps"] or 0)

            telemetry_rows = int(tel_stats["telemetry_rows"] or 0)

            # Expected count spans the observed sequence range.
            if tel_stats["min_seq"] is not None and tel_stats["max_seq"] is not None:
                expected = int(tel_stats["max_seq"]) - int(tel_stats["min_seq"]) + 1
            else:
                expected = 0
            packet_loss_pct = round(100.0 * seq_gaps / expected, 4) if expected > 0 else 0.0

            # duration: prefer session span, fall back to telemetry span.
            started_at = session["started_at"]
            ended_at = session["ended_at"]
            if ended_at is not None:
                duration_s = ended_at - started_at
            elif tel_stats["min_t"] is not None and tel_stats["max_t"] is not None:
                duration_s = tel_stats["max_t"] - tel_stats["min_t"]
            else:
                duration_s = 0.0

            def _round(v, nd=2):
                return round(v, nd) if v is not None else None

            return {
                "session_id": session_id,
                "lap_count": int(lap_stats["lap_count"] or 0),
                "best_lap_s": _round(lap_stats["best_lap_s"]),
                "avg_lap_s": _round(lap_stats["avg_lap_s"]),
                "max_speed_mps": _round(tel_stats["max_speed_mps"]),
                "avg_speed_mps": _round(tel_stats["avg_speed_mps"]),
                "min_battery_v": _round(tel_stats["min_battery_v"]),
                "telemetry_rows": telemetry_rows,
                "seq_gaps": seq_gaps,
                "packet_loss_pct": packet_loss_pct,
                "duration_s": _round(duration_s),
            }
        finally:
            conn.close()
