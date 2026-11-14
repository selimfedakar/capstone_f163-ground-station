// Drive control input hook.
// - Tracks throttle/steering in [-1, 1] from keyboard and on-screen widgets.
// - Keyboard: W/ArrowUp = +throttle, S/ArrowDown = -throttle,
//   A/ArrowLeft = steer left, D/ArrowRight = steer right, Space = zero/brake.
// - Sends `control` only when values change OR every 100 ms while nonzero
//   (heartbeat), at up to 30 Hz. Values are clamped by the connection layer.

import { useCallback, useEffect, useRef, useState } from 'react'

const STEP = 0.1 // keyboard increment per key event
const HEARTBEAT_MS = 100 // resend period while nonzero
const MIN_SEND_INTERVAL_MS = 1000 / 30 // 30 Hz cap

const clamp = (v: number) => Math.max(-1, Math.min(1, v))

export interface DriveControls {
  throttle: number
  steering: number
  setThrottle: (v: number) => void
  setSteering: (v: number) => void
  zero: () => void
  /** Attach keyboard handlers to window; returns detach. */
  enabled: boolean
  setEnabled: (v: boolean) => void
}

export function useDriveControls(
  send: (throttle: number, steering: number) => void,
  canSend: boolean,
): DriveControls {
  const [throttle, setThrottleState] = useState(0)
  const [steering, setSteeringState] = useState(0)
  const [enabled, setEnabled] = useState(true)

  // Refs mirror state for the timer/keyboard closures.
  const throttleRef = useRef(0)
  const steeringRef = useRef(0)
  const lastSentRef = useRef({ throttle: 0, steering: 0, at: 0 })
  const canSendRef = useRef(canSend)
  useEffect(() => {
    canSendRef.current = canSend
  }, [canSend])

  const doSend = useCallback(
    (force: boolean) => {
      if (!canSendRef.current) return
      const now = Date.now()
      const last = lastSentRef.current
      const changed =
        throttleRef.current !== last.throttle ||
        steeringRef.current !== last.steering
      const sinceLast = now - last.at
      if (!force && !changed) return
      if (sinceLast < MIN_SEND_INTERVAL_MS && !force) return
      send(throttleRef.current, steeringRef.current)
      lastSentRef.current = {
        throttle: throttleRef.current,
        steering: steeringRef.current,
        at: now,
      }
    },
    [send],
  )

  const setThrottle = useCallback(
    (v: number) => {
      const c = clamp(v)
      throttleRef.current = c
      setThrottleState(c)
      doSend(true)
    },
    [doSend],
  )

  const setSteering = useCallback(
    (v: number) => {
      const c = clamp(v)
      steeringRef.current = c
      setSteeringState(c)
      doSend(true)
    },
    [doSend],
  )

  const zero = useCallback(() => {
    throttleRef.current = 0
    steeringRef.current = 0
    setThrottleState(0)
    setSteeringState(0)
    doSend(true)
  }, [doSend])

  // Keyboard handling.
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (e: KeyboardEvent) => {
      // Ignore when typing in an input/textarea/select.
      const target = e.target as HTMLElement | null
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT')
      ) {
        return
      }
      let handled = true
      switch (e.key) {
        case 'w':
        case 'W':
        case 'ArrowUp':
          setThrottle(throttleRef.current + STEP)
          break
        case 's':
        case 'S':
        case 'ArrowDown':
          setThrottle(throttleRef.current - STEP)
          break
        case 'a':
        case 'A':
        case 'ArrowLeft':
          setSteering(steeringRef.current - STEP)
          break
        case 'd':
        case 'D':
        case 'ArrowRight':
          setSteering(steeringRef.current + STEP)
          break
        case ' ':
          zero()
          break
        default:
          handled = false
      }
      if (handled) e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, setThrottle, setSteering, zero])

  // Heartbeat: resend while any value is nonzero.
  useEffect(() => {
    const id = setInterval(() => {
      if (throttleRef.current !== 0 || steeringRef.current !== 0) {
        doSend(true)
      }
    }, HEARTBEAT_MS)
    return () => clearInterval(id)
  }, [doSend])

  return {
    throttle,
    steering,
    setThrottle,
    setSteering,
    zero,
    enabled,
    setEnabled,
  }
}
