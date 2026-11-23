// Drive control input hook.
//
// Hold-to-drive, like an RC transmitter: a key or lever commands the car only
// while it is held, and everything returns to zero on release.
// - Keyboard: W/ArrowUp forward, S/ArrowDown brake or reverse, A/D or
//   ArrowLeft/ArrowRight steer, Space cuts both to zero, 1/2/3 pick the power
//   limit, R puts the car back on the start line. Key input eases toward its target so steering is not a step.
// - Levers (touch or mouse) set the value directly and override the keys.
// - Sends `control` when the values change, and every 100 ms while nonzero as a
//   heartbeat, never faster than 30 Hz (contract section 3, FR-5).
// - Losing focus zeroes everything, so a backgrounded tab cannot keep driving.

import { useCallback, useEffect, useRef, useState } from 'react'

const TICK_MS = 1000 / 30
const HEARTBEAT_MS = 100
const THROTTLE_RATE = 4 // full scale per second, keyboard only
const STEERING_RATE = 6

export const POWER_LIMITS = [0.4, 0.7, 1] as const

export interface DriveControls {
  throttle: number
  steering: number
  /** Index into POWER_LIMITS. */
  power: number
  setPower: (i: number) => void
  /** Lever input in [-1, 1], or null when the lever is released. */
  setLeverThrottle: (v: number | null) => void
  setLeverSteering: (v: number | null) => void
}

const approach = (cur: number, target: number, maxStep: number) =>
  Math.abs(target - cur) <= maxStep ? target : cur + Math.sign(target - cur) * maxStep

export function useDriveControls(
  send: (throttle: number, steering: number) => void,
  canSend: boolean,
  onReset?: () => void,
): DriveControls {
  const [throttle, setThrottle] = useState(0)
  const [steering, setSteering] = useState(0)
  const [power, setPowerState] = useState(1)

  const keys = useRef(new Set<string>())
  const lever = useRef<{ throttle: number | null; steering: number | null }>({
    throttle: null,
    steering: null,
  })
  const value = useRef({ throttle: 0, steering: 0 })
  const sent = useRef({ throttle: 0, steering: 0, at: 0 })
  const powerRef = useRef(1)
  const sendRef = useRef(send)
  const canSendRef = useRef(canSend)
  const resetRef = useRef(onReset)
  useEffect(() => {
    sendRef.current = send
    canSendRef.current = canSend
    resetRef.current = onReset
  }, [send, canSend, onReset])

  const setPower = useCallback((i: number) => {
    powerRef.current = i
    setPowerState(i)
  }, [])

  const setLeverThrottle = useCallback((v: number | null) => {
    lever.current.throttle = v
  }, [])
  const setLeverSteering = useCallback((v: number | null) => {
    lever.current.steering = v
  }, [])

  // Keyboard state.
  useEffect(() => {
    const NAMES: Record<string, string> = {
      w: 'fwd', arrowup: 'fwd', s: 'back', arrowdown: 'back',
      a: 'left', arrowleft: 'left', d: 'right', arrowright: 'right', ' ': 'stop',
    }
    const typing = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')
    }
    const down = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === '1' || k === '2' || k === '3') {
        setPower(Number(k) - 1)
        return
      }
      if (k === 'r') {
        if (!e.repeat) resetRef.current?.()
        return
      }
      const name = NAMES[k]
      if (!name) return
      keys.current.add(name)
      e.preventDefault()
    }
    const up = (e: KeyboardEvent) => {
      const name = NAMES[e.key.toLowerCase()]
      if (name) keys.current.delete(name)
    }
    const release = () => {
      keys.current.clear()
      lever.current = { throttle: null, steering: null }
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', release)
    const hidden = () => {
      if (document.visibilityState === 'hidden') release()
    }
    document.addEventListener('visibilitychange', hidden)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', release)
      document.removeEventListener('visibilitychange', hidden)
    }
  }, [setPower])

  // Control loop.
  useEffect(() => {
    let last = performance.now()
    const id = setInterval(() => {
      const now = performance.now()
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      const k = keys.current
      const limit = POWER_LIMITS[powerRef.current]
      const v = value.current

      if (k.has('stop')) {
        v.throttle = 0
        v.steering = 0
      } else {
        if (lever.current.throttle != null) {
          v.throttle = lever.current.throttle * limit
        } else {
          const target = ((k.has('fwd') ? 1 : 0) - (k.has('back') ? 1 : 0)) * limit
          v.throttle = approach(v.throttle, target, THROTTLE_RATE * dt)
        }
        if (lever.current.steering != null) {
          v.steering = lever.current.steering
        } else {
          const target = (k.has('right') ? 1 : 0) - (k.has('left') ? 1 : 0)
          v.steering = approach(v.steering, target, STEERING_RATE * dt)
        }
      }

      const t = Math.round(v.throttle * 100) / 100
      const s = Math.round(v.steering * 100) / 100
      setThrottle(t)
      setSteering(s)

      if (!canSendRef.current) return
      const changed = t !== sent.current.throttle || s !== sent.current.steering
      const heartbeat = (t !== 0 || s !== 0) && now - sent.current.at >= HEARTBEAT_MS
      if (changed || heartbeat) {
        sendRef.current(t, s)
        sent.current = { throttle: t, steering: s, at: now }
      }
    }, TICK_MS)
    return () => clearInterval(id)
  }, [])

  return { throttle, steering, power, setPower, setLeverThrottle, setLeverSteering }
}
