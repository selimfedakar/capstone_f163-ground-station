# Fall Semester Milestone Plan

Project 2627-F-163 Autonomous RC Car Racing Platform, Software Engineering (SEN) lane.
Author and SEN lane owner: Ahmet Selim Fedakar. SEN lane members: Ahmet Selim Fedakar, Cuneytemir Ciftsuren.
Advisors: Serkan Simsek, Tarkan Aydin, Ercan Erturk.

As of 2026-11-14. The semester effectively ends mid-January; Capstone I deliverables are likely due mid-December. Exact dates are marked TBD-pending-advisor and are unblocked by the item (a) request in `docs/ADVISOR-NOTE-2026-11.md`.

This plan covers only the SEN lane. It references `docs/SRS.md` (requirement IDs) and `docs/CONTRACT.md`.

---

## 1. Status as of 2026-11-14

Built and tested end to end against the simulator:

- Contract v1 (`docs/CONTRACT.md`) frozen as the single interface source of truth.
- FastAPI server: `/ws/car`, `/ws/ui`, REST `/api/*`, SQLite storage, KPI computation.
- Physics simulator (`sim/car.py`): kinematic bicycle, pure-pursuit auto mode, manual mode with 0.5 s safety decay, noise injection, `--loss`.
- React and TypeScript web UI: drive panel, live telemetry view, dashboard.
- SRS and architecture documents drafted.

Not yet done (this plan): formal multi-car run, latency measurement report, integration with CMP's onboard stack, responsive-phone pass against NFR-6, demo rehearsal.

---

## 2. Weekly milestones (SEN lane)

Week labels are concrete; calendar dates for M4 onward depend on the advisor-confirmed demo date (TBD).

### M1, week of 2026-11-17: Multi-car and measurement harness

- Verify two simulated cars connect with independent sessions and sequence counters (FR-18, acceptance A1).
- Add a latency measurement harness driving `ping`/`pong` and comparing `control_log` timestamps (supports NFR-1, NFR-9).
- Confirm telemetry persists at 20 Hz x 2 cars with zero server-side loss over a short run (FR-11, FR-12, NFR-2, NFR-3).
- Dependency: none (self-contained with the simulator).

### M2, week of 2026-11-24: Latency and throughput report

- Run the 10-minute two-car sustained test; record persisted-row counts against received `seq` ranges (NFR-2, NFR-3).
- Produce a short latency report: p50 and p95 control latency on loopback and on a LAN with a phone as the second client (NFR-1, NFR-6).
- Responsive pass: drive panel and dashboard summary usable at 390 px, 44 px touch targets, no horizontal scroll (NFR-6, acceptance A2).
- Dependency: a LAN and a second device (phone); no other lane required.

### M3, week of 2026-12-01: Contract integration with the CMP onboard stack

- Point the CMP onboard stack (or an early build of it) at `/ws/car` and confirm `hello`, `telemetry`, `lap`, and `control` conform to the contract.
- Run the server against the CMP stack with the simulator removed for at least one car; verify sessions, KPIs, and live fan-out behave identically (FR-9 to FR-16).
- Log any contract gaps; a change requires a version bump agreed by both lanes.
- Dependency (hard): CMP provides a runnable onboard stack build that speaks `/ws/car`. Mechatronics comm link not required for this step if the CMP stack runs on a laptop or Pi over the LAN.

### M4, TBD-pending-advisor (target early-to-mid December): Demo rehearsal 1

- Full acceptance pass A1 to A8 (`docs/SRS.md` section 4) against the simulator.
- Dry-run the demo script: connect two cars, manual drive on desktop and phone, auto laps, 10-minute ingest, open dashboard, show KPIs and charts, show loss KPI with `--loss`.
- Fix defects found; freeze features after this rehearsal.
- Dependency: advisor-confirmed demo date and deliverable list (item (a)).

### M5, TBD-pending-advisor (target mid-December): Final deliverables and demo

- Submit Capstone I documents (SRS, architecture, this plan, and any advisor-required report) in the required format and venue (TBD).
- Deliver the demo per acceptance criteria.
- Dependency: advisor-confirmed submission format, venue, and date.

---

## 3. Dependencies on the other two departments

| Needed from | What | Blocks | When needed |
|---|---|---|---|
| CMP | A runnable onboard-stack build that speaks `/ws/car` per contract | M3 integration | by week of 2026-12-01 |
| CMP | Confirmation that `auto` mode telemetry and `lap` events match the contract | M3 verification | week of 2026-12-01 |
| Mechatronics | Wi-Fi vs Bluetooth decision for the comm link | latency and jitter budget, bridge design | before spring; flagged now |
| Mechatronics | Whether the comm link is IP-capable (if not, a car-side bridge is a shared task) | spring deployment path | before spring |
| Advisors | Capstone I deliverable list, deadlines, demo date and venue | M4, M5 dates | ASAP (item (a)) |
| Advisors | Confirmation of the department-based work split | scope lock | ASAP (item (b)) |
| Advisors | Hardware inventory status | fall-vs-spring hardware expectation | ASAP (item (c)) |

The SEN lane is not blocked for M1 and M2; those run entirely on the simulator. The first hard cross-lane dependency is CMP at M3.

---

## 4. Definition of done for the fall demo

The fall demo is done when all are true:

1. Acceptance criteria A1 to A8 in `docs/SRS.md` section 4 pass live against the simulator.
2. `make test` passes, covering session lifecycle, telemetry persistence, KPI computation, control clamping, and ping/pong (NFR-12).
3. The latency report (M2) documents p95 control latency at or under 100 ms on the demo LAN (NFR-1).
4. The 10-minute two-car ingest shows zero server-side row loss (NFR-2, NFR-3).
5. The UI passes the 390 px responsive check (NFR-6).
6. At least one M3 integration run against the CMP onboard stack has succeeded over the contract, or, if CMP is not ready, the gap is documented with a dated follow-up (the simulator still satisfies the SEN deliverables for the demo).
7. Capstone I documents are submitted in the required format (deadline TBD-pending-advisor).
