// Central connection hook shared by the Drive and Live views.
//
// Telemetry arrives at 20 Hz per car. Pushing every frame through React state
// re-rendered the whole app 40 times a second with two cars, so the high-rate
// data lives in a mutable store (`LiveStore`) that the canvases read directly,
// and React only sees a snapshot ten times a second.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  CarState,
  ControlMsg,
  LapMsg,
  RaceInfo,
  Reading,
  ServerToUiMsg,
  TelemetryMsg,
} from './contract'
import { startMock, type MockHandle } from './mock'
import { DEFAULT_TRACK, gpsToLocal, type Pt, type Track } from './track'
import { UiWsClient, type WsStatus } from './ws'

export const ROLLING_WINDOW_S = 60
const PING_INTERVAL_MS = 1000
const SNAPSHOT_INTERVAL_MS = 100
const MAX_LAPS_KEPT = 50
const TRAIL_POINTS = 70
/** No telemetry for this long while "connected" means the link is stale (NFR-7). */
export const STALE_AFTER_MS = 1000
/** Command round trips kept for the delay readout (about 5 s at 30 Hz). */
const ACK_SAMPLES = 150
const ACK_FRESH_MS = 3000

export interface Sample {
  t: number
  speed: Reading
  battery: Reading
  throttle: Reading
  steering: Reading
  ax: Reading
  ay: Reading
}

export interface CarLive {
  latest: TelemetryMsg
  /** Last known position; kept when a frame has no usable GPS reading. */
  pos: Pt | null
  /** performance.now() when the last frame arrived. */
  rxAt: number
  trail: Pt[]
  history: Sample[]
}

const num = (v: unknown): Reading => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** Mutable high-rate data. Read it from requestAnimationFrame, not from render. */
export class LiveStore {
  cars = new Map<string, CarLive>()
  track: Track = DEFAULT_TRACK

  push(msg: TelemetryMsg): void {
    let car = this.cars.get(msg.car_id)
    if (!car) {
      car = { latest: msg, pos: null, rxAt: 0, trail: [], history: [] }
      this.cars.set(msg.car_id, car)
    }
    car.latest = msg
    car.rxAt = performance.now()

    const lat = num(msg.gps?.lat)
    const lon = num(msg.gps?.lon)
    if (lat != null && lon != null) {
      car.pos = gpsToLocal(this.track, lat, lon)
      car.trail.push(car.pos)
      if (car.trail.length > TRAIL_POINTS) car.trail.shift()
    }

    const t = num(msg.t)
    if (t == null) return
    car.history.push({
      t,
      speed: num(msg.speed_mps),
      battery: num(msg.battery_v),
      throttle: num(msg.throttle),
      steering: num(msg.steering),
      ax: num(msg.imu?.ax),
      ay: num(msg.imu?.ay),
    })
    const cutoff = t - ROLLING_WINDOW_S
    while (car.history.length && car.history[0].t < cutoff) car.history.shift()
  }

  reset(carId: string): void {
    this.cars.delete(carId)
  }

  /** Drop the trail only, e.g. when the car jumps back to the start line. */
  clearTrail(carId: string): void {
    const car = this.cars.get(carId)
    if (car) car.trail = []
  }
}

export interface LapEvent extends LapMsg {
  /** Monotonic id for stable React keys (laps can repeat across cars). */
  key: number
}

export interface LapStats {
  count: number
  last: number | null
  /** False when the last lap left track limits. */
  lastValid: boolean
  /** Best lap that stayed within track limits. */
  best: number | null
}

export type Signal = 'live' | 'stale' | 'offline'

/** How long a command takes to reach the car, from acknowledged commands. */
export interface CommandDelay {
  /** 95th percentile of the one-way estimate over the last few seconds. */
  p95Ms: number
  /** Latest full loop UI -> server -> car -> server -> UI. */
  loopMs: number
  /** Latest server <-> car round trip, as measured by the server. */
  carRttMs: number
}

export interface ConnectionState {
  status: WsStatus
  mock: boolean
  cars: CarState[]
  /** Latest frame per car, refreshed 10 times a second. */
  latestByCar: Record<string, TelemetryMsg>
  signalByCar: Record<string, Signal>
  lapStats: Record<string, LapStats>
  laps: LapEvent[]
  /** Last measured UI <-> server round trip in ms, or null if unknown. */
  latencyMs: number | null
  commandDelay: CommandDelay | null
  /** The race in progress, if any, and the one that finished last. */
  race: RaceInfo | null
  finishedRace: (RaceInfo & { reason: string }) | null
  store: LiveStore
  sendControl: (carId: string, throttle: number, steering: number) => void
  /** Put a car back on the start/finish line, stopped. */
  resetCar: (carId: string) => void
}

export function useConnection(track: Track): ConnectionState {
  const [status, setStatus] = useState<WsStatus>('connecting')
  const [mock, setMock] = useState(false)
  const [cars, setCars] = useState<CarState[]>([])
  const [latestByCar, setLatestByCar] = useState<Record<string, TelemetryMsg>>({})
  const [signalByCar, setSignalByCar] = useState<Record<string, Signal>>({})
  const [lapStats, setLapStats] = useState<Record<string, LapStats>>({})
  const [laps, setLaps] = useState<LapEvent[]>([])
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const [commandDelay, setCommandDelay] = useState<CommandDelay | null>(null)
  const [race, setRace] = useState<RaceInfo | null>(null)
  const [finishedRace, setFinishedRace] = useState<(RaceInfo & { reason: string }) | null>(null)

  const [store] = useState(() => new LiveStore())
  const clientRef = useRef<UiWsClient | null>(null)
  const mockRef = useRef<MockHandle | null>(null)
  const pendingPingRef = useRef<number | null>(null)
  const lapKeyRef = useRef(0)
  const carsRef = useRef<CarState[]>([])
  const latencyRef = useRef<number | null>(null)
  const acksRef = useRef({ loops: [] as number[], carRtt: 0, at: 0 })
  useEffect(() => {
    carsRef.current = cars
  }, [cars])
  useEffect(() => {
    store.track = track
  }, [store, track])

  const handleMessage = useCallback(
    (msg: ServerToUiMsg) => {
      switch (msg.type) {
        case 'state':
          setCars(msg.cars)
          if (msg.race !== undefined) setRace(msg.race)
          break
        case 'car_connected': {
          // A reconnect is a new session: start its trail and traces afresh.
          store.reset(msg.car_id)
          setLapStats((prev) => {
            const next = { ...prev }
            delete next[msg.car_id]
            return next
          })
          const mode = msg.mode ?? 'manual'
          setCars((prev) => [
            ...prev.filter((c) => c.car_id !== msg.car_id),
            { car_id: msg.car_id, session_id: msg.session_id, mode, connected: true, fw: msg.fw },
          ])
          // A v1 server does not say which mode the car is in: ask for the state.
          if (msg.mode === undefined) clientRef.current?.sendHello()
          break
        }
        case 'car_disconnected':
          setCars((prev) =>
            prev.map((c) => (c.car_id === msg.car_id ? { ...c, connected: false } : c)),
          )
          break
        case 'telemetry':
          store.push(msg)
          break
        case 'lap': {
          setLaps((prev) => {
            lapKeyRef.current += 1
            return [{ ...msg, key: lapKeyRef.current }, ...prev].slice(0, MAX_LAPS_KEPT)
          })
          // A lap the car reported but the server did not time is shown in the
          // feed and counted nowhere.
          if (msg.source === 'car') break
          const valid = msg.valid !== false
          setLapStats((prev) => {
            const cur = prev[msg.car_id]
            const prevBest = cur?.best ?? null
            const best = !valid
              ? prevBest
              : prevBest == null
                ? msg.lap_time_s
                : Math.min(prevBest, msg.lap_time_s)
            return {
              ...prev,
              [msg.car_id]: {
                count: msg.lap_number,
                last: msg.lap_time_s,
                lastValid: valid,
                best,
              },
            }
          })
          break
        }
        case 'race':
          setRace(msg.race)
          if (msg.finished) setFinishedRace(msg.finished)
          else if (msg.race) setFinishedRace(null)
          break
        case 'control_ack': {
          const loop = Date.now() - msg.ts * 1000
          if (loop >= 0 && loop < 10_000) {
            const a = acksRef.current
            a.loops.push(loop)
            if (a.loops.length > ACK_SAMPLES) a.loops.shift()
            a.carRtt = msg.car_rtt_ms
            a.at = performance.now()
          }
          break
        }
        case 'pong':
          if (pendingPingRef.current != null && msg.ts === pendingPingRef.current) {
            const rtt = Math.max(0, Math.round(Date.now() - msg.ts))
            latencyRef.current = rtt
            setLatencyMs(rtt)
            pendingPingRef.current = null
          }
          break
      }
    },
    [store],
  )

  // Establish connection once on mount. If the WS cannot open within a short
  // grace period and ?mock=1 is present, fall back to the mock generator.
  useEffect(() => {
    const mockEnabled = new URLSearchParams(window.location.search).get('mock') === '1'
    let disposed = false

    const client = new UiWsClient({
      onMessage: handleMessage,
      onStatus: (s) => {
        if (disposed) return
        setStatus(s)
        if (s === 'open') {
          setMock(false)
          mockRef.current?.stop()
          mockRef.current = null
        }
      },
    })
    clientRef.current = client
    client.connect()

    let graceTimer: ReturnType<typeof setTimeout> | null = null
    if (mockEnabled) {
      graceTimer = setTimeout(() => {
        if (disposed || client.isOpen() || mockRef.current) return
        setMock(true)
        setStatus('open')
        mockRef.current = startMock(handleMessage)
      }, 2000)
    }

    return () => {
      disposed = true
      if (graceTimer) clearTimeout(graceTimer)
      client.close()
      clientRef.current = null
      mockRef.current?.stop()
      mockRef.current = null
    }
  }, [handleMessage])

  // Low-rate snapshot of the store for React (readouts, timing table).
  useEffect(() => {
    const id = setInterval(() => {
      const now = performance.now()
      const latest: Record<string, TelemetryMsg> = {}
      const signal: Record<string, Signal> = {}
      for (const c of carsRef.current) {
        const live = store.cars.get(c.car_id)
        if (live) latest[c.car_id] = live.latest
        signal[c.car_id] = !c.connected
          ? 'offline'
          : !live || now - live.rxAt > STALE_AFTER_MS
            ? 'stale'
            : 'live'
      }
      setLatestByCar(latest)
      setSignalByCar((prev) => {
        const keys = Object.keys(signal)
        const same =
          keys.length === Object.keys(prev).length && keys.every((k) => prev[k] === signal[k])
        return same ? prev : signal
      })

      const a = acksRef.current
      if (a.loops.length === 0 || now - a.at > ACK_FRESH_MS) {
        if (a.loops.length) a.loops = []
        setCommandDelay(null)
      } else {
        const sorted = [...a.loops].sort((x, y) => x - y)
        const p95 = sorted[Math.min(sorted.length - 1, Math.ceil(0.95 * sorted.length) - 1)]
        const next: CommandDelay = {
          // Half the loop is the one-way trip, assuming a symmetric link.
          p95Ms: Math.round(p95 / 2),
          loopMs: Math.round(a.loops[a.loops.length - 1]),
          carRttMs: Math.round(a.carRtt),
        }
        setCommandDelay((prev) =>
          prev && prev.p95Ms === next.p95Ms && prev.loopMs === next.loopMs && prev.carRttMs === next.carRttMs
            ? prev
            : next,
        )
      }
    }, SNAPSHOT_INTERVAL_MS)
    return () => clearInterval(id)
  }, [store])

  // Latency ping loop (once per second).
  useEffect(() => {
    const id = setInterval(() => {
      const ts = Date.now()
      pendingPingRef.current = ts
      if (mockRef.current) mockRef.current.ping({ type: 'ping', ts })
      else clientRef.current?.sendPing({ type: 'ping', ts })
    }, PING_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  const sendControl = useCallback((carId: string, throttle: number, steering: number) => {
    const clamp = (v: number) => Math.max(-1, Math.min(1, v))
    const msg: ControlMsg = {
      type: 'control',
      car_id: carId,
      throttle: clamp(throttle),
      steering: clamp(steering),
      ts: Date.now() / 1000,
    }
    if (latencyRef.current != null) msg.ui_rtt_ms = latencyRef.current
    if (clientRef.current?.isOpen()) clientRef.current.sendControl(msg)
    // In mock mode controls are accepted silently (no real actuation).
  }, [])

  const resetCar = useCallback(
    (carId: string) => {
      if (!clientRef.current?.isOpen()) return
      clientRef.current.sendReset({ type: 'reset', car_id: carId })
      // The car teleports; a trail drawn across the infield would be a lie.
      store.clearTrail(carId)
      setTimeout(() => store.clearTrail(carId), 250)
    },
    [store],
  )

  // A race start puts every car back on the line: same treatment for trails.
  useEffect(() => {
    if (!race) return
    for (const id of race.cars) store.clearTrail(id)
    const timer = setTimeout(() => {
      for (const id of race.cars) store.clearTrail(id)
    }, 250)
    return () => clearTimeout(timer)
    // Only when a new race begins, not when its car list is refreshed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [race?.id, store])

  return useMemo(
    () => ({
      status,
      mock,
      cars,
      latestByCar,
      signalByCar,
      lapStats,
      laps,
      latencyMs,
      commandDelay,
      race,
      finishedRace,
      store,
      sendControl,
      resetCar,
    }),
    [
      status, mock, cars, latestByCar, signalByCar, lapStats, laps, latencyMs,
      commandDelay, race, finishedRace, store, sendControl, resetCar,
    ],
  )
}
