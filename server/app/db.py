"""SQLite storage layer for the F163 ground station.

The storage layer is deliberately isolated (contract 7) so it can be swapped
later. A single background writer task owns the write connection and flushes
inserts in batches (every 50 statements or 1 s, whichever comes first, per
contract 5); laps and race changes flush at once so reads see them promptly.
Reads use short-lived connections.

Databases created by an earlier version are upgraded in place on start-up
(see ``_ADDED_COLUMNS``); no data is rewritten.
"""

import asyncio
import math
import os
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  fw TEXT
);
CREATE TABLE IF NOT EXISTS telemetry (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t REAL NOT NULL,
  ax REAL, ay REAL, az REAL, gx REAL, gy REAL, gz REAL,
  lat REAL, lon REAL,
  speed_mps REAL, heading_deg REAL, battery_v REAL,
  steering REAL, throttle REAL,
  recv_t REAL,
  off_track INTEGER,
  track_s REAL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_session_t ON telemetry(session_id, t);
CREATE TABLE IF NOT EXISTS laps (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  lap_number INTEGER NOT NULL,
  lap_time_s REAL NOT NULL,
  t REAL NOT NULL,
  recv_t REAL,
  valid INTEGER,
  source TEXT,
  off_track_s REAL,
  car_time_s REAL,
  race_id INTEGER,
  race_lap INTEGER
);
CREATE TABLE IF NOT EXISTS control_log (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  ts REAL NOT NULL,
  throttle REAL NOT NULL,
  steering REAL NOT NULL,
  recv_t REAL,
  forwarded INTEGER,
  ack_rtt_ms REAL,
  ui_rtt_ms REAL
);
CREATE TABLE IF NOT EXISTS races (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  laps_target INTEGER,
  started_at REAL NOT NULL,
  ended_at REAL
);
CREATE TABLE IF NOT EXISTS race_entries (
  race_id INTEGER NOT NULL REFERENCES races(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  car_id TEXT NOT NULL,
  start_t REAL,
  end_t REAL,
  joined_at REAL NOT NULL,
  PRIMARY KEY (race_id, session_id)
);
"""

# Columns added after contract v1. A v1 database gets them via ALTER TABLE;
# their rows keep NULL there, which every query below treats as "unknown".
_ADDED_COLUMNS: Sequence[Tuple[str, str, str]] = (
    ("sessions", "fw", "TEXT"),
    ("telemetry", "recv_t", "REAL"),
    ("telemetry", "off_track", "INTEGER"),
    ("telemetry", "track_s", "REAL"),
    ("laps", "recv_t", "REAL"),
    ("laps", "valid", "INTEGER"),
    ("laps", "source", "TEXT"),
    ("laps", "off_track_s", "REAL"),
    ("laps", "car_time_s", "REAL"),
    ("laps", "race_id", "INTEGER"),
    ("laps", "race_lap", "INTEGER"),
    ("control_log", "recv_t", "REAL"),
    ("control_log", "forwarded", "INTEGER"),
    ("control_log", "ack_rtt_ms", "REAL"),
    ("control_log", "ui_rtt_ms", "REAL"),
)

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_laps_session ON laps(session_id);
CREATE INDEX IF NOT EXISTS idx_laps_race ON laps(race_id);
CREATE INDEX IF NOT EXISTS idx_control_session ON control_log(session_id);
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
    "recv_t", "off_track", "track_s",
)
_TELEMETRY_INSERT = (
    f"INSERT INTO telemetry ({', '.join(_TELEMETRY_COLS)}) "
    f"VALUES ({', '.join(['?'] * len(_TELEMETRY_COLS))})"
)

_LAP_COLS = (
    "lap_number", "lap_time_s", "t", "valid", "source", "off_track_s",
    "car_time_s", "race_id", "race_lap",
)
_LAP_INSERT = (
    "INSERT INTO laps (session_id, lap_number, lap_time_s, t, recv_t, valid, source, "
    "off_track_s, car_time_s, race_id, race_lap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_CONTROL_INSERT = (
    "INSERT INTO control_log (session_id, ts, throttle, steering, recv_t, forwarded, "
    "ack_rtt_ms, ui_rtt_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)

# ---- what counts as a bad sensor reading (contract 4) -------------------
# A reading is an error when it is missing or physically implausible.
MAX_PLAUSIBLE_ACCEL = 160.0   # m/s^2, about 16 g: beyond a hobby IMU's range
MAX_PLAUSIBLE_SPEED = 50.0    # m/s
MAX_PLAUSIBLE_BATTERY = 30.0  # volts
# Samples further apart than this are a dropout, not something to integrate over.
MAX_INTEGRATION_DT = 1.0
MOVING_SPEED_MPS = 0.1

_ERR_GPS = "(lat IS NULL OR lon IS NULL OR ABS(lat) > 90 OR ABS(lon) > 180)"
_ERR_IMU = (
    "(ax IS NULL OR ay IS NULL OR az IS NULL OR gx IS NULL OR gy IS NULL OR gz IS NULL"
    f" OR ABS(ax) > {MAX_PLAUSIBLE_ACCEL} OR ABS(ay) > {MAX_PLAUSIBLE_ACCEL}"
    f" OR ABS(az) > {MAX_PLAUSIBLE_ACCEL})"
)
_ERR_SPEED = f"(speed_mps IS NULL OR ABS(speed_mps) > {MAX_PLAUSIBLE_SPEED})"
_ERR_HEADING = "(heading_deg IS NULL OR heading_deg < 0 OR heading_deg > 360)"
_ERR_BATTERY = f"(battery_v IS NULL OR battery_v <= 0 OR battery_v > {MAX_PLAUSIBLE_BATTERY})"
_ERR_ANY = f"({_ERR_GPS} OR {_ERR_IMU} OR {_ERR_SPEED} OR {_ERR_HEADING} OR {_ERR_BATTERY})"

# Laps that count: timed by the server, or written before the server timed
# laps at all (source NULL). A car's own unconfirmed report never counts.
_COUNTED_LAP = "(source = 'server' OR source IS NULL)"
_VALID_LAP = "(valid IS NULL OR valid = 1)"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: str) -> None:
    """Create the schema if needed and upgrade an older database in place."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        for table, column, decl in _ADDED_COLUMNS:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.executescript(_INDEXES)
        conn.commit()
    finally:
        conn.close()


def percentile(sorted_values: Sequence[float], p: float) -> Optional[float]:
    """Nearest-rank percentile of an ascending list; None if it is empty."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _round(v: Optional[float], nd: int = 2) -> Optional[float]:
    return round(v, nd) if v is not None else None


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
            await self._queue.put(("__stop__", None, None, True))
            await self._writer_task
            self._writer_task = None

    def close_orphans(self) -> None:
        """End sessions and races left open by a server that stopped abruptly.

        Call once at start-up, before any car connects: nothing can still be
        running then, so anything without an end time is stale.
        """
        conn = _connect(self.path)
        try:
            conn.execute(
                """
                UPDATE sessions SET ended_at = COALESCE(
                    (SELECT MAX(COALESCE(recv_t, t)) FROM telemetry
                      WHERE telemetry.session_id = sessions.id),
                    started_at)
                WHERE ended_at IS NULL
                """
            )
            conn.execute(
                """
                UPDATE races SET ended_at = COALESCE(
                    (SELECT MAX(s.ended_at) FROM race_entries e
                       JOIN sessions s ON s.id = e.session_id
                      WHERE e.race_id = races.id),
                    started_at)
                WHERE ended_at IS NULL
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ---- synchronous writes (short-lived connection) --------------------
    def _execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        conn = _connect(self.path)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return int(cur.lastrowid or 0)
        finally:
            conn.close()

    def create_session(
        self,
        car_id: str,
        mode: str,
        started_at: Optional[float] = None,
        fw: Optional[str] = None,
    ) -> int:
        if started_at is None:
            started_at = time.time()
        return self._execute(
            "INSERT INTO sessions (car_id, mode, started_at, ended_at, fw) VALUES (?, ?, ?, NULL, ?)",
            (car_id, mode, started_at, fw),
        )

    def end_session(self, session_id: int, ended_at: Optional[float] = None) -> None:
        if ended_at is None:
            ended_at = time.time()
        self._execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (ended_at, session_id),
        )

    @staticmethod
    def _lap_params(
        session_id: int,
        lap_number: int,
        lap_time_s: float,
        t: float,
        recv_t: Optional[float] = None,
        valid: Optional[bool] = True,
        source: str = "server",
        off_track_s: Optional[float] = None,
        car_time_s: Optional[float] = None,
        race_id: Optional[int] = None,
        race_lap: Optional[int] = None,
    ) -> tuple:
        return (
            session_id, lap_number, lap_time_s, t, recv_t,
            None if valid is None else int(valid), source,
            off_track_s, car_time_s, race_id, race_lap,
        )

    def insert_lap(self, session_id: int, lap_number: int, lap_time_s: float, t: float, **extra) -> None:
        self._execute(_LAP_INSERT, self._lap_params(session_id, lap_number, lap_time_s, t, **extra))

    @staticmethod
    def _control_params(
        session_id: int,
        ts: float,
        throttle: float,
        steering: float,
        recv_t: Optional[float] = None,
        forwarded: Optional[bool] = None,
        ack_rtt_ms: Optional[float] = None,
        ui_rtt_ms: Optional[float] = None,
    ) -> tuple:
        return (
            session_id, ts, throttle, steering, recv_t,
            None if forwarded is None else int(forwarded), ack_rtt_ms, ui_rtt_ms,
        )

    def insert_control(self, session_id: int, ts: float, throttle: float, steering: float, **extra) -> None:
        self._execute(_CONTROL_INSERT, self._control_params(session_id, ts, throttle, steering, **extra))

    def insert_telemetry_row(self, row: Dict[str, Any]) -> None:
        """Synchronous single-row telemetry insert (used by tests)."""
        self._execute(_TELEMETRY_INSERT, tuple(row.get(col) for col in _TELEMETRY_COLS))

    # ---- queued writes (the hot path) -----------------------------------
    async def _enqueue(self, sql: str, params: Sequence[Any], urgent: bool = False) -> None:
        await self._queue.put(("sql", sql, tuple(params), urgent))

    async def queue_telemetry(self, row: Dict[str, Any]) -> None:
        await self._enqueue(_TELEMETRY_INSERT, tuple(row.get(col) for col in _TELEMETRY_COLS))

    async def queue_lap(self, session_id: int, lap_number: int, lap_time_s: float, t: float, **extra) -> None:
        await self._enqueue(
            _LAP_INSERT, self._lap_params(session_id, lap_number, lap_time_s, t, **extra), urgent=True
        )

    async def queue_lap_car_time(self, session_id: int, lap_number: int, car_time_s: float) -> None:
        await self._enqueue(
            "UPDATE laps SET car_time_s = ? WHERE session_id = ? AND lap_number = ? AND source = 'server'",
            (car_time_s, session_id, lap_number),
            urgent=True,
        )

    async def queue_control(self, session_id: int, ts: float, throttle: float, steering: float, **extra) -> None:
        await self._enqueue(
            _CONTROL_INSERT, self._control_params(session_id, ts, throttle, steering, **extra)
        )

    async def flush(self) -> None:
        """Ask the writer to commit whatever it is holding, now."""
        await self._queue.put(("flush", None, None, True))

    async def _writer_loop(self) -> None:
        conn = _connect(self.path)
        buffer: List[Tuple[str, tuple]] = []
        last_flush = time.monotonic()

        def flush():
            nonlocal buffer, last_flush
            if buffer:
                for sql, params in buffer:
                    conn.execute(sql, params)
                conn.commit()
                buffer = []
            last_flush = time.monotonic()

        try:
            while True:
                try:
                    kind, sql, params, urgent = await asyncio.wait_for(
                        self._queue.get(), timeout=BATCH_INTERVAL_S
                    )
                except asyncio.TimeoutError:
                    flush()
                    continue

                if kind == "__stop__":
                    flush()
                    break
                if kind == "sql":
                    buffer.append((sql, params))
                if (
                    urgent
                    or len(buffer) >= BATCH_SIZE
                    or time.monotonic() - last_flush >= BATCH_INTERVAL_S
                ):
                    flush()
        finally:
            flush()
            conn.close()

    # ---- read helpers --------------------------------------------------
    def _all(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        conn = _connect(self.path)
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def list_sessions(self) -> List[Dict[str, Any]]:
        return self._all(
            "SELECT id, car_id, started_at, ended_at, mode, fw FROM sessions ORDER BY id DESC"
        )

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        rows = self._all(
            "SELECT id, car_id, started_at, ended_at, mode, fw FROM sessions WHERE id = ?",
            (session_id,),
        )
        return rows[0] if rows else None

    def get_telemetry(
        self,
        session_id: int,
        from_t: Optional[float] = None,
        to_t: Optional[float] = None,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
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
        return self._all(query, params)

    def iter_telemetry(self, session_id: int, chunk: int = 2000) -> Iterator[List[tuple]]:
        """Yield every telemetry row of a session in order, a chunk at a time."""
        conn = _connect(self.path)
        try:
            cur = conn.execute(
                f"SELECT {', '.join(_TELEMETRY_COLS)} FROM telemetry WHERE session_id = ? ORDER BY seq",
                (session_id,),
            )
            while True:
                rows = cur.fetchmany(chunk)
                if not rows:
                    break
                yield [tuple(r) for r in rows]
        finally:
            conn.close()

    telemetry_columns = _TELEMETRY_COLS

    def get_laps(self, session_id: int) -> List[Dict[str, Any]]:
        """Every lap row of a session: server-timed laps and unconfirmed car reports."""
        rows = self._all(
            f"SELECT {', '.join(_LAP_COLS)} FROM laps WHERE session_id = ? ORDER BY t, lap_number",
            (session_id,),
        )
        for r in rows:
            r["valid"] = None if r["valid"] is None else bool(r["valid"])
        return rows

    # ---- KPIs ------------------------------------------------------------
    def compute_kpis(
        self,
        session_id: int,
        t_from: Optional[float] = None,
        t_to: Optional[float] = None,
        race_id: Optional[int] = None,
        recv_from: Optional[float] = None,
        recv_to: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compute the KPIs of contract 4 for a session, or for part of one.

        ``t_from``/``t_to`` bound telemetry and laps on the car's clock;
        ``recv_from``/``recv_to`` bound the command log on the server's clock;
        ``race_id`` restricts laps to one race. All are optional.
        """
        conn = _connect(self.path)
        try:
            session = conn.execute(
                "SELECT id, started_at, ended_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None

            where = "session_id = ?"
            params: List[Any] = [session_id]
            if t_from is not None:
                where += " AND t >= ?"
                params.append(t_from)
            if t_to is not None:
                where += " AND t <= ?"
                params.append(t_to)

            # ---- laps ----
            lap_where = f"{where} AND {_COUNTED_LAP}"
            lap_params = list(params)
            if race_id is not None:
                lap_where += " AND race_id = ?"
                lap_params.append(race_id)
            laps = conn.execute(
                f"""
                SELECT COUNT(*) AS lap_count,
                       COALESCE(SUM(CASE WHEN valid = 0 THEN 1 ELSE 0 END), 0) AS invalid_laps,
                       MIN(CASE WHEN {_VALID_LAP} THEN lap_time_s END) AS best_lap_s,
                       AVG(CASE WHEN {_VALID_LAP} THEN lap_time_s END) AS avg_lap_s
                FROM laps WHERE {lap_where}
                """,
                lap_params,
            ).fetchone()
            unconfirmed = conn.execute(
                f"SELECT COUNT(*) AS n FROM laps WHERE {where} AND source = 'car'", params
            ).fetchone()["n"]

            # ---- telemetry aggregates ----
            tel = conn.execute(
                f"""
                SELECT COUNT(*) AS telemetry_rows,
                       MAX(CASE WHEN NOT {_ERR_SPEED} THEN speed_mps END) AS max_speed_mps,
                       AVG(CASE WHEN NOT {_ERR_SPEED} THEN speed_mps END) AS avg_speed_mps,
                       MIN(CASE WHEN NOT {_ERR_BATTERY} THEN battery_v END) AS min_battery_v,
                       MIN(seq) AS min_seq, MAX(seq) AS max_seq,
                       MIN(t) AS min_t, MAX(t) AS max_t,
                       MIN(recv_t) AS min_recv, MAX(recv_t) AS max_recv,
                       COUNT(recv_t) AS recv_rows,
                       MAX(CASE WHEN ABS(ax) <= {MAX_PLAUSIBLE_ACCEL} THEN ax END) AS max_ax,
                       MIN(CASE WHEN ABS(ax) <= {MAX_PLAUSIBLE_ACCEL} THEN ax END) AS min_ax,
                       MAX(CASE WHEN ABS(ay) <= {MAX_PLAUSIBLE_ACCEL} THEN ABS(ay) END) AS max_ay,
                       COALESCE(SUM({_ERR_GPS}), 0) AS err_gps,
                       COALESCE(SUM({_ERR_IMU}), 0) AS err_imu,
                       COALESCE(SUM({_ERR_SPEED}), 0) AS err_speed,
                       COALESCE(SUM({_ERR_HEADING}), 0) AS err_heading,
                       COALESCE(SUM({_ERR_BATTERY}), 0) AS err_battery,
                       COALESCE(SUM({_ERR_ANY}), 0) AS err_any
                FROM telemetry WHERE {where}
                """,
                params,
            ).fetchone()

            # ---- quantities that depend on the previous sample ----
            ok_dt = f"dt > 0 AND dt <= {MAX_INTEGRATION_DT}"
            # Off-track time is time spent *driving* outside the limits: a car
            # parked beside the track is not gaining anything, and would
            # otherwise swamp the figure.
            moving = f"sp_ok AND ABS(sp) > {MOVING_SPEED_MPS}"
            seqd = conn.execute(
                f"""
                SELECT COALESCE(SUM(CASE WHEN gap > 0 THEN gap END), 0) AS seq_gaps,
                       COALESCE(SUM(CASE WHEN {ok_dt} AND sp_ok THEN ABS(sp) * dt END), 0) AS distance_m,
                       COALESCE(SUM(CASE WHEN {ok_dt} AND sp_ok AND ABS(sp) > {MOVING_SPEED_MPS}
                                         THEN dt END), 0) AS moving_s,
                       SUM(CASE WHEN {ok_dt} AND off_track = 1 AND {moving} THEN dt END)
                           AS off_track_s,
                       COALESCE(SUM(CASE WHEN {ok_dt} AND off_track IS NOT NULL THEN dt END), 0)
                           AS located_s,
                       COALESCE(SUM(CASE WHEN {ok_dt} AND off_track IS NOT NULL AND {moving}
                                         THEN dt END), 0) AS located_moving_s,
                       MAX(rdt) AS max_gap_s
                FROM (
                    SELECT speed_mps AS sp,
                           (speed_mps IS NOT NULL AND ABS(speed_mps) <= {MAX_PLAUSIBLE_SPEED}) AS sp_ok,
                           off_track,
                           t - LAG(t) OVER (ORDER BY seq) AS dt,
                           seq - LAG(seq) OVER (ORDER BY seq) - 1 AS gap,
                           recv_t - LAG(recv_t) OVER (ORDER BY seq) AS rdt
                    FROM telemetry WHERE {where}
                )
                """,
                params,
            ).fetchone()

            rows = int(tel["telemetry_rows"] or 0)
            seq_gaps = int(seqd["seq_gaps"] or 0)
            if tel["min_seq"] is not None:
                expected = int(tel["max_seq"]) - int(tel["min_seq"]) + 1
            else:
                expected = 0
            packet_loss_pct = round(100.0 * seq_gaps / expected, 4) if expected > 0 else 0.0

            # duration: the window if one was given, else the session span,
            # falling back to the telemetry span while the session is open.
            if t_from is not None and t_to is not None:
                duration_s = t_to - t_from
            elif t_from is None and t_to is None and session["ended_at"] is not None:
                duration_s = session["ended_at"] - session["started_at"]
            elif tel["min_t"] is not None:
                duration_s = tel["max_t"] - tel["min_t"]
            else:
                duration_s = 0.0

            distance_m = float(seqd["distance_m"] or 0.0)
            moving_s = float(seqd["moving_s"] or 0.0)
            located_s = float(seqd["located_s"] or 0.0)
            off_track_s = seqd["off_track_s"]
            if located_s <= 0:
                off_track_s = off_track_pct = None  # position never checked against a track
            else:
                off_track_s = float(off_track_s or 0.0)
                located_moving_s = float(seqd["located_moving_s"] or 0.0)
                off_track_pct = (
                    round(100.0 * off_track_s / located_moving_s, 2) if located_moving_s > 0 else 0.0
                )

            recv_span = (
                tel["max_recv"] - tel["min_recv"]
                if tel["recv_rows"] and tel["recv_rows"] > 1
                else None
            )
            rate_hz = (tel["recv_rows"] - 1) / recv_span if recv_span else None

            # ---- command log ----
            c_where = "session_id = ?"
            c_params: List[Any] = [session_id]
            if recv_from is not None:
                c_where += " AND recv_t >= ?"
                c_params.append(recv_from)
            if recv_to is not None:
                c_where += " AND recv_t <= ?"
                c_params.append(recv_to)
            ctl = conn.execute(
                f"""
                SELECT COUNT(*) AS sent,
                       COALESCE(SUM(CASE WHEN forwarded = 1 THEN 1 ELSE 0 END), 0) AS forwarded,
                       COUNT(ack_rtt_ms) AS acked
                FROM control_log WHERE {c_where}
                """,
                c_params,
            ).fetchone()
            acks = conn.execute(
                f"SELECT ack_rtt_ms, ui_rtt_ms FROM control_log WHERE {c_where} AND ack_rtt_ms IS NOT NULL",
                c_params,
            ).fetchall()
            car_rtt = sorted(float(a["ack_rtt_ms"]) for a in acks)
            # One-way UI -> car estimate: half of each measured round trip.
            one_way = sorted(
                (float(a["ack_rtt_ms"]) + float(a["ui_rtt_ms"])) / 2.0
                for a in acks
                if a["ui_rtt_ms"] is not None
            )
            acked = int(ctl["acked"])
            forwarded = int(ctl["forwarded"])

            return {
                "session_id": session_id,
                # laps
                "lap_count": int(laps["lap_count"] or 0),
                "invalid_laps": int(laps["invalid_laps"] or 0),
                "unconfirmed_car_laps": int(unconfirmed or 0),
                "best_lap_s": _round(laps["best_lap_s"], 3),
                "avg_lap_s": _round(laps["avg_lap_s"], 3),
                # speed and distance
                "max_speed_mps": _round(tel["max_speed_mps"]),
                "avg_speed_mps": _round(tel["avg_speed_mps"]),
                "avg_moving_speed_mps": _round(distance_m / moving_s) if moving_s > 0 else None,
                "distance_m": round(distance_m, 2),
                "moving_time_s": round(moving_s, 2),
                "off_track_s": _round(off_track_s),
                "off_track_pct": off_track_pct,
                # acceleration (IMU)
                "max_accel_mps2": _round(tel["max_ax"]),
                "max_brake_mps2": _round(-tel["min_ax"]) if tel["min_ax"] is not None else None,
                "max_lateral_mps2": _round(tel["max_ay"]),
                # battery
                "min_battery_v": _round(tel["min_battery_v"]),
                # link health
                "telemetry_rows": rows,
                "seq_gaps": seq_gaps,
                "packet_loss_pct": packet_loss_pct,
                "telemetry_rate_hz": _round(rate_hz),
                "max_gap_s": _round(seqd["max_gap_s"], 3),
                # sensor health
                "sensor_error_rows": int(tel["err_any"]),
                "sensor_error_pct": round(100.0 * tel["err_any"] / rows, 4) if rows else 0.0,
                "sensor_errors": {
                    "gps": int(tel["err_gps"]),
                    "imu": int(tel["err_imu"]),
                    "speed": int(tel["err_speed"]),
                    "heading": int(tel["err_heading"]),
                    "battery": int(tel["err_battery"]),
                },
                # command latency
                "controls_sent": int(ctl["sent"]),
                "controls_acked": acked,
                # A car that never acknowledges is a v1 car, not a lossy link.
                "controls_lost": max(0, forwarded - acked) if acked > 0 else None,
                "control_rtt_p50_ms": _round(percentile(car_rtt, 50)),
                "control_rtt_p95_ms": _round(percentile(car_rtt, 95)),
                "latency_p50_ms": _round(percentile(one_way, 50)),
                "latency_p95_ms": _round(percentile(one_way, 95)),
                "duration_s": _round(duration_s),
            }
        finally:
            conn.close()

    # ---- races -----------------------------------------------------------
    def create_race(self, name: str, laps_target: Optional[int], started_at: float) -> int:
        return self._execute(
            "INSERT INTO races (name, laps_target, started_at, ended_at) VALUES (?, ?, ?, NULL)",
            (name, laps_target, started_at),
        )

    def add_race_entry(
        self, race_id: int, session_id: int, car_id: str, start_t: Optional[float], joined_at: float
    ) -> None:
        self._execute(
            "INSERT OR IGNORE INTO race_entries (race_id, session_id, car_id, start_t, end_t, joined_at)"
            " VALUES (?, ?, ?, ?, NULL, ?)",
            (race_id, session_id, car_id, start_t, joined_at),
        )

    def set_race_entry_start(self, race_id: int, session_id: int, start_t: float) -> None:
        self._execute(
            "UPDATE race_entries SET start_t = ? WHERE race_id = ? AND session_id = ? AND start_t IS NULL",
            (start_t, race_id, session_id),
        )

    def set_race_entry_end(self, race_id: int, session_id: int, end_t: Optional[float]) -> None:
        self._execute(
            "UPDATE race_entries SET end_t = ? WHERE race_id = ? AND session_id = ? AND end_t IS NULL",
            (end_t, race_id, session_id),
        )

    def finish_race(self, race_id: int, ended_at: float) -> None:
        self._execute(
            "UPDATE races SET ended_at = ? WHERE id = ? AND ended_at IS NULL", (ended_at, race_id)
        )

    def list_races(self) -> List[Dict[str, Any]]:
        return self._all(
            """
            SELECT r.id, r.name, r.laps_target, r.started_at, r.ended_at,
                   (SELECT COUNT(*) FROM race_entries e WHERE e.race_id = r.id) AS cars
            FROM races r ORDER BY r.id DESC
            """
        )

    def get_race(self, race_id: int) -> Optional[Dict[str, Any]]:
        rows = self._all(
            "SELECT id, name, laps_target, started_at, ended_at FROM races WHERE id = ?", (race_id,)
        )
        return rows[0] if rows else None

    def race_results(self, race_id: int) -> Optional[Dict[str, Any]]:
        """Classification of a race: most laps first, then least time."""
        race = self.get_race(race_id)
        if race is None:
            return None
        entries = self._all(
            "SELECT session_id, car_id, start_t, end_t FROM race_entries WHERE race_id = ?",
            (race_id,),
        )
        results: List[Dict[str, Any]] = []
        for e in entries:
            laps = self._all(
                "SELECT race_lap, lap_time_s, t, valid, off_track_s FROM laps"
                " WHERE race_id = ? AND session_id = ? AND source = 'server' ORDER BY race_lap",
                (race_id, e["session_id"]),
            )
            total = None
            if laps and e["start_t"] is not None:
                total = laps[-1]["t"] - e["start_t"]
            k = self.compute_kpis(
                e["session_id"],
                t_from=e["start_t"],
                t_to=e["end_t"],
                race_id=race_id,
                recv_from=race["started_at"],
                recv_to=race["ended_at"],
            ) or {}
            results.append({
                "car_id": e["car_id"],
                "session_id": e["session_id"],
                "start_t": e["start_t"],
                "end_t": e["end_t"],
                "laps": len(laps),
                "total_time_s": _round(total, 3),
                "last_lap_s": _round(laps[-1]["lap_time_s"], 3) if laps else None,
                "best_lap_s": k.get("best_lap_s"),
                "avg_lap_s": k.get("avg_lap_s"),
                "invalid_laps": k.get("invalid_laps", 0),
                "max_speed_mps": k.get("max_speed_mps"),
                "avg_moving_speed_mps": k.get("avg_moving_speed_mps"),
                "distance_m": k.get("distance_m"),
                "off_track_s": k.get("off_track_s"),
                "packet_loss_pct": k.get("packet_loss_pct"),
                "sensor_error_pct": k.get("sensor_error_pct"),
                "latency_p95_ms": k.get("latency_p95_ms"),
                "lap_times": [
                    {
                        "race_lap": lap["race_lap"],
                        "lap_time_s": round(lap["lap_time_s"], 3),
                        "valid": None if lap["valid"] is None else bool(lap["valid"]),
                    }
                    for lap in laps
                ],
            })

        results.sort(
            key=lambda r: (
                -r["laps"],
                r["total_time_s"] if r["total_time_s"] is not None else float("inf"),
                r["car_id"],
            )
        )
        leader = results[0] if results else None
        for i, r in enumerate(results):
            r["position"] = i + 1
            if leader is None or r is leader:
                r["gap_laps"], r["gap_s"] = 0, 0.0 if r["total_time_s"] is not None else None
            elif r["laps"] == leader["laps"]:
                r["gap_laps"] = 0
                r["gap_s"] = (
                    round(r["total_time_s"] - leader["total_time_s"], 3)
                    if r["total_time_s"] is not None and leader["total_time_s"] is not None
                    else None
                )
            else:
                r["gap_laps"], r["gap_s"] = leader["laps"] - r["laps"], None
        return {**race, "results": results}
