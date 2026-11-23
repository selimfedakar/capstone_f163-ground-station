// The "?" beside a value. Hover, focus or tap shows a Turkish explanation of
// what the value is and how it is calculated.

import { useCallback, useId, useRef, useState, type ReactNode } from 'react'
import { GLOSSARY, type GlossaryKey } from '../lib/glossary'

const POP_WIDTH = 288

export function Hint({ k }: { k: GlossaryKey }) {
  const id = useId()
  const ref = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState({ dx: 0, above: false })

  const show = useCallback(() => {
    const el = ref.current
    if (el) {
      const r = el.getBoundingClientRect()
      const margin = 8
      // Keep the bubble inside the viewport horizontally.
      const left = Math.min(
        Math.max(margin, r.left + r.width / 2 - POP_WIDTH / 2),
        window.innerWidth - POP_WIDTH - margin,
      )
      setPlace({ dx: left - r.left, above: r.bottom + 190 > window.innerHeight })
    }
    setOpen(true)
  }, [])
  const hide = useCallback(() => setOpen(false), [])

  return (
    <span className="hint" ref={ref} onMouseEnter={show} onMouseLeave={hide}>
      <button
        type="button"
        className="hint-mark"
        aria-label="Açıklama"
        aria-describedby={open ? id : undefined}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          e.stopPropagation()
          if (open) hide()
          else show()
        }}
      >
        ?
      </button>
      {open && (
        <span
          role="tooltip"
          id={id}
          className={`hint-pop${place.above ? ' above' : ''}`}
          style={{ left: place.dx, width: POP_WIDTH }}
        >
          {GLOSSARY[k]}
        </span>
      )}
    </span>
  )
}

/** A label followed by its explanation mark. */
export function Label({ k, children }: { k: GlossaryKey; children: ReactNode }) {
  return (
    <span className="label">
      {children}
      <Hint k={k} />
    </span>
  )
}
