// Bird's-eye track drawings.
//  - LiveMap: every connected car at its reported position, with a short trail.
//  - PathMap: the line one or more cars drove, coloured by speed or by car.
//
// The track is whatever the server describes (a centreline and a width), so
// nothing here assumes a particular shape: kerbs go on the inside of any bend,
// direction arrows on any straight, the chequered line across point 0.

import { useCallback } from 'react'
import { theme } from '../lib/theme'
import { gpsToLocal, type Pt, type Track } from '../lib/track'
import { useTrack } from '../lib/trackContext'
import type { LiveStore, Signal } from '../lib/useConnection'
import { useCanvas } from './useCanvas'

const CAR_LENGTH = 0.62
const CAR_WIDTH = 0.34
/** Inset, in metres, at which an out-of-view car is pinned. */
const EDGE = 0.5
/** Bends tighter than this radius get a kerb on the inside, metres. */
const KERB_MAX_RADIUS = 9
/** Flatter than this counts as a straight, for direction arrows. */
const STRAIGHT_MIN_RADIUS = 50
const ARROW_SPACING = 2
/** Same limits the server uses to tell a jump from driving (server/app/laps.py). */
const MAX_PLAUSIBLE_SPEED = 15
const MIN_JUMP_M = 1

interface Mark {
  x: number
  y: number
  /** Direction of travel, radians counter-clockwise from +x. */
  angle: number
}

interface Shape {
  kerbs: Pt[][]
  arrows: Mark[]
  start: Mark
}

const shapes = new WeakMap<Track, Shape>()

/** Kerb runs, arrow positions and the start line, worked out once per track. */
function shapeOf(track: Track): Shape {
  const cached = shapes.get(track)
  if (cached) return cached
  const pts = track.centerline
  const n = pts.length
  // Look a few points either side so sampling noise does not read as a bend.
  const k = Math.max(1, Math.round(n / 130))
  const kerbs: Pt[][] = []
  const arrows: Mark[] = []
  let run: Pt[] = []
  let sinceArrow = ARROW_SPACING / 2
  let along = 0

  for (let i = 0; i < n; i++) {
    const a = pts[(i - k + n) % n]
    const p = pts[i]
    const b = pts[(i + k) % n]
    const v1 = { x: p.x - a.x, y: p.y - a.y }
    const v2 = { x: b.x - p.x, y: b.y - p.y }
    const l1 = Math.hypot(v1.x, v1.y)
    const l2 = Math.hypot(v2.x, v2.y)
    const turn = Math.atan2(v1.x * v2.y - v1.y * v2.x, v1.x * v2.x + v1.y * v2.y)
    const curvature = turn / ((l1 + l2) / 2) // signed, positive = left
    const angle = Math.atan2(v1.y + v2.y, v1.x + v2.x)

    if (Math.abs(curvature) > 1 / KERB_MAX_RADIUS) {
      const side = Math.sign(curvature) // the inside of the bend
      const off = track.width / 2 - 0.04
      run.push({ x: p.x - Math.sin(angle) * side * off, y: p.y + Math.cos(angle) * side * off })
    } else if (run.length) {
      kerbs.push(run)
      run = []
    }

    const step = Math.hypot(pts[(i + 1) % n].x - p.x, pts[(i + 1) % n].y - p.y)
    along += step
    sinceArrow += step
    const nearLine = along < 1.4 || track.length - along < 0.6
    if (Math.abs(curvature) < 1 / STRAIGHT_MIN_RADIUS && sinceArrow >= ARROW_SPACING && !nearLine) {
      arrows.push({ x: p.x, y: p.y, angle })
      sinceArrow = 0
    }
  }
  if (run.length) kerbs.push(run)

  const start: Mark = {
    x: pts[0].x,
    y: pts[0].y,
    angle: Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x),
  }
  const shape = { kerbs, arrows, start }
  shapes.set(track, shape)
  return shape
}

interface View {
  width: number
  scale: number
  px: (x: number, y: number) => [number, number]
}

function makeView(track: Track, w: number, h: number): View {
  const v = track.view
  const scale = Math.min(w / (v.maxX - v.minX), h / (v.maxY - v.minY))
  const cx = (v.minX + v.maxX) / 2
  const cy = (v.minY + v.maxY) / 2
  return { width: w, scale, px: (x, y) => [w / 2 + (x - cx) * scale, h / 2 - (y - cy) * scale] }
}

function trace(ctx: CanvasRenderingContext2D, v: View, pts: Pt[], close: boolean) {
  ctx.beginPath()
  pts.forEach((p, i) => {
    const [x, y] = v.px(p.x, p.y)
    if (i === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  if (close) ctx.closePath()
}

function drawTrack(ctx: CanvasRenderingContext2D, track: Track, w: number, h: number): View {
  const v = makeView(track, w, h)
  const s = v.scale
  const shape = shapeOf(track)
  const edge = Math.max(1.5, s * 0.05)

  // Painted edge lines, then the asphalt over them.
  ctx.lineJoin = 'round'
  trace(ctx, v, track.centerline, true)
  ctx.strokeStyle = theme.paint
  ctx.lineWidth = track.width * s + edge * 2
  ctx.stroke()
  ctx.strokeStyle = theme.asphalt
  ctx.lineWidth = track.width * s
  ctx.stroke()

  // Kerbs on the inside of every bend.
  ctx.lineWidth = Math.max(3, s * 0.14)
  for (const run of shape.kerbs) {
    ctx.setLineDash([])
    ctx.strokeStyle = theme.paint
    trace(ctx, v, run, false)
    ctx.stroke()
    ctx.strokeStyle = theme.kerb
    ctx.setLineDash([s * 0.35, s * 0.35])
    trace(ctx, v, run, false)
    ctx.stroke()
  }

  // Centreline.
  ctx.setLineDash([s * 0.3, s * 0.45])
  ctx.strokeStyle = 'rgba(245, 246, 241, 0.22)'
  ctx.lineWidth = Math.max(1, s * 0.03)
  trace(ctx, v, track.centerline, true)
  ctx.stroke()
  ctx.setLineDash([])

  // Start/finish: a two-column chequered band across the track.
  {
    const [x, y] = v.px(shape.start.x, shape.start.y)
    const cell = (track.width / 6) * s
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-shape.start.angle)
    for (let col = 0; col < 2; col++) {
      for (let row = 0; row < 6; row++) {
        ctx.fillStyle = (col + row) % 2 === 0 ? theme.paint : theme.ink
        ctx.fillRect(col * cell, (row - 3) * cell, cell + 0.5, cell + 0.5)
      }
    }
    ctx.restore()
  }

  // Direction of travel, painted on the straights.
  ctx.strokeStyle = 'rgba(245, 246, 241, 0.5)'
  ctx.lineWidth = Math.max(1.5, s * 0.05)
  ctx.lineCap = 'round'
  const a = s * 0.22
  for (const m of shape.arrows) {
    const [x, y] = v.px(m.x, m.y)
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-m.angle)
    ctx.beginPath()
    ctx.moveTo(-a, -a)
    ctx.lineTo(a * 0.2, 0)
    ctx.lineTo(-a, a)
    ctx.stroke()
    ctx.restore()
  }
  ctx.lineCap = 'butt'

  // Scale bar.
  const [bx, by] = v.px(track.view.minX + 0.6, track.view.minY + 0.6)
  ctx.strokeStyle = theme.muted
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(bx, by - 4)
  ctx.lineTo(bx, by)
  ctx.lineTo(bx + 2 * s, by)
  ctx.lineTo(bx + 2 * s, by - 4)
  ctx.stroke()
  ctx.fillStyle = theme.muted
  ctx.font = `500 11px ${theme.font}`
  ctx.textBaseline = 'bottom'
  ctx.textAlign = 'left'
  ctx.fillText('2 m', bx + 2 * s + 6, by + 4)
  return v
}

function drawCar(
  ctx: CanvasRenderingContext2D,
  v: View,
  pos: Pt,
  headingDeg: number | null,
  color: string,
  opts: { selected: boolean; faded: boolean; label: string },
) {
  const [x, y] = v.px(pos.x, pos.y)
  const len = Math.max(18, CAR_LENGTH * v.scale)
  const wid = Math.max(10, CAR_WIDTH * v.scale)
  ctx.save()
  ctx.globalAlpha = opts.faded ? 0.4 : 1
  ctx.translate(x, y)
  if (opts.selected) {
    ctx.beginPath()
    ctx.arc(0, 0, len * 0.95, 0, Math.PI * 2)
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    ctx.stroke()
    ctx.setLineDash([])
  }
  if (headingDeg == null) {
    // No heading reading: a plain dot rather than a guessed direction.
    ctx.beginPath()
    ctx.arc(0, 0, wid * 0.7, 0, Math.PI * 2)
  } else {
    ctx.rotate((-headingDeg * Math.PI) / 180)
    // Body with a tapered nose so the heading reads at a glance.
    ctx.beginPath()
    ctx.moveTo(-len / 2, -wid / 2)
    ctx.lineTo(len * 0.18, -wid / 2)
    ctx.lineTo(len / 2, 0)
    ctx.lineTo(len * 0.18, wid / 2)
    ctx.lineTo(-len / 2, wid / 2)
    ctx.closePath()
  }
  ctx.fillStyle = color
  ctx.fill()
  ctx.strokeStyle = theme.paint
  ctx.lineWidth = 1.5
  ctx.stroke()
  ctx.restore()

  // Name tag, kept upright and inside the canvas.
  ctx.save()
  ctx.globalAlpha = opts.faded ? 0.55 : 1
  ctx.font = `600 12px ${theme.font}`
  const tw = ctx.measureText(opts.label).width
  const tx = x + len * 0.75 + tw + 8 > v.width ? x - len * 0.75 - tw : x + len * 0.75
  const ty = Math.max(12, y - len * 0.75)
  ctx.fillStyle = theme.paper
  ctx.fillRect(tx - 4, ty - 9, tw + 8, 18)
  ctx.fillStyle = color
  ctx.fillRect(tx - 4, ty - 9, 3, 18)
  ctx.fillStyle = theme.ink
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'left'
  ctx.fillText(opts.label, tx + 3, ty + 0.5)
  ctx.restore()
}

/** CSS aspect ratio that fits the track's view without wasted space. */
function aspectOf(track: Track): string {
  const v = track.view
  return `${(v.maxX - v.minX).toFixed(2)} / ${(v.maxY - v.minY).toFixed(2)}`
}

export interface MapCar {
  id: string
  color: string
  signal: Signal
}

export function LiveMap({
  store,
  cars,
  selected,
}: {
  store: LiveStore
  cars: MapCar[]
  selected?: string | null
}) {
  const track = useTrack()
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      const v = drawTrack(ctx, track, w, h)
      for (const car of cars) {
        const live = store.cars.get(car.id)
        if (!live) continue
        // Trail: older points fade out.
        const n = live.trail.length
        ctx.lineWidth = Math.max(2, v.scale * 0.08)
        ctx.lineCap = 'round'
        ctx.strokeStyle = car.color
        for (let i = 1; i < n; i++) {
          const [x0, y0] = v.px(live.trail[i - 1].x, live.trail[i - 1].y)
          const [x1, y1] = v.px(live.trail[i].x, live.trail[i].y)
          ctx.globalAlpha = (i / n) * (car.signal === 'live' ? 0.75 : 0.25)
          ctx.beginPath()
          ctx.moveTo(x0, y0)
          ctx.lineTo(x1, y1)
          ctx.stroke()
        }
        ctx.globalAlpha = 1
        ctx.lineCap = 'butt'
      }
      // Cars on top of every trail; the selected one last.
      const ordered = [...cars].sort((a, b) => Number(a.id === selected) - Number(b.id === selected))
      for (const car of ordered) {
        const live = store.cars.get(car.id)
        if (!live?.pos) continue
        // A car that has left the mapped area is pinned to the nearest edge
        // so it never silently disappears.
        const view = track.view
        const pos = {
          x: Math.max(view.minX + EDGE, Math.min(view.maxX - EDGE, live.pos.x)),
          y: Math.max(view.minY + EDGE, Math.min(view.maxY - EDGE, live.pos.y)),
        }
        const gone = pos.x !== live.pos.x || pos.y !== live.pos.y
        const heading = live.latest.heading_deg
        drawCar(ctx, v, pos, typeof heading === 'number' ? heading : null, car.color, {
          selected: car.id === selected,
          faded: car.signal !== 'live' || gone,
          label: gone ? `${car.id}, off the map` : car.id,
        })
      }
    },
    [store, cars, selected, track],
  )
  const ref = useCanvas(draw, 30)
  return (
    <canvas ref={ref} className="map" style={{ aspectRatio: aspectOf(track) }} aria-label="Pist haritası" />
  )
}

/** Blue (slow) through yellow to kerb red (fast). */
function speedColor(f: number): string {
  const stops = [
    [43, 108, 176],
    [232, 179, 26],
    [213, 51, 42],
  ]
  const x = Math.max(0, Math.min(1, f)) * 2
  const i = Math.min(1, Math.floor(x))
  const k = x - i
  const c = stops[i].map((a, j) => Math.round(a + (stops[i + 1][j] - a) * k))
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

export interface PathPoint {
  /** Car clock, seconds. */
  t: number
  lat: number | null
  lon: number | null
  speed_mps: number | null
}

export interface DrivenPath {
  rows: PathPoint[]
  /** Fixed colour for the whole line; omit to colour it by speed. */
  color?: string
}

export function PathMap({ paths, maxSpeed }: { paths: DrivenPath[]; maxSpeed: number }) {
  const track = useTrack()
  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, w: number, h: number) => {
      const v = drawTrack(ctx, track, w, h)
      ctx.lineCap = 'round'
      for (const path of paths) {
        ctx.lineWidth = Math.max(2.5, v.scale * (path.color ? 0.07 : 0.1))
        let prev: { px: [number, number]; x: number; y: number; t: number } | null = null
        for (const r of path.rows) {
          if (r.lat == null || r.lon == null) {
            prev = null // a gap in the position data, not a straight line
            continue
          }
          const p = gpsToLocal(track, r.lat, r.lon)
          const cur = { px: v.px(p.x, p.y), x: p.x, y: p.y, t: r.t }
          // A car cannot cover this much ground between two samples: it was
          // put back on the start line (or the fix jumped). Lift the pen.
          const jumped =
            prev != null &&
            Math.hypot(cur.x - prev.x, cur.y - prev.y) >
              Math.max(MIN_JUMP_M, MAX_PLAUSIBLE_SPEED * (cur.t - prev.t))
          if (prev && !jumped) {
            ctx.strokeStyle =
              path.color ?? speedColor(maxSpeed > 0 ? (r.speed_mps ?? 0) / maxSpeed : 0)
            ctx.beginPath()
            ctx.moveTo(prev.px[0], prev.px[1])
            ctx.lineTo(cur.px[0], cur.px[1])
            ctx.stroke()
          }
          prev = cur
        }
      }
      ctx.lineCap = 'butt'
    },
    [paths, maxSpeed, track],
  )
  const ref = useCanvas(draw, 0)
  return (
    <canvas ref={ref} className="map" style={{ aspectRatio: aspectOf(track) }} aria-label="İzlenen yol" />
  )
}
