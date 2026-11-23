# F163 Ground Station — Server & Simulator

Python backend for Project 2627-F-163 (Autonomous RC Car Racing Platform,
software lane). It ingests vehicle telemetry over WebSocket, relays operator
control to cars, broadcasts live data to web UIs, stores everything in SQLite,
and exposes a REST dashboard API. A companion simulator produces realistic
telemetry for development and demos.

All interfaces follow `docs/CONTRACT.md` (v1.1, proposed). A v1 vehicle still
connects unmodified, and a v1 database is upgraded in place on start-up.

## Layout

```
server/app/      FastAPI server
  main.py          app factory + WS routes + lifespan (DB start/stop)
  ws_car.py        /ws/car handler (hello, telemetry, lap, control_ack)
  ws_ui.py         /ws/ui handler (state, control relay, reset, ping/pong)
  api.py           REST /api/* endpoints (sessions, KPIs, track, races, CSV)
  db.py            SQLite storage layer (single batched writer task + KPIs + race results)
  state.py         in-memory car/UI registry + broadcast + control clamping
  track.py         track description: centreline, width, GPS anchor
  laps.py          lap timing and validation from reported positions
  race.py          race start, finish and membership
sim/             car simulator
  car.py           kinematic bicycle model, pure-pursuit, telemetry emitter
  track.py         closed stadium/oval centerline + pure-pursuit helpers
tests/           pytest suite (DB, KPIs, laps, track, races, API, simulator, WS integration)
scripts/smoke.sh end-to-end smoke test
```

The database file is created at `data/f163.db` (directory auto-created). Set
`F163_DB_PATH` to override the path.

The track that positions are judged against defaults to the simulator's
stadium. Set `F163_TRACK` to a JSON file to use another one:

```json
{"name": "Campus car park", "anchor": {"lat": 41.0421, "lon": 29.0093},
 "width_m": 1.6, "centerline": [[0, 0], [1, 0], [2, 0.1]]}
```

`centerline` is a closed loop in metres east and north of `anchor`, in driving
order; point 0 is the start/finish line (contract section 4.1).

## Install

```bash
make install           # creates .venv and installs pinned requirements
# or manually:
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run the server

```bash
make server            # uvicorn on http://127.0.0.1:8000
# or:
.venv/bin/python -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
```

Endpoints: `GET /api/health`, `/api/track`, `/api/sessions`,
`/api/sessions/{id}/telemetry` (and `.csv`), `/api/sessions/{id}/laps` (and
`.csv`), `/api/sessions/{id}/kpis`, `GET` and `POST /api/races`,
`GET /api/races/{id}`, `POST /api/races/{id}/finish`,
`GET /api/races/{id}/results.csv`.
WebSockets: `/ws/car` (vehicles), `/ws/ui` (operator UIs).

Start and finish a race from the command line (the Live view does the same):

```bash
curl -X POST localhost:8000/api/races -H 'content-type: application/json' -d '{"name": "Heat 1", "laps": 5}'
curl -X POST localhost:8000/api/races/1/finish
```

## Run the simulator

Auto mode (onboard pure-pursuit autopilot, completes laps):

```bash
make sim ARGS="--mode auto --duration 20"
# or:
.venv/bin/python -m sim.car --mode auto --server ws://127.0.0.1:8000/ws/car
```

Manual mode (applies the last UI control; throttle decays to zero after 0.5 s
without a command):

```bash
.venv/bin/python -m sim.car --mode manual
```

Flags: `--server <ws-url>`, `--car-id <id>`, `--mode {auto,manual}`,
`--pace <f>` (autopilot speed factor, 0.2 to 1.15, so two simulated cars can
race), `--loss <p>` (telemetry drop probability, e.g. `--loss 0.01`, which
creates sequence gaps for the packet-loss KPI), `--sensor-fault <p>`
(probability that a frame carries one sensor with no reading, for the
sensor-error KPI), `--duration <seconds>` (0 = run until interrupted).

The simulator follows the contract's steering sign (negative = left),
acknowledges every command, and obeys `reset`.

## Tests

```bash
make test              # pytest (unit + WS integration)
```

79 tests. Covers the DB layer and the upgrade of a v1 database, KPI
computation, the lap tracker (full circuit required, interpolated crossing,
track limits, resets and jumps), track geometry, races, the REST API including
CSV, control clamping and acknowledgement, the simulator (laps, reset, steering
direction, IMU, sensor faults), and full WebSocket round-trips (fake car +
fake UI through a temp DB).

## Smoke test

```bash
make smoke             # runs scripts/smoke.sh
```

Creates the venv if missing, starts the server, runs the simulator in auto mode
for 15 s, then asserts via the REST API that a session exists with
`lap_count >= 1` and `telemetry_rows > 100`. Prints `PASS`/`FAIL` and cleans up.
Port 8000 already in use? `F163_SMOKE_PORT=8011 make smoke`.
