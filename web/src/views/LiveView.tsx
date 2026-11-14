// LIVE view — rolling ~60 s charts of speed, battery, and steering/throttle,
// plus a lap ticker. Driven from broadcast telemetry/lap messages.

import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { secs } from '../lib/format'
import type { ConnectionState } from '../lib/useConnection'

interface ChartPoint {
  rel: number // seconds relative to the latest sample
  speed: number
  battery: number
  steering: number
  throttle: number
}

export function LiveView({ conn }: { conn: ConnectionState }) {
  const { cars, window: windowData, laps } = conn
  const [carFilter, setCarFilter] = useState<string>('')

  const series = useMemo<ChartPoint[]>(() => {
    const rows = carFilter
      ? windowData.filter((r) => r.car_id === carFilter)
      : windowData
    if (rows.length === 0) return []
    const latestT = rows[rows.length - 1].t
    return rows.map((r) => ({
      rel: Number((r.t - latestT).toFixed(2)),
      speed: r.speed_mps,
      battery: r.battery_v,
      steering: r.steering,
      throttle: r.throttle,
    }))
  }, [windowData, carFilter])

  const relAxis = (
    <XAxis
      dataKey="rel"
      stroke="#8a93a6"
      tick={{ fontSize: 11 }}
      domain={[-60, 0]}
      type="number"
      tickFormatter={(v: number) => `${v}s`}
    />
  )

  const tooltipStyle = {
    background: '#1b2130',
    border: '1px solid #2a3242',
    borderRadius: 8,
    color: '#e6eaf2',
  }

  return (
    <div className="grid" style={{ gridTemplateColumns: '1fr' }}>
      <div className="row">
        <span className="muted">Car:</span>
        <select
          value={carFilter}
          onChange={(e) => setCarFilter(e.target.value)}
          aria-label="Filter car"
        >
          <option value="">All cars</option>
          {cars.map((c) => (
            <option key={c.car_id} value={c.car_id}>
              {c.car_id}
            </option>
          ))}
        </select>
        <span className="muted">
          {series.length} samples in window ({'~'}60 s)
        </span>
      </div>

      <div className="chart-stack">
        <div className="chart-card">
          <h3>Speed (m/s)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              {relAxis}
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
        </div>

        <div className="chart-card">
          <h3>Battery (V)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              {relAxis}
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
        </div>

        <div className="chart-card">
          <h3>Steering / Throttle (applied)</h3>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series}>
              <CartesianGrid stroke="#2a3242" strokeDasharray="3 3" />
              {relAxis}
              <YAxis
                stroke="#8a93a6"
                tick={{ fontSize: 11 }}
                domain={[-1, 1]}
              />
              <Tooltip contentStyle={tooltipStyle} isAnimationActive={false} />
              <Line
                type="monotone"
                dataKey="throttle"
                stroke="#f4c430"
                dot={false}
                isAnimationActive={false}
                strokeWidth={2}
              />
              <Line
                type="monotone"
                dataKey="steering"
                stroke="#ff4d4f"
                dot={false}
                isAnimationActive={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <h2>Lap Ticker</h2>
          {laps.length === 0 ? (
            <p className="muted">No laps yet.</p>
          ) : (
            <div className="lap-ticker">
              {laps.map((lap) => (
                <div className="lap-row" key={lap.key}>
                  <span>
                    {lap.car_id} · lap {lap.lap_number}
                  </span>
                  <span>{secs(lap.lap_time_s)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
