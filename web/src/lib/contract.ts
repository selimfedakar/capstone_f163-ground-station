// TypeScript interfaces mirroring docs/CONTRACT.md (v1.1) exactly.
// These types are the single source of truth for message/REST shapes in the UI.

// ---- Shared ----

export type CarMode = 'manual' | 'auto'

/** A sensor field is null when the car has no valid reading for it (§2). */
export type Reading = number | null

export interface Imu {
  ax: Reading
  ay: Reading
  az: Reading
  gx: Reading
  gy: Reading
  gz: Reading
}

export interface Gps {
  lat: Reading
  lon: Reading
}

/** The race in progress, as announced by the server (§3, v1.1). */
export interface RaceInfo {
  id: number
  name: string
  laps_target: number | null
  started_at: number
  ended_at: number | null
  cars: string[]
}

// ---- WS /ws/ui : server -> UI ----

/** Current server state, sent in reply to the UI `hello`. (§3) */
export interface StateMsg {
  type: 'state'
  cars: CarState[]
  race?: RaceInfo | null
}

export interface CarState {
  car_id: string
  session_id: number
  mode: CarMode
  connected: boolean
  fw?: string | null
}

/** Telemetry row, broadcast verbatim as received from the car. (§2) */
export interface TelemetryMsg {
  type: 'telemetry'
  car_id: string
  seq: number
  t: number
  imu: Imu
  gps: Gps
  speed_mps: Reading
  heading_deg: Reading
  battery_v: Reading
  steering: Reading
  throttle: Reading
}

/**
 * Lap event (§3). Since v1.1 the server times laps itself: `source` is
 * 'server' for those, and 'car' for a lap the car reported that the server's
 * timing did not confirm (always `valid: false`, never counted).
 */
export interface LapMsg {
  type: 'lap'
  car_id: string
  lap_number: number
  lap_time_s: number
  t: number
  /** False when the car left track limits on this lap. */
  valid?: boolean
  source?: 'server' | 'car'
  off_track_s?: number | null
  race_id?: number | null
  race_lap?: number | null
  /** Time since the race started, at the end of this lap. */
  race_time_s?: number | null
}

export interface CarConnectedMsg {
  type: 'car_connected'
  car_id: string
  session_id: number
  mode?: CarMode
  fw?: string | null
}

/** A race started (`race` set) or finished (`race` null, `finished` set). */
export interface RaceMsg {
  type: 'race'
  race: RaceInfo | null
  finished?: RaceInfo & { reason: string }
}

/** The car acknowledged a command this UI sent (§3, v1.1). */
export interface ControlAckMsg {
  type: 'control_ack'
  car_id: string
  /** The `ts` of the command being acknowledged. */
  ts: number
  /** Server <-> car round trip for that command, measured on the server. */
  car_rtt_ms: number
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
  | RaceMsg
  | ControlAckMsg

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
  /** This UI's latest ping round trip, so the server can log end-to-end delay. */
  ui_rtt_ms?: number
}

export interface PingMsg {
  type: 'ping'
  ts: number
}

/** Ask a car to return to the start/finish line and stop. (§3, v1.1) */
export interface ResetMsg {
  type: 'reset'
  car_id: string
}

export type UiToServerMsg = UiHelloMsg | ControlMsg | PingMsg | ResetMsg

// ---- REST API (§4) ----

export interface Session {
  id: number
  car_id: string
  started_at: number
  ended_at: number | null
  mode: CarMode
  fw?: string | null
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
  /** Server clock when the frame arrived. */
  recv_t?: number | null
  /** 1 when the car was outside track limits, null if position was unusable. */
  off_track?: number | null
  /** Metres from the start/finish line along the lap. */
  track_s?: number | null
}

export interface Lap {
  lap_number: number
  lap_time_s: number
  t: number
  valid?: boolean | null
  source?: 'server' | 'car' | null
  off_track_s?: number | null
  /** What the car itself reported for this lap, as a cross-check. */
  car_time_s?: number | null
  race_id?: number | null
  race_lap?: number | null
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
  // ---- v1.1 ----
  invalid_laps?: number
  unconfirmed_car_laps?: number
  avg_moving_speed_mps?: number | null
  distance_m?: number
  moving_time_s?: number
  off_track_s?: number | null
  off_track_pct?: number | null
  max_accel_mps2?: number | null
  max_brake_mps2?: number | null
  max_lateral_mps2?: number | null
  telemetry_rate_hz?: number | null
  max_gap_s?: number | null
  sensor_error_rows?: number
  sensor_error_pct?: number
  sensor_errors?: Record<'gps' | 'imu' | 'speed' | 'heading' | 'battery', number>
  controls_sent?: number
  controls_acked?: number
  controls_lost?: number | null
  control_rtt_p50_ms?: number | null
  control_rtt_p95_ms?: number | null
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
}

/** GET /api/track */
export interface TrackSpec {
  name: string
  anchor: { lat: number; lon: number }
  width_m: number
  length_m?: number
  /** Local metres, driving order, point 0 on the start/finish line. */
  centerline: [number, number][]
}

/** One row of GET /api/races */
export interface RaceSummary {
  id: number
  name: string
  laps_target: number | null
  started_at: number
  ended_at: number | null
  cars: number
}

export interface RaceResult {
  position: number
  car_id: string
  session_id: number
  start_t: number | null
  end_t: number | null
  laps: number
  total_time_s: number | null
  gap_laps: number
  gap_s: number | null
  last_lap_s: number | null
  best_lap_s: number | null
  avg_lap_s: number | null
  invalid_laps: number
  max_speed_mps: number | null
  avg_moving_speed_mps: number | null
  distance_m: number | null
  off_track_s: number | null
  packet_loss_pct: number | null
  sensor_error_pct: number | null
  latency_p95_ms: number | null
  lap_times: { race_lap: number; lap_time_s: number; valid: boolean | null }[]
}

/** GET /api/races/{id} */
export interface RaceDetail {
  id: number
  name: string
  laps_target: number | null
  started_at: number
  ended_at: number | null
  results: RaceResult[]
}

export interface Health {
  status: string
}

// ---- Shared constants ----

export const LOW_BATTERY_V = 6.8
