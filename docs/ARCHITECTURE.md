# Software Architecture Document

Project 2627-F-163 Autonomous RC Car Racing Platform, Software Engineering (SEN) lane.
Author and SEN lane owner: Ahmet Selim Fedakar. SEN lane members: Ahmet Selim Fedakar, Cuneytemir Ciftsuren.
Advisors: Serkan Simsek, Tarkan Aydin, Ercan Erturk.

This document describes the architecture of the F163 ground station (the `f163-ground-station` monorepo). It is scoped to the SEN lane and reads against `docs/CONTRACT.md` (the binding interface contract) and `docs/SRS.md`.

---

## 1. System context (whole F163 system)

The context diagram below shows the whole F163 platform and which parts belong to which department. The SEN lane owns only the ground station box.

```
                         F163 Autonomous RC Car Racing Platform

  +-------------------- MECHATRONICS lane ---------------------+
  |  RC car chassis, motors, steering servo                    |
  |  Sensors: IMU, GPS, wheel speed, battery monitor           |
  |  Wireless comm link (Wi-Fi or Bluetooth, decision pending) |
  +-----------------------------+------------------------------+
                                |  raw sensor / actuator signals
                                v
  +----------------------- CMP lane ---------------------------+
  |  Onboard computer (Raspberry Pi or Jetson)                 |
  |  Perception, planning, control, game-theoretic strategy    |
  |  Produces telemetry, consumes control (in manual mode)     |
  +-----------------------------+------------------------------+
                                |  WebSocket /ws/car  (contract sec. 2, 3)
                                |  JSON frames over the comm link / LAN
                                v
  +----------------------- SEN lane (this document) -----------+
  |                     GROUND STATION                          |
  |   FastAPI server  <--->  SQLite DB (data/f163.db)           |
  |        ^   ^                                                |
  |  /ws/ui|   | REST /api/*                                    |
  |        v   v                                                |
  |   Web UI: Drive panel / Live view / Dashboard               |
  |   (responsive; phone-capable for fall demo)                 |
  |                                                             |
  |   Car Simulator (stands in for the real car until the       |
  |   mechatronics cars exist; connects on /ws/car)             |
  +------------------------------------------------------------+

Users: Operator/Driver, Race Engineer, Team Analyst (browser clients on /ws/ui and /api/*)
```

In fall, the Simulator box occupies the same contract position as the CMP onboard stack, so the ground station is exercised end to end with no hardware. In spring, the CMP onboard stack (over the mechatronics comm link) replaces the simulator with no server or UI change.

---

## 2. Ground station component view

```
                          GROUND STATION (f163-ground-station)

  server/app/                                        web/ (React + TypeScript + Vite)
  +-------------------------------------+            +-----------------------------------+
  |  main.py        FastAPI app + routes |            |  Drive panel view                 |
  |  ws_car         /ws/car handler      |            |   - car select, throttle/steer    |
  |  ws_ui          /ws/ui handler       |            |   - latency readout (ping/pong)   |
  |  hub            in-memory fan-out,    |<--/ws/ui-->|  Live telemetry view              |
  |                 car + UI registries   |            |   - per-car gauges, connection    |
  |  ingest         telemetry batching     |            |  Dashboard view                   |
  |  storage        SQLite gateway        |            |   - session list, KPIs, charts    |
  |                 (isolated boundary)   |<--REST---->|   - lap table                     |
  |  kpis           KPI computation       |            +-----------------------------------+
  |  api            REST /api/* handlers  |
  +----------------+--------------------+
                   |  /ws/car
                   v
  sim/car.py  (Simulator)
  +-------------------------------------+
  |  kinematic bicycle model, 20 Hz     |
  |  pure-pursuit follower (auto mode)   |
  |  manual mode: applies last control, |
  |  0.5 s safety decay to zero throttle|
  |  noise injection, --loss packet drop |
  +-------------------------------------+
```

Module responsibilities:

- `main.py`: builds the FastAPI app, mounts WS and REST routes, creates the DB on startup.
- `ws_car`: validates `hello`, issues `hello_ack` with a new `session_id`, routes `telemetry` and `lap` to ingest and to the hub, delivers forwarded `control` to the car in manual mode.
- `ws_ui`: handles UI `hello`, replies with `state`, accepts UI `control`, answers `ping` with `pong`, subscribes the UI to hub broadcasts.
- `hub`: the only shared mutable state; registries of connected cars and UIs, verbatim fan-out of telemetry and lap frames, connect and disconnect broadcasts.
- `ingest`: flattens telemetry to table columns, tracks `seq` per session for gap counting, batches inserts (50 rows or 1 s).
- `storage`: the single SQLite boundary (open, schema create, insert, query). This boundary exists so the database can be swapped in spring (NFR-10).
- `kpis`: pure functions over stored rows producing the KPI schema.
- `api`: REST read endpoints.
- `sim/car.py`: the standalone simulator process, a WebSocket client of `/ws/car`.

---

## 3. Data flow

### 3.1 One control command (operator drives a car)

Numbered steps with a per-hop latency budget. Total budget 100 ms at p95 on LAN (NFR-1). Figures are LAN targets, not loopback.

| Step | Action | Budget |
|---|---|---|
| 1 | Operator moves the control; UI builds `control` with client `ts` (FR-3). | <= 5 ms |
| 2 | UI sends the frame over `/ws/ui` to the server. | <= 20 ms |
| 3 | `ws_ui` clamps ranges (FR-17), looks up the target car in the hub. | <= 5 ms |
| 4 | Server forwards `control` over `/ws/car` to the car (or simulator). | <= 20 ms |
| 5 | Car applies actuation; simulator records it; next telemetry echoes applied `steering`/`throttle`. | <= 20 ms |
| 6 | (Async, off the control path) server appends to `control_log`. | not on path |
| | Headline figure is the `ping`/`pong` RTT on a single clock (NFR-9). | <= 100 ms p95 |

### 3.2 One telemetry sample (car to dashboard and live view)

| Step | Action | Budget |
|---|---|---|
| 1 | Car (or simulator) emits `telemetry` at 20 Hz with monotonic `seq` (contract sec. 2). | 50 ms tick |
| 2 | Frame arrives at `ws_car`. | <= 20 ms |
| 3 | `ingest` flattens the frame, updates the per-session `seq` gap counter (FR-14). | <= 2 ms |
| 4 | Hub fans the frame out verbatim to all connected UIs (FR-16); live view updates. | <= 20 ms |
| 5 | `ingest` enqueues the row; batched flush at 50 rows or 1 s (FR-12). | <= 1 s to disk |
| 6 | Later, dashboard reads via REST; `kpis` and charts computed from stored rows. | see NFR-4, NFR-5 |

Live fan-out (step 4) is independent of persistence (step 5), so the live view stays real-time even while inserts batch.

---

## 4. Technology choices and rationale

Each choice lists the decision, why it is right at this scale, the main alternative considered, the honest tradeoff, and the spring swap path.

### 4.1 Server framework: FastAPI (chosen) vs Node.js/Express

- Decision: FastAPI on uvicorn.
- Why: native async WebSocket and HTTP in one process, Python matches the team's and CMP's language, and it keeps the server, the simulator, and any future glue to the onboard stack in one toolchain. Pydantic gives schema validation that maps directly onto the contract.
- Alternative: Node.js with `ws` and Express. Strong at many sockets, but it would split the codebase across two languages and duplicate the contract types.
- Tradeoff: Python async throughput is lower than Node at very high connection counts, which is irrelevant at two cars and a handful of UIs.
- Spring swap: not expected. If connection counts grow by an order of magnitude, the hub is the only hot path and is already isolated.

### 4.2 Storage: SQLite (chosen) vs TimescaleDB / InfluxDB

- Decision: SQLite file at `data/f163.db`, inserts batched, one composite index `idx_telemetry_session_t`.
- Why: at 20 Hz x 2 cars (40 rows/s, about 24k rows per 10-minute run) SQLite is comfortably within range for both ingest and the dashboard queries, with zero operational setup, which matters for a demo laptop and for reproducibility (NFR-11). A time-series database solves a problem this scale does not have.
- Alternatives: TimescaleDB (Postgres extension, hypertables, continuous aggregates) or InfluxDB (purpose-built TSDB). Both add a server process, a connection, and ops burden; InfluxDB would also impose a different query model.
- Tradeoff: SQLite has a single writer and no built-in downsampling or retention. At this scale the single writer is a non-issue because inserts are batched through one `ingest` path; downsampling is unnecessary for 10-minute sessions.
- Spring swap: the `storage` module is a single boundary (NFR-10). If spring runs long multi-car sessions or wants continuous aggregates, swapping to TimescaleDB means reimplementing that one module; handlers, KPIs, and UI are untouched because they depend on the contract, not the database.

### 4.3 Transport: WebSocket (chosen) vs raw UDP vs MQTT

- Decision: WebSocket JSON text frames for both `/ws/car` and `/ws/ui`.
- Why: one transport serves both the car link and the browser link, which no other option does (browsers cannot speak raw UDP or MQTT without a broker and a bridge). JSON frames are directly inspectable, match the contract verbatim, and keep debugging cheap during integration. TCP ordering under WebSocket gives the monotonic `seq` stream the packet-loss KPI relies on.
- Alternatives: raw UDP (lowest latency, lossy, no browser support, would need a separate UI transport); MQTT (clean publish/subscribe, good for many cars, but adds a broker and a second protocol and still needs a browser bridge).
- Tradeoff: WebSocket over TCP can suffer head-of-line blocking under heavy loss, and JSON is heavier than a binary frame. At 20 Hz with small frames on a LAN this is immaterial; the loss the KPI measures is the link's, injected by the simulator's `--loss`.
- Spring swap: if the real comm link is high-loss (long-range RF) and control latency suffers, the car-side bridge can switch the car-to-bridge hop to UDP while still presenting WebSocket to the server. The UI transport stays WebSocket regardless. MQTT becomes worth revisiting only if the car count grows well beyond the two-car demo.

---

## 5. Deployment view

### 5.1 Fall (everything on one laptop plus simulator)

```
                     Demo laptop
  +-----------------------------------------------+
  |  uvicorn: FastAPI server  127.0.0.1:8000       |
  |     /ws/car   /ws/ui   /api/*                   |
  |  SQLite file data/f163.db                       |
  |                                                 |
  |  sim/car.py  (one process per car)  --> /ws/car |
  |  Browser (Chrome): Drive / Live / Dashboard     |
  +-----------------------------------------------+
  Optional: a second device (phone) on the same LAN
  points its browser at the laptop's LAN IP:8000.
```

Bring-up: `make server`, then `make sim ARGS="--car-id car-1 --mode manual"` (and a second instance for `car-2`), then the web dev server. Schema is created on first run (NFR-11).

### 5.2 Spring (trackside laptop plus real car over RF)

```
   Trackside laptop                         RC car (Mechatronics + CMP)
  +---------------------------+            +------------------------------+
  |  FastAPI server            |            |  Onboard computer (Pi/Jetson)|
  |  SQLite (or swapped DB)     |<--/ws/car--|  CMP onboard stack           |
  |  Dashboard served to clients|  over the  |  (perception/planning/ctrl)  |
  +------------+--------------+   comm link  |  + car-side bridge if the    |
               | /ws/ui                      |    link is not IP-capable    |
               v                             +------------------------------+
   Operator / engineer browsers on the trackside LAN
```

The simulator is removed; the car (via the onboard stack, possibly through a bridge) takes its contract position. No server or UI change is required if the car honors the contract.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Wi-Fi latency jitter | p95 control latency breaches 100 ms under a congested 2.4 GHz band at the track. | Measure early (latency report milestone, `docs/PLAN.md`); prefer 5 GHz or a dedicated AP; keep frames small; the `ping`/`pong` readout surfaces jitter live so the operator sees degradation (NFR-7, NFR-8). |
| Bluetooth vs Wi-Fi decision pending (mechatronics) | Link choice sets the real latency and jitter budget; BT has lower throughput and may not carry 20 Hz x 2 cars comfortably. | Architecture is link-agnostic above the socket; if BT is chosen, a car-side bridge terminates BT and speaks WebSocket. Flagged for the advisor meeting (`docs/ADVISOR-NOTE-2026-11.md`). |
| Packet loss on the real link | Missing telemetry inflates the sensor-error-rate KPI and can starve the live view. | `seq` gap counting already models this; the simulator reproduces it with `--loss`; the KPI reports `packet_loss_pct` honestly rather than hiding gaps; UI shows stale-link state within 1 s. |
| Clock sync between car and server | Cross-machine timestamp diffs are not a reliable latency metric; clocks may drift. | Headline latency uses single-clock `ping`/`pong` RTT (NFR-9); stored `t` is used for ordering and KPIs, not for cross-machine latency. If needed in spring, record a per-session clock offset at `hello` using `server_time` in `hello_ack`. |
| Hardware not ready by demo | No real car to drive at the fall demo. | The simulator is the planned stand-in for fall; the contract guarantees the swap path, so the SEN deliverables are demonstrable without hardware. |
| Contract drift across lanes | A unilateral change breaks integration silently. | The contract requires a version bump on change; all lanes build against it; integration tests verify it (NFR-12). |
