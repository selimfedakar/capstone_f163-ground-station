// Connection status + latency badges, shown in the top bar on live views.

import type { WsStatus } from '../lib/ws'

function statusLabel(status: WsStatus, mock: boolean): string {
  if (mock) return 'MOCK'
  switch (status) {
    case 'open':
      return 'CONNECTED'
    case 'connecting':
      return 'CONNECTING'
    case 'closed':
      return 'OFFLINE'
  }
}

function statusDotClass(status: WsStatus, mock: boolean): string {
  if (mock) return 'yellow'
  if (status === 'open') return 'green'
  if (status === 'connecting') return 'yellow'
  return 'red'
}

function latencyClass(ms: number): string {
  if (ms < 50) return 'txt-green'
  if (ms < 150) return 'txt-yellow'
  return 'txt-red'
}

export function ConnectionBadge({
  status,
  mock,
}: {
  status: WsStatus
  mock: boolean
}) {
  return (
    <span className="pill">
      <span className={`dot ${statusDotClass(status, mock)}`} />
      {statusLabel(status, mock)}
    </span>
  )
}

export function LatencyBadge({ latencyMs }: { latencyMs: number | null }) {
  return (
    <span className="pill">
      <span className="txt-dim">RTT</span>
      {latencyMs == null ? (
        <span className="txt-dim">-- ms</span>
      ) : (
        <span className={latencyClass(latencyMs)}>{latencyMs} ms</span>
      )}
    </span>
  )
}
