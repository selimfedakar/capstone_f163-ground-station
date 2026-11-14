// Built-in fake telemetry generator for standalone demos (?mock=1).
// Emits the same ServerToUiMsg stream a real server would push to a UI:
//   state (once) -> telemetry @ 20 Hz -> lap every ~15 s -> pong for pings.
// Speed follows a sine wave, battery drains slowly, a lap fires on a timer.

import type { PingMsg, ServerToUiMsg } from './contract'

const MOCK_CAR_ID = 'car-mock'
const MOCK_SESSION_ID = 1
const TICK_HZ = 20
const LAP_INTERVAL_S = 15

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
  let lastThrottle = 0
  let lastSteering = 0

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

  const tick = () => {
    const t = Date.now() / 1000
    const elapsed = t - startT

    // Sine-wave speed between ~1 and ~5 m/s.
    const speed = 3 + 2 * Math.sin(elapsed * 0.6)
    // Battery sags with speed and drains slowly over time.
    battery = Math.max(6.2, 8.3 - elapsed * 0.004 - speed * 0.02)
    const heading = (elapsed * 30) % 360
    // Simulated applied actuation tracks the last command, else autopilot-ish.
    const throttle = lastThrottle || Math.min(1, speed / 5)
    const steering = lastSteering || 0.3 * Math.sin(elapsed * 0.9)

    seq += 1
    onMessage({
      type: 'telemetry',
      car_id: MOCK_CAR_ID,
      seq,
      t,
      imu: {
        ax: 0.1 * Math.sin(elapsed),
        ay: 0.1 * Math.cos(elapsed),
        az: 9.81,
        gx: 0,
        gy: 0,
        gz: 0.3 * steering,
      },
      gps: {
        lat: 41.0421 + 0.0001 * Math.sin(elapsed * 0.6),
        lon: 29.0093 + 0.0001 * Math.cos(elapsed * 0.6),
      },
      speed_mps: speed,
      heading_deg: heading,
      battery_v: battery,
      steering,
      throttle,
    })

    if (t - lastLapT >= LAP_INTERVAL_S) {
      lapNumber += 1
      onMessage({
        type: 'lap',
        car_id: MOCK_CAR_ID,
        lap_number: lapNumber,
        lap_time_s: t - lastLapT,
        t,
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
