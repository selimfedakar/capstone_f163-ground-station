// TypeScript interfaces mirroring docs/CONTRACT.md (v1) exactly.
// These types are the single source of truth for message/REST shapes in the UI.

// ---- Shared ----

export type CarMode = 'manual' | 'auto'

export interface Imu {
  ax: number
  ay: number
  az: number
  gx: number
  gy: number
  gz: number
}

export interface Gps {
  lat: number
  lon: number
}

// ---- WS /ws/ui : server -> UI ----

/** Current server state, sent in reply to the UI `hello`. (§3) */
export interface StateMsg {
  type: 'state'
  cars: CarState[]
}

export interface CarState {
  car_id: string
  session_id: number
  mode: CarMode
  connected: boolean
}

/** Telemetry row, broadcast verbatim as received from the car. (§2) */
export interface TelemetryMsg {
  type: 'telemetry'
  car_id: string
  seq: number
  t: number
  imu: Imu
  gps: Gps
  speed_mps: number
  heading_deg: number
  battery_v: number
  steering: number
  throttle: number
}

/** Lap completion event, broadcast verbatim. (§2) */
export interface LapMsg {
  type: 'lap'
  car_id: string
  lap_number: number
  lap_time_s: number
  t: number
}

export interface CarConnectedMsg {
  type: 'car_connected'
  car_id: string
  session_id: number
}

export interface CarDisconnectedMsg {
  type: 'car_disconnected'
  car_id: string
  session_id: number
}

/** Reply to a UI `ping`; used for the latency display. (§3) */
export interface PongMsg {
  type: 'pong'
  ts: number
  server_time: number
}

export type ServerToUiMsg =
  | StateMsg
  | TelemetryMsg
  | LapMsg
  | CarConnectedMsg
  | CarDisconnectedMsg
  | PongMsg

// ---- WS /ws/ui : UI -> server ----

export interface UiHelloMsg {
  type: 'hello'
  client: 'web'
}

/** Drive command. throttle/steering in [-1, 1]; server clamps. (§3) */
export interface ControlMsg {
  type: 'control'
  car_id: string
  throttle: number
  steering: number
  ts: number
}

export interface PingMsg {
  type: 'ping'
  ts: number
}

export type UiToServerMsg = UiHelloMsg | ControlMsg | PingMsg

// ---- REST API (§4) ----

export interface Session {
  id: number
  car_id: string
  started_at: number
  ended_at: number | null
  mode: CarMode
}

/** Flattened telemetry row as returned by REST (§5). */
export interface TelemetryRow {
  seq: number
  t: number
  ax: number | null
  ay: number | null
  az: number | null
  gx: number | null
  gy: number | null
  gz: number | null
  lat: number | null
  lon: number | null
  speed_mps: number | null
  heading_deg: number | null
  battery_v: number | null
  steering: number | null
  throttle: number | null
}

export interface Lap {
  lap_number: number
  lap_time_s: number
  t: number
}

export interface Kpis {
  session_id: number
  lap_count: number
  best_lap_s: number | null
  avg_lap_s: number | null
  max_speed_mps: number | null
  avg_speed_mps: number | null
  min_battery_v: number | null
  telemetry_rows: number
  seq_gaps: number
  packet_loss_pct: number
  duration_s: number
}

export interface Health {
  status: string
}

// ---- Shared constants ----

export const LOW_BATTERY_V = 6.8
