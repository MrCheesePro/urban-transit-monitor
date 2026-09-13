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
| 10 | `/live` would scan raw table | `vehicle_latest` table + short TTL cache |
| 11 | Cancelled/added trips ignored | Store `schedule_relationship`. Exclude CANCELED from delay, count separately |
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
  id bigint generated always as identity,
  feed_timestamp timestamptz NOT NULL,
  vehicle_id text NOT NULL, trip_id text, route_id text, direction_id smallint,
  stop_id text, stop_sequence int, current_status text, schedule_relationship text,
  lat double precision, lon double precision, service_date date,
  UNIQUE (vehicle_id, feed_timestamp)
) PARTITION BY RANGE (feed_timestamp);   -- one partition per day
```

### Derived
```sql
stop_events(
  trip_id text, service_date date, stop_sequence int,
  route_id text, direction_id smallint, stop_id text,
  scheduled_arrival timestamptz, observed_arrival timestamptz,
  delay_seconds int, headway_seconds int, scheduled_headway_seconds int,
  UNIQUE (trip_id, service_date, stop_sequence)
)

vehicle_latest(
  vehicle_id text PK, trip_id text, route_id text, direction_id smallint,
  stop_id text, current_status text, lat double precision, lon double precision,
  delay_seconds int, feed_timestamp timestamptz, updated_at timestamptz
)
```

### Aggregates
```sql
route_hourly_performance(
  id bigint PK, route_id text, direction_id smallint,
  hour_bucket timestamptz, day_of_week smallint, hour_of_day smallint,   -- local time
  avg_delay_seconds real, p90_delay_seconds real, on_time_percentage real,
  avg_headway_seconds real, headway_cv real, excess_wait_seconds real,
  cancelled_trips int, sample_count int,
  UNIQUE (route_id, direction_id, hour_bucket)
)
```

### Ops
```sql
ingest_runs(id bigint PK, job text, started_at timestamptz, finished_at timestamptz,
            rows int, status text, error text)
```

## Metric definitions
- **Delay:** `observed_arrival − scheduled_arrival` in seconds. Positive = late.
- **On-time:** delay within `[ON_TIME_EARLY_SECONDS, ON_TIME_LATE_SECONDS]`, default `[-60, 300]`.
- **Headway:** gap between consecutive observed arrivals at the same stop, route, and direction.
- **Headway CV:** stddev(headway) / mean(headway) per bucket. 0 = perfectly even.
- **Excess wait time:** average rider wait from actual headways minus average wait from scheduled headways. Rider wait ≈ E[h²] / (2·E[h]).
- **Frequent route:** scheduled headway ≤ 15 min. Rank these primarily on headway metrics.
- **Severity (live):** `on_time` inside the window, `minor` < 5 min, `major` < 15 min, `severe` ≥ 15 min.

## Worker jobs (APScheduler, one process)
| Job | Schedule | Details |
|---|---|---|
| `poll_realtime` | every 60s | Fetch both feeds concurrently. Skip if header timestamp unchanged. Bulk insert positions, upsert `vehicle_latest`, derive `stop_events` |
| `aggregate_hourly` | hourly at :15 | Recompute the last 3 hour buckets, upsert |
| `load_static_gtfs` | startup + daily 03:00 | Download zip, load in a transaction only if the version changed |
| `retention` | daily 04:00 | Create next 3 days of partitions, drop partitions older than `RETENTION_DAYS` (14) |

Every job takes `pg_try_advisory_lock(job_id)`, skips if already held, and writes an `ingest_runs` row.

## API (`/api/v1`)
| Endpoint | Returns |
|---|---|
| `GET /routes` | route list |
| `GET /routes/{id}/live` | vehicles (position, delay, severity), route summary, `data_age_seconds` |
| `GET /routes/{id}/historical?direction=&from=&to=` | 7×24 grid (day of week × hour): avg delay, on-time %, headway CV, samples |
| `GET /performance/rankings?days=30&metric=on_time\|delay\|headway&min_samples=200` | routes ordered most → least reliable, weighted by samples |
| `GET /health` | DB status, seconds since last successful poll |

## Configuration (env, pydantic-settings)
`DATABASE_URL`, `MBTA_VEHICLE_POSITIONS_URL`, `MBTA_TRIP_UPDATES_URL`, `MBTA_STATIC_GTFS_URL`, `POLL_INTERVAL_SECONDS=60`, `ON_TIME_EARLY_SECONDS=-60`, `ON_TIME_LATE_SECONDS=300`, `FREQUENT_HEADWAY_SECONDS=900`, `RETENTION_DAYS=14`, `RANKING_MIN_SAMPLES=200`, `TIMEZONE=America/New_York`.

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
