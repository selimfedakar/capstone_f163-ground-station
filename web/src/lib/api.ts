// Typed REST client for the dashboard reads (§4).
// Uses relative URLs so the Vite dev proxy (and any reverse proxy in prod)
// forwards /api/* to the ground-station server.

import type { Health, Kpis, Lap, Session, TelemetryRow } from './contract'

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
