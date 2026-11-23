// Typed WebSocket client for /ws/ui.
// - Auto-reconnect with exponential backoff capped at 5 s.
// - Sends the UI `hello` on open.
// - Decodes incoming frames to the ServerToUiMsg union and dispatches to a
//   single listener; sends ControlMsg/PingMsg out.

import type {
  ControlMsg,
  PingMsg,
  ResetMsg,
  ServerToUiMsg,
  UiHelloMsg,
} from './contract'

export type WsStatus = 'connecting' | 'open' | 'closed'

export interface WsClientHandlers {
  onMessage: (msg: ServerToUiMsg) => void
  onStatus: (status: WsStatus) => void
}

const BACKOFF_BASE_MS = 500
const BACKOFF_MAX_MS = 5000

/** Resolve the ws:// (or wss://) URL for /ws/ui using the current host. */
export function resolveUiWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/ui`
}

export class UiWsClient {
  private ws: WebSocket | null = null
  private handlers: WsClientHandlers
  private url: string
  private attempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private closedByUser = false

  constructor(handlers: WsClientHandlers, url: string = resolveUiWsUrl()) {
    this.handlers = handlers
    this.url = url
  }

  connect(): void {
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    this.handlers.onStatus('connecting')
    let ws: WebSocket
    try {
      ws = new WebSocket(this.url)
    } catch {
      this.scheduleReconnect()
      return
    }
    this.ws = ws

    ws.onopen = () => {
      this.attempt = 0
      this.handlers.onStatus('open')
      const hello: UiHelloMsg = { type: 'hello', client: 'web' }
      this.rawSend(hello)
    }

    ws.onmessage = (ev: MessageEvent) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(ev.data as string)
      } catch {
        return
      }
      if (parsed && typeof parsed === 'object' && 'type' in parsed) {
        this.handlers.onMessage(parsed as ServerToUiMsg)
      }
    }

    ws.onerror = () => {
      // The close handler drives reconnect; nothing to do here.
    }

    ws.onclose = () => {
      this.ws = null
      this.handlers.onStatus('closed')
      if (!this.closedByUser) this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer != null) return
    const delay = Math.min(
      BACKOFF_MAX_MS,
      BACKOFF_BASE_MS * 2 ** this.attempt,
    )
    this.attempt += 1
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (!this.closedByUser) this.open()
    }, delay)
  }

  private rawSend(msg: unknown): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  /** Ask the server for a fresh `state` (it answers any `hello`). */
  sendHello(): void {
    const hello: UiHelloMsg = { type: 'hello', client: 'web' }
    this.rawSend(hello)
  }

  sendControl(msg: ControlMsg): void {
    this.rawSend(msg)
  }

  sendReset(msg: ResetMsg): void {
    this.rawSend(msg)
  }

  sendPing(msg: PingMsg): void {
    this.rawSend(msg)
  }

  isOpen(): boolean {
    return this.ws != null && this.ws.readyState === WebSocket.OPEN
  }

  close(): void {
    this.closedByUser = true
    if (this.reconnectTimer != null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.handlers.onStatus('closed')
  }
}
