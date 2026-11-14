// DRIVE view — low-latency control panel.
// Car selector, keyboard + touch controls, live readouts, warnings.

import { useCallback, useMemo, useState } from 'react'
import { TouchControls } from '../components/TouchControls'
import { LOW_BATTERY_V } from '../lib/contract'
import { deg, kmh, mps, volts } from '../lib/format'
import type { ConnectionState } from '../lib/useConnection'
import { useDriveControls } from '../lib/useDriveControls'

export function DriveView({ conn }: { conn: ConnectionState }) {
  const { cars, latestByCar, sendControl, mock, status } = conn
  // The user's explicit pick (null until they choose).
  const [picked, setPicked] = useState<string | null>(null)

  // Effective selection: the explicit pick if still present, else the first
  // connected car. Derived during render (no effect/setState churn).
  const selectedCar = useMemo(() => {
    if (picked && cars.some((c) => c.car_id === picked)) return picked
    const fallback = cars.find((c) => c.connected) ?? cars[0]
    return fallback ? fallback.car_id : null
  }, [picked, cars])
  const setSelectedCar = setPicked

  const send = useCallback(
    (throttle: number, steering: number) => {
      if (selectedCar) sendControl(selectedCar, throttle, steering)
    },
    [selectedCar, sendControl],
  )

  // Controls can be sent when there is a selected car and a live (non-mock) link.
  const canSend = useMemo(
    () => selectedCar != null && status === 'open' && !mock,
    [selectedCar, status, mock],
  )
  const controls = useDriveControls(send, canSend)

  const tele = selectedCar ? latestByCar[selectedCar] : undefined
  const lowBattery = tele != null && tele.battery_v < LOW_BATTERY_V

  return (
    <div className="grid drive-grid">
      <div className="panel">
        <h2>Vehicle</h2>
        <div className="row">
          <select
            value={selectedCar ?? ''}
            onChange={(e) => setSelectedCar(e.target.value || null)}
            aria-label="Select car"
          >
            {cars.length === 0 && <option value="">No cars</option>}
            {cars.map((c) => (
              <option key={c.car_id} value={c.car_id}>
                {c.car_id} {c.connected ? `(${c.mode})` : '(offline)'}
              </option>
            ))}
          </select>
        </div>

        {mock && (
          <p className="muted" style={{ marginTop: '0.75rem' }}>
            Mock mode: telemetry is simulated; control commands are not sent.
          </p>
        )}
        {!mock && status !== 'open' && (
          <p className="error" style={{ marginTop: '0.75rem' }}>
            Not connected — controls disabled.
          </p>
        )}

        <div className="spacer-sm" />
        <TouchControls controls={controls} />

        <div className="ctl-help">
          <div>
            <kbd>W</kbd>/<kbd>↑</kbd> throttle up · <kbd>S</kbd>/<kbd>↓</kbd>{' '}
            throttle down
          </div>
          <div>
            <kbd>A</kbd>/<kbd>←</kbd> left · <kbd>D</kbd>/<kbd>→</kbd> right ·{' '}
            <kbd>Space</kbd> brake/zero
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Readouts</h2>
        {lowBattery && (
          <div className="warn-banner">
            LOW BATTERY — {volts(tele?.battery_v)} V (below {LOW_BATTERY_V} V)
          </div>
        )}
        <div className="readouts">
          <div className="readout big">
            <div className="label">Speed</div>
            <div className="value">
              {mps(tele?.speed_mps)} <small>m/s</small>
            </div>
            <div className="value" style={{ fontSize: '1.1rem' }}>
              {kmh(tele?.speed_mps)} <small>km/h</small>
            </div>
          </div>

          <div className={`readout${lowBattery ? ' warn' : ''}`}>
            <div className="label">Battery</div>
            <div className={`value${lowBattery ? ' txt-red' : ''}`}>
              {volts(tele?.battery_v)} <small>V</small>
            </div>
          </div>

          <div className="readout">
            <div className="label">Heading</div>
            <div className="value">{deg(tele?.heading_deg)}</div>
          </div>

          <div className="readout">
            <div className="label">Throttle (applied)</div>
            <div className="value">
              {tele ? tele.throttle.toFixed(2) : '--'}
            </div>
          </div>

          <div className="readout">
            <div className="label">Steering (applied)</div>
            <div className="value">
              {tele ? tele.steering.toFixed(2) : '--'}
            </div>
          </div>

          <div className="readout">
            <div className="label">Seq</div>
            <div className="value">{tele ? tele.seq : '--'}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
