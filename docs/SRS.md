# Software Requirements Specification (SRS)

Project 2627-F-163 Autonomous RC Car Racing Platform, Software Engineering (SEN) lane.

Course: SEN4991 Capstone Project I, Fall 2026-2027, Bahcesehir University.
Advisors: Serkan Simsek, Tarkan Aydin, Ercan Erturk.
SEN lane author and owner: Ahmet Selim Fedakar. SEN lane members: Ahmet Selim Fedakar, Cuneytemir Ciftsuren.

This specification is IEEE-830 inspired and deliberately pragmatic for a capstone scope. It covers only the Software Engineering lane (the ground station). It does not restate the mechatronics or computer engineering requirements except where they are interfaces this lane depends on.

---

## 1. Introduction

### 1.1 Purpose

This SRS defines the requirements for the F163 ground station, the software system owned by the SEN lane. The ground station provides three deliverables agreed in the official department-based work split announced 2026-10-30:

1. A web and mobile user interface that sends low-latency steering and throttle commands to a car over a wireless link.
2. A real-time data-ingestion pipeline that captures sensor telemetry (IMU, GPS, speed, battery voltage) into a database.
3. A post-race analysis dashboard that computes and displays key performance indicators (lap times, max speed, sensor error rates).

The requirements here are testable and traceable to the binding interface contract in `docs/CONTRACT.md` (referred to below as "the contract").

### 1.2 Scope

The software product is a monorepo named `f163-ground-station` containing:

- A FastAPI server that accepts vehicle and UI WebSocket connections, relays control commands, ingests telemetry into SQLite, and serves a REST API for post-race reads.
- A physics-based car simulator (kinematic bicycle model with a pure-pursuit autopilot) that stands in for real hardware until the mechatronics cars exist.
- A React and TypeScript web client with three views: a drive panel, a live telemetry view, and a post-race dashboard. Responsive layout covers phone use for the fall demo.

Out of scope for this lane (per the work split): the RC car hardware, sensor and actuator integration, the physical communication radio, the onboard computer (Raspberry Pi or Jetson) software, the autonomous planning and control algorithms, and the game-theoretic racing strategy. Those belong to the Mechatronics and Computer Engineering (CMP) lanes. The ground station treats the car, whether real or simulated, as a WebSocket peer that obeys the contract.

Out of scope for v1 (per contract section 7): authentication, multi-server deployment, a native mobile application (deferred to spring), and a non-SQLite database.

### 1.3 Definitions, acronyms, abbreviations

| Term | Meaning |
|---|---|
| Ground station | The SEN lane software system: server, simulator, and web UI. |
| Car / vehicle | A WebSocket peer on `/ws/car`, either the simulator (fall) or a real RC car bridge (spring). |
| Onboard stack | The CMP lane software running on the car's Raspberry Pi or Jetson (perception, planning, control). |
| Comm link | The mechatronics wireless link (Wi-Fi or Bluetooth, decision pending) carrying frames between car and ground station. |
| Telemetry | A 20 Hz per-car sensor sample as defined in contract section 2. |
| Control command | A throttle and steering actuation message as defined in contract section 3. |
| Session | One car connection, one row in the `sessions` table, created on `hello`. |
| KPI | Key performance indicator computed over a session (contract section 4). |
| seq | Per-session monotonic sequence integer used to detect packet loss. |
| Operator / driver | User who manually drives a car from the UI. |
| Race engineer | User who monitors live telemetry and connection health during a run. |
| Team analyst | User who reviews completed sessions on the dashboard. |
| LAN | Local area network; the fall demo runs on one laptop or a local switch. |
| WS | WebSocket. |
| RTT | Round-trip time. |

### 1.4 References

- `docs/CONTRACT.md`, F163 Ground Station Interface Contract v1. The binding source of truth for all interfaces.
- `docs/ARCHITECTURE.md`, software architecture document for this lane.
- `docs/PLAN.md`, fall milestone plan.
- `F163-KICKOFF-BRIEF-2026-10-30.md`, team kickoff brief. Its three-pillar role assumption is superseded by the official department-based work split.
- IEEE Std 830-1998, Recommended Practice for Software Requirements Specifications (structure reference only).

---

## 2. Overall Description

### 2.1 Product perspective within the three-department system

F163 is built by three lanes. The ground station is one node in a larger system and depends on the other two lanes through narrow, explicit interfaces.

```
Mechatronics lane            CMP lane                     SEN lane (this SRS)
-----------------            --------                     -------------------
RC car chassis       -->     Onboard computer      -->    Ground station server
sensors + actuators          perception + planning        telemetry ingestion + DB
comm link (Wi-Fi/BT)         control + strategy           drive UI + dashboard
```

The ground station does not assume anything about how the car produces telemetry or consumes control, only that both conform to the contract. In fall, the simulator plays the role of the car so the SEN lane can be built and tested end to end before any hardware exists. In spring, a bridge process on the real car replaces the simulator with no change to the server or UI, because the contract is the interface.

### 2.2 User classes and characteristics

| User class | Description | Primary needs |
|---|---|---|
| Operator / driver | Drives a car manually from the UI during a run or demo. Low-latency, reliable control is the priority. | Drive panel, immediate command feedback, live latency readout, clear connection status. |
| Race engineer | Monitors one or more cars live during a run; watches telemetry health, battery, and packet loss. | Live telemetry view, per-car connection state, packet-loss indicator, multi-car display. |
| Team analyst | Reviews completed sessions after a run to evaluate performance. | Dashboard with KPIs, lap table, speed and battery time series, session list. |

A single person may hold more than one role during the fall demo. There is no login; the contract declares no auth for v1.

### 2.3 Interfaces to the CMP onboard stack and the mechatronics comm link

- Interface to the CMP onboard stack: WebSocket `/ws/car` as defined in contract sections 2 and 3. The onboard stack (or the simulator standing in for it) sends `hello`, `telemetry`, and `lap`; the ground station sends `control` and `hello_ack`. In `auto` mode the onboard stack ignores forwarded control. The ground station requires that `seq` is monotonic per session and that timestamps are Unix seconds UTC.
- Interface to the mechatronics comm link: the WebSocket transport runs over whatever IP-capable wireless link the mechatronics lane provides. The ground station is link-agnostic above the socket. The Wi-Fi versus Bluetooth decision (pending mechatronics) affects only latency and jitter budgets, not the message schema. If the final link is not IP-capable, a thin bridge on the car terminates the radio and speaks WebSocket to the server; that bridge is a shared integration task.

### 2.4 Constraints and assumptions

- Python 3.10, FastAPI 0.162.x, uvicorn 0.54.x, websockets 16.x, pytest 9.x (see `requirements.txt`).
- Server default bind `http://127.0.0.1:8000`; vehicle endpoint `/ws/car`, UI endpoint `/ws/ui`.
- Storage is SQLite at `data/f163.db`; the storage layer is isolated to allow a spring swap.
- Fall demo runs on a single laptop (server, simulator, and browser) or a small LAN.
- Assumption: two cars is the maximum concurrent count for the fall demo. Assumption to confirm with advisors: exact demo date and deliverable list (see `docs/PLAN.md`), marked TBD.

---

## 3. Specific Requirements

Each functional requirement is written to be testable and carries a trace to the contract (see the traceability table in section 3.4). Non-functional requirements carry measurable targets.

### 3.1 Functional requirements, Deliverable 1: Drive UI

FR-1. The UI shall open a WebSocket to `/ws/ui`, send `{"type":"hello","client":"web"}` on connect, and render the returned `state` message listing connected cars.

FR-2. The UI shall provide a drive panel that lets the operator select a target car by `car_id` from the connected set.

FR-3. The drive panel shall emit `control` messages with `throttle` in [-1.0, 1.0] and `steering` in [-1.0, 1.0], each including a client `ts` in Unix seconds, matching contract section 3.

FR-4. The drive panel shall support keyboard and on-screen touch controls so the same panel is usable on a desktop and on a phone touchscreen.

FR-5. The UI shall rate-limit outgoing `control` messages to at most 30 Hz, matching the contract's nominal control rate, and shall not send duplicate identical commands faster than that cap.

FR-6. The UI shall display live connection status per car (`connected` true or false) by consuming `car_connected` and `car_disconnected` broadcasts.

FR-7. The UI shall measure and display end-to-end control-path latency by sending `{"type":"ping","ts":...}` and rendering the RTT from the matching `pong`.

FR-8. The drive panel shall visually indicate when a selected car is in `auto` mode and shall communicate that manual commands are ignored by the car in that mode (per contract section 2, control is forwarded only in `manual` mode).

### 3.2 Functional requirements, Deliverable 2: Telemetry ingestion pipeline

FR-9. The server shall accept vehicle connections on `/ws/car`, require the first frame to be `hello`, and reply with `hello_ack` carrying a new `session_id` and `server_time`.

FR-10. The server shall create exactly one `sessions` row per car connection with `car_id`, `mode`, and `started_at`, and shall set `ended_at` on disconnect.

FR-11. The server shall accept `telemetry` frames at the nominal 20 Hz per car, flatten them into the `telemetry` table columns defined in contract section 5, and persist them.

FR-12. The server shall batch telemetry inserts, flushing every 50 rows or every 1 second, whichever comes first, as stated in the contract.

FR-13. The server shall persist `lap` frames into the `laps` table with `lap_number`, `lap_time_s`, and `t`.

FR-14. The server shall track `seq` per session and count gaps so the packet-loss and sensor-error-rate KPI can be computed.

FR-15. The server shall forward operator `control` messages received on `/ws/ui` to the addressed car immediately and record each into `control_log`.

FR-16. The server shall rebroadcast every `telemetry` and `lap` frame verbatim to all connected UIs, and shall emit `car_connected` and `car_disconnected` on state changes.

FR-17. The server shall clamp out-of-range `throttle` or `steering` values into [-1.0, 1.0] before forwarding, per contract section 3.

FR-18. The server shall support at least two cars connected concurrently, each with an independent session, sequence counter, and telemetry stream.

FR-19. The server shall answer `{"type":"ping","ts":...}` from a UI with `{"type":"pong","ts":<echo>,"server_time":...}`.

### 3.3 Functional requirements, Deliverable 3: Post-race dashboard

FR-20. The server shall expose `GET /api/health` returning `{"status":"ok"}`.

FR-21. The server shall expose `GET /api/sessions` returning sessions newest first with `id`, `car_id`, `started_at`, `ended_at`, and `mode`.

FR-22. The server shall expose `GET /api/sessions/{id}/telemetry` with `from_t`, `to_t`, and `limit` query parameters (default limit 5000), returning flattened telemetry rows ordered by `t`.

FR-23. The server shall expose `GET /api/sessions/{id}/laps` returning the lap list.

FR-24. The server shall expose `GET /api/sessions/{id}/kpis` computing `lap_count`, `best_lap_s`, `avg_lap_s`, `max_speed_mps`, `avg_speed_mps`, `min_battery_v`, `telemetry_rows`, `seq_gaps`, `packet_loss_pct`, and `duration_s`, matching the contract KPI schema.

FR-25. The dashboard view shall list available sessions and let the analyst open one.

FR-26. The dashboard shall display the KPI summary (lap times including best and average, max and average speed, min battery, and packet-loss percentage as the sensor-error-rate KPI).

FR-27. The dashboard shall render time-series charts of speed and battery voltage over a selected session.

FR-28. The dashboard shall render the lap table with lap number and lap time.

### 3.4 Requirements-to-contract traceability

| Requirement | Contract reference | What it binds to |
|---|---|---|
| FR-1, FR-6 | section 3 (`hello`, `state`, `car_connected`, `car_disconnected`) | UI connection and car state |
| FR-2, FR-3, FR-5 | section 3 (UI `control` schema and ranges) | Drive command format and rate |
| FR-4 | sections 3, 7 (responsive web covers phone) | Phone usability |
| FR-7, FR-19 | section 3 (`ping`, `pong`) | Latency display |
| FR-8 | section 2 (`mode`, control only in manual) | Auto-mode handling |
| FR-9, FR-10 | section 2 (`hello`, `hello_ack`); section 5 (`sessions`) | Session lifecycle |
| FR-11, FR-12 | section 2 (telemetry schema); section 5 (`telemetry` table, batching) | Telemetry persistence |
| FR-13 | section 2 (`lap`); section 5 (`laps` table) | Lap persistence |
| FR-14 | section 2 (`seq`); section 4 (`seq_gaps`, `packet_loss_pct`) | Packet-loss KPI source |
| FR-15, FR-17 | section 3 (control forwarding, clamp); section 5 (`control_log`) | Control relay and logging |
| FR-16 | section 3 (UI broadcasts) | Live fan-out |
| FR-18 | sections 1, 5 (20 Hz x 2 cars, per-session rows) | Multi-car |
| FR-20..FR-24 | section 4 (REST API) | Dashboard reads and KPIs |
| FR-25..FR-28 | section 4 (sessions, telemetry, laps, kpis) | Dashboard views |

### 3.5 Non-functional requirements (measurable)

NFR-1. Control-path latency. On a LAN (or single laptop loopback), end-to-end control latency from UI command send to car-side receipt shall be at most 100 ms at the 95th percentile, measured with the `ping`/`pong` path and timestamp diffs from `control_log`.

NFR-2. Telemetry throughput. The pipeline shall sustain 20 Hz per car for two cars (40 messages per second aggregate) for at least 10 minutes with zero persisted-row loss attributable to the server, verified by comparing received `seq` ranges against stored rows.

NFR-3. Ingestion-induced loss separation. Any missing `seq` must be attributable to the link or simulated `--loss`, not to server backpressure; under NFR-2 load, server-side drop shall be 0 rows.

NFR-4. Dashboard load time. Opening a 10-minute session (about 12000 telemetry rows per car) and rendering KPIs plus charts shall complete in under 3 seconds on the demo laptop.

NFR-5. KPI query latency. `GET /api/sessions/{id}/kpis` shall return in under 500 ms for a 10-minute session, aided by the `idx_telemetry_session_t` index.

NFR-6. Mobile usability. The UI shall be usable on a 390 px wide viewport (iPhone-class phone) with no horizontal scrolling and with touch targets at least 44 px, for the drive panel and the dashboard summary.

NFR-7. Control safety decay. When the car (or simulator) receives no `control` for more than 0.5 seconds, throttle shall decay to zero (enforced by the simulator per contract section 6; the UI must make the operator aware the link is stale within 1 second).

NFR-8. Reconnect resilience. On a dropped UI or car WebSocket, the affected client shall attempt reconnect, and the server shall emit the correct `car_connected` or `car_disconnected` broadcast within 2 seconds of the state change.

NFR-9. Clock handling. All timestamps are Unix seconds UTC per the contract; latency computations shall not assume synchronized clocks across machines and shall prefer single-clock RTT (`ping`/`pong`) for the headline latency figure (see the clock-sync risk in `docs/ARCHITECTURE.md`).

NFR-10. Portability of storage. The storage layer shall remain isolated behind a single module boundary so SQLite can be replaced in spring without changing the WebSocket handlers, the REST handlers, or the UI.

NFR-11. Startup simplicity. A developer shall bring up the full stack with the documented commands (`make server`, `make sim`, and the web dev server) with no manual DB bootstrap step; the schema is created on first run.

NFR-12. Test coverage of the contract. Automated tests (`make test`) shall cover the session lifecycle, telemetry persistence, KPI computation, control clamping, and the ping/pong path, so the contract is machine-verified.

---

## 4. Acceptance criteria for the end-of-fall demo

The fall demo passes when all of the following are observed live, using the simulator as the car (hardware substitution is a spring item):

A1. Two simulated cars connect to the server; the UI shows both as connected (FR-1, FR-6, FR-18).

A2. An operator drives at least one car manually from the drive panel, on both a desktop browser and a 390 px phone viewport, with visible, responsive command feedback (FR-2 to FR-5, NFR-6).

A3. The live latency readout shows at most 100 ms at the 95th percentile on the demo LAN during manual driving (FR-7, NFR-1).

A4. One car runs in `auto` mode following the racing line and completes laps; `lap` events appear live (FR-13, FR-16; simulator per contract section 6).

A5. Telemetry from both cars is ingested at 20 Hz for a continuous 10-minute run with zero server-side row loss (FR-11, FR-12, NFR-2, NFR-3).

A6. The dashboard opens the just-completed 10-minute session in under 3 seconds and shows correct KPIs, the lap table, and speed and battery charts (FR-20 to FR-28, NFR-4, NFR-5).

A7. With simulated packet loss enabled (`--loss`), the dashboard's sensor-error-rate KPI (`packet_loss_pct`) reflects the induced loss within a reasonable tolerance (FR-14, FR-24).

A8. `make test` passes, demonstrating contract-level coverage (NFR-12).

Items requiring advisor or cross-lane input before the demo is scheduled are tracked in `docs/PLAN.md` and marked TBD-pending-advisor.

---

Requirement counts: 28 functional requirements (FR-1 to FR-28), 12 non-functional requirements (NFR-1 to NFR-12).
