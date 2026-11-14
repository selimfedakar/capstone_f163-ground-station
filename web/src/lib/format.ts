// Small formatting helpers used across views.

export function mps(v: number | null | undefined): string {
  return v == null ? '--' : v.toFixed(2)
}

export function kmh(v: number | null | undefined): string {
  return v == null ? '--' : (v * 3.6).toFixed(1)
}

export function volts(v: number | null | undefined): string {
  return v == null ? '--' : v.toFixed(2)
}

export function deg(v: number | null | undefined): string {
  return v == null ? '--' : `${Math.round(v)}°`
}

export function secs(v: number | null | undefined): string {
  return v == null ? '--' : `${v.toFixed(2)} s`
}

export function pct(v: number | null | undefined): string {
  return v == null ? '--' : `${v.toFixed(2)} %`
}

export function clockTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString()
}

export function dateTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleString()
}
