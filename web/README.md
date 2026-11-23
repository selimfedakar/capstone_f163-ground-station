# F163 Ground Station — Web UI

Operator web UI for the F163 Autonomous RC Car Racing Platform (SEN4991).
Three views, all built against `docs/CONTRACT.md` (v1.1):

- **Drive** — one car, driven by hand. A top-down track map with the car on
  it, hold-to-drive controls (keys or on-screen levers), a power limit, a
  button that puts the car back on the start line, and the car's readouts:
  speed, battery, command delay, applied throttle and steering, forward and
  sideways acceleration, heading, turn rate, lap times, signal, packet number.
- **Live** — every connected car at once. The track map with all cars, race
  control (start a race with an optional lap target, finish it), the timing
  table (race position and gap while a race runs), laps as they finish, and
  six rolling 60-second plots.
- **Dashboard** — review after the run, over REST. Pick a session (one car,
  one connection) or a race (cars timed together). A session report groups
  the figures under laps, speed and distance, forces and battery, data link
  and sensors, and commands, with the line driven, lap times, and speed,
  acceleration and battery over time. A race report has the classification,
  the lines driven, and lap-time and speed comparisons. Both offer CSV
  downloads.

Every value has a "?" beside it that explains, in Turkish, what the value is
and how it is calculated. The texts live in `src/lib/glossary.ts`.

Stack: Vite + React + TypeScript, charts and the track map drawn on canvas
(no chart library). Node 20.

## Controls

Hold-to-drive, like an RC transmitter: the car is commanded only while a key
or lever is held, and everything returns to zero on release.

| Input | Does |
|---|---|
| `W` / `ArrowUp` | forward |
| `S` / `ArrowDown` | brake or reverse |
| `A` `D` / `ArrowLeft` `ArrowRight` | steer left, right |
| `Space` | cut throttle and steering |
| `1` `2` `3` | power limit 40 %, 70 %, 100 % |
| `R` | put the car back on the start line |
| Levers | drag (mouse or touch); they override the keys |

Commands are sent when a value changes and every 100 ms while non-zero, never
faster than 30 Hz. Losing focus or hiding the tab zeroes everything.

## Development

The UI talks to the ground-station server over relative URLs. The Vite dev
server proxies `/api` and `/ws` to `http://127.0.0.1:8000` (see
`vite.config.ts`), so start the backend first, then:

```bash
npm install
npm run dev
```

Open the printed URL (default http://localhost:5173).

The track drawn on the maps is whatever the server serves at `/api/track`, so
a real track needs no UI change (contract section 4.1).

### Mock mode (no backend)

If the WebSocket cannot connect and `?mock=1` is present in the URL, a built-in
fake telemetry generator runs so the UI can be demoed standalone:

```
http://localhost:5173/?mock=1
```

The mock car laps the simulator's stadium track. Control commands are accepted
but not actuated, and the Dashboard and race control need the real server.

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
    contract.ts         TypeScript types mirroring docs/CONTRACT.md
    ws.ts               Typed /ws/ui client (auto-reconnect, backoff <= 5 s)
    api.ts              Typed REST client (/api/*), CSV links, race start/finish
    useConnection.ts    Shared connection state: cars, live store, laps, race,
                        server delay, command delay
    useDriveControls.ts Hold-to-drive keyboard + lever input, 30 Hz send
    track.ts            Track geometry from the server's description, GPS <-> metres
    trackContext.ts     The current track, for the map components
    glossary.ts         Turkish explanation for every value
    axes.ts             Plot ranges and time axes
    format.ts           Display formatting helpers
    theme.ts            Colours shared with the canvas drawings
    mock.ts             Standalone fake telemetry generator (?mock=1)
  components/
    TrackMap.tsx        LiveMap (cars on the track) and PathMap (lines driven)
    Plot.tsx            LivePlot (rolling) and XYPlot (fixed series)
    Lever.tsx           On-screen throttle / steering lever
    Hint.tsx            The "?" explanation mark and labelled values
    bits.tsx            Flags, meters, swatches
    useCanvas.ts        Canvas sizing and redraw loop
  views/
    DriveView.tsx       Drive one car
    LiveView.tsx        All cars, race control, timing, rolling plots
    DashboardView.tsx   Session and race reports over REST
  App.tsx               Hash-router shell + masthead
  index.css             All styles
```
