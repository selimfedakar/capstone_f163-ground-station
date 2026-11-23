// Typed REST client for the dashboard reads (§4).
// Uses relative URLs so the Vite dev proxy (and any reverse proxy in prod)
// forwards /api/* to the ground-station server.

import type {
  Health,
  Kpis,
  Lap,
  RaceDetail,
  RaceInfo,
  RaceSummary,
  Session,
  TelemetryRow,
  TrackSpec,
} from './contract'

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

export function getHealth(): Promise<Health> {
  return getJson<Health>('/api/health')
}

/** Sessions, newest first (as ordered by the server). */
export function getSessions(): Promise<Session[]> {
  return getJson<Session[]>('/api/sessions')
}

export interface TelemetryQuery {
  fromT?: number
  toT?: number
  limit?: number
}

export function getTelemetry(
  sessionId: number,
  query: TelemetryQuery = {},
): Promise<TelemetryRow[]> {
  const params = new URLSearchParams()
  if (query.fromT != null) params.set('from_t', String(query.fromT))
  if (query.toT != null) params.set('to_t', String(query.toT))
  if (query.limit != null) params.set('limit', String(query.limit))
  const qs = params.toString()
  return getJson<TelemetryRow[]>(
    `/api/sessions/${sessionId}/telemetry${qs ? `?${qs}` : ''}`,
  )
}

export function getLaps(sessionId: number): Promise<Lap[]> {
  return getJson<Lap[]>(`/api/sessions/${sessionId}/laps`)
}

export function getKpis(sessionId: number): Promise<Kpis> {
  return getJson<Kpis>(`/api/sessions/${sessionId}/kpis`)
}

export function getTrack(): Promise<TrackSpec> {
  return getJson<TrackSpec>('/api/track')
}

// ---- CSV downloads (plain links; the browser saves them) ----

export const telemetryCsvUrl = (sessionId: number) => `/api/sessions/${sessionId}/telemetry.csv`
export const lapsCsvUrl = (sessionId: number) => `/api/sessions/${sessionId}/laps.csv`
export const raceCsvUrl = (raceId: number) => `/api/races/${raceId}/results.csv`

// ---- Races ----

export function getRaces(): Promise<RaceSummary[]> {
  return getJson<RaceSummary[]>('/api/races')
}

export function getRace(raceId: number): Promise<RaceDetail> {
  return getJson<RaceDetail>(`/api/races/${raceId}`)
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) {
    // The server explains refusals (no car connected, race already running).
    const detail = await res
      .json()
      .then((j: { detail?: unknown }) => (typeof j.detail === 'string' ? j.detail : null))
      .catch(() => null)
    throw new Error(detail ?? `${res.status} ${res.statusText}`)
  }
  return (await res.json()) as T
}

export interface RaceStartOptions {
  name?: string
  /** End the race when the first car completes this many laps. */
  laps?: number
  /** Send every car back to the start line first (default true). */
  reset?: boolean
}

export function startRace(options: RaceStartOptions): Promise<RaceInfo> {
  return postJson<RaceInfo>('/api/races', options)
}

export function finishRace(raceId: number): Promise<RaceInfo> {
  return postJson<RaceInfo>(`/api/races/${raceId}/finish`)
}
