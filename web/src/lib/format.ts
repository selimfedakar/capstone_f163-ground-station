// Small formatting helpers used across views.

const DASH = '–'

export function fixed(v: number | null | undefined, digits = 2): string {
  return v == null || Number.isNaN(v) ? DASH : v.toFixed(digits)
}

export function kmh(v: number | null | undefined): string {
  return v == null ? DASH : (v * 3.6).toFixed(1)
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (v == null) return DASH
  const s = v.toFixed(digits)
  return v > 0 ? `+${s}` : s
}

export function lapTime(v: number | null | undefined): string {
  return v == null ? DASH : v.toFixed(2)
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return DASH
  const s = Math.max(0, Math.round(seconds))
  const m = Math.floor(s / 60)
  return m > 0 ? `${m} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`
}

export function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function dayAndTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString([], {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Acceleration in g, from m/s^2. */
export function gForce(v: number | null | undefined): string {
  return v == null ? DASH : (v / 9.81).toFixed(2)
}

/** Elapsed time as m:ss.t */
export function raceClock(seconds: number | null | undefined): string {
  if (seconds == null) return DASH
  const s = Math.max(0, seconds)
  const m = Math.floor(s / 60)
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`
}

export function whole(v: number | null | undefined): string {
  return v == null ? DASH : Math.round(v).toLocaleString('en')
}
