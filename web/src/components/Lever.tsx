// A sprung lever for touch and mouse: drag to command, release to return to
// centre. Reports a value in [-1, 1] while held and null on release.

import { useCallback, useRef, useState, type PointerEvent } from 'react'

interface Props {
  orientation: 'vertical' | 'horizontal'
  /** Value currently being sent, used to place the thumb when keys drive it. */
  value: number
  onChange: (v: number | null) => void
  disabled?: boolean
  label: string
}

export function Lever({ orientation, value, onChange, disabled, label }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [held, setHeld] = useState(false)

  const read = useCallback(
    (e: PointerEvent) => {
      const r = ref.current!.getBoundingClientRect()
      const f =
        orientation === 'vertical'
          ? 1 - (e.clientY - r.top) / r.height
          : (e.clientX - r.left) / r.width
      const v = Math.max(-1, Math.min(1, f * 2 - 1))
      // A small dead zone makes centre easy to find with a thumb.
      return Math.abs(v) < 0.06 ? 0 : v
    },
    [orientation],
  )

  const down = (e: PointerEvent) => {
    if (disabled) return
    e.currentTarget.setPointerCapture(e.pointerId)
    setHeld(true)
    onChange(read(e))
  }
  const move = (e: PointerEvent) => {
    if (held) onChange(read(e))
  }
  const up = () => {
    if (!held) return
    setHeld(false)
    onChange(null)
  }

  const pct = ((value + 1) / 2) * 100
  const fill =
    orientation === 'vertical'
      ? { bottom: `${Math.min(50, pct)}%`, height: `${Math.abs(pct - 50)}%` }
      : { left: `${Math.min(50, pct)}%`, width: `${Math.abs(pct - 50)}%` }
  const thumb = orientation === 'vertical' ? { bottom: `${pct}%` } : { left: `${pct}%` }

  return (
    <div
      ref={ref}
      className={`lever ${orientation}${held ? ' held' : ''}${disabled ? ' disabled' : ''}`}
      role="slider"
      aria-label={label}
      aria-valuemin={-1}
      aria-valuemax={1}
      aria-valuenow={value}
      aria-disabled={disabled}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
    >
      <span className="lever-centre" />
      <span className="lever-fill" style={fill} />
      <span className="lever-thumb" style={thumb} />
    </div>
  )
}
