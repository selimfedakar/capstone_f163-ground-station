# F163 Ground Station — Interface Contract (v1)

Project 2627-F-163 Autonomous RC Car Racing Platform, Software (SEN) lane.
This document is the single source of truth for every interface between the
simulator / real car, the ground-station server, and the web UI.
All components are built against this contract. Changes require a version bump.

## 1. Topology

```
[RC Car or Simulator] <--WS /ws/car--> [Ground Station Server] <--WS /ws/ui--> [Web UI (Drive + Live)]
                                              |                      ^
                                         [SQLite DB]            REST /api/* (Dashboard)
```

- Server: FastAPI + uvicorn, default `http://127.0.0.1:8000`.
- One WebSocket endpoint for vehicles (`/ws/car`), one for operator UIs (`/ws/ui`).
- All WS messages are JSON text frames. All timestamps are Unix seconds (float, UTC).
- Telemetry nominal rate: 20 Hz per car. Control nominal rate: up to 30 Hz.

## 2. WS /ws/car  (vehicle -> server, server -> vehicle)

Vehicle sends on connect, exactly once, first message:

```json
{"type": "hello", "car_id": "car-1", "fw": "sim-0.1", "mode": "manual"}
```

`mode` is `"manual"` (driven from UI) or `"auto"` (onboard/autopilot). Server replies:

```json
{"type": "hello_ack", "session_id": 12, "server_time": 1763100000.0}
```

A new DB session row is created per car connection (see §5).

Vehicle -> server, 20 Hz:

```json
{
  "type": "telemetry",
  "car_id": "car-1",
  "seq": 1042,
  "t": 1763100012.350,
  "imu": {"ax": 0.12, "ay": -0.03, "az": 9.81, "gx": 0.0, "gy": 0.0, "gz": 0.4},
  "gps": {"lat": 41.0421, "lon": 29.0093},
  "speed_mps": 3.25,
  "heading_deg": 92.5,
  "battery_v": 7.41,
  "steering": -0.15,
  "throttle": 0.60
}
```

Units: m/s^2 (ax..az), rad/s (gx..gz), m/s, degrees [0,360), volts.
`steering`/`throttle` echo the currently applied actuation (normalized, §3).
`seq` is a per-session monotonically increasing integer; the server uses gaps
in `seq` to compute the packet-loss / sensor-error-rate KPI.

Vehicle -> server, on lap completion:

```json
{"type": "lap", "car_id": "car-1", "lap_number": 3, "lap_time_s": 14.82, "t": 1763100040.1}
```

Server -> vehicle (forwarded operator commands, only in `manual` mode):

```json
{"type": "control", "throttle": 0.6, "steering": -0.25, "ts": 1763100012.401}
```

## 3. WS /ws/ui  (UI -> server, server -> UI)

UI sends on connect: `{"type": "hello", "client": "web"}`.
Server replies with the current state:

```json
{"type": "state", "cars": [{"car_id": "car-1", "session_id": 12, "mode": "manual", "connected": true}]}
```

UI -> server (drive commands):

```json
{"type": "control", "car_id": "car-1", "throttle": 0.6, "steering": -0.25, "ts": 1763100012.400}
```

- `throttle` in [-1.0, 1.0] (negative = brake/reverse), `steering` in [-1.0, 1.0]
  (negative = left, positive = right). Server clamps out-of-range values.
- Server forwards to the car immediately and logs to `control_log`.

Server -> UI (broadcast to all connected UIs):

- Every `telemetry` message, verbatim as received (same schema as §2).
- Every `lap` message, verbatim.
- `{"type": "car_connected", "car_id": "...", "session_id": N}` and
  `{"type": "car_disconnected", "car_id": "...", "session_id": N}` on changes.
- `{"type": "pong", "ts": <echo>, "server_time": ...}` in reply to
  `{"type": "ping", "ts": ...}` — the UI uses this for its latency display.

## 4. REST API (dashboard reads)

- `GET /api/health` -> `{"status": "ok"}`
- `GET /api/sessions` -> `[{"id": 12, "car_id": "car-1", "started_at": ..., "ended_at": ...|null, "mode": "manual"}]` (newest first)
- `GET /api/sessions/{id}/telemetry?from_t=&to_t=&limit=` -> array of telemetry rows (flattened, §5), default limit 5000, ordered by `t`
- `GET /api/sessions/{id}/laps` -> `[{"lap_number": 1, "lap_time_s": 15.2, "t": ...}]`
- `GET /api/sessions/{id}/kpis` -> computed KPIs:

```json
{
  "session_id": 12,
  "lap_count": 5,
  "best_lap_s": 14.82,
  "avg_lap_s": 15.40,
  "max_speed_mps": 4.91,
  "avg_speed_mps": 3.10,
  "min_battery_v": 7.02,
  "telemetry_rows": 6000,
  "seq_gaps": 12,
  "packet_loss_pct": 0.2,
  "duration_s": 310.5
}
```

## 5. SQLite schema (`data/f163.db`)

```sql
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL
);
CREATE TABLE telemetry (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t REAL NOT NULL,
  ax REAL, ay REAL, az REAL, gx REAL, gy REAL, gz REAL,
  lat REAL, lon REAL,
  speed_mps REAL, heading_deg REAL, battery_v REAL,
  steering REAL, throttle REAL
);
CREATE INDEX idx_telemetry_session_t ON telemetry(session_id, t);
CREATE TABLE laps (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  lap_number INTEGER NOT NULL,
  lap_time_s REAL NOT NULL,
  t REAL NOT NULL
);
CREATE TABLE control_log (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  ts REAL NOT NULL,
  throttle REAL NOT NULL,
  steering REAL NOT NULL
);
```

Telemetry inserts are batched (flush every 50 rows or 1 s, whichever first).

## 6. Simulator requirements

- Kinematic bicycle model on a closed oval/stadium track; 20 Hz tick.
- `--mode auto`: pure-pursuit follower on the track centerline, completes laps.
- `--mode manual`: applies the last received `control` message (with a safety
  decay to zero throttle if no command for > 0.5 s).
- Emits `lap` when crossing the start/finish line.
- Injects realistic noise (IMU jitter, battery sag with throttle) and can drop
  packets with `--loss 0.01` to exercise the `seq_gaps` KPI.

## 7. Non-goals for v1

No auth, no multi-server, no native mobile app (responsive web covers phone
use for the fall demo), no PostgreSQL/Timescale (SQLite is sufficient at
20 Hz x 2 cars; the storage layer is isolated so it can be swapped in spring).
