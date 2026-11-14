# F163 Ground Station

The Software Engineering lane of BAU SEN4991 Capstone Project I, project 2627-F-163
"Autonomous RC Car Racing Platform". This repository is the ground station: the
operator drive UI, the telemetry ingestion pipeline, and the post-race analytics
dashboard. The RC cars that would feed it do not exist yet (Mechatronics is still
building them), so a physics-based simulator stands in and speaks the exact same
wire contract a real car will. Nothing above the socket knows the difference, which
is the whole point.

Clone it, run three commands, and you are driving a (simulated) car in a browser in
about two minutes. See [Quickstart](#quickstart).

## Where this fits in F163

F163 is built by three departments. This repository is only the middle-and-right of
the picture below. The boundary marked `[ THIS REPO ]` is everything the SEN lane
owns; everything outside it is another lane's deliverable that we integrate with
over `docs/CONTRACT.md`.

```
                 F163 AUTONOMOUS RC CAR RACING PLATFORM

  +------------------------- MECHATRONICS ------------------------+
  |  RC car chassis, motors, steering servo                       |
  |  Sensors: IMU, GPS, wheel speed, battery monitor              |
  |  Wireless comm link (Wi-Fi or Bluetooth, decision pending)    |
  +------------------------------+--------------------------------+
                                 |  raw sensor / actuator signals
                                 v
  +--------------------------- CMP ENG ---------------------------+
  |  Onboard computer (Raspberry Pi or Jetson)                    |
  |  Perception, planning, control, game-theoretic strategy       |
  |  Produces telemetry, consumes control (manual mode)           |
  +------------------------------+--------------------------------+
                                 |  WebSocket /ws/car  (JSON frames)
                                 |  the binding contract: docs/CONTRACT.md
  . . . . . . . . . . . . . . . .v. . . . . . . . . . . . . . . . . .
  :                       [ THIS REPO ]  SOFTWARE ENG               :
  :                          GROUND STATION                         :
  :                                                                 :
  :     FastAPI server  <-------->  SQLite DB (data/f163.db)        :
  :         ^    ^                                                  :
  :  /ws/ui |    | REST /api/*                                      :
  :         v    v                                                  :
  :     Web UI:  Drive  |  Live telemetry  |  Dashboard             :
  :              (responsive, phone-capable for the demo)           :
  :                                                                 :
  :     Car Simulator  ---> /ws/car   (stands in for the real car   :
  :                                    until Mechatronics ships it) :
  : . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . :

  In fall the Simulator occupies the real car's contract position, so the
  ground station runs end to end with zero hardware. In spring the CMP
  onboard stack replaces the simulator on /ws/car with no server or UI change.
```

## Team

| Department | People |
|---|---|
| Software Engineering (this repo) | Ahmet Selim Fedakar, Cuneytemir Ciftsuren |
| Computer Engineering | Mithatcan Temizkan |
| Mechatronics Engineering | TBD (roster being finalized) |
| Advisors | Serkan Simsek, Tarkan Aydin, Ercan Erturk |

## What works today

Built and tested end to end against the simulator (no hardware required):

- [x] FastAPI server: `/ws/car` (vehicles), `/ws/ui` (operator UIs), REST `/api/*`,
      SQLite persistence, and KPI computation, all built against `docs/CONTRACT.md` v1.
- [x] Car simulator: kinematic bicycle model at 20 Hz on a closed oval track, with a
      pure-pursuit autopilot (`--mode auto`) that drives real laps, a manual mode that
      applies the last operator command with a 0.5 s safety decay to zero throttle,
      sensor noise injection, and `--loss` packet dropping to exercise the loss KPI.
- [x] Web UI, three views (React + TypeScript + Vite): Drive (keyboard and touch
      control with a live latency badge and auto-reconnect), Live (rolling ~60 s
      charts and a lap ticker), Dashboard (session list, KPI cards, lap-time and
      speed/battery charts over REST).
- [x] Test suite: 19 tests (`make test`) covering the DB layer, exact KPI math
      including `seq_gaps` and `packet_loss_pct`, control clamping, and a full
      WebSocket round-trip with a fake car and a fake UI, plus an end-to-end smoke
      script (`make smoke`) that boots the server, runs the autopilot for 10 s, and
      asserts a real session landed in the database.

## What's next

- [ ] Multi-car run: two simulated cars with independent sessions and sequence counters.
- [ ] Latency report: p50 and p95 control latency on loopback and on a LAN with a phone
      as a second client, measured through `ping`/`pong` RTT.
- [ ] Integration with the CMP onboard stack over `/ws/car` (the first hard cross-lane
      dependency; see `docs/PLAN.md` milestone M3).
- [ ] Real hardware link once Mechatronics ships cars and the Wi-Fi vs Bluetooth comm
      decision is made.
- [ ] Responsive pass at 390 px for the phone demo.

## Quickstart

Requires Python 3.10+ and Node 20+.

Backend (server + simulator + tests), from the repository root:

```bash
make install                              # create .venv, install pinned requirements
make server                               # uvicorn on http://127.0.0.1:8000
```

In a second terminal, drive a car with the autopilot:

```bash
make sim ARGS="--mode auto --duration 20" # pure-pursuit, completes laps
```

Run the tests and the end-to-end smoke check:

```bash
make test                                 # 19-test pytest suite
make smoke                                # boot server + autopilot, assert via REST
```

Web UI (start the backend first; the dev server proxies `/api` and `/ws` to port 8000):

```bash
cd web
npm install
npm run dev                               # open the printed URL (default http://localhost:5173)
```

No backend handy? Run the UI standalone with a built-in fake telemetry generator:

```
http://localhost:5173/?mock=1
```

Useful simulator flags: `--car-id <id>`, `--mode {auto,manual}`, `--loss <p>` (telemetry
drop probability, for example `--loss 0.01`, which opens `seq` gaps for the packet-loss
KPI), `--duration <seconds>` (0 runs until interrupted). Manual mode applies the last
control received over `/ws/ui` and decays throttle to zero after 0.5 s of silence.

## Architecture

The ground-station internals:

```
                      GROUND STATION (this repo)

  sim/car.py ---/ws/car---> server/app/ <---/ws/ui---> web/ (React + TS + Vite)
  (or real car)             +----------------+          +----------------------+
                            | ws_car  ingest |          | DriveView   control  |
                            | ws_ui   state  |          | LiveView    charts   |
                            | api     db     |          | DashboardView  KPIs  |
                            +--------+-------+          +----------------------+
                                     |  REST /api/*            ^
                                     v                         | reads
                             SQLite data/f163.db  -------------+
                             sessions / telemetry / laps / control_log
```

The server fans every telemetry and lap frame out to all connected UIs verbatim
(`state`), relays clamped operator `control` to the target car, batches telemetry
into SQLite (50 rows or 1 s), and computes KPIs on demand over REST. The simulator is
just a WebSocket client of `/ws/car`, so a real car takes its place by honoring the
same frames.

`docs/CONTRACT.md` is the single source of truth for every frame, endpoint, and table
in this picture. All three components (simulator, server, UI) are built against it;
the contract is law, and changing it requires a version bump agreed across lanes. For
the deeper picture, see `docs/SRS.md` (requirements), `docs/ARCHITECTURE.md`
(component and data-flow design, technology rationale, risks), and `docs/PLAN.md`
(semester milestones and cross-lane dependencies).

## Repository layout

```
f163-ground-station/
  docs/
    CONTRACT.md              binding interface contract v1 (frames, REST, schema)
    SRS.md                   software requirements specification
    ARCHITECTURE.md          architecture document
    PLAN.md                  fall-semester milestone plan
    ADVISOR-NOTE-2026-11.md  open questions for the advisor meeting
  server/
    app/
      main.py                FastAPI app factory + WS routes + DB lifespan
      ws_car.py              /ws/car handler (hello, telemetry, lap)
      ws_ui.py               /ws/ui handler (state, control relay, ping/pong)
      api.py                 REST /api/* endpoints
      db.py                  SQLite storage layer + KPI computation
      state.py               in-memory car/UI registry + broadcast + clamping
    README.md                server and simulator usage
  sim/
    car.py                   kinematic bicycle simulator, pure-pursuit, emitter
    track.py                 closed stadium/oval centerline + pursuit helpers
  tests/                     pytest suite (DB, KPIs, control clamp, WS round-trip)
  scripts/smoke.sh           end-to-end smoke test
  web/                       React + TypeScript + Vite UI (Drive / Live / Dashboard)
  Makefile                   install / server / sim / test / smoke
  requirements.txt           pinned Python dependencies
  conftest.py                pytest path setup
```
