# F163 Ground Station — Server & Simulator

Python backend for Project 2627-F-163 (Autonomous RC Car Racing Platform,
software lane). It ingests vehicle telemetry over WebSocket, relays operator
control to cars, broadcasts live data to web UIs, stores everything in SQLite,
and exposes a REST dashboard API. A companion simulator produces realistic
telemetry for development and demos.

All interfaces follow `docs/CONTRACT.md` (v1) exactly.

## Layout

```
server/app/      FastAPI server
  main.py          app factory + WS routes + lifespan (DB start/stop)
  ws_car.py        /ws/car handler (hello, telemetry, lap)
  ws_ui.py         /ws/ui handler (state, control relay, ping/pong)
  api.py           REST /api/* endpoints
  db.py            SQLite storage layer (single batched writer task + KPIs)
  state.py         in-memory car/UI registry + broadcast + control clamping
sim/             car simulator
  car.py           kinematic bicycle model, pure-pursuit, telemetry emitter
  track.py         closed stadium/oval centerline + pure-pursuit helpers
tests/           pytest suite (DB, KPIs, control clamp, WS integration)
scripts/smoke.sh end-to-end smoke test
```

The database file is created at `data/f163.db` (directory auto-created). Set
`F163_DB_PATH` to override the path.

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

Endpoints: `GET /api/health`, `/api/sessions`, `/api/sessions/{id}/telemetry`,
`/api/sessions/{id}/laps`, `/api/sessions/{id}/kpis`.
WebSockets: `/ws/car` (vehicles), `/ws/ui` (operator UIs).

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
`--loss <p>` (telemetry drop probability, e.g. `--loss 0.01`, which creates
sequence gaps for the packet-loss KPI), `--duration <seconds>` (0 = run until
interrupted).

## Tests

```bash
make test              # pytest (unit + WS integration)
```

Covers the DB layer, exact KPI computation (including `seq_gaps` and
`packet_loss_pct`), control clamping, and a full WebSocket round-trip
(fake car + fake UI through a temp DB).

## Smoke test

```bash
make smoke             # runs scripts/smoke.sh
```

Creates the venv if missing, starts the server, runs the simulator in auto mode
for 10 s, then asserts via the REST API that a session exists with
`lap_count >= 1` and `telemetry_rows > 100`. Prints `PASS`/`FAIL` and cleans up.
