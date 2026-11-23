// Track geometry for the map views.
//
// The server owns the track definition (GET /api/track): a closed centreline
// in local metres, its width, and the GPS anchor that maps reported lat/lon
// onto it. The UI draws whatever it is given, so swapping the simulator's
// stadium for a real circuit is a server-side change only.
//
// DEFAULT_TRACK is that same stadium built locally (it mirrors sim/track.py),
// used until the server answers and by the standalone ?mock=1 demo.

import type { TrackSpec } from './contract'

const M_PER_DEG_LAT = 111_320

export interface Pt {
  x: number
  y: number
}

export interface Track {
  name: string
  anchor: { lat: number; lon: number }
  /** Width of the racing surface, metres. */
  width: number
  length: number
  centerline: Pt[]
  /** World window the map shows: the track plus room to run wide. */
  view: { minX: number; maxX: number; minY: number; maxY: number }
  mPerDegLon: number
}

/** Margin around the track kept in view, metres. */
const VIEW_MARGIN = 1.6

export function buildTrack(spec: TrackSpec): Track {
  const centerline = spec.centerline.map(([x, y]) => ({ x, y }))
  let length = 0
  let minX = Infinity
  let maxX = -Infinity
  let minY = Infinity
  let maxY = -Infinity
  centerline.forEach((p, i) => {
    const q = centerline[(i + 1) % centerline.length]
    length += Math.hypot(q.x - p.x, q.y - p.y)
    minX = Math.min(minX, p.x)
    maxX = Math.max(maxX, p.x)
    minY = Math.min(minY, p.y)
    maxY = Math.max(maxY, p.y)
  })
  const pad = spec.width_m / 2 + VIEW_MARGIN
  return {
    name: spec.name,
    anchor: spec.anchor,
    width: spec.width_m,
    length,
    centerline,
    view: { minX: minX - pad, maxX: maxX + pad, minY: minY - pad, maxY: maxY + pad },
    mPerDegLon: M_PER_DEG_LAT * Math.cos((spec.anchor.lat * Math.PI) / 180),
  }
}

export function gpsToLocal(track: Track, lat: number, lon: number): Pt {
  return {
    x: (lon - track.anchor.lon) * track.mPerDegLon,
    y: (lat - track.anchor.lat) * M_PER_DEG_LAT,
  }
}

export function localToGps(track: Track, x: number, y: number): { lat: number; lon: number } {
  return {
    lat: track.anchor.lat + y / M_PER_DEG_LAT,
    lon: track.anchor.lon + x / track.mPerDegLon,
  }
}

/** Distance from a point to the nearest part of the centreline, metres. */
export function distanceToCentreline(track: Track, p: Pt): number {
  const pts = track.centerline
  let best = Infinity
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const len2 = dx * dx + dy * dy
    const u = len2 > 0 ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2)) : 0
    const d = Math.hypot(p.x - (a.x + u * dx), p.y - (a.y + u * dy))
    if (d < best) best = d
  }
  return best
}

export function isOffTrack(track: Track, p: Pt): boolean {
  return distanceToCentreline(track, p) > track.width / 2
}

// ---- The simulator's stadium ------------------------------------------

const STRAIGHT_LEN = 8
const RADIUS = 3
const STADIUM_LENGTH = 2 * STRAIGHT_LEN + 2 * Math.PI * RADIUS

/** Point and heading (radians, counter-clockwise from +x) along the stadium lap. */
export function stadiumPointAt(d: number): Pt & { heading: number } {
  const half = STRAIGHT_LEN / 2
  const arc = Math.PI * RADIUS
  let s = ((d % STADIUM_LENGTH) + STADIUM_LENGTH) % STADIUM_LENGTH
  if (s < STRAIGHT_LEN) return { x: -half + s, y: -RADIUS, heading: 0 }
  s -= STRAIGHT_LEN
  if (s < arc) {
    const a = -Math.PI / 2 + s / RADIUS
    return { x: half + RADIUS * Math.cos(a), y: RADIUS * Math.sin(a), heading: a + Math.PI / 2 }
  }
  s -= arc
  if (s < STRAIGHT_LEN) return { x: half - s, y: RADIUS, heading: Math.PI }
  s -= STRAIGHT_LEN
  const a = Math.PI / 2 + s / RADIUS
  return { x: -half + RADIUS * Math.cos(a), y: RADIUS * Math.sin(a), heading: a + Math.PI / 2 }
}

export const STADIUM = { straight: STRAIGHT_LEN, length: STADIUM_LENGTH }

function stadiumSpec(): TrackSpec {
  const n = 400
  const centerline: [number, number][] = []
  for (let i = 0; i < n; i++) {
    const p = stadiumPointAt((i / n) * STADIUM_LENGTH)
    centerline.push([p.x, p.y])
  }
  return {
    name: 'Simulator stadium',
    anchor: { lat: 41.0421, lon: 29.0093 },
    width_m: 1.6,
    centerline,
  }
}

export const DEFAULT_TRACK: Track = buildTrack(stadiumSpec())
