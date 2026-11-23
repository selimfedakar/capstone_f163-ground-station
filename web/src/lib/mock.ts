// Built-in fake telemetry generator for standalone demos (?mock=1).
// Emits the same ServerToUiMsg stream a real server would push to a UI:
//   state (once) -> telemetry @ 20 Hz -> lap on each lap -> pong for pings.
// The mock car laps the same stadium track the simulator uses, slowing for
// the corners, so the map views work without a backend.

import type { PingMsg, ServerToUiMsg } from './contract'
import { DEFAULT_TRACK, STADIUM, localToGps, stadiumPointAt } from './track'

const MOCK_CAR_ID = 'car-mock'
const MOCK_SESSION_ID = 1
const TICK_HZ = 20

export interface MockHandle {
  /** Feed a ping so the mock can answer with a pong (latency display). */
  ping: (msg: PingMsg) => void
  stop: () => void
}

/**
 * Start the mock stream. Returns a handle; messages arrive via `onMessage`
 * exactly as if they came from the server.
 */
export function startMock(
  onMessage: (msg: ServerToUiMsg) => void,
): MockHandle {
  const startT = Date.now() / 1000
  let seq = 0
  let battery = 8.3
  let lastLapT = startT
  let lapNumber = 0
  const lastThrottle = 0
  const lastSteering = 0

  // Announce current state immediately (one connected mock car).
  onMessage({
    type: 'state',
    cars: [
      {
        car_id: MOCK_CAR_ID,
        session_id: MOCK_SESSION_ID,
        mode: 'manual',
        connected: true,
      },
    ],
  })

  let distance = 0
  let speed = 0

  const tick = () => {
    const t = Date.now() / 1000
    const elapsed = t - startT
    const dt = 1 / TICK_HZ

    // Slower through the two corners, faster down the straights.
    const along = distance % STADIUM.length
    const half = STADIUM.length / 2
    const inCorner = along % half > STADIUM.straight
    const target = inCorner ? 2.8 : 4.4
    speed += Math.max(-4 * dt, Math.min(4 * dt, target - speed))
    distance += speed * dt

    const p = stadiumPointAt(distance)
    const { lat, lon } = localToGps(DEFAULT_TRACK, p.x, p.y)
    const throttle = lastThrottle || speed / 5
    const steering = lastSteering || (inCorner ? 0.16 : 0)
    battery = Math.max(6.2, 8.3 - elapsed * 0.004 - throttle * 0.5)

    seq += 1
    onMessage({
      type: 'telemetry',
      car_id: MOCK_CAR_ID,
      seq,
      t,
      imu: { ax: 0, ay: 0, az: 9.81, gx: 0, gy: 0, gz: inCorner ? speed / 3 : 0 },
      gps: { lat, lon },
      speed_mps: speed,
      heading_deg: (((p.heading * 180) / Math.PI) % 360 + 360) % 360,
      battery_v: battery,
      steering,
      throttle,
    })

    if (Math.floor(distance / STADIUM.length) > lapNumber) {
      lapNumber += 1
      onMessage({
        type: 'lap',
        car_id: MOCK_CAR_ID,
        lap_number: lapNumber,
        lap_time_s: t - lastLapT,
        t,
        valid: true,
        source: 'server',
      })
      lastLapT = t
    }
  }

  const interval = setInterval(tick, 1000 / TICK_HZ)

  return {
    ping: (msg: PingMsg) => {
      // Echo the ping ts back as a pong with a small synthetic server offset.
      onMessage({
        type: 'pong',
        ts: msg.ts,
        server_time: Date.now() / 1000,
      })
    },
    stop: () => clearInterval(interval),
  }
}

/** Allow the control UI to reflect commands into the mock's applied values. */
export function isMockEnabled(): boolean {
  return new URLSearchParams(window.location.search).get('mock') === '1'
}
