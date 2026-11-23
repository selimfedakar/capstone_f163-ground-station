// Drive: pick a car, drive it with keys or the two levers, and watch what it
// reports back. The map follows every car; the picked one is ringed.

import { useCallback, useMemo, useState } from 'react'
import { Level, Meter, SignalFlag, Swatch } from '../components/bits'
import { Label } from '../components/Hint'
import { Lever } from '../components/Lever'
import { LiveMap } from '../components/TrackMap'
import { LOW_BATTERY_V } from '../lib/contract'
import { fixed, gForce, kmh, lapTime, signed } from '../lib/format'
import { liveryFor } from '../lib/theme'
import { gpsToLocal, isOffTrack } from '../lib/track'
import { useTrack } from '../lib/trackContext'
import type { ConnectionState } from '../lib/useConnection'
import { POWER_LIMITS, useDriveControls } from '../lib/useDriveControls'

const RAD_TO_DEG = 180 / Math.PI

export function DriveView({ conn }: { conn: ConnectionState }) {
  const {
    cars, latestByCar, signalByCar, lapStats, commandDelay, sendControl, resetCar,
    mock, status, store,
  } = conn
  const track = useTrack()
  const [picked, setPicked] = useState<string | null>(null)

  const ids = useMemo(() => cars.map((c) => c.car_id), [cars])
  // The explicit pick if it is still there, else the first drivable car.
  const car = useMemo(() => {
    const byPick = cars.find((c) => c.car_id === picked)
    return (
      byPick ??
      cars.find((c) => c.connected && c.mode === 'manual') ??
      cars.find((c) => c.connected) ??
      cars[0] ??
      null
    )
  }, [picked, cars])

  const signal = car ? (signalByCar[car.car_id] ?? 'offline') : 'offline'
  const drivable = !!car && car.connected && car.mode === 'manual' && status === 'open' && !mock

  const send = useCallback(
    (throttle: number, steering: number) => {
      if (car) sendControl(car.car_id, throttle, steering)
    },
    [car, sendControl],
  )
  // Reset works for any connected car, auto ones included.
  const canReset = !!car && car.connected && status === 'open' && !mock
  const reset = useCallback(() => {
    if (car && canReset) resetCar(car.car_id)
  }, [car, canReset, resetCar])
  const controls = useDriveControls(send, drivable, reset)

  const mapCars = useMemo(
    () =>
      cars.map((c) => ({
        id: c.car_id,
        color: liveryFor(c.car_id, ids),
        signal: signalByCar[c.car_id] ?? 'offline',
      })),
    [cars, ids, signalByCar],
  )

  const tele = car ? latestByCar[car.car_id] : undefined
  const laps = car ? lapStats[car.car_id] : undefined
  const battery = tele?.battery_v
  const lowBattery = battery != null && battery < LOW_BATTERY_V
  const hasPosition = tele?.gps?.lat != null && tele?.gps?.lon != null
  const offTrack =
    tele && hasPosition
      ? isOffTrack(track, gpsToLocal(track, tele.gps.lat as number, tele.gps.lon as number))
      : false
  const yaw = tele?.imu?.gz

  let notice: { tone: 'warn' | 'stop'; text: string } | null = null
  if (mock) notice = { tone: 'warn', text: 'Demo data. Commands are not sent to any car.' }
  else if (status !== 'open')
    notice = { tone: 'stop', text: 'No connection to the server. Controls are off until it returns.' }
  else if (!car) notice = null
  else if (!car.connected)
    notice = { tone: 'stop', text: `${car.car_id} has disconnected. Pick another car or restart it.` }
  else if (car.mode === 'auto')
    notice = { tone: 'warn', text: `${car.car_id} drives itself and ignores commands. Pick a manual car to drive.` }
  else if (signal === 'stale')
    notice = { tone: 'warn', text: `No data from ${car.car_id} for over a second. It cuts its own throttle after 0.5 s without commands.` }

  if (cars.length === 0) {
    return (
      <div className="empty">
        <h1>No car on the grid yet</h1>
        <p>Start a simulated car from the repository root and it appears here:</p>
        <pre>make sim ARGS="--car-id car-1 --mode manual"</pre>
        <p>
          Add <code>--mode auto</code> for a car that laps on its own.
        </p>
      </div>
    )
  }

  return (
    <div className="drive">
      <section className="drive-pick" aria-label="Car">
        <Label k="car">Car</Label>
        <div className="picker" role="radiogroup">
          {cars.map((c) => (
            <button
              key={c.car_id}
              type="button"
              role="radio"
              aria-checked={c.car_id === car?.car_id}
              className={`pick${c.car_id === car?.car_id ? ' on' : ''}`}
              onClick={() => setPicked(c.car_id)}
            >
              <Swatch color={liveryFor(c.car_id, ids)} />
              <span className="pick-name">{c.car_id}</span>
              <span className="pick-mode">{c.connected ? c.mode : 'offline'}</span>
            </button>
          ))}
        </div>
        <Label k="mode">manual or auto</Label>
      </section>

      <section className="drive-map">
        <div className="map-head">
          <Label k="trackMap">Track</Label>
          <span className={`tag${offTrack ? ' stop' : ''}`}>
            {!tele ? 'No position yet' : !hasPosition ? 'No GPS reading' : offTrack ? 'Off track' : 'On track'}
            <Label k="position">{''}</Label>
          </span>
        </div>
        <LiveMap store={store} cars={mapCars} selected={car?.car_id} />
      </section>

      <section className="readouts" aria-label="Car readouts">
        {notice && <p className={`notice ${notice.tone}`}>{notice.text}</p>}
        <div className="figure hero">
          <Label k="speed">Speed</Label>
          <p className="big">
            {fixed(tele?.speed_mps)} <span className="unit">m/s</span>
          </p>
          <p className="sub">{kmh(tele?.speed_mps)} km/h</p>
        </div>
        <div className="figure">
          <Label k="battery">Battery</Label>
          <p className={`mid${lowBattery ? ' stop' : ''}`}>
            {fixed(battery)} <span className="unit">V</span>
          </p>
          <Level value={battery} min={6} max={8.4} warn={lowBattery} />
          {lowBattery && <p className="sub stop">Below {LOW_BATTERY_V} V. Bring it in.</p>}
        </div>
        <div className="figure">
          <Label k="commandDelay">Command delay</Label>
          <p className={`mid${commandDelay && commandDelay.p95Ms > 100 ? ' stop' : ''}`}>
            {commandDelay ? commandDelay.p95Ms : '–'} <span className="unit">ms</span>
          </p>
          <p className="sub">
            {commandDelay
              ? `Last round trip ${commandDelay.loopMs} ms`
              : drivable
                ? 'Measured while you drive'
                : 'Needs a manual car'}
          </p>
        </div>
        <div className="figure">
          <Label k="appliedThrottle">Throttle at the car</Label>
          <p className="mid">{signed(tele?.throttle)}</p>
          <Meter value={tele?.throttle} />
        </div>
        <div className="figure">
          <Label k="appliedSteering">Steering at the car</Label>
          <p className="mid">{signed(tele?.steering)}</p>
          <Meter value={tele?.steering} />
        </div>
        <div className="figure">
          <Label k="accelForward">Acceleration, forward</Label>
          <p className="mid">
            {signed(tele?.imu?.ax, 1)} <span className="unit">m/s²</span>
          </p>
          <p className="sub">{gForce(tele?.imu?.ax)} g</p>
        </div>
        <div className="figure">
          <Label k="accelSide">Acceleration, sideways</Label>
          <p className="mid">
            {signed(tele?.imu?.ay, 1)} <span className="unit">m/s²</span>
          </p>
          <p className="sub">{gForce(tele?.imu?.ay)} g</p>
        </div>
        <div className="figure">
          <Label k="heading">Heading</Label>
          <p className="mid">
            {tele?.heading_deg != null ? Math.round(tele.heading_deg) : '–'}
            <span className="unit">°</span>
          </p>
        </div>
        <div className="figure">
          <Label k="yawRate">Turn rate</Label>
          <p className="mid">
            {yaw != null ? signed(yaw * RAD_TO_DEG, 0) : '–'} <span className="unit">°/s</span>
          </p>
        </div>
        <div className="figure">
          <Label k="lastLap">Last lap</Label>
          <p className="mid">
            {lapTime(laps?.last)} <span className="unit">s</span>
          </p>
          {laps && !laps.lastValid && <p className="sub stop">Off track, time does not count</p>}
        </div>
        <div className="figure">
          <Label k="bestLap">Best lap</Label>
          <p className="mid">
            {lapTime(laps?.best)} <span className="unit">s</span>
          </p>
        </div>
        <div className="figure">
          <Label k="laps">Laps</Label>
          <p className="mid">{laps?.count ?? '–'}</p>
        </div>
        <div className="figure">
          <Label k="signal">Signal</Label>
          <p className="mid small">
            <SignalFlag signal={signal} />
          </p>
        </div>
        <div className="figure">
          <Label k="seq">Packet number</Label>
          <p className="mid">{tele ? tele.seq : '–'}</p>
        </div>
      </section>

      <section className={`dock${drivable ? '' : ' off'}`} aria-label="Controls">
        <div className="dock-lever">
          <Label k="throttle">Throttle</Label>
          <Lever
            orientation="vertical"
            label="Throttle"
            value={controls.throttle}
            onChange={controls.setLeverThrottle}
            disabled={!drivable}
          />
          <p className="cmd">{signed(controls.throttle)}</p>
        </div>

        <div className="dock-mid">
          <div className="power">
            <Label k="power">Power limit</Label>
            <div className="seg" role="radiogroup" aria-label="Power limit">
              {POWER_LIMITS.map((p, i) => (
                <button
                  key={p}
                  type="button"
                  role="radio"
                  aria-checked={controls.power === i}
                  className={controls.power === i ? 'on' : ''}
                  onClick={() => controls.setPower(i)}
                >
                  {Math.round(p * 100)}%
                </button>
              ))}
            </div>
          </div>
          <div className="power">
            <Label k="reset">Back to the start line</Label>
            <button type="button" className="action" onClick={reset} disabled={!canReset}>
              Reset {car ? car.car_id : 'car'}
            </button>
          </div>
          <div className="keys">
            <Label k="keys">Keyboard</Label>
            <dl>
              <div>
                <dt>
                  <kbd>W</kbd> <kbd>S</kbd>
                </dt>
                <dd>forward, brake or reverse</dd>
              </div>
              <div>
                <dt>
                  <kbd>A</kbd> <kbd>D</kbd>
                </dt>
                <dd>steer left, right</dd>
              </div>
              <div>
                <dt>
                  <kbd>Space</kbd>
                </dt>
                <dd>cut throttle and steering</dd>
              </div>
              <div>
                <dt>
                  <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd>
                </dt>
                <dd>power limit</dd>
              </div>
              <div>
                <dt>
                  <kbd>R</kbd>
                </dt>
                <dd>back to the start line</dd>
              </div>
            </dl>
          </div>
        </div>

        <div className="dock-lever wide">
          <Label k="steering">Steering</Label>
          <Lever
            orientation="horizontal"
            label="Steering"
            value={controls.steering}
            onChange={controls.setLeverSteering}
            disabled={!drivable}
          />
          <p className="cmd">{signed(controls.steering)}</p>
        </div>
      </section>
    </div>
  )
}
