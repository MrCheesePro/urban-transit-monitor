# Design: Urban Public Transit Reliability & Delay Monitor

## Goal
Monitor live vehicle feeds for Boston (MBTA), Los Angeles (LA Metro bus and rail), the LA municipal operators (LADOT Transit, Long Beach Transit, Torrance Transit), and Orange County (OCTA), detect delays against each scheduled timetable, and produce historical route performance metrics (delay, on-time percentage, headway variance) through a REST API.

## Agencies and regions
- An **agency** is one static GTFS feed plus its two realtime feeds: `mbta`, `lametro-bus`, `lametro-rail` (LA Metro publishes buses and trains as separate feeds), `ladot`, `longbeach`, `torrance`, `octa`. A **region** is a place on the website: `boston` holds `mbta`, `los-angeles` holds the two LA Metro agencies, `la-municipal` holds the city-run operators `ladot`, `longbeach`, and `torrance` (kept apart from LA Metro so their smaller networks are ranked against each other), and `orange-county` holds `octa`. The registry is `app/core/agencies.py`; `ENABLED_REGIONS` switches cities on. Only LA Metro's live feeds need a key; every other agency's feeds are open.
- One database for all agencies. Every table has an `agency` column first in its primary key (migration `7c1d2e3f4a5b`), so the same route, trip, stop, or vehicle id can exist in two agencies. `feed_versions` is unique on `(agency, version)`; `ingest_runs.agency` is null for jobs that cover everyone (retention).
- Each agency has its own time zone for service days, grid hours, and the 03:00 timetable job.
- Every job except retention runs once per agency, with its own advisory lock (`job:agency`).
- LA Metro timetables are open GitLab zips with an empty `feed_version`, so the loader falls back to a sha256 of the zip. LA Metro realtime comes from Swiftly (`api.goswift.ly/real-time/{lametro,lametro-rail}/gtfs-rt-*`) and needs `LA_METRO_API_KEY`, sent in `LA_METRO_API_KEY_HEADER` (default `Authorization`). Without a key the scheduler skips LA live jobs, `/health` reports them `not_configured`, and responses carry `realtime_configured: false`.

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

Data sources (per agency; the diagram shows the MBTA):
- MBTA static: `https://cdn.mbta.com/MBTA_GTFS.zip`
- MBTA realtime: `https://cdn.mbta.com/realtime/VehiclePositions.pb`, `https://cdn.mbta.com/realtime/TripUpdates.pb`
- LA Metro static: `https://gitlab.com/LACMTA/gtfs_bus/-/raw/master/gtfs_bus.zip`, `https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip`
- LA Metro realtime (API key): `https://api.goswift.ly/real-time/lametro/gtfs-rt-vehicle-positions` and `.../gtfs-rt-trip-updates`, and the same under `lametro-rail`

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
Every table below also has `agency text` as the first column of its primary key (and of `realtime_feed_state`'s key and the trips to routes foreign key). It is left out of the column lists for readability.

### Static GTFS
```sql
routes(route_id text PK, agency_id text, route_short_name text, route_long_name text,
       route_type smallint, route_sort_order int,
       route_color text, route_text_color text)   -- hex without "#", used for website badges
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
| `poll_alerts` | every `ALERTS_POLL_INTERVAL_SECONDS` (300) | Fetch the agency's service alerts and replace that agency's stored alerts, periods, and route links in one transaction. Replacing is what makes a withdrawn alert disappear: agencies simply stop publishing it |
| `derive_stop_events` | every 5 min | Trips with positions in the last 15 min: load their last 4 h of positions and timetable, estimate arrivals, upsert `stop_events`, recompute headways for the touched stops |
| `aggregate_hourly` | startup + hourly at :15 | Recompute the last `AGGREGATE_LOOKBACK_HOURS` (3) complete hours from `stop_events`: delete and rewrite that window in one transaction |
| `load_static_gtfs` | startup + daily 03:00 | Download zip, load in a transaction only if the version changed |
| `retention` | startup + daily 04:00 | Mark runs still "running" after `ORPHANED_RUN_TIMEOUT_SECONDS` (6 h) as `interrupted`, since a worker that died leaves them open forever. Then create partitions for today and the next `PARTITION_DAYS_AHEAD` (3) days, drop partitions older than `RETENTION_DAYS` (14), batch-delete stop_events older than 90 days, hourly rows older than 400 days, ingest_runs older than 30 days, and vehicle_latest rows not seen for 24 hours |

Every job takes `pg_try_advisory_lock(job_id)`, skips if already held, and writes an `ingest_runs` row.

## API (`/api/v1`)
| Endpoint | Returns |
|---|---|
| `GET /regions` | enabled regions with their agencies and `realtime_configured` per agency |
| `GET /regions/{region}/routes?route_type=` | the region's routes, agency order then sort order; 404 unknown region |
| `GET /regions/{region}/live` | region-wide snapshot (as `/system/live` below, across the region's agencies; `as_of` is the oldest agency's latest snapshot) |
| `GET /regions/{region}/rankings?...` | as `/performance/rankings` below, ranking the region's routes across its agencies |
| `GET /agencies/{agency}/routes/{id}/live` and `/historical` | as `/routes/{id}/live` and `/historical` below, in the agency's time zone; 404 unknown agency |
| `GET /regions/{region}/alerts` | service alerts in force now across the region's agencies, newest first, each with the agency's own cause, effect, text, and the routes it names; 404 unknown region |
| `GET /agencies/{agency}/routes/{id}/alerts` | alerts in force now that name this route, plus the agency's service-wide alerts (which name no route); 404 unknown agency |
| `GET /jobs/summary?hours=&job=&agency=` | one row per job and agency over the window: counts by outcome, `success_rate` (partial counts as success, skipped is excluded), p50/p90/max duration from `timed_run_count` finished runs, `rows_written`, and the most recent failure; `hours` 1-720, 404 unknown agency |
| `GET /jobs/history?hours=&job=&agency=` | run counts per UTC hour, every hour in the window returned so "no runs recorded" is explicit rather than a gap |
| `GET /jobs/runs?hours=&job=&agency=&status=&limit=&offset=` | individual runs newest first with `duration_seconds`, `rows`, and `error`, plus `total` and `has_more`; 422 for an unknown status |

The rows below describe the behavior of each view; their original single-agency paths were replaced by the paths above.

| Endpoint | Returns |
|---|---|
| `GET /routes/{id}/live?direction_id=` | vehicles seen in the last `LIVE_VEHICLE_MAX_AGE_SECONDS` (position, delay, severity), route summary, `as_of`, `data_age_seconds`, `stale`; 404 for unknown routes |
| `GET /routes/{id}/historical?direction_id=&start_date=&end_date=` | all 168 cells of the local day-of-week × hour grid (sample counts, avg and absolute delay, on-time %, avg headway, headway CV, excess wait) plus a period summary; local inclusive dates, default last 30 days, max 366; 404 unknown route, 422 bad range |
| `GET /performance/rankings?metric=on_time\|delay\|headway&days=30&min_samples=&route_type=&limit=` | routes ordered most → least reliable over complete hours, both directions combined, with `excluded_routes` for those below `min_samples`; days 1-90 |
| `GET /system/live` | network-wide snapshot of vehicles seen in the last `LIVE_VEHICLE_MAX_AGE_SECONDS`: severity counts, median and worst delay, the same per mode (route_type), data age |
| `GET /health` | always 200; `status` ok only if the database is up and every job that should run is ok. Per job and agency: `state` (ok, failing = latest finished run failed, stale = no success within its max age, never_run, not_configured = needs an API key and does not count against status), last status, last success, seconds since success, last error |

## Configuration (env, pydantic-settings)
`DATABASE_URL`, `ENABLED_REGIONS=["boston","los-angeles","la-municipal","orange-county"]`, `LA_METRO_API_KEY`, `LA_METRO_API_KEY_HEADER=Authorization`, `LA_METRO_BUS_STATIC_GTFS_URL`, `LA_METRO_BUS_VEHICLE_POSITIONS_URL`, `LA_METRO_BUS_TRIP_UPDATES_URL`, `LA_METRO_RAIL_STATIC_GTFS_URL`, `LA_METRO_RAIL_VEHICLE_POSITIONS_URL`, `LA_METRO_RAIL_TRIP_UPDATES_URL`, `LADOT_STATIC_GTFS_URL`, `LADOT_VEHICLE_POSITIONS_URL`, `LADOT_TRIP_UPDATES_URL`, `BIG_BLUE_BUS_STATIC_GTFS_URL`, `BIG_BLUE_BUS_VEHICLE_POSITIONS_URL`, `BIG_BLUE_BUS_TRIP_UPDATES_URL`, `LONG_BEACH_STATIC_GTFS_URL`, `LONG_BEACH_VEHICLE_POSITIONS_URL`, `LONG_BEACH_TRIP_UPDATES_URL`, `TORRANCE_STATIC_GTFS_URL`, `TORRANCE_VEHICLE_POSITIONS_URL`, `TORRANCE_TRIP_UPDATES_URL`, `OCTA_STATIC_GTFS_URL`, `OCTA_VEHICLE_POSITIONS_URL`, `OCTA_TRIP_UPDATES_URL`, `MBTA_VEHICLE_POSITIONS_URL`, `MBTA_TRIP_UPDATES_URL`, `MBTA_STATIC_GTFS_URL`, `MBTA_ALERTS_URL`, `LA_METRO_BUS_ALERTS_URL`, `LA_METRO_RAIL_ALERTS_URL`, `LADOT_ALERTS_URL`, `LONG_BEACH_ALERTS_URL`, `TORRANCE_ALERTS_URL`, `OCTA_ALERTS_URL`, `ALERTS_POLL_INTERVAL_SECONDS=300`, `HTTP_TIMEOUT_SECONDS=60`, `REALTIME_HTTP_TIMEOUT_SECONDS=15`, `POLL_INTERVAL_SECONDS=60`, `ON_TIME_EARLY_SECONDS=-60`, `ON_TIME_LATE_SECONDS=300`, `SEVERITY_MAJOR_SECONDS=600`, `SEVERITY_SEVERE_SECONDS=1200`, `LIVE_VEHICLE_MAX_AGE_SECONDS=300`, `FEED_STALE_AFTER_SECONDS=180`, `STOP_EVENTS_INTERVAL_SECONDS=300`, `STOP_EVENTS_ACTIVE_WINDOW_MINUTES=15`, `STOP_EVENTS_HISTORY_HOURS=4`, `STOP_EVENT_MAX_GAP_SECONDS=600`, `AGGREGATE_LOOKBACK_HOURS=3`, `HISTORICAL_DEFAULT_DAYS=30`, `FREQUENT_HEADWAY_SECONDS=900`, `RETENTION_DAYS=14`, `PARTITION_DAYS_AHEAD=3`, `STOP_EVENTS_RETENTION_DAYS=90`, `HOURLY_PERFORMANCE_RETENTION_DAYS=400`, `INGEST_RUNS_RETENTION_DAYS=30`, `VEHICLE_LATEST_RETENTION_HOURS=24`, `RETENTION_BATCH_SIZE=10000`, `RANKING_MIN_SAMPLES=200`, `TIMEZONE=America/New_York` (only for jobs that are not per agency).

## Testing
- Unit: pure functions in `app/metrics` (matching, delay, headway, aggregation), including post-midnight trips and cancelled trips.
- Integration: Postgres in Docker/CI. Load a small GTFS fixture, replay recorded `.pb` snapshots, assert `stop_events` and aggregates.
- API: FastAPI `TestClient` against seeded data.
- Agency separation: the fixture timetable is loaded as both `mbta` and `lametro-rail` so tests prove loads, polls, stop events, aggregates, rankings, and API views never mix agencies.
- Never call live agency endpoints in tests.

## Milestones
All of M0 through M5 are complete, plus the Linecheck website, multi-agency and multi-region support
(Boston, Los Angeles, the LA municipal operators, Orange County), service alerts, and deployment to a
public server.

- **M0** Scaffold: pyproject (uv), docker-compose, config, Alembic, CI (ruff, mypy, pytest).
- **M1** Static GTFS loader, `GET /routes`.
- **M2** Realtime polling, partitioned `vehicle_positions`, `vehicle_latest`, `GET /routes/{id}/live`.
- **M3** Trip matching, `stop_events`, delay and headway, with fixture-based tests.
- **M4** Hourly aggregation, `/historical`, `/performance/rankings`.
- **M5** Retention, `ingest_runs`, `/health`, README with diagram and screenshots.

## Open items
- Record CANCELED trips from trip updates so cancellations can be counted per hour.
- ADDED trips (common on MBTA subway) have no timetable, so they get no delay and no stop events. Headway for them could be measured from vehicle positions alone.
- LA Metro publishes neither `directions.txt` nor any `trip_headsign`, so its lines still show "Direction 0" and "Direction 1" while every other agency is named.
- Torrance Transit's timetable host blocks data centre IP addresses, so the nightly `load_static_gtfs:torrance` job fails on the deployed server (403) and its timetable is loaded by hand there. `/health` reports that job as failing, which is accurate. The permanent fix is for the agency to allow the server's address.
- Alerts are replaced on every poll, so withdrawn ones are not kept. Keeping them would allow joining causes (crashes, police activity) against the delay figures for the same hours.

## Website (Linecheck)
A React single-page app in `web/`, served by nginx in Docker at `http://localhost:8080` (or by Vite at `:5173` during development). nginx forwards `/api` and `/health` to the api container, so the browser only ever talks to one origin and the API needs no CORS setup.

| Page | Address | Data |
|---|---|---|
| Home | `/` | `/regions`, and `/regions/{region}/live` per city with live feeds connected |
| City overview | `/{region}` | `/regions/{region}/live` (network now, by mode), `/regions/{region}/rankings?days=1&min_samples=50` (most and least reliable) |
| Lines | `/{region}/lines` | `/regions/{region}/routes`, grouped by mode with search |
| Line live | `/{region}/lines/{agency}/{id}` | `/agencies/{agency}/routes/{id}/live` every 30 s: map, vehicle table with stop names, summary |
| Line history | `/{region}/lines/{agency}/{id}/history` | `/agencies/{agency}/routes/{id}/historical`: period totals and the weekly day-by-hour grid |
| Rankings | `/{region}/rankings` | `/regions/{region}/rankings`, filters kept in the address bar |
| Service news | `/{region}/service-news` | `/regions/{region}/alerts`: alerts in force now, newest first, with the agency's own cause and text. A shorter panel also appears on the city page, and a per-line one on each line's live page |
| Status | `/status` | `/health` every 30 s, one row per job and agency |
| Run history | `/status/history` | `/jobs/summary`, `/jobs/history`, and `/jobs/runs`: what each job has been doing, grouped by agency and job, an hour-by-hour timeline, and the individual runs with paging. Filters kept in the address bar; not refreshed on a timer, because a table that reshuffles while a reader pages through it is worse than a stale one |

The header has a city switcher that keeps the reader in the same section (lines or rankings). Times on city pages are in that city's time zone. A city without connected live feeds shows a plain notice in place of live figures and rankings; its lines and timetables still work.
| How it works, Privacy Policy, Terms & Conditions | `/how-it-works`, `/privacy`, `/terms` | static text |

Design: pale station-tile ground, ink text, a separate six-color severity scale (so it never collides with line colors, which only appear on route badges from `routes.route_color`; LA Metro buses have none and use a neutral badge), Big Shoulders Display for headings, Public Sans for text, IBM Plex Mono for numbers. Solid colors only; no scroll animations. The weekly grid is a real `<table>` so screen readers announce day and hour for every cell.

The live endpoint joins `stops` so vehicles are described by stop name ("Stopped at Harvard"); MBTA `stop_sequence` values jump in tens, so they are never shown to riders.

## Implementation notes
- Lookups by many keys (the poller's `(trip_id, stop_sequence)` schedule lookup and the headway recomputation's `(route_id, direction_id, stop_id)` groups) pass parallel arrays joined with `unnest`. The first version used a literal tuple `IN (...)` list, which worked in tests and overnight but failed at daytime scale with "stack depth limit exceeded". `tests/integration/test_large_key_lists.py` guards against it with 5,000 keys.
