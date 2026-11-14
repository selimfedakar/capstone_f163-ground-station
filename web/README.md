# F163 Ground Station — Web UI

Operator web UI for the F163 Autonomous RC Car Racing Platform (SEN4991).
Three views, all built against `docs/CONTRACT.md` (v1):

- **Drive** — low-latency control panel. Car selector, keyboard (`W`/`S` or
  arrows = throttle, `A`/`D` = steering, `Space` = brake/zero) and on-screen
  touch controls, live readouts (speed, battery with low-voltage warning,
  heading, applied throttle/steering), latency badge, auto-reconnect.
- **Live** — rolling ~60 s charts of speed, battery, and steering/throttle,
  plus a lap ticker fed by broadcast telemetry.
- **Dashboard** — post-race analysis over REST: session list, KPI cards,
  lap-time bar chart (best lap highlighted), speed/battery over time.

Stack: Vite + React + TypeScript + recharts. Node 20.

## Development

The UI talks to the ground-station server over relative URLs. The Vite dev
server proxies `/api` and `/ws` to `http://127.0.0.1:8000` (see
`vite.config.ts`), so start the backend first, then:

```bash
npm install
npm run dev
```

Open the printed URL (default http://localhost:5173).

### Mock mode (no backend)

If the WebSocket cannot connect and `?mock=1` is present in the URL, a built-in
fake telemetry generator runs so the UI can be demoed standalone:

```
http://localhost:5173/?mock=1
```

Mock mode produces sine-wave speed, a draining battery, and a lap every ~15 s.
Control commands are accepted but not actuated in mock mode.

## Build

```bash
npm run build     # tsc -b && vite build  -> dist/
npm run preview   # serve the production build locally
npm run lint      # oxlint
```

The production build in `dist/` is a static bundle; serve it behind any reverse
proxy that forwards `/api` and `/ws` to the ground-station server.

## Layout

```
src/
  lib/
    contract.ts        TypeScript types mirroring docs/CONTRACT.md
    ws.ts              Typed /ws/ui client (auto-reconnect, backoff <= 5 s)
    api.ts             Typed REST client (/api/*)
    mock.ts            Standalone fake telemetry generator (?mock=1)
    useConnection.ts   Shared connection state (cars, telemetry, laps, latency)
    useDriveControls.ts Keyboard + touch input, 30 Hz send with 100 ms heartbeat
    format.ts          Display formatting helpers
  components/
    StatusBar.tsx      Connection + latency badges
    TouchControls.tsx  On-screen throttle/steering sliders
  views/
    DriveView.tsx      Drive control panel
    LiveView.tsx       Real-time charts + lap ticker
    DashboardView.tsx  REST-based post-race dashboard
  App.tsx              Hash-router shell + top bar
```
