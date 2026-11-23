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

Eight students across three departments. This repo is owned by the Software
Engineering lane; everyone builds against the same interface contract.

| Member | Department | GitHub |
|---|---|---|
| Ahmet Selim Fedakar | Software Engineering | [@selimfedakar](https://github.com/selimfedakar) |
| Cuneytemir Ciftsuren | Software Engineering | TBA |
| Mithatcan Temizkan | Computer Engineering | TBA |
| TBA | TBA | TBA |
| TBA | TBA | TBA |
| TBA | TBA | TBA |
| TBA | TBA | TBA |
| TBA | TBA | TBA |

Rows marked TBA are filled in as teammates confirm their names, departments,
and GitHub handles (roster lives on the university capstone portal).

**Advisors:** Serkan Simsek, Tarkan Aydin, Ercan Erturk

## What works today

Built and tested end to end against the simulator (no hardware required):

- [x] FastAPI server: `/ws/car` (vehicles), `/ws/ui` (operator UIs), REST `/api/*`,
      SQLite persistence, and KPI computation, all built against `docs/CONTRACT.md`
      (v1.1, proposed; a v1 car still connects unmodified).
- [x] Server-side lap timing: laps are timed and validated from the positions a car
      reports (a full circuit is required, the crossing time is interpolated, a lap
      that leaves the track does not count toward best or average). A car's own lap
      report is kept as a cross-check.
- [x] Races: start one from the Live view, every connected car is put on the start
      line and timed from the same instant, the race ends at the lap target or when
      the operator finishes it, and the classification is stored.
- [x] Measured command latency: the car acknowledges each command, the server logs
      the round trip, and p50/p95 one-way latency is a KPI (requirement: p95 at or
      below 100 ms).
- [x] KPIs beyond v1: distance, average speed while moving, off-track time, hardest
      acceleration / braking / cornering from the IMU, data rate, longest silence,
      and a sensor error rate that is separate from packet loss.
- [x] CSV export of telemetry, laps and race results.
- [x] Car simulator: kinematic bicycle model at 20 Hz on a closed oval track, with a
      pure-pursuit autopilot (`--mode auto`) that drives real laps, a manual mode that
      applies the last operator command with a 0.5 s safety decay to zero throttle,
      IMU readings derived from the motion, command acknowledgement, `reset`, and
      fault injection (`--loss` drops packets, `--sensor-fault` blanks readings).
- [x] Web UI, three views (React + TypeScript + Vite): Drive (track map, hold-to-drive
      keys and levers, reset, live readouts including command delay and IMU), Live
      (all cars on the map, race control, timing table, rolling 60 s plots),
      Dashboard (session and race reports over REST, CSV downloads). Every value
      carries a "?" with a Turkish explanation of what it is and how it is computed.
- [x] Test suite: 79 tests (`make test`) covering the DB layer and v1 migration, KPI
      math, the lap tracker, track geometry, races, the REST API, control clamping,
      the simulator (laps, reset, steering direction, IMU), and full WebSocket
      round-trips with a fake car and a fake UI, plus an end-to-end smoke script
      (`make smoke`) that boots the server, runs the autopilot for 15 s, and asserts
      a real session with a timed lap landed in the database.

## What's next

- [ ] Cross-lane review of contract v1.1 with the CMP lane; the open points are listed
      in `docs/CONTRACT.md` section 9 (position accuracy, heading convention, the real
      track's survey, lap authority).
- [ ] Latency report on a LAN with a phone as a second client. The measurement exists
      (Dashboard, "Commands"); loopback gives about 3 ms, the real link is untested.
- [ ] Integration with the CMP onboard stack over `/ws/car` (the first hard cross-lane
      dependency; see `docs/PLAN.md` milestone M3).
- [ ] Real hardware link once Mechatronics ships cars and the Wi-Fi vs Bluetooth comm
      decision is made.
- [ ] A track file for the real track (`F163_TRACK`, contract section 4.1).
- [ ] Test the phone layout on a real phone; so far it has only been checked at phone
      width in a desktop browser.

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
make test                                 # 79-test pytest suite
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

Useful simulator flags: `--car-id <id>`, `--mode {auto,manual}`, `--pace <f>` (autopilot
speed factor, 0.2 to 1.15), `--loss <p>` (telemetry drop probability, for example
`--loss 0.01`, which opens `seq` gaps for the packet-loss KPI), `--sensor-fault <p>`
(probability that a frame carries a sensor with no reading, for the sensor-error KPI),
`--duration <seconds>` (0 runs until interrupted). Manual mode applies the last
control received over `/ws/ui` and decays throttle to zero after 0.5 s of silence.

A race between two simulated cars, one slower and with a flaky link:

```bash
make sim ARGS="--car-id car-1 --mode auto"
make sim ARGS="--car-id car-2 --mode auto --pace 0.9 --loss 0.01 --sensor-fault 0.01"
```

Then open the Live view and press Start race.

## Architecture

The ground-station internals:

```
                      GROUND STATION (this repo)

  sim/car.py ---/ws/car---> server/app/ <---/ws/ui---> web/ (React + TS + Vite)
  (or real car)             +----------------+          +----------------------+
                            | ws_car  ingest |          | DriveView   control  |
                            | ws_ui   state  |          | LiveView    race     |
                            | laps    race   |          | DashboardView  KPIs  |
                            | track   api db |          +----------------------+
                            +--------+-------+                 ^
                                     |  REST /api/*            | reads
                                     v                         |
                             SQLite data/f163.db  -------------+
                             sessions / telemetry / laps / control_log
                             races / race_entries
```

The server fans every telemetry frame out to all connected UIs verbatim, locates each
position on the track and times the laps itself (`laps`, `track`), relays clamped
operator `control` to the target car and measures its acknowledgement, runs races
(`race`), batches telemetry into SQLite (50 rows or 1 s), and computes KPIs on demand
over REST. The simulator is just a WebSocket client of `/ws/car`, so a real car takes
its place by honoring the same frames.

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
    CONTRACT.md              interface contract v1.1, proposed (frames, REST, schema, KPIs)
    SRS.md                   software requirements specification
    ARCHITECTURE.md          architecture document
    PLAN.md                  fall-semester milestone plan
    ADVISOR-NOTE-2026-11.md  open questions for the advisor meeting
  server/
    app/
      main.py                FastAPI app factory + WS routes + DB lifespan
      ws_car.py              /ws/car handler (hello, telemetry, lap, control_ack)
      ws_ui.py               /ws/ui handler (state, control relay, reset, ping/pong)
      api.py                 REST /api/* endpoints (sessions, KPIs, track, races, CSV)
      db.py                  SQLite storage layer + KPI computation + race results
      state.py               in-memory car/UI registry + broadcast + clamping
      track.py               track description: centreline, width, GPS anchor
      laps.py                lap timing and validation from reported positions
      race.py                race start, finish and membership
    README.md                server and simulator usage
  sim/
    car.py                   kinematic bicycle simulator, pure-pursuit, emitter
    track.py                 closed stadium/oval centerline + pursuit helpers
  tests/                     pytest suite (DB, KPIs, laps, track, races, API, simulator, WS)
  scripts/smoke.sh           end-to-end smoke test
  web/                       React + TypeScript + Vite UI (Drive / Live / Dashboard)
  Makefile                   install / server / sim / test / smoke
  requirements.txt           pinned Python dependencies
  conftest.py                pytest path setup
```
