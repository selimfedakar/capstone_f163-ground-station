// Live: every car on the track at once, race control and timing, rolling traces.

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { SignalFlag, Swatch } from '../components/bits'
import { Label } from '../components/Hint'
import { LivePlot } from '../components/Plot'
import { LiveMap } from '../components/TrackMap'
import { finishRace, getRace, startRace } from '../lib/api'
import type { PlotRange } from '../lib/axes'
import { LOW_BATTERY_V, type RaceResult } from '../lib/contract'
import { clockTime, fixed, lapTime, raceClock } from '../lib/format'
import { liveryFor, theme } from '../lib/theme'
import type { ConnectionState } from '../lib/useConnection'

const SPEED: PlotRange = { min: 0, max: 5.5, ticks: [0, 1, 2, 3, 4, 5], digits: 0 }
const BATTERY: PlotRange = {
  min: 6,
  max: 8.6,
  ticks: [6, 6.5, 7, 7.5, 8, 8.5],
  digits: 1,
  mark: { y: LOW_BATTERY_V, color: theme.kerb },
}
const UNIT: PlotRange = {
  min: -1.1,
  max: 1.1,
  ticks: [-1, -0.5, 0, 0.5, 1],
  digits: 1,
  mark: { y: 0, color: theme.muted },
}
const ACCEL: PlotRange = {
  min: -9,
  max: 9,
  ticks: [-8, -4, 0, 4, 8],
  digits: 0,
  mark: { y: 0, color: theme.muted },
}

const STANDINGS_REFRESH_MS = 5000

function gapText(r: RaceResult): string {
  if (r.position === 1) return 'Leader'
  if (r.gap_laps > 0) return `+${r.gap_laps} lap${r.gap_laps > 1 ? 's' : ''}`
  return r.gap_s == null ? '–' : `+${r.gap_s.toFixed(2)} s`
}

/** Seconds since the race started, ticking. */
function useElapsed(startedAt: number | undefined): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (startedAt == null) return
    const id = setInterval(() => setNow(Date.now()), 200)
    return () => clearInterval(id)
  }, [startedAt])
  return startedAt == null ? null : Math.max(0, now / 1000 - startedAt)
}

function RaceControl({ conn }: { conn: ConnectionState }) {
  const { race, finishedRace, cars, status, mock } = conn
  const [name, setName] = useState('')
  const [laps, setLaps] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const elapsed = useElapsed(race?.started_at)
  const connected = cars.filter((c) => c.connected).length
  const online = status === 'open' && !mock

  const start = (e: FormEvent) => {
    e.preventDefault()
    const n = Number(laps)
    setBusy(true)
    setError(null)
    startRace({
      name: name.trim() || undefined,
      laps: laps.trim() && Number.isInteger(n) && n > 0 ? n : undefined,
    })
      // The next race gets its own default name; the lap target is kept.
      .then(() => setName(''))
      .catch((err: unknown) => setError(`Race not started: ${err instanceof Error ? err.message : String(err)}.`))
      .finally(() => setBusy(false))
  }
  const finish = () => {
    if (!race) return
    setBusy(true)
    setError(null)
    finishRace(race.id)
      .catch((err: unknown) => setError(`Race not finished: ${err instanceof Error ? err.message : String(err)}.`))
      .finally(() => setBusy(false))
  }

  return (
    <section className="race" aria-label="Race control">
      <Label k="race">Race</Label>
      {race ? (
        <div className="race-on">
          <div>
            <p className="race-name">{race.name}</p>
            <p className="quiet">
              {race.laps_target ? `First to ${race.laps_target} laps` : 'Runs until you finish it'}
            </p>
          </div>
          <div className="race-clock">
            <Label k="raceElapsed">Elapsed</Label>
            <b className="num">{raceClock(elapsed)}</b>
          </div>
          <button type="button" className="action" onClick={finish} disabled={busy}>
            Finish race
          </button>
        </div>
      ) : (
        <form className="race-form" onSubmit={start}>
          <div className="field">
            <label className="label" htmlFor="race-name">
              Name
            </label>
            <input
              id="race-name"
              type="text"
              value={name}
              maxLength={80}
              placeholder="Race at start time"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <Label k="raceLaps">
              <label htmlFor="race-laps">Laps to win</label>
            </Label>
            <input
              id="race-laps"
              type="number"
              min={1}
              max={500}
              inputMode="numeric"
              value={laps}
              placeholder="No limit"
              onChange={(e) => setLaps(e.target.value)}
            />
          </div>
          <button type="submit" className="action go" disabled={busy || !online || connected === 0}>
            Start race
          </button>
        </form>
      )}
      {error && <p className="notice stop">{error}</p>}
      {!race && (
        <p className="quiet">
          {finishedRace
            ? `${finishedRace.name} finished (${finishedRace.reason}). The result is under Dashboard, Races.`
            : connected === 0
              ? 'Connect a car to start a race.'
              : `Starting puts ${connected === 1 ? 'the car' : `all ${connected} cars`} back on the start line and times ${connected === 1 ? 'it' : 'them'} from the same instant.`}
        </p>
      )}
    </section>
  )
}

export function LiveView({ conn }: { conn: ConnectionState }) {
  const { cars, latestByCar, signalByCar, lapStats, laps, race, store } = conn
  const [standings, setStandings] = useState<RaceResult[] | null>(null)

  const ids = useMemo(() => cars.map((c) => c.car_id), [cars])
  const sorted = useMemo(() => [...cars].sort((a, b) => a.car_id.localeCompare(b.car_id)), [cars])
  const mapCars = useMemo(
    () =>
      sorted.map((c) => ({
        id: c.car_id,
        color: liveryFor(c.car_id, ids),
        signal: signalByCar[c.car_id] ?? 'offline',
      })),
    [sorted, ids, signalByCar],
  )
  const plotCars = useMemo(() => mapCars.map(({ id, color }) => ({ id, color })), [mapCars])

  // Race standings come from the server, which is the one timing the laps.
  // Refresh on every lap and on a slow tick.
  const raceId = race?.id
  const lapSeen = laps[0]?.key
  const loadStandings = useCallback(() => {
    if (raceId == null) return
    getRace(raceId)
      .then((r) => setStandings(r.results))
      .catch(() => {
        // Keep the last standings; the next refresh will try again.
      })
  }, [raceId])
  useEffect(() => {
    if (raceId == null) return
    loadStandings()
    const id = setInterval(loadStandings, STANDINGS_REFRESH_MS)
    return () => clearInterval(id)
  }, [raceId, lapSeen, loadStandings])

  const racing = race != null && standings != null
  const byCar = useMemo(() => {
    const m = new Map<string, RaceResult>()
    if (racing) for (const r of standings) m.set(r.car_id, r)
    return m
  }, [racing, standings])
  const rows = useMemo(() => {
    if (!racing) return sorted
    const pos = (id: string) => byCar.get(id)?.position ?? 999
    return [...sorted].sort((a, b) => pos(a.car_id) - pos(b.car_id))
  }, [racing, sorted, byCar])

  const bests = rows
    .map((c) => (racing ? byCar.get(c.car_id)?.best_lap_s : lapStats[c.car_id]?.best))
    .filter((b): b is number => b != null)
  const fastest = bests.length ? Math.min(...bests) : null

  if (cars.length === 0) {
    return (
      <div className="empty">
        <h1>Nothing to watch yet</h1>
        <p>Cars show up here as soon as they connect. Start two and watch them lap:</p>
        <pre>
          make sim ARGS="--car-id car-1 --mode auto"{'\n'}make sim ARGS="--car-id car-2 --mode auto"
        </pre>
      </div>
    )
  }

  return (
    <div className="live">
      <section className="live-map">
        <div className="map-head">
          <Label k="trackMap">Track</Label>
        </div>
        <LiveMap store={store} cars={mapCars} />
      </section>

      <div className="live-side">
        <RaceControl conn={conn} />

        <section className={`timing${racing ? ' racing' : ''}`} aria-label="Timing">
          <table>
            <thead>
              <tr>
                {racing && <th><Label k="racePos">Pos</Label></th>}
                <th><Label k="car">Car</Label></th>
                <th className="opt"><Label k="mode">Mode</Label></th>
                <th className="r opt2"><Label k="speed">m/s</Label></th>
                <th className="r"><Label k="laps">Laps</Label></th>
                {racing && <th className="r"><Label k="raceGap">Gap</Label></th>}
                <th className="r opt2"><Label k="lastLap">Last</Label></th>
                <th className="r"><Label k="bestLap">Best</Label></th>
                <th className="r opt"><Label k="battery">Volts</Label></th>
                <th><Label k="signal">Signal</Label></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const t = latestByCar[c.car_id]
                const l = lapStats[c.car_id]
                const r = byCar.get(c.car_id)
                const battery = t?.battery_v
                const low = battery != null && battery < LOW_BATTERY_V
                const lapCount = racing ? (r?.laps ?? '–') : (l?.count ?? '–')
                const last = racing ? r?.last_lap_s : l?.last
                const best = racing ? r?.best_lap_s : l?.best
                return (
                  <tr key={c.car_id}>
                    {racing && <td className="num">{r?.position ?? '–'}</td>}
                    <td>
                      <Swatch color={liveryFor(c.car_id, ids)} />
                      <b>{c.car_id}</b>
                    </td>
                    <td className="opt">{c.mode}</td>
                    <td className="r num opt2">{fixed(t?.speed_mps)}</td>
                    <td className="r num">{lapCount}</td>
                    {racing && <td className="r num">{r ? gapText(r) : '–'}</td>}
                    <td className="r num opt2">{lapTime(last)}</td>
                    <td className={`r num${best != null && best === fastest ? ' fastest' : ''}`}>
                      {lapTime(best)}
                    </td>
                    <td className={`r num opt${low ? ' stop' : ''}`}>{fixed(battery)}</td>
                    <td>
                      <SignalFlag signal={signalByCar[c.car_id] ?? 'offline'} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        <section className="feed">
          <Label k="lapFeed">Laps as they finish</Label>
          {laps.length === 0 ? (
            <p className="quiet">No lap finished yet. A lap counts once the car has been all the way round.</p>
          ) : (
            <ol>
              {laps.slice(0, 8).map((l) => (
                <li key={l.key} className={l.source === 'car' ? 'unconfirmed' : ''}>
                  <Swatch color={liveryFor(l.car_id, ids)} />
                  <span>{l.car_id}</span>
                  <span className="quiet">
                    {l.source === 'car'
                      ? 'not confirmed'
                      : `lap ${l.race_lap ?? l.lap_number}${l.valid === false ? ', off track' : ''}`}
                  </span>
                  <b className="num">{lapTime(l.lap_time_s)} s</b>
                  <span className="quiet">{clockTime(l.t)}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>

      <section className="traces" aria-label="Last 60 seconds">
        <div className="trace">
          <Label k="speedTrace">Speed, m/s</Label>
          <LivePlot store={store} cars={plotCars} field="speed" range={SPEED} label="Hız grafiği" />
        </div>
        <div className="trace">
          <Label k="batteryTrace">Battery, V</Label>
          <LivePlot store={store} cars={plotCars} field="battery" range={BATTERY} label="Batarya grafiği" />
        </div>
        <div className="trace">
          <Label k="throttleTrace">Throttle at the car</Label>
          <LivePlot store={store} cars={plotCars} field="throttle" range={UNIT} label="Gaz grafiği" />
        </div>
        <div className="trace">
          <Label k="steeringTrace">Steering at the car</Label>
          <LivePlot store={store} cars={plotCars} field="steering" range={UNIT} label="Direksiyon grafiği" />
        </div>
        <div className="trace">
          <Label k="accelForward">Acceleration forward, m/s²</Label>
          <LivePlot store={store} cars={plotCars} field="ax" range={ACCEL} label="İleri ivme grafiği" />
        </div>
        <div className="trace">
          <Label k="accelSide">Acceleration sideways, m/s²</Label>
          <LivePlot store={store} cars={plotCars} field="ay" range={ACCEL} label="Yan ivme grafiği" />
        </div>
      </section>
    </div>
  )
}
