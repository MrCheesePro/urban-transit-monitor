# Design: Urban Public Transit Reliability & Delay Monitor

## Goal
Monitor MBTA live vehicle feeds, detect delays against the scheduled timetable, and produce historical route performance metrics (delay, on-time percentage, headway variance) through a REST API.

## Architecture

```
[MBTA static GTFS zip] ──daily──▶ load_static_gtfs ──▶ routes, trips, stops, stop_times, calendar*
                                                                │ (schedule lookup)
[MBTA GTFS-RT .pb feeds] ──60s──▶ poll_realtime ───────────────┤
   VehiclePositions.pb            - decode protobuf             ▼
   TripUpdates.pb                 - dedup by (vehicle, ts)   vehicle_positions (partitioned by day)
                                  - upsert vehicle_latest    vehicle_latest
                                  - derive stop arrivals ──▶ stop_events (delay, headway)
                                                                │
                                     aggregate_hourly (:15) ◀───┘
                                     - re-aggregates last 3h (idempotent upsert)
                                                                ▼
                                                     route_hourly_performance
                                                                │
                                     FastAPI /api/v1  ◀─────────┘  (+ vehicle_latest for /live)

retention (daily): create future partitions, drop vehicle_positions partitions older than 14 days
```

Data sources:
- Static: `https://cdn.mbta.com/MBTA_GTFS.zip`
- Realtime: `https://cdn.mbta.com/realtime/VehiclePositions.pb`, `https://cdn.mbta.com/realtime/TripUpdates.pb`

## Why this differs from the original draft
| # | Gap in draft | Fix |
|---|---|---|
| 1 | No static schedule, so delay and scheduled headway can't be computed | Daily static GTFS loader, versioned via `feed_info` |
| 2 | `delay_seconds` assumed present in vehicle positions | MBTA omits it. Compute actual − scheduled from `stop_times` |
| 3 | Headway computed from raw GPS points | Derive `stop_events` (arrival per trip per stop). Headway = gap between consecutive arrivals at same stop, route, and direction |
| 4 | Schema lacks direction and time-of-day grouping | `direction_id`, `day_of_week`, `hour_of_day` on aggregates |
| 5 | On-time undefined | Configurable window, default −60s to +300s. Headway adherence for frequent routes |
| 6 | Purge right after aggregation loses late data | Re-aggregate last 3h with upserts. Keep raw data 14 days |
| 7 | Timezone and post-midnight trips ignored | `service_date` + GTFS seconds, `America/New_York`, UTC `timestamptz` |
| 8 | Dedup key unspecified | UNIQUE `(vehicle_id, feed_timestamp)`. Skip poll if feed header timestamp unchanged |
| 9 | ~1.4M raw rows/day | Daily range partitions, bulk inserts |
| 10 | `/live` would scan raw table | `vehicle_latest` table indexed by route (add a TTL cache only if load requires it) |
| 11 | Cancelled/added trips ignored | Store `schedule_relationship`; ADDED trips get no delay. Recording CANCELED trips from trip updates is still open, so no metric counts them |
| 12 | No failure handling | httpx timeouts/retries, `ingest_runs` log, advisory locks, staleness flag |
| 13 | Rankings noisy for low-volume routes | Weight by `sample_count`, `min_samples` threshold |
| 14 | "FastAPI / Express" undecided | FastAPI |

## Schema (PostgreSQL 16)

### Static GTFS
```sql
routes(route_id text PK, agency_id text, route_short_name text, route_long_name text,
       route_type smallint, route_sort_order int)
trips(trip_id text PK, route_id text FK, service_id text, direction_id smallint,
      trip_headsign text, shape_id text)
stops(stop_id text PK, stop_name text, lat double precision, lon double precision,
      location_type smallint, parent_station text)
stop_times(trip_id text, stop_sequence int, stop_id text, arrival_secs int, departure_secs int,
           PRIMARY KEY (trip_id, stop_sequence))   -- no FK to trips: keeps ~4M-row reloads fast
calendar(service_id text PK, monday..sunday bool, start_date date, end_date date)
calendar_dates(service_id text, date date, exception_type smallint, PRIMARY KEY (service_id, date))
feed_versions(id serial PK, version text UNIQUE, loaded_at timestamptz)
```

### Raw realtime
```sql
vehicle_positions(
  vehicle_id text, feed_timestamp timestamptz,
  label text, trip_id text, route_id text, direction_id smallint, service_date date,
  stop_id text, stop_sequence int, current_status text, schedule_relationship text,
  lat double precision, lon double precision, bearing double precision,
  delay_seconds int,                          -- estimate at poll time, null if unknown
  PRIMARY KEY (vehicle_id, feed_timestamp)    -- must include the partition key; also dedups
) PARTITION BY RANGE (feed_timestamp);        -- vehicle_positions_pYYYYMMDD per UTC day
-- index (route_id, feed_timestamp)

realtime_feed_state(feed text PK, header_timestamp timestamptz, entity_count int,
                    fetched_at timestamptz)  -- skip unchanged snapshots, report data age
```

### Derived
```sql
stop_events(
  trip_id text, service_date date, stop_sequence int,   -- PRIMARY KEY
  route_id text, direction_id smallint, stop_id text, vehicle_id text,
  observed_arrival timestamptz, scheduled_arrival timestamptz,
  delay_seconds int, headway_seconds int, scheduled_headway_seconds int,
  updated_at timestamptz
)  -- indexes: (route_id, direction_id, stop_id, observed_arrival), (observed_arrival)
-- not partitioned: roughly 500k rows/day at full service; revisit if retention grows

vehicle_latest(
  vehicle_id text PK, <same snapshot columns as vehicle_positions>,
  feed_timestamp timestamptz, updated_at timestamptz
)  -- upsert only moves forward in time; index on route_id
```

### Aggregates
```sql
route_hourly_performance(
  route_id text, direction_id smallint, hour_bucket timestamptz,   -- PRIMARY KEY; UTC hour
  day_of_week smallint, hour_of_day smallint,                      -- local time, 0 = Monday
  sample_count int,                                                -- events with a delay
  avg_delay_seconds double, avg_abs_delay_seconds double, p90_delay_seconds double,
  on_time_percentage double,
  headway_sample_count int,                                        -- events with a headway
  avg_headway_seconds double, avg_scheduled_headway_seconds double,
  headway_cv double, excess_wait_seconds double,
  updated_at timestamptz
)  -- index (hour_bucket). No cancelled_trips column: cancellations are not recorded yet.
```

### Ops
```sql
ingest_runs(id bigint PK, job text, started_at timestamptz, finished_at timestamptz,
            rows int, status text, error text)
```

## Metric definitions
- **Delay:** `observed_arrival − scheduled_arrival` in seconds. Positive = late.
- **On-time:** delay within `[ON_TIME_EARLY_SECONDS, ON_TIME_LATE_SECONDS]`, default `[-60, 300]`.
- **Observed arrival:** each snapshot places a vehicle at a position along its trip (stopped at stop i = i, in transit to stop i = i - 0.5; progress never goes backwards). A stop's arrival lies between the last snapshot before it and the first at or past it: the midpoint if the vehicle is caught stopped there, otherwise interpolated by scheduled time between the two positions. Skipped: the first stop, stops already passed when first seen, and stops whose surrounding snapshots are more than `STOP_EVENT_MAX_GAP_SECONDS` apart. Error is at most one poll interval.
- **Service date without start_date:** the local date of the first matching snapshot or the day before, whichever is closer to the timetable.
- **Headway:** gap between consecutive observed arrivals at the same stop, route, and direction. Gaps over 3 hours are service breaks. The scheduled headway is the planned gap between the same two trips, dropped if bunching reversed their order.
- **Headway CV:** population stddev(headway) / mean(headway) per hour, needs 2+ headways. 0 = perfectly even.
- **Hourly delay figures:** `avg_delay_seconds` (signed), `avg_abs_delay_seconds` (early counts against reliability too), `p90_delay_seconds` (linear interpolation), `on_time_percentage` (share inside the on-time window).
- **Combining hours** (grid cells, period summaries, rankings): delay figures weighted by `sample_count`, headway figures by `headway_sample_count`. On-time %, average delay, and average headway are exact; headway CV and excess wait are sample-weighted means of hourly values.
- **Rankings:** `on_time` highest first, `delay` lowest average absolute delay first, `headway` lowest CV first (requires `min_samples` headways). Ties: more samples, then route_id.
- **Excess wait time:** average rider wait from actual headways minus average wait from scheduled headways. Rider wait ≈ E[h²] / (2·E[h]).
- **Frequent route:** scheduled headway ≤ 15 min. Rank these primarily on headway metrics.
- **Live delay estimate:** for each vehicle, take its trip's first non-skipped predicted stop at or after the vehicle's `current_stop_sequence`, then predicted time minus scheduled time for that stop. If the trip has no `start_date`, try the local date of the prediction and the day before, and keep the smaller delay. `ADDED` trips have no timetable, so their delay is null.
- **Severity (live):** `on_time` inside the window, `early` before it, `minor` late up to `SEVERITY_MAJOR_SECONDS` (600), `major` up to `SEVERITY_SEVERE_SECONDS` (1200), `severe` beyond, `unknown` without an estimate. Route severity = severity of the median known delay.

## Worker jobs (APScheduler, one process)
| Job | Schedule | Details |
|---|---|---|
| `poll_realtime` | every 60s | Fetch both feeds concurrently. Skip if header timestamp unchanged. Bulk insert positions, upsert `vehicle_latest`, estimate live delay |
| `derive_stop_events` | every 5 min | Trips with positions in the last 15 min: load their last 4 h of positions and timetable, estimate arrivals, upsert `stop_events`, recompute headways for the touched stops |
| `aggregate_hourly` | startup + hourly at :15 | Recompute the last `AGGREGATE_LOOKBACK_HOURS` (3) complete hours from `stop_events`: delete and rewrite that window in one transaction |
| `load_static_gtfs` | startup + daily 03:00 | Download zip, load in a transaction only if the version changed |
| `retention` | daily 04:00 | Create next 3 days of partitions, drop partitions older than `RETENTION_DAYS` (14) |

Every job takes `pg_try_advisory_lock(job_id)`, skips if already held, and writes an `ingest_runs` row.

## API (`/api/v1`)
| Endpoint | Returns |
|---|---|
| `GET /routes` | route list |
| `GET /routes/{id}/live?direction_id=` | vehicles seen in the last `LIVE_VEHICLE_MAX_AGE_SECONDS` (position, delay, severity), route summary, `as_of`, `data_age_seconds`, `stale`; 404 for unknown routes |
| `GET /routes/{id}/historical?direction_id=&start_date=&end_date=` | all 168 cells of the local day-of-week × hour grid (sample counts, avg and absolute delay, on-time %, avg headway, headway CV, excess wait) plus a period summary; local inclusive dates, default last 30 days, max 366; 404 unknown route, 422 bad range |
| `GET /performance/rankings?metric=on_time\|delay\|headway&days=30&min_samples=&route_type=&limit=` | routes ordered most → least reliable over complete hours, both directions combined, with `excluded_routes` for those below `min_samples`; days 1-90 |
| `GET /health` | DB status, seconds since last successful poll |

## Configuration (env, pydantic-settings)
`DATABASE_URL`, `MBTA_VEHICLE_POSITIONS_URL`, `MBTA_TRIP_UPDATES_URL`, `MBTA_STATIC_GTFS_URL`, `HTTP_TIMEOUT_SECONDS=60`, `REALTIME_HTTP_TIMEOUT_SECONDS=15`, `POLL_INTERVAL_SECONDS=60`, `ON_TIME_EARLY_SECONDS=-60`, `ON_TIME_LATE_SECONDS=300`, `SEVERITY_MAJOR_SECONDS=600`, `SEVERITY_SEVERE_SECONDS=1200`, `LIVE_VEHICLE_MAX_AGE_SECONDS=300`, `FEED_STALE_AFTER_SECONDS=180`, `STOP_EVENTS_INTERVAL_SECONDS=300`, `STOP_EVENTS_ACTIVE_WINDOW_MINUTES=15`, `STOP_EVENTS_HISTORY_HOURS=4`, `STOP_EVENT_MAX_GAP_SECONDS=600`, `AGGREGATE_LOOKBACK_HOURS=3`, `HISTORICAL_DEFAULT_DAYS=30`, `FREQUENT_HEADWAY_SECONDS=900`, `RETENTION_DAYS=14`, `RANKING_MIN_SAMPLES=200`, `TIMEZONE=America/New_York`.

## Testing
- Unit: pure functions in `app/metrics` (matching, delay, headway, aggregation), including post-midnight trips and cancelled trips.
- Integration: Postgres in Docker/CI. Load a small GTFS fixture, replay recorded `.pb` snapshots, assert `stop_events` and aggregates.
- API: FastAPI `TestClient` against seeded data.
- Never call live MBTA endpoints in tests.

## Milestones
- **M0** Scaffold: pyproject (uv), docker-compose, config, Alembic, CI (ruff, mypy, pytest).
- **M1** Static GTFS loader, `GET /routes`.
- **M2** Realtime polling, partitioned `vehicle_positions`, `vehicle_latest`, `GET /routes/{id}/live`.
- **M3** Trip matching, `stop_events`, delay and headway, with fixture-based tests.
- **M4** Hourly aggregation, `/historical`, `/performance/rankings`.
- **M5** Retention, `ingest_runs`, `/health`, README with diagram and screenshots. Optional map dashboard.
