# Progress Note, SEN Lane, November 2026

Project: 2627-F-163 Autonomous RC Car Racing Platform
Course: SEN4991 Capstone Project I, Fall 2026-2027, Bahcesehir University
Advisors: Serkan Simsek, Tarkan Aydin, Ercan Erturk
Prepared by: Ahmet Selim Fedakar (SEN lane owner), on behalf of the SEN lane (Ahmet Selim Fedakar, Cuneytemir Ciftsuren)
Date: 2026-11-14

---

## What the SEN lane has built

Working from the official department split (SEN owns the ground station: drive UI, telemetry pipeline, post-race dashboard), we have built and tested a complete ground station end to end against a simulator, ahead of any hardware being available.

- Contract-first design. We froze a single interface contract (`docs/CONTRACT.md`) that defines every message between the car, the server, and the UI. All components are built and tested against it, so the mechatronics car and the CMP onboard stack can plug in later without changing our code.
- Server. FastAPI service with a vehicle WebSocket (`/ws/car`), an operator WebSocket (`/ws/ui`), telemetry ingestion into SQLite, control relay, and a REST API that computes the required KPIs (lap times, max and average speed, min battery, packet-loss rate).
- Simulator. A physics-based car (kinematic bicycle model, pure-pursuit racing-line follower) that stands in for the real car. It emits 20 Hz telemetry with realistic noise, completes laps in auto mode, applies operator commands in manual mode with a safety decay, and can inject packet loss to exercise the error-rate KPI.
- Web UI. React and TypeScript client with a drive panel (low-latency throttle and steering, live latency readout), a live telemetry view, and a post-race dashboard (KPIs, lap table, speed and battery charts). Responsive layout covers phone use for the fall demo; the native app is deferred to spring.

In short, the software lane is already demonstrable: we can connect cars, drive them, ingest telemetry, and review a race on the dashboard, all without waiting for hardware.

## What we need from the advisors

(a) The official Capstone I deliverable list and deadlines. We need the required documents (SRS, design report, anything else), the submission format and venue, and the demo date so we can lock milestones M4 and M5 in our plan.

(b) Confirmation of the department-based work split announced 2026-10-30 (Mechatronics builds the cars and comm link; CMP owns the onboard computer, planning, control, and strategy; SEN owns the ground station). We have scoped our work to this and want it confirmed so there is no overlap or gap.

(c) Hardware inventory status, and the Wi-Fi versus Bluetooth decision for the comm link. Our architecture is link-agnostic above the socket, but the link choice sets our latency and jitter budget and decides whether a car-side bridge is needed. Knowing what hardware exists today also sets expectations for what is simulator-only in fall versus real in spring.

(d) Preferred meeting cadence and the primary point of contact among the three advisors. We propose a weekly sync with a short written progress note before each meeting.

## Next two weeks (SEN lane)

- Week of 2026-11-17: verify two simulated cars with independent sessions; add a latency and throughput measurement harness; confirm 20 Hz x 2-car ingest with zero server-side loss.
- Week of 2026-11-24: run the 10-minute sustained two-car test; produce a short latency report (p50 and p95 on loopback and on a LAN with a phone as a second client); complete the 390 px responsive pass on the drive panel and dashboard.
- Dependency starting 2026-12-01: a runnable CMP onboard-stack build that speaks `/ws/car` so we can do the first cross-lane integration test over the contract.

We are not blocked for the next two weeks; both measurement milestones run entirely on the simulator. Our first hard cross-lane dependency is the CMP onboard stack for integration in early December.
