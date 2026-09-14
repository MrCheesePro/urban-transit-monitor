// Types and fetch helpers for the Linecheck API (the FastAPI backend in app/). Field names match the
// JSON the API returns exactly. Timestamps are ISO 8601 strings in UTC.

export type Severity = 'on_time' | 'early' | 'minor' | 'major' | 'severe' | 'unknown'
export type RankingMetric = 'on_time' | 'delay' | 'headway'
export type JobState = 'ok' | 'failing' | 'stale' | 'never_run'

export interface Route {
  route_id: string
  agency_id: string | null
  route_short_name: string | null
  route_long_name: string | null
  route_type: number
  route_sort_order: number | null
  route_color: string | null
  route_text_color: string | null
}

export interface FleetSummary {
  vehicle_count: number
  vehicles_with_delay: number
  median_delay_seconds: number | null
  max_delay_seconds: number | null
  severity: Severity
  severity_counts: Record<Severity, number>
}

export interface LiveVehicle {
  vehicle_id: string
  label: string | null
  trip_id: string | null
  direction_id: number | null
  service_date: string | null
  stop_id: string | null
  stop_name: string | null
  stop_sequence: number | null
  current_status: string | null
  schedule_relationship: string | null
  lat: number | null
  lon: number | null
  bearing: number | null
  delay_seconds: number | null
  severity: Severity
  feed_timestamp: string
}

export interface LiveRoute {
  route_id: string
  route_short_name: string | null
  route_long_name: string | null
  route_type: number
  as_of: string | null
  data_age_seconds: number | null
  stale: boolean
  summary: FleetSummary
  vehicles: LiveVehicle[]
}

export interface ModeSummary {
  route_type: number | null
  vehicle_count: number
  vehicles_with_delay: number
  median_delay_seconds: number | null
  severity: Severity
}

export interface SystemLive {
  as_of: string | null
  data_age_seconds: number | null
  stale: boolean
  summary: FleetSummary
  modes: ModeSummary[]
}

export interface Performance {
  sample_count: number
  avg_delay_seconds: number | null
  avg_abs_delay_seconds: number | null
  on_time_percentage: number | null
  headway_sample_count: number
  avg_headway_seconds: number | null
  headway_cv: number | null
  excess_wait_seconds: number | null
}

export interface HistoricalCell extends Performance {
  day_of_week: number
  day_name: string
  hour_of_day: number
}

export interface HistoricalRoute {
  route_id: string
  route_short_name: string | null
  route_long_name: string | null
  route_type: number
  direction_id: number | null
  start_date: string
  end_date: string
  timezone: string
  summary: Performance
  cells: HistoricalCell[]
}

export interface RankedRoute {
  rank: number
  route_id: string
  route_short_name: string | null
  route_long_name: string | null
  route_type: number | null
  sample_count: number
  headway_sample_count: number
  on_time_percentage: number | null
  avg_delay_seconds: number | null
  avg_abs_delay_seconds: number | null
  headway_cv: number | null
}

export interface Rankings {
  metric: RankingMetric
  days: number
  min_samples: number
  route_type: number | null
  period_start: string
  period_end: string
  excluded_routes: number
  routes: RankedRoute[]
}

export interface JobHealth {
  job: string
  state: JobState
  last_status: string | null
  last_finished_at: string | null
  last_success_at: string | null
  seconds_since_success: number | null
  max_age_seconds: number
  last_error: string | null
}

export interface Health {
  status: 'ok' | 'degraded'
  database: 'up' | 'down'
  checked_at: string
  jobs: JobHealth[]
}

type QueryValue = string | number | null | undefined

// An API request that did not succeed. status is the HTTP status code, or 0 when the API could not
// be reached at all.
export class ApiError extends Error {
  status: number

  // Keep the HTTP status next to the message so pages can treat "not found" differently.
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// Build a path with query parameters, leaving out any parameter that has no value.
function withParams(path: string, params: Record<string, QueryValue> = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

// Fetch JSON from the API. When the request fails, throws an ApiError carrying the API's own
// explanation (FastAPI's "detail" field) so the page can show a specific message.
async function getJson<T>(path: string, params?: Record<string, QueryValue>): Promise<T> {
  let response: Response
  try {
    response = await fetch(withParams(path, params))
  } catch {
    throw new ApiError('The Linecheck API could not be reached.', 0)
  }
  if (!response.ok) {
    let detail = `The API answered with status ${response.status}.`
    try {
      const body: unknown = await response.json()
      if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
        detail = body.detail
      }
    } catch {
      // The body was not JSON (for example a proxy error page); keep the generic message.
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

export interface HistoricalParams {
  startDate: string
  endDate: string
  directionId?: number
}

export interface RankingsParams {
  metric: RankingMetric
  days: number
  minSamples: number
  routeType?: number
  limit?: number
}

export const api = {
  // Every route in the loaded timetable, in the MBTA's display order.
  routes: () => getJson<Route[]>('/api/v1/routes'),

  // Vehicles currently on one route, optionally in one direction.
  liveRoute: (routeId: string, directionId?: number) =>
    getJson<LiveRoute>(`/api/v1/routes/${encodeURIComponent(routeId)}/live`, {
      direction_id: directionId,
    }),

  // The whole network right now, split by mode.
  systemLive: () => getJson<SystemLive>('/api/v1/system/live'),

  // One route's weekly day-by-hour grid for a date range.
  historicalRoute: (routeId: string, params: HistoricalParams) =>
    getJson<HistoricalRoute>(`/api/v1/routes/${encodeURIComponent(routeId)}/historical`, {
      start_date: params.startDate,
      end_date: params.endDate,
      direction_id: params.directionId,
    }),

  // Routes ordered from most to least reliable.
  rankings: (params: RankingsParams) =>
    getJson<Rankings>('/api/v1/performance/rankings', {
      metric: params.metric,
      days: params.days,
      min_samples: params.minSamples,
      route_type: params.routeType,
      limit: params.limit,
    }),

  // Database and background job health.
  health: () => getJson<Health>('/health'),
}
