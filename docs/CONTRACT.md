# F163 Ground Station — Interface Contract (v1.1, proposed)

Project 2627-F-163 Autonomous RC Car Racing Platform, Software (SEN) lane.
This document is the single source of truth for every interface between the
simulator / real car, the ground-station server, and the web UI.
All components are built against this contract. Changes require a version bump.

**Status of v1.1.** Proposed by the SEN lane, implemented in this repository,
not yet agreed with the CMP lane. Everything it adds is optional for a vehicle:
a v1 car (no `control_ack`, no `fw`, its own lap reports) connects and works
unmodified, and a v1 database is upgraded in place. What a vehicle gains by
adopting each addition is listed in §8, and the points that still need a
cross-lane decision in §9.

What v1.1 adds:

| Area | Addition | Section |
|---|---|---|
| Laps | The server times and validates laps from reported positions; a car's own `lap` message becomes a cross-check | §2.3, §4.2 |
| Track | The track (centreline, width, GPS anchor) is server configuration, served over REST | §4.1 |
| Commands | `cseq` on forwarded `control`, `control_ack` from the car, measured command latency | §2.4, §3 |
| Sensors | A reading may be `null`; sensor error rate is a KPI separate from packet loss | §2.2, §4.4 |
| Races | Cars timed together from one start, classified, stored | §3, §4.5 |
| Reset | `reset` puts a (simulated) car back on the start line | §2.5, §3 |
| KPIs | Distance, moving-average speed, off-track time, accelerations, data rate, latency percentiles | §4.4 |
| Export | CSV downloads for telemetry, laps and race results | §4.3, §4.5 |

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
- Two clocks are in play and are never mixed: `t` is the **car's** clock (used
  for lap times, distance, anything measured along the drive), `recv_t` is the
  **server's** clock when a frame arrived (used for data rate and silences).

## 2. WS /ws/car  (vehicle <-> server)

### 2.1 Hello

Vehicle sends on connect, exactly once, first message:

```json
{"type": "hello", "car_id": "car-1", "fw": "sim-0.2", "mode": "manual"}
```

`mode` is `"manual"` (driven from UI) or `"auto"` (onboard/autopilot). `fw` is
a free-text software version and is stored with the session. Server replies:

```json
{"type": "hello_ack", "session_id": 12, "server_time": 1763100000.0}
```

A new DB session row is created per car connection (§5). If the same `car_id`
connects again while the old socket is still registered, the new connection
takes over.

### 2.2 Telemetry

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

- Units: m/s^2 (`ax`..`az`), rad/s (`gx`..`gz`), m/s, degrees [0, 360), volts.
- IMU axes are the car's own: x forward, y left, z up. So `ax` > 0 is
  speeding up, `ay` > 0 is a left turn, `gz` > 0 is turning left.
- `heading_deg` is measured counter-clockwise from the track frame's +x axis
  (east): 0 = east, 90 = north. See §9 if the car reports a compass bearing.
- `steering`/`throttle` echo the currently applied actuation (normalized, §3):
  `steering` < 0 is left.
- `seq` is a per-session monotonically increasing integer; gaps in `seq` are
  lost packets (§4.4). A frame without an integer `seq` is dropped; a frame
  without a numeric `t` is stamped with the server's receive time.
- **A sensor with no reading sends `null`** for its value (v1.1), for example
  `"gps": {"lat": null, "lon": null}` or `"speed_mps": null`. The frame is
  still stored and broadcast; the missing value is stored as NULL and counted
  as a sensor error (§4.4), never as zero. Anything that is not a number is
  treated the same way.

The server stamps each frame with `recv_t`, locates the position on the track
(§4.1) and stores `off_track` and `track_s` (distance along the centreline)
with it.

### 2.3 Laps

**The server times laps** (v1.1). From each car's reported positions it tracks
progress along the centreline and records a lap when the car crosses the
start/finish line forwards having covered at least 90 % of the track length
since the previous crossing. Circling on the line, reversing over it, or being
moved (a jump no car could drive: more than 1 m and faster than 15 m/s between
two samples) does not produce a lap. The crossing instant is interpolated
between the two samples either side of the line, on the car's clock.

A lap is **valid** if the car was off the track (§4.1) for no more than 0.25 s
in total during it. An invalid lap is counted but its time is excluded from
best and average.

A vehicle may still report its own laps:

```json
{"type": "lap", "car_id": "car-1", "lap_number": 3, "lap_time_s": 14.82, "t": 1763100040.1}
```

This is a cross-check only. If it matches a server-timed lap (crossing times
within 1.5 s) the car's time is stored beside the server's as `car_time_s`. If
it matches nothing it is stored with `source = "car"`, `valid = false`, shown
to the operator as unconfirmed, and counted in no KPI.

### 2.4 Control and acknowledgement

Server -> vehicle (forwarded operator commands, only in `manual` mode):

```json
{"type": "control", "throttle": 0.6, "steering": -0.25, "ts": 1763100012.401, "cseq": 57}
```

`cseq` (v1.1) is a per-connection counter. A vehicle that supports
acknowledgement replies as soon as it has applied the command:

```json
{"type": "control_ack", "cseq": 57}
```

The server measures the time from forwarding to acknowledgement on its own
monotonic clock (`ack_rtt_ms`), logs it with the command, and relays the result
to the UI that sent the command (§3). A command not acknowledged within 2 s is
logged as unacknowledged. A vehicle that never acknowledges is not penalised:
with no acknowledgement in a session, "commands lost" is reported as unknown.

### 2.5 Reset

Server -> vehicle (either mode):

```json
{"type": "reset"}
```

Asks the vehicle to return to the start/finish line and stop. The simulator
obeys: pose back to the line, speed and applied actuation to zero, the lap in
progress abandoned (completed laps, `seq`, and battery are unchanged). A real
car cannot move itself there and may ignore the message. The server abandons
the lap in progress either way.

## 3. WS /ws/ui  (UI <-> server)

UI sends on connect: `{"type": "hello", "client": "web"}`.
Server replies with the current state:

```json
{
  "type": "state",
  "cars": [{"car_id": "car-1", "session_id": 12, "mode": "manual", "fw": "sim-0.2", "connected": true}],
  "race": null
}
```

`race` is the running race (§4.5) or `null`.

UI -> server (drive commands):

```json
{"type": "control", "car_id": "car-1", "throttle": 0.6, "steering": -0.25, "ts": 1763100012.400, "ui_rtt_ms": 6.0}
```

- `throttle` in [-1.0, 1.0] (negative = brake/reverse), `steering` in [-1.0, 1.0]
  (negative = left, positive = right). Server clamps out-of-range values.
- `ui_rtt_ms` (v1.1, optional) is the UI's latest ping round trip to the
  server; it is logged with the command and used for the latency KPI (§4.4).
- The server forwards to the car immediately (manual mode only) and logs every
  command to `control_log`, including those not forwarded because the car is
  in auto mode.

UI -> server (reset request):

```json
{"type": "reset", "car_id": "car-1"}
```

Server forwards `{"type": "reset"}` to that car (§2.5). A reset or control for
an unknown car is ignored.

Server -> UI:

- Every `telemetry` message, verbatim as received (§2.2), to all UIs.
- Lap events, to all UIs:

  ```json
  {"type": "lap", "car_id": "car-1", "lap_number": 3, "lap_time_s": 14.823, "t": 1763100040.112,
   "valid": true, "source": "server", "off_track_s": 0.0,
   "race_id": 4, "race_lap": 2, "race_time_s": 31.507}
  ```

  `source` is `"server"` for a timed lap, `"car"` for an unconfirmed car
  report (§2.3). The `race_*` fields are `null` outside a race; `race_time_s`
  is the time from the race start to this crossing.
- `{"type": "car_connected", "car_id": "...", "session_id": N, "mode": "...", "fw": "..."}`
  and `{"type": "car_disconnected", "car_id": "...", "session_id": N}`.
- To the UI that sent the command, when the car acknowledges it:
  `{"type": "control_ack", "car_id": "car-1", "ts": <the command's ts>, "car_rtt_ms": 3.2}`.
  The UI matches `ts` to its own send time to measure the full loop
  UI -> server -> car -> server -> UI on its own clock.
- `{"type": "race", "race": {...}}` when a race starts, and
  `{"type": "race", "race": null, "finished": {..., "reason": "..."}}` when it ends.
- `{"type": "pong", "ts": <echo>, "server_time": ...}` in reply to
  `{"type": "ping", "ts": ...}`.

## 4. REST API

`GET /api/health` -> `{"status": "ok"}`

### 4.1 Track

`GET /api/track` -> the track every position is judged against:

```json
{"name": "Simulator stadium", "anchor": {"lat": 41.0421, "lon": 29.0093},
 "width_m": 1.6, "length_m": 34.849, "centerline": [[-4.0, -3.0], [-3.96, -3.0], ...]}
```

- `centerline` is a closed polyline in metres, east (x) and north (y) of
  `anchor`, in driving order. **Point 0 is the start/finish line** and the
  direction to point 1 is the direction of travel.
- A car is off the track when it is further than `width_m / 2` from the
  centreline.
- The default is the simulator's stadium (two 8 m straights, two 3 m radius
  bends). A real track is supplied without code changes: set `F163_TRACK` to
  the path of a JSON file with `name`, `anchor`, `width_m` and `centerline`.
  The UI draws whatever the server serves.

### 4.2 Sessions and laps

- `GET /api/sessions` -> `[{"id": 12, "car_id": "car-1", "started_at": ..., "ended_at": ...|null, "mode": "manual", "fw": "sim-0.2"}]` (newest first).
  A session left open by a server crash is closed at the next start-up.
- `GET /api/sessions/{id}/laps` -> every lap row, in time order:
  `[{"lap_number": 1, "lap_time_s": 15.2, "t": ..., "valid": true, "source": "server", "off_track_s": 0.0, "car_time_s": 15.21, "race_id": null, "race_lap": null}]`

### 4.3 Telemetry

- `GET /api/sessions/{id}/telemetry?from_t=&to_t=&limit=` -> array of telemetry
  rows (flattened, §5), default limit 5000, ordered by `t`.
- `GET /api/sessions/{id}/telemetry.csv` -> the whole session as CSV, streamed.
- `GET /api/sessions/{id}/laps.csv` -> the laps as CSV.

### 4.4 KPIs

`GET /api/sessions/{id}/kpis`:

```json
{
  "session_id": 12,
  "lap_count": 5, "invalid_laps": 1, "unconfirmed_car_laps": 0,
  "best_lap_s": 14.82, "avg_lap_s": 15.40,
  "max_speed_mps": 4.91, "avg_speed_mps": 3.10, "avg_moving_speed_mps": 3.62,
  "distance_m": 962.4, "moving_time_s": 265.8,
  "off_track_s": 2.05, "off_track_pct": 0.77,
  "max_accel_mps2": 4.1, "max_brake_mps2": 3.8, "max_lateral_mps2": 5.7,
  "min_battery_v": 7.02,
  "telemetry_rows": 6000, "seq_gaps": 12, "packet_loss_pct": 0.2,
  "telemetry_rate_hz": 19.9, "max_gap_s": 0.31,
  "sensor_error_rows": 9, "sensor_error_pct": 0.15,
  "sensor_errors": {"gps": 4, "imu": 2, "speed": 1, "heading": 0, "battery": 2},
  "controls_sent": 812, "controls_acked": 810, "controls_lost": 2,
  "control_rtt_p50_ms": 4.1, "control_rtt_p95_ms": 9.8,
  "latency_p50_ms": 5.6, "latency_p95_ms": 11.2,
  "duration_s": 310.5
}
```

The v1 keys keep their meaning. How each figure is computed:

| Key | Definition |
|---|---|
| `lap_count` | Server-timed laps (valid or not). In a v1 recording, the laps the car reported. |
| `invalid_laps` | Server-timed laps with more than 0.25 s off the track. |
| `unconfirmed_car_laps` | Car lap reports the server could not match (§2.3). |
| `best_lap_s`, `avg_lap_s` | Over valid server-timed laps only. |
| `max_speed_mps`, `avg_speed_mps` | Over every stored speed reading, standing time included. |
| `distance_m` | Sum of \|speed\| x dt over consecutive samples on the car's clock. Gaps longer than 1 s are not integrated over. |
| `moving_time_s` | Sum of dt while \|speed\| > 0.1 m/s. |
| `avg_moving_speed_mps` | `distance_m / moving_time_s`. |
| `off_track_s`, `off_track_pct` | Time spent off the track while moving, and its share of the moving time. A car parked beside the track adds nothing. `null` if positions were never checked against a track (v1 recording). |
| `max_accel_mps2`, `max_brake_mps2` | Largest positive and largest negative `ax`. |
| `max_lateral_mps2` | Largest \|`ay`\|. |
| `seq_gaps`, `packet_loss_pct` | Missing sequence numbers, and their share of `last seq - first seq + 1`. |
| `telemetry_rate_hz` | `(rows - 1) / (last recv_t - first recv_t)`. |
| `max_gap_s` | Longest wait between two consecutive frames, by `recv_t`. |
| `sensor_error_rows`, `sensor_error_pct` | Frames with at least one bad reading, and their share of all frames. |
| `sensor_errors` | Bad readings per sensor. A reading is bad when it is missing or implausible: GPS outside +-90 / +-180 degrees; any acceleration above 160 m/s^2 (about 16 g); \|speed\| above 50 m/s; heading outside [0, 360]; battery at or below 0 V or above 30 V. |
| `controls_sent` | Commands logged for the session. |
| `controls_acked`, `controls_lost` | Forwarded commands the car acknowledged, and forwarded commands it did not. `controls_lost` is `null` when the car acknowledged nothing at all. |
| `control_rtt_p50_ms`, `control_rtt_p95_ms` | Server -> car -> server round trip (`ack_rtt_ms`), nearest-rank percentiles. |
| `latency_p50_ms`, `latency_p95_ms` | One-way command latency estimate per command, `(ui_rtt_ms + ack_rtt_ms) / 2`, nearest-rank percentiles. Requirement: p95 at or below 100 ms. |
| `duration_s` | `ended_at - started_at`; while the session is open, the telemetry span. |

Packet loss and sensor error are different things: a lost packet never
arrived; a sensor error arrived with a reading that is missing or impossible.

### 4.5 Races

A race groups the connected cars, times them from one instant and ranks them.
One race runs at a time.

- `POST /api/races` with `{"name": "Heat 1", "laps": 5, "reset": true}` (all
  optional) -> `201` and the race. `name` defaults to the start time, `laps`
  (1..500) is the lap target, `reset` sends every car `reset` first (§2.5).
  `409` if a race is already running or no car is connected.
- Each car is timed on its own clock, from the last frame it sent before the
  start. A car that connects during a race joins it and is timed from its
  first frame.
- The first race lap runs from the start to the car's first full circuit. The
  race **finishes by itself** when a car reaches the lap target, or when an
  operator calls `POST /api/races/{id}/finish`.
- `GET /api/races` -> `[{"id": 4, "name": "Heat 1", "laps_target": 5, "started_at": ..., "ended_at": ...|null, "cars": 2}]` (newest first).
- `GET /api/races/{id}` -> the race and its classification:

  ```json
  {"id": 4, "name": "Heat 1", "laps_target": 5, "started_at": ..., "ended_at": ...,
   "results": [{"position": 1, "car_id": "car-1", "session_id": 12, "laps": 5,
                "total_time_s": 43.1, "gap_laps": 0, "gap_s": 0.0,
                "best_lap_s": 8.51, "avg_lap_s": 8.62, "last_lap_s": 8.51, "invalid_laps": 0,
                "max_speed_mps": 4.25, "avg_moving_speed_mps": 4.04, "distance_m": 174.2,
                "off_track_s": 0.0, "packet_loss_pct": 0.0, "sensor_error_pct": 0.0,
                "latency_p95_ms": null, "start_t": ..., "end_t": ...,
                "lap_times": [{"race_lap": 1, "lap_time_s": 9.02, "t": ..., "valid": true, "off_track_s": 0.0}]}]}
  ```

  Classification: more laps first; on equal laps, the car that finished its
  last lap earlier. `total_time_s` runs from the race start to the car's last
  completed lap. `gap_s` is given for cars on the leader's lap, `gap_laps`
  otherwise. The per-car figures are the session KPIs (§4.4) restricted to the
  race window.
- `GET /api/races/{id}/results.csv` -> the classification as CSV.

## 5. SQLite schema (`data/f163.db`)

```sql
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  started_at REAL NOT NULL,
  ended_at REAL,
  fw TEXT                                   -- v1.1
);
CREATE TABLE telemetry (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  seq INTEGER NOT NULL,
  t REAL NOT NULL,
  ax REAL, ay REAL, az REAL, gx REAL, gy REAL, gz REAL,
  lat REAL, lon REAL,
  speed_mps REAL, heading_deg REAL, battery_v REAL,
  steering REAL, throttle REAL,
  recv_t REAL,                              -- v1.1: server clock on arrival
  off_track INTEGER,                        -- v1.1: 1 off the track, 0 on it, NULL not located
  track_s REAL                              -- v1.1: metres along the centreline
);
CREATE INDEX idx_telemetry_session_t ON telemetry(session_id, t);
CREATE TABLE laps (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  lap_number INTEGER NOT NULL,
  lap_time_s REAL NOT NULL,
  t REAL NOT NULL,
  recv_t REAL,                              -- v1.1
  valid INTEGER,                            -- v1.1: 0 if the lap left the track
  source TEXT,                              -- v1.1: 'server' or 'car'; NULL in a v1 row
  off_track_s REAL,                         -- v1.1
  car_time_s REAL,                          -- v1.1: the car's own time for the same lap
  race_id INTEGER,                          -- v1.1
  race_lap INTEGER                          -- v1.1
);
CREATE TABLE control_log (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  ts REAL NOT NULL,
  throttle REAL NOT NULL,
  steering REAL NOT NULL,
  recv_t REAL,                              -- v1.1: server clock on arrival
  forwarded INTEGER,                        -- v1.1: 0 when the car was in auto mode
  ack_rtt_ms REAL,                          -- v1.1: NULL if never acknowledged
  ui_rtt_ms REAL                            -- v1.1
);
CREATE TABLE races (                        -- v1.1
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  laps_target INTEGER,
  started_at REAL NOT NULL,
  ended_at REAL
);
CREATE TABLE race_entries (                 -- v1.1
  race_id INTEGER NOT NULL REFERENCES races(id),
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  car_id TEXT NOT NULL,
  start_t REAL, end_t REAL,
  joined_at REAL NOT NULL,
  PRIMARY KEY (race_id, session_id)
);
```

Telemetry inserts are batched (flush every 50 rows or 1 s, whichever first).
A v1 database is upgraded in place on start-up (`ALTER TABLE ... ADD COLUMN`);
its old rows keep NULL in the new columns, which every query reads as
"unknown".

## 6. Simulator requirements

- Kinematic bicycle model on a closed oval/stadium track; 20 Hz tick.
- `--mode auto`: pure-pursuit follower on the track centerline, completes laps.
  `--pace` (0.2..1.15, default 1.0) scales its speed, so two simulated cars
  can run a real race.
- `--mode manual`: applies the last received `control` message (with a safety
  decay to zero throttle if no command for > 0.5 s). Steering follows §3:
  negative turns left.
- Acknowledges every `control` with `control_ack` (§2.4).
- Reports IMU readings that follow the motion: `ax` from the change in speed,
  `ay` = speed x yaw rate, `gz` = yaw rate, each with noise.
- Emits `lap` when it crosses the start/finish line having covered at least
  90 % of the track since the last crossing.
- Obeys `reset` (§2.5) in both modes.
- Injects realistic noise (IMU jitter, battery sag with throttle), can drop
  packets with `--loss 0.01` to exercise the packet-loss KPI, and can blank a
  sensor reading with `--sensor-fault 0.01` to exercise the sensor-error KPI.

## 7. Non-goals for v1

No auth, no multi-server, no native mobile app (responsive web covers phone
use for the fall demo), no PostgreSQL/Timescale (SQLite is sufficient at
20 Hz x 2 cars; the storage layer is isolated so it can be swapped in spring).

## 8. What a vehicle needs to send for each figure

| To get | The vehicle must |
|---|---|
| Lap times, lap validity, off-track time, race classification | Send `gps` positions that are accurate to a fraction of the track width (§9) |
| Distance, moving-average speed | Send `speed_mps` |
| Acceleration, braking, cornering figures | Send `imu` with the axes of §2.2 |
| Packet loss | Increment `seq` once per frame, including frames it fails to send |
| Sensor error rate | Send `null` for a reading it does not have, instead of 0 or the last value |
| Command latency, commands lost | Reply `control_ack` with the `cseq` it was given |
| Software version in the session record | Send `fw` in `hello` |

## 9. Open points for the cross-lane review

1. **Position accuracy.** Everything in §2.3 depends on position. The
   simulator's track is 1.6 m wide and 35 m long; consumer GPS is accurate to
   2-5 m and cannot tell which side of a kerb a car is on. The real car needs
   a position good to roughly 0.2 m in the track frame (RTK GPS, UWB anchors,
   an overhead camera, or onboard localisation). The field is called `gps`
   and carries latitude/longitude; if the car localises in metres instead, it
   can convert with the anchor of §4.1, or the contract can gain an `xy` field.
2. **Heading convention.** §2.2 fixes counter-clockwise from east, which is
   what the simulator sends and the UI draws. A magnetometer gives a compass
   bearing (clockwise from north); the conversion is `heading = 90 - bearing`.
   One of the two must be agreed.
3. **The real track.** Its centreline, width and anchor have to be surveyed
   and put in a track file (§4.1) before lap validity means anything on it.
4. **Clocks.** Lap and race times use each car's own clock, measured from
   that car's own start instant, so cars do not need synchronised clocks for
   gaps to be right. The start instant is known to within one telemetry
   period (50 ms at 20 Hz). A clock that jumps mid-session (an NTP step) would
   corrupt the lap in progress; cars should time with a monotonic clock.
5. **Lap authority.** v1.1 makes the server the authority and the car's
   `lap` a cross-check. If the CMP lane prefers the car to be the authority,
   §2.3 and the KPI definitions change accordingly.
