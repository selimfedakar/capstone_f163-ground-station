// Central connection hook shared by the Drive and Live views.
// Owns: the WS client (or mock), car list, latest telemetry per car,
// a rolling telemetry window, lap events, latency (RTT), and control sending.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  CarState,
  ControlMsg,
  LapMsg,
  ServerToUiMsg,
  TelemetryMsg,
} from './contract'
import { startMock, type MockHandle } from './mock'
import { UiWsClient, type WsStatus } from './ws'

const ROLLING_WINDOW_S = 60
const PING_INTERVAL_MS = 1000
const MAX_LAPS_KEPT = 50

export interface LapEvent extends LapMsg {
  /** Monotonic id for stable React keys (laps can repeat across cars). */
  key: number
}

export interface ConnectionState {
  status: WsStatus
  mock: boolean
  cars: CarState[]
  latestByCar: Record<string, TelemetryMsg>
  /** Rolling ~60 s window of telemetry (all cars), oldest first. */
  window: TelemetryMsg[]
  laps: LapEvent[]
  /** Last measured round-trip latency in ms, or null if unknown. */
  latencyMs: number | null
  sendControl: (carId: string, throttle: number, steering: number) => void
}

export function useConnection(): ConnectionState {
  const [status, setStatus] = useState<WsStatus>('connecting')
  const [mock, setMock] = useState(false)
  const [cars, setCars] = useState<CarState[]>([])
  const [latestByCar, setLatestByCar] = useState<Record<string, TelemetryMsg>>(
    {},
  )
  const [windowData, setWindowData] = useState<TelemetryMsg[]>([])
  const [laps, setLaps] = useState<LapEvent[]>([])
  const [latencyMs, setLatencyMs] = useState<number | null>(null)

  const clientRef = useRef<UiWsClient | null>(null)
  const mockRef = useRef<MockHandle | null>(null)
  const pendingPingRef = useRef<number | null>(null)
  const lapKeyRef = useRef(0)
  const mockEnabledRef = useRef(false)

  const handleMessage = useCallback((msg: ServerToUiMsg) => {
    switch (msg.type) {
      case 'state':
        setCars(msg.cars)
        break
      case 'car_connected':
        setCars((prev) => {
          const others = prev.filter((c) => c.car_id !== msg.car_id)
          return [
            ...others,
            {
              car_id: msg.car_id,
              session_id: msg.session_id,
              mode: 'manual',
              connected: true,
            },
          ]
        })
        break
      case 'car_disconnected':
        setCars((prev) =>
          prev.map((c) =>
            c.car_id === msg.car_id ? { ...c, connected: false } : c,
          ),
        )
        break
      case 'telemetry': {
        setLatestByCar((prev) => ({ ...prev, [msg.car_id]: msg }))
        setWindowData((prev) => {
          const cutoff = msg.t - ROLLING_WINDOW_S
          const next = prev.filter((row) => row.t >= cutoff)
          next.push(msg)
          return next
        })
        break
      }
      case 'lap':
        setLaps((prev) => {
          lapKeyRef.current += 1
          const next = [{ ...msg, key: lapKeyRef.current }, ...prev]
          return next.slice(0, MAX_LAPS_KEPT)
        })
        break
      case 'pong': {
        if (pendingPingRef.current != null && msg.ts === pendingPingRef.current) {
          setLatencyMs(Math.max(0, Math.round(Date.now() - msg.ts)))
          pendingPingRef.current = null
        }
        break
      }
    }
  }, [])

  // Establish connection once on mount. If the WS cannot open within a short
  // grace period and ?mock=1 is present, fall back to the mock generator.
  useEffect(() => {
    mockEnabledRef.current =
      new URLSearchParams(window.location.search).get('mock') === '1'

    let disposed = false

    const startMockMode = () => {
      if (disposed || mockRef.current) return
      setMock(true)
      setStatus('open')
      mockRef.current = startMock(handleMessage)
    }

    const client = new UiWsClient({
      onMessage: handleMessage,
      onStatus: (s) => {
        if (disposed) return
        setStatus(s)
        if (s === 'open') {
          setMock(false)
          if (mockRef.current) {
            mockRef.current.stop()
            mockRef.current = null
          }
        }
      },
    })
    clientRef.current = client
    client.connect()

    // Mock fallback: if still not open after the grace period, use the mock.
    let graceTimer: ReturnType<typeof setTimeout> | null = null
    if (mockEnabledRef.current) {
      graceTimer = setTimeout(() => {
        if (!client.isOpen()) startMockMode()
      }, 2000)
    }

    return () => {
      disposed = true
      if (graceTimer) clearTimeout(graceTimer)
      client.close()
      clientRef.current = null
      if (mockRef.current) {
        mockRef.current.stop()
        mockRef.current = null
      }
    }
  }, [handleMessage])

  // Latency ping loop (once per second).
  useEffect(() => {
    const id = setInterval(() => {
      const ts = Date.now()
      pendingPingRef.current = ts
      if (mockRef.current) {
        mockRef.current.ping({ type: 'ping', ts })
      } else if (clientRef.current) {
        clientRef.current.sendPing({ type: 'ping', ts })
      }
    }, PING_INTERVAL_MS)
    return () => clearInterval(id)
  }, [])

  const sendControl = useCallback(
    (carId: string, throttle: number, steering: number) => {
      const clamp = (v: number) => Math.max(-1, Math.min(1, v))
      const msg: ControlMsg = {
        type: 'control',
        car_id: carId,
        throttle: clamp(throttle),
        steering: clamp(steering),
        ts: Date.now() / 1000,
      }
      if (clientRef.current && clientRef.current.isOpen()) {
        clientRef.current.sendControl(msg)
      }
      // In mock mode controls are accepted silently (no real actuation).
    },
    [],
  )

  return useMemo(
    () => ({
      status,
      mock,
      cars,
      latestByCar,
      window: windowData,
      laps,
      latencyMs,
      sendControl,
    }),
    [status, mock, cars, latestByCar, windowData, laps, latencyMs, sendControl],
  )
}
