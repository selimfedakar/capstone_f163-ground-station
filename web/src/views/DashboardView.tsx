// Dashboard: post-race review, read over REST.
// Pick a single car's session or a whole race on the left; the report is on
// the right. Every figure is computed by the server (contract section 4).

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Swatch } from '../components/bits'
import { Label } from '../components/Hint'
import { XYPlot, type XYSeries } from '../components/Plot'
import { PathMap, type DrivenPath } from '../components/TrackMap'
import {
  getKpis,
  getLaps,
  getRace,
  getRaces,
  getSessions,
  getTelemetry,
  lapsCsvUrl,
  raceCsvUrl,
  telemetryCsvUrl,
} from '../lib/api'
import { fitRange, timeAxis, type PlotRange } from '../lib/axes'
import {
  LOW_BATTERY_V,
  type Kpis,
  type Lap,
  type RaceDetail,
  type RaceResult,
  type RaceSummary,
  type Session,
  type TelemetryRow,
} from '../lib/contract'
import { dayAndTime, duration, fixed, gForce, kmh, lapTime, raceClock, whole } from '../lib/format'
import type { GlossaryKey } from '../lib/glossary'
import { liveryFor, theme } from '../lib/theme'

// A 10-minute session is about 12 000 rows at 20 Hz; ask for all of it and
// thin it out here, so the charts cover the whole run rather than the start.
const TELEMETRY_LIMIT = 50_000
const MAX_PLOT_POINTS = 1500
const MAX_PATH_POINTS = 4000
const REFRESH_MS = 5000

function thin<T>(rows: T[], max: number): T[] {
  if (rows.length <= max) return rows
  const stride = Math.ceil(rows.length / max)
  return rows.filter((_, i) => i % stride === 0)
}

const SPEED: PlotRange = { min: 0, max: 5.5, ticks: [0, 1, 2, 3, 4, 5], digits: 0 }
const BATTERY: PlotRange = {
  min: 6,
  max: 8.6,
  ticks: [6, 6.5, 7, 7.5, 8, 8.5],
  digits: 1,
  mark: { y: LOW_BATTERY_V, color: theme.kerb },
}
const FORWARD_COLOR = theme.ink
const SIDEWAYS_COLOR = '#0f6fde'

const explain = (e: unknown) =>
  `Could not read from the server (${e instanceof Error ? e.message : String(e)}). Check that it is running, then reload.`

function Figure({
  k,
  name,
  value,
  unit,
  note,
  alert,
}: {
  k: GlossaryKey
  name: string
  value: string
  unit?: string
  note?: string
  alert?: boolean
}) {
  return (
    <div className="figure">
      <Label k={k}>{name}</Label>
      <p className={`mid${alert ? ' stop' : ''}`}>
        {value} {unit && <span className="unit">{unit}</span>}
      </p>
      {note && <p className="sub">{note}</p>}
    </div>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="group">
      <h2>{title}</h2>
      <div className="figures">{children}</div>
    </section>
  )
}

// ---- One car's session ----------------------------------------------------

function SessionReport({ session }: { session: Session }) {
  const id = session.id
  const running = session.ended_at == null
  const [kpis, setKpis] = useState<Kpis | null>(null)
  const [laps, setLaps] = useState<Lap[]>([])
  const [telemetry, setTelemetry] = useState<TelemetryRow[]>([])
  const [loadedId, setLoadedId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    Promise.all([getKpis(id), getLaps(id), getTelemetry(id, { limit: TELEMETRY_LIMIT })])
      .then(([k, l, t]) => {
        if (cancelled) return
        setKpis(k)
        setLaps(l)
        setTelemetry(t)
        setLoadedId(id)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(explain(e))
      })
    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => load(), [load])
  // While the car is still out, keep everything current.
  useEffect(() => {
    if (!running) return
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [running, load])

  const t0 = telemetry[0]?.t ?? 0
  const span = telemetry.length ? telemetry[telemetry.length - 1].t - t0 : 0
  const plotRows = useMemo(() => thin(telemetry, MAX_PLOT_POINTS), [telemetry])
  const paths = useMemo<DrivenPath[]>(
    () => [{ rows: thin(telemetry, MAX_PATH_POINTS) }],
    [telemetry],
  )
  const xAxis = useMemo(() => timeAxis(span), [span])
  const speedSeries = useMemo<XYSeries[]>(
    () => [{ color: theme.ink, points: plotRows.map((r) => ({ x: r.t - t0, y: r.speed_mps })) }],
    [plotRows, t0],
  )
  const batterySeries = useMemo<XYSeries[]>(
    () => [{ color: theme.ink, points: plotRows.map((r) => ({ x: r.t - t0, y: r.battery_v })) }],
    [plotRows, t0],
  )
  const accelSeries = useMemo<XYSeries[]>(
    () => [
      { color: SIDEWAYS_COLOR, points: plotRows.map((r) => ({ x: r.t - t0, y: r.ay })) },
      { color: FORWARD_COLOR, points: plotRows.map((r) => ({ x: r.t - t0, y: r.ax })) },
    ],
    [plotRows, t0],
  )
  const accelRange = useMemo(
    () =>
      fitRange(
        plotRows.flatMap((r) => [r.ax, r.ay]).filter((v): v is number => v != null && Math.abs(v) < 160),
        0,
        { y: 0, color: theme.muted },
      ),
    [plotRows],
  )

  // Laps the server timed (or, in an older recording, the only laps there are).
  const counted = laps.filter((l) => l.source !== 'car')
  const unconfirmed = laps.filter((l) => l.source === 'car')
  const slowest = counted.reduce((m, l) => Math.max(m, l.lap_time_s), 0)

  const ready = loadedId === id && kpis != null
  const errors = kpis?.sensor_errors
  const errorNote = errors
    ? (Object.entries(errors) as [string, number][])
        .filter(([, n]) => n > 0)
        .map(([name, n]) => `${name} ${n}`)
        .join(', ')
    : ''

  return (
    <>
      <header className="report-head">
        <h1>
          {session.car_id}, session {session.id}
        </h1>
        <p className="quiet">
          {session.mode === 'auto' ? 'Drove itself' : 'Driven by hand'}, started{' '}
          {dayAndTime(session.started_at)}
          {session.fw ? `, software ${session.fw}` : ''}
          {running ? '. Still running, figures refresh every 5 seconds.' : '.'}
        </p>
        <p className="downloads">
          <a href={telemetryCsvUrl(id)} download>
            Download telemetry (CSV)
          </a>
          <a href={lapsCsvUrl(id)} download>
            Download laps (CSV)
          </a>
          <Label k="csv">{''}</Label>
        </p>
      </header>
      {error && <p className="notice stop">{error}</p>}

      {!ready ? (
        <p className="quiet">Reading the session…</p>
      ) : (
        <>
          <Group title="Laps">
            <Figure k="bestLap" name="Best lap" value={lapTime(kpis.best_lap_s)} unit="s" />
            <Figure k="avgLap" name="Average lap" value={lapTime(kpis.avg_lap_s)} unit="s" />
            <Figure k="laps" name="Laps" value={String(kpis.lap_count)} />
            <Figure
              k="invalidLaps"
              name="Laps off track"
              value={String(kpis.invalid_laps ?? 0)}
              alert={(kpis.invalid_laps ?? 0) > 0}
            />
            <Figure
              k="unconfirmedLaps"
              name="Laps not confirmed"
              value={String(kpis.unconfirmed_car_laps ?? 0)}
              alert={(kpis.unconfirmed_car_laps ?? 0) > 0}
            />
          </Group>

          <Group title="Speed and distance">
            <Figure
              k="maxSpeed"
              name="Top speed"
              value={fixed(kpis.max_speed_mps)}
              unit="m/s"
              note={`${kmh(kpis.max_speed_mps)} km/h`}
            />
            <Figure
              k="avgMovingSpeed"
              name="Average while moving"
              value={fixed(kpis.avg_moving_speed_mps)}
              unit="m/s"
            />
            <Figure k="avgSpeed" name="Average overall" value={fixed(kpis.avg_speed_mps)} unit="m/s" />
            <Figure k="distance" name="Distance" value={fixed(kpis.distance_m, 1)} unit="m" />
            <Figure
              k="offTrackTime"
              name="Time off track"
              value={fixed(kpis.off_track_s, 1)}
              unit="s"
              note={kpis.off_track_pct != null ? `${fixed(kpis.off_track_pct, 1)}% of the driving time` : 'Position not checked'}
            />
          </Group>

          <Group title="Forces and battery">
            <Figure
              k="maxAccel"
              name="Hardest acceleration"
              value={fixed(kpis.max_accel_mps2, 1)}
              unit="m/s²"
              note={`${gForce(kpis.max_accel_mps2)} g`}
            />
            <Figure
              k="maxBrake"
              name="Hardest braking"
              value={fixed(kpis.max_brake_mps2, 1)}
              unit="m/s²"
              note={`${gForce(kpis.max_brake_mps2)} g`}
            />
            <Figure
              k="maxLateral"
              name="Hardest cornering"
              value={fixed(kpis.max_lateral_mps2, 1)}
              unit="m/s²"
              note={`${gForce(kpis.max_lateral_mps2)} g`}
            />
            <Figure
              k="minBattery"
              name="Lowest battery"
              value={fixed(kpis.min_battery_v)}
              unit="V"
              alert={kpis.min_battery_v != null && kpis.min_battery_v < LOW_BATTERY_V}
            />
            <Figure k="duration" name="Duration" value={duration(kpis.duration_s)} />
          </Group>

          <Group title="Data link and sensors">
            <Figure
              k="packetLoss"
              name="Packet loss"
              value={fixed(kpis.packet_loss_pct)}
              unit="%"
              note={`${whole(kpis.seq_gaps)} packets lost`}
            />
            <Figure
              k="sensorErrors"
              name="Sensor errors"
              value={fixed(kpis.sensor_error_pct)}
              unit="%"
              note={errorNote || 'No bad reading'}
              alert={(kpis.sensor_error_rows ?? 0) > 0}
            />
            <Figure k="telemetryRows" name="Rows saved" value={whole(kpis.telemetry_rows)} />
            <Figure k="dataRate" name="Data rate" value={fixed(kpis.telemetry_rate_hz, 1)} unit="Hz" />
            <Figure k="maxGap" name="Longest silence" value={fixed(kpis.max_gap_s)} unit="s" />
          </Group>

          <Group title="Commands">
            <Figure k="controlsSent" name="Commands sent" value={whole(kpis.controls_sent)} />
            <Figure
              k="latencyP50"
              name="Delay, typical"
              value={fixed(kpis.latency_p50_ms, 0)}
              unit="ms"
            />
            <Figure
              k="latencyP95"
              name="Delay, 95th percentile"
              value={fixed(kpis.latency_p95_ms, 0)}
              unit="ms"
              note="Target: 100 ms or less"
              alert={kpis.latency_p95_ms != null && kpis.latency_p95_ms > 100}
            />
            <Figure
              k="controlsLost"
              name="Commands lost"
              value={kpis.controls_lost == null ? '–' : whole(kpis.controls_lost)}
              note={kpis.controls_lost == null && (kpis.controls_sent ?? 0) > 0 ? 'Car sent no acknowledgements' : undefined}
              alert={(kpis.controls_lost ?? 0) > 0}
            />
          </Group>

          <div className="report-pair">
            <section>
              <div className="map-head">
                <Label k="pathMap">Line driven, coloured by speed</Label>
                <span className="ramp" aria-hidden="true">
                  slow <i /> fast
                </span>
              </div>
              {telemetry.length > 1 ? (
                <PathMap paths={paths} maxSpeed={kpis.max_speed_mps ?? 0} />
              ) : (
                <p className="quiet">This session has no position data.</p>
              )}
            </section>

            <section>
              <Label k="lapChart">Lap times</Label>
              {counted.length === 0 ? (
                <p className="quiet">No lap was completed in this session.</p>
              ) : (
                <ol className="lapbars">
                  {counted.map((l) => (
                    <li
                      key={`${l.lap_number}-${l.t}`}
                      className={
                        l.valid === false ? 'invalid' : l.lap_time_s === kpis.best_lap_s ? 'best' : ''
                      }
                    >
                      <span className="lap-n">{l.lap_number}</span>
                      <span className="lap-bar">
                        <i style={{ width: `${(l.lap_time_s / slowest) * 100}%` }} />
                      </span>
                      <b className="num">{lapTime(l.lap_time_s)} s</b>
                    </li>
                  ))}
                </ol>
              )}
              {counted.some((l) => l.valid === false) && (
                <p className="quiet">Hatched laps left the track; their times do not count.</p>
              )}
              {unconfirmed.length > 0 && (
                <p className="quiet">
                  The car also reported {unconfirmed.length} lap{unconfirmed.length > 1 ? 's' : ''} the
                  server could not confirm ({unconfirmed.map((l) => `${lapTime(l.lap_time_s)} s`).join(', ')}).
                </p>
              )}
            </section>
          </div>

          <section className="trace">
            <Label k="speedTrace">Speed over the session, m/s</Label>
            <XYPlot series={speedSeries} range={SPEED} x={xAxis} label="Hız grafiği" />
          </section>
          <section className="trace">
            <div className="map-head">
              <Label k="accelTrace">Acceleration over the session, m/s²</Label>
              <span className="legend">
                <Swatch color={FORWARD_COLOR} /> forward
                <Swatch color={SIDEWAYS_COLOR} /> sideways
              </span>
            </div>
            <XYPlot series={accelSeries} range={accelRange} x={xAxis} label="İvme grafiği" />
          </section>
          <section className="trace">
            <Label k="batteryTrace">Battery over the session, V</Label>
            <XYPlot series={batterySeries} range={BATTERY} x={xAxis} label="Batarya grafiği" />
          </section>
        </>
      )}
    </>
  )
}

// ---- A race ----------------------------------------------------------------

function gapText(r: RaceResult): string {
  if (r.position === 1) return 'Winner'
  if (r.gap_laps > 0) return `+${r.gap_laps} lap${r.gap_laps > 1 ? 's' : ''}`
  return r.gap_s == null ? '–' : `+${r.gap_s.toFixed(2)} s`
}

function RaceReport({ raceId, running }: { raceId: number; running: boolean }) {
  const [race, setRace] = useState<RaceDetail | null>(null)
  const [telemetry, setTelemetry] = useState<Record<number, TelemetryRow[]>>({})
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    getRace(raceId)
      .then(async (r) => {
        const rows = await Promise.all(
          r.results.map((e) =>
            getTelemetry(e.session_id, {
              fromT: e.start_t ?? undefined,
              toT: e.end_t ?? undefined,
              limit: TELEMETRY_LIMIT,
            }),
          ),
        )
        if (cancelled) return
        setRace(r)
        setTelemetry(Object.fromEntries(r.results.map((e, i) => [e.session_id, rows[i]])))
        setError(null)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(explain(e))
      })
    return () => {
      cancelled = true
    }
  }, [raceId])

  useEffect(() => load(), [load])
  useEffect(() => {
    if (!running) return
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [running, load])

  const results = useMemo(() => (race?.id === raceId ? race.results : []), [race, raceId])
  const ids = useMemo(() => results.map((r) => r.car_id), [results])

  const lapSeries = useMemo<XYSeries[]>(
    () =>
      results.map((r) => ({
        color: liveryFor(r.car_id, ids),
        points: r.lap_times.map((l) => ({ x: l.race_lap, y: l.lap_time_s })),
      })),
    [results, ids],
  )
  const maxLap = Math.max(1, ...results.map((r) => r.laps))
  const lapAxis = useMemo(() => {
    const step = Math.max(1, Math.ceil(maxLap / 12))
    const ticks: number[] = []
    for (let n = 1; n <= maxLap; n += step) ticks.push(n)
    // Half a lap of room either side, so the first and last dots are not on the edge.
    return { x0: 0.5, x1: maxLap + 0.5, ticks, label: (n: number) => String(n) }
  }, [maxLap])
  const lapRange = useMemo(
    () => fitRange(results.flatMap((r) => r.lap_times.map((l) => l.lap_time_s)), 1),
    [results],
  )

  const { speedSeries, paths, span, topSpeed } = useMemo(() => {
    let span = 0
    let topSpeed = 0
    const speedSeries: XYSeries[] = []
    const paths: DrivenPath[] = []
    for (const r of results) {
      const rows = telemetry[r.session_id] ?? []
      if (!rows.length) continue
      const t0 = r.start_t ?? rows[0].t
      span = Math.max(span, rows[rows.length - 1].t - t0)
      topSpeed = Math.max(topSpeed, r.max_speed_mps ?? 0)
      const color = liveryFor(r.car_id, ids)
      speedSeries.push({
        color,
        points: thin(rows, MAX_PLOT_POINTS).map((row) => ({ x: row.t - t0, y: row.speed_mps })),
      })
      paths.push({ color, rows: thin(rows, MAX_PATH_POINTS) })
    }
    return { speedSeries, paths, span, topSpeed }
  }, [results, telemetry, ids])
  const xAxis = useMemo(() => timeAxis(span), [span])

  if (!race || race.id !== raceId) {
    return error ? <p className="notice stop">{error}</p> : <p className="quiet">Reading the race…</p>
  }

  return (
    <>
      <header className="report-head">
        <h1>{race.name}</h1>
        <p className="quiet">
          Started {dayAndTime(race.started_at)}
          {race.laps_target ? `, first to ${race.laps_target} laps` : ', no lap limit'}
          {race.ended_at == null
            ? '. Still running, the table refreshes every 5 seconds.'
            : `, lasted ${duration(race.ended_at - race.started_at)}.`}
        </p>
        <p className="downloads">
          <a href={raceCsvUrl(race.id)} download>
            Download results (CSV)
          </a>
          <Label k="csv">{''}</Label>
        </p>
      </header>
      {error && <p className="notice stop">{error}</p>}

      {results.length === 0 ? (
        <p className="quiet">No car took part in this race.</p>
      ) : (
        <>
          <section className="results" aria-label="Classification">
            <table>
              <thead>
                <tr>
                  <th><Label k="racePos">Pos</Label></th>
                  <th><Label k="car">Car</Label></th>
                  <th className="r"><Label k="laps">Laps</Label></th>
                  <th className="r"><Label k="raceTime">Time</Label></th>
                  <th className="r"><Label k="raceGap">Gap</Label></th>
                  <th className="r"><Label k="bestLap">Best lap</Label></th>
                  <th className="r opt"><Label k="avgLap">Avg lap</Label></th>
                  <th className="r opt"><Label k="maxSpeed">Top m/s</Label></th>
                  <th className="r opt"><Label k="distance">Metres</Label></th>
                  <th className="r opt"><Label k="offTrackTime">Off track</Label></th>
                  <th className="r opt"><Label k="packetLoss">Loss</Label></th>
                  <th className="r opt"><Label k="latencyP95">Delay</Label></th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.session_id}>
                    <td className="num">{r.position}</td>
                    <td>
                      <Swatch color={liveryFor(r.car_id, ids)} />
                      <b>{r.car_id}</b>
                    </td>
                    <td className="r num">{r.laps}</td>
                    <td className="r num">{raceClock(r.total_time_s)}</td>
                    <td className="r num">{gapText(r)}</td>
                    <td className="r num">{lapTime(r.best_lap_s)}</td>
                    <td className="r num opt">{lapTime(r.avg_lap_s)}</td>
                    <td className="r num opt">{fixed(r.max_speed_mps)}</td>
                    <td className="r num opt">{fixed(r.distance_m, 0)}</td>
                    <td className={`r num opt${(r.off_track_s ?? 0) > 0 ? ' stop' : ''}`}>
                      {r.off_track_s == null ? '–' : `${fixed(r.off_track_s, 1)} s`}
                    </td>
                    <td className="r num opt">
                      {r.packet_loss_pct == null ? '–' : `${fixed(r.packet_loss_pct)}%`}
                    </td>
                    <td className="r num opt">
                      {r.latency_p95_ms == null ? '–' : `${fixed(r.latency_p95_ms, 0)} ms`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <div className="report-pair">
            <section>
              <Label k="racePaths">Lines driven</Label>
              {paths.length ? (
                <PathMap paths={paths} maxSpeed={topSpeed} />
              ) : (
                <p className="quiet">No position data for this race.</p>
              )}
            </section>
            <section>
              <Label k="raceLapChart">Lap times by lap, s</Label>
              {results.every((r) => r.laps === 0) ? (
                <p className="quiet">No car completed a lap.</p>
              ) : (
                <XYPlot series={lapSeries} range={lapRange} x={lapAxis} dots label="Tur süreleri" />
              )}
            </section>
          </div>

          <section className="trace">
            <Label k="raceSpeedChart">Speed through the race, m/s</Label>
            <XYPlot series={speedSeries} range={SPEED} x={xAxis} label="Yarış hız grafiği" />
          </section>
        </>
      )}
    </>
  )
}

// ---- Page -------------------------------------------------------------------

export function DashboardView() {
  const [tab, setTab] = useState<'sessions' | 'races'>('sessions')
  const [sessions, setSessions] = useState<Session[] | null>(null)
  const [races, setRaces] = useState<RaceSummary[]>([])
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [raceId, setRaceId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadLists = useCallback(() => {
    Promise.all([getSessions(), getRaces().catch(() => [] as RaceSummary[])])
      .then(([s, r]) => {
        setSessions(s)
        setRaces(r)
        setSessionId((cur) => cur ?? s[0]?.id ?? null)
        setRaceId((cur) => cur ?? r[0]?.id ?? null)
        setError(null)
      })
      .catch((e: unknown) => setError(explain(e)))
  }, [])

  // Lists: on mount, then every few seconds so new runs appear.
  useEffect(() => {
    loadLists()
    const id = setInterval(loadLists, REFRESH_MS)
    return () => clearInterval(id)
  }, [loadLists])

  if (sessions == null) {
    return error ? <p className="notice stop">{error}</p> : <p className="quiet">Reading sessions…</p>
  }
  if (sessions.length === 0) {
    return (
      <div className="empty">
        <h1>No session recorded yet</h1>
        <p>A session is saved every time a car connects. Run one for twenty seconds and it will be listed here:</p>
        <pre>make sim ARGS="--mode auto --duration 20"</pre>
      </div>
    )
  }

  const session = sessions.find((s) => s.id === sessionId) ?? null
  const race = races.find((r) => r.id === raceId) ?? null

  return (
    <div className="dash">
      <aside className="sessions">
        <div className="seg wide" role="tablist" aria-label="What to review">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'sessions'}
            className={tab === 'sessions' ? 'on' : ''}
            onClick={() => setTab('sessions')}
          >
            Sessions
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'races'}
            className={tab === 'races' ? 'on' : ''}
            onClick={() => setTab('races')}
          >
            Races
          </button>
        </div>
        <Label k={tab === 'sessions' ? 'session' : 'race'}>
          {tab === 'sessions' ? 'One car, one connection' : 'Cars timed together'}
        </Label>

        {tab === 'sessions' ? (
          <ul>
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={s.id === sessionId ? 'on' : ''}
                  aria-current={s.id === sessionId}
                  onClick={() => setSessionId(s.id)}
                >
                  <span className="ses-top">
                    <b>{s.car_id}</b>
                    <span>{s.mode}</span>
                  </span>
                  <span className="ses-sub">
                    {dayAndTime(s.started_at)}
                    {s.ended_at == null ? (
                      <em>Running</em>
                    ) : (
                      <span>{duration(s.ended_at - s.started_at)}</span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : races.length === 0 ? (
          <p className="quiet">No race yet. Start one from the Live view once cars are connected.</p>
        ) : (
          <ul>
            {races.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={r.id === raceId ? 'on' : ''}
                  aria-current={r.id === raceId}
                  onClick={() => setRaceId(r.id)}
                >
                  <span className="ses-top">
                    <b>{r.name}</b>
                    <span>
                      {r.cars} car{r.cars === 1 ? '' : 's'}
                    </span>
                  </span>
                  <span className="ses-sub">
                    {dayAndTime(r.started_at)}
                    {r.ended_at == null ? (
                      <em>Running</em>
                    ) : (
                      <span>{duration(r.ended_at - r.started_at)}</span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="report">
        {error && <p className="notice stop">{error}</p>}
        {tab === 'sessions' && session && <SessionReport key={session.id} session={session} />}
        {tab === 'races' && race && (
          <RaceReport key={race.id} raceId={race.id} running={race.ended_at == null} />
        )}
        {tab === 'races' && !race && races.length === 0 && (
          <div className="empty">
            <h1>No race recorded yet</h1>
            <p>
              A race times several cars from the same instant and ranks them. Open the Live view,
              connect the cars, and press Start race.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
