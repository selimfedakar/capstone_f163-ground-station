// Small shared pieces: status flag, centre-zero meter, signal text.

import { theme } from '../lib/theme'
import type { Signal } from '../lib/useConnection'

/** A marshal's flag: the colour carries the state. */
export function Flag({ color }: { color: string }) {
  return (
    <svg className="flag" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <rect x="2" y="1" width="1.6" height="14" fill={theme.ink} />
      <path d="M3.6 2h10l-2.4 3.5 2.4 3.5h-10z" fill={color} stroke={theme.ink} strokeWidth="0.8" />
    </svg>
  )
}

/** Bar that grows left or right from centre for a value in [-1, 1]. */
export function Meter({ value }: { value: number | null | undefined }) {
  const v = Math.max(-1, Math.min(1, value ?? 0))
  const pct = ((v + 1) / 2) * 100
  return (
    <span className="meter" aria-hidden="true">
      <i style={{ left: `${Math.min(50, pct)}%`, width: `${Math.abs(pct - 50)}%` }} />
    </span>
  )
}

/** Bar for a value between min and max. */
export function Level({ value, min, max, warn }: { value: number | null | undefined; min: number; max: number; warn?: boolean }) {
  const f = value == null ? 0 : Math.max(0, Math.min(1, (value - min) / (max - min)))
  return (
    <span className={`level${warn ? ' warn' : ''}`} aria-hidden="true">
      <i style={{ width: `${f * 100}%` }} />
    </span>
  )
}

const SIGNAL_TEXT: Record<Signal, string> = { live: 'Live', stale: 'Stale', offline: 'Offline' }
const SIGNAL_COLOR: Record<Signal, string> = {
  live: theme.green,
  stale: theme.yellow,
  offline: theme.kerb,
}

export function SignalFlag({ signal }: { signal: Signal }) {
  return (
    <span className="signal">
      <Flag color={SIGNAL_COLOR[signal]} />
      {SIGNAL_TEXT[signal]}
    </span>
  )
}

export function Swatch({ color }: { color: string }) {
  return <span className="swatch" style={{ background: color }} aria-hidden="true" />
}
