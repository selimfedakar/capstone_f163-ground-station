// Line plots drawn on canvas.
//  - LivePlot: a rolling window read straight from the live store.
//  - XYPlot: fixed series for the post-race dashboard.
// A missing value (a sensor with no reading) breaks the line instead of being
// drawn as zero.

import { useCallback } from 'react'
import type { PlotRange, XAxis } from '../lib/axes'
import { theme } from '../lib/theme'
import { ROLLING_WINDOW_S, type LiveStore, type Sample } from '../lib/useConnection'
import { useCanvas } from './useCanvas'

interface Axis {
  x0: number
  x1: number
  y0: number
  y1: number
  yTicks: number[]
  xTicks: number[]
  xLabel: (x: number) => string
  yLabel: (y: number) => string
  /** Draw a heavier rule at this y value (e.g. zero, or a warning level). */
  mark?: { y: number; color: string }
}

const PAD = { left: 38, right: 10, top: 8, bottom: 22 }

function frame(ctx: CanvasRenderingContext2D, w: number, h: number, a: Axis) {
  const iw = w - PAD.left - PAD.right
  const ih = h - PAD.top - PAD.bottom
  const X = (x: number) => PAD.left + ((x - a.x0) / (a.x1 - a.x0)) * iw
  const Y = (y: number) => PAD.top + (1 - (y - a.y0) / (a.y1 - a.y0)) * ih

  ctx.font = `500 11px ${theme.font}`
  ctx.fillStyle = theme.muted
  ctx.strokeStyle = theme.rule
  ctx.lineWidth = 1
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'right'
  for (const t of a.yTicks) {
    const y = Math.round(Y(t)) + 0.5
    ctx.beginPath()
    ctx.moveTo(PAD.left, y)
    ctx.lineTo(w - PAD.right, y)
    ctx.stroke()
    ctx.fillText(a.yLabel(t), PAD.left - 6, y)
  }
  ctx.textBaseline = 'top'
  for (const t of a.xTicks) {
    // Keep the end labels inside the plot instead of clipping them.
    ctx.textAlign = t === a.x1 ? 'right' : t === a.x0 ? 'left' : 'center'
    ctx.fillText(a.xLabel(t), X(t), h - PAD.bottom + 6)
  }
  if (a.mark) {
    const y = Math.round(Y(a.mark.y)) + 0.5
    ctx.strokeStyle = a.mark.color
    ctx.setLineDash([5, 4])
    ctx.beginPath()
    ctx.moveTo(PAD.left, y)
    ctx.lineTo(w - PAD.right, y)
    ctx.stroke()
    ctx.setLineDash([])
  }
  return { X, Y }
}

function line(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  n: number,
  at: (i: number) => [number, number] | null,
  color: string,
  dots = false,
) {
  ctx.save()
  ctx.beginPath()
  ctx.rect(PAD.left, 0, w - PAD.left - PAD.right, h - PAD.bottom + 1)
  ctx.clip()
  ctx.beginPath()
  let pen = false
  const pts: [number, number][] = []
  for (let i = 0; i < n; i++) {
    const p = at(i)
    if (!p) {
      pen = false
      continue
    }
    if (pen) ctx.lineTo(p[0], p[1])
    else ctx.moveTo(p[0], p[1])
    pen = true
    if (dots) pts.push(p)
  }
  ctx.strokeStyle = color
  ctx.lineWidth = 1.75
  ctx.lineJoin = 'round'
  ctx.stroke()
  ctx.fillStyle = color
  for (const [x, y] of pts) {
    ctx.beginPath()
    ctx.arc(x, y, 3, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

export function LivePlot({
  store,
  cars,
  field,
  range,
  label,
}: {
  store: LiveStore
  cars: { id: string; color: string }[]
  field: keyof Omit<Sample, 't'>
  range: PlotRange
  label: string
}) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      const { X, Y } = frame(ctx, w, h, {
        x0: -ROLLING_WINDOW_S,
        x1: 0,
        y0: range.min,
        y1: range.max,
        yTicks: range.ticks,
        xTicks: [-60, -45, -30, -15, 0],
        xLabel: (x) => (x === 0 ? 'şimdi' : `${x} s`),
        yLabel: (y) => y.toFixed(range.digits),
        mark: range.mark,
      })
      // One shared "now" so cars line up in time.
      let now = 0
      for (const c of cars) {
        const hst = store.cars.get(c.id)?.history
        if (hst?.length) now = Math.max(now, hst[hst.length - 1].t)
      }
      for (const c of cars) {
        const hst = store.cars.get(c.id)?.history
        if (!hst?.length) continue
        line(
          ctx,
          w,
          h,
          hst.length,
          (i) => {
            const v = hst[i][field]
            return v == null ? null : [X(hst[i].t - now), Y(v)]
          },
          c.color,
        )
      }
    },
    [store, cars, field, range],
  )
  const ref = useCanvas(draw, 10)
  return <canvas ref={ref} className="plot" aria-label={label} />
}

export interface XYSeries {
  color: string
  points: { x: number; y: number | null }[]
}

export function XYPlot({
  series,
  range,
  x,
  dots,
  label,
}: {
  series: XYSeries[]
  range: PlotRange
  x: XAxis
  /** Mark each point, for a handful of values such as lap times. */
  dots?: boolean
  label: string
}) {
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      const { X, Y } = frame(ctx, w, h, {
        x0: x.x0,
        x1: x.x1,
        y0: range.min,
        y1: range.max,
        yTicks: range.ticks,
        xTicks: x.ticks,
        xLabel: x.label,
        yLabel: (y) => y.toFixed(range.digits),
        mark: range.mark,
      })
      for (const s of series) {
        line(
          ctx,
          w,
          h,
          s.points.length,
          (i) => {
            const p = s.points[i]
            return p.y == null ? null : [X(p.x), Y(p.y)]
          },
          s.color,
          dots,
        )
      }
    },
    [series, range, x, dots],
  )
  const ref = useCanvas(draw, 0)
  return <canvas ref={ref} className="plot" aria-label={label} />
}
