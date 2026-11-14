// DASHBOARD view — post-race analysis over REST only.
// Session list, KPI cards, lap-time bar chart, speed/battery line charts.

import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getKpis, getLaps, getSessions, getTelemetry } from '../lib/api'
import type { Kpis, Lap, Session, TelemetryRow } from '../lib/contract'
import { dateTime, kmh, mps, pct, secs, volts } from '../lib/format'

const TELEMETRY_LIMIT = 5000
const MAX_CHART_POINTS = 2000

// Uniformly downsample to at most `max` points, preserving order.
function downsample<T>(rows: T[], max: number): T[] {
  if (rows.length <= max) return rows
  const stride = Math.ceil(rows.length / max)
  const out: T[] = []
  for (let i = 0; i < rows.length; i += stride) out.push(rows[i])
  return out
}

export function DashboardView() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [kpis, setKpis] = useState<Kpis | null>(null)
  const [laps, setLaps] = useState<Lap[]>([])
  const [telemetry, setTelemetry] = useState<TelemetryRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load session list on mount.
  useEffect(() => {
    let cancelled = false
    getSessions()
      .then((s) => {
        if (cancelled) return
        setSessions(s)
        if (s.length > 0) setSelectedId((cur) => cur ?? s[0].id)
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      )
    return () => {
      cancelled = true
    }
  }, [])

  // Load details when the selected session changes.
  useEffect(() => {
    if (selectedId == null) return
    let cancelled = false
    // Reset UI state before fetching the newly selected session's data.
    // oxlint-disable-next-line react/set-state-in-effect
    setLoading(true)
    setError(null)
    Promise.all([
      getKpis(selectedId),
      getLaps(selectedId),
      getTelemetry(selectedId, { limit: TELEMETRY_LIMIT }),
    ])
      .then(([k, l, t]) => {
        if (cancelled) return
        setKpis(k)
        setLaps(l)
        setTelemetry(t)
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : String(e)),
      )
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const bestLapNumber = useMemo(() => {
    if (laps.length === 0) return null
    let best = laps[0]
    for (const lap of laps) if (lap.lap_time_s < best.lap_time_s) best = lap
    return best.lap_number
  }, [laps])

  const lapChartData = useMemo(
    () => laps.map((l) => ({ lap: l.lap_number, time: l.lap_time_s })),
    [laps],
  )

  const teleChartData = useMemo(() => {
    const sampled = downsample(telemetry, MAX_CHART_POINTS)
    if (sampled.length === 0) return []
    const t0 = sampled[0].t
    return sampled.map((r) => ({
      rel: Number((r.t - t0).toFixed(1)),
      speed: r.speed_mps,
      battery: r.battery_v,
    }))
  }, [telemetry])

  const tooltipStyle = {
    background: '#1b2130',
    border: '1px solid #2a3242',
    borderRadius: 8,
    color: '#e6eaf2',
  }

  return (
    <div className="stack">
      <div className="panel">
        <h2>Session</h2>
        <div className="session-picker">
          <select
            value={selectedId ?? ''}
            onChange={(e) =>
              setSelectedId(e.target.value ? Number(e.target.value) : null)
            }
            aria-label="Select session"
          >
            {sessions.length === 0 && <option value="">No sessions</option>}
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                #{s.id} · {s.car_id} · {s.mode} · {dateTime(s.started_at)}
                {s.ended_at == null ? ' · live' : ''}
              </option>
            ))}
          </select>
          {loading && <span className="muted">Loading…</span>}
        </div>
        {error && <p className="error">Error: {error}</p>}
      </div>

      {kpis && (
        <div className="panel">
          <h2>KPIs</h2>
          <div className="kpi-grid">
            <Kpi label="Best lap" value={secs(kpis.best_lap_s)} />
            <Kpi label="Avg lap" value={secs(kpis.avg_lap_s)} />
            <Kpi label="Lap count" value={String(kpis.lap_count)} />
            <Kpi
              label="Max speed"
              value={`${mps(kpis.max_speed_mps)} m/s (${kmh(
                kpis.max_speed_mps,
              )} km/h)`}
            />
            <Kpi label="Avg speed" value={`${mps(kpis.avg_speed_mps)} m/s`} />
            <Kpi label="Min battery" value={`${volts(kpis.min_battery_v)} V`} />
            <Kpi label="Packet loss" value={pct(kpis.packet_loss_pct)} />
            <Kpi label="Telemetry rows" value={String(kpis.telemetry_rows)} />
            <Kpi label="Seq gaps" value={String(kpis.seq_gaps)} />
            <Kpi label="Duration" value={secs(kpis.duration_s)} />
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Lap Times</h2>
        {lapChartData.length === 0 ? (
          <p className="muted">No laps recorded.</p>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={lapChartData}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              <XAxis
                dataKey="lap"
                stroke="#8a93a6"
                tick={{ fontSize: 11 }}
                label={{
                  value: 'Lap',
                  position: 'insideBottom',
                  offset: -2,
                  fill: '#8a93a6',
                }}
              />
              <YAxis stroke="#8a93a6" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} isAnimationActive={false} />
              <Bar dataKey="time" isAnimationActive={false}>
                {lapChartData.map((d) => (
                  <Cell
                    key={d.lap}
                    fill={d.lap === bestLapNumber ? '#2ecc71' : '#35c4ff'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
        {bestLapNumber != null && (
          <p className="muted">Best lap highlighted (lap {bestLapNumber}).</p>
        )}
      </div>

      <div className="panel">
        <h2>Speed over time</h2>
        {teleChartData.length === 0 ? (
          <p className="muted">No telemetry.</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={teleChartData}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              <XAxis
                dataKey="rel"
                stroke="#8a93a6"
                tick={{ fontSize: 11 }}
                tickFormatter={(v: number) => `${v}s`}
              />
              <YAxis stroke="#8a93a6" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} isAnimationActive={false} />
              <Line
                type="monotone"
                dataKey="speed"
                stroke="#35c4ff"
                dot={false}
                isAnimationActive={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="panel">
        <h2>Battery over time</h2>
        {teleChartData.length === 0 ? (
          <p className="muted">No telemetry.</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={teleChartData}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              <XAxis
                dataKey="rel"
                stroke="#8a93a6"
                tick={{ fontSize: 11 }}
                tickFormatter={(v: number) => `${v}s`}
              />
              <YAxis
                stroke="#8a93a6"
                tick={{ fontSize: 11 }}
                domain={['auto', 'auto']}
              />
              <Tooltip contentStyle={tooltipStyle} isAnimationActive={false} />
              <Line
                type="monotone"
                dataKey="battery"
                stroke="#2ecc71"
                dot={false}
                isAnimationActive={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  )
}
