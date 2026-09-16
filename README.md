# Linecheck: Urban Public Transit Reliability & Delay Monitor

A backend service and website that watch live vehicle feeds for four places, Boston (MBTA), Los Angeles (LA Metro bus and rail), the LA municipal operators (LADOT Transit, Long Beach Transit, Torrance Transit), and Orange County (OCTA), work out how late each bus and train is against the published timetable, reconstruct when vehicles actually reached each stop, and turn that into hourly on-time and headway statistics you can explore by city, line, hour, and day of week.

Status: milestones M0 through M5 are complete, plus the Linecheck website. See [docs/DESIGN.md](docs/DESIGN.md) for the full design, schema, and open items.

![Linecheck home page showing the live MBTA network](docs/images/website-home.png)

## What it measures

- **Live delay** for every vehicle on a line, with a severity label, the stop it is at or heading to, and a line-level summary.
- **Observed stop arrivals**, estimated between one-minute position snapshots, with the delay at each stop.
- **Headway**: the actual gap between consecutive vehicles at the same stop, next to the gap the timetable planned.
- **Hourly reliability** per line and direction: on-time percentage, average and 90th percentile delay, headway regularity (coefficient of variation), and the extra wait riders face when vehicles bunch.
- **Rankings** of lines from most to least reliable over a chosen period.

## Website

| Page | What it shows |
|---|---|
| Home | Each city with its vehicles reporting right now, split by severity |
| City overview (`/boston`, `/los-angeles`) | The city's network right now by severity and mode, plus its most and least reliable lines of the past 24 hours |
| Lines | Every route in the city's timetables grouped by mode, with search |
| Line live | A map and table of the line's vehicles with delay and stop names, refreshed every 30 seconds |
| Line history | Period totals and a weekly grid of on-time share, typical delay, or spacing by day and hour |
| Rankings | Lines ranked by on-time share, delay, or even spacing, with period, mode, and minimum-sample filters |
| Status | Whether each background job is running on schedule for each agency |
| How it works, Privacy Policy, Terms & Conditions | How every figure is calculated, and the site's policies |

![Red Line live page with map and vehicle delays](docs/images/website-line-live.png)

![Rankings page](docs/images/website-rankings.png)

## Architecture

```mermaid
flowchart LR
    subgraph SOURCES["Per agency: MBTA, LA Metro Bus and Rail, LADOT, Long Beach, Torrance, OCTA"]
        GTFS["Static GTFS zip (timetable)"]
        VP_FEED["Vehicle positions feed"]
        TU_FEED["Trip updates feed"]
    end

    subgraph WORKER["worker process (APScheduler), jobs run per agency"]
        LOAD["load_static_gtfs<br/>startup, daily 03:00"]
        POLL["poll_realtime<br/>every 60 s"]
        DERIVE["derive_stop_events<br/>every 5 min"]
        AGG["aggregate_hourly<br/>startup, hourly at :15"]
        RET["retention<br/>startup, daily 04:00"]
    end

    subgraph DB["PostgreSQL 16"]
        STATIC[("routes, trips, stops, stop_times")]
        POSITIONS[("vehicle_positions<br/>one partition per day")]
        LATEST[("vehicle_latest")]
        EVENTS[("stop_events")]
        HOURLY[("route_hourly_performance")]
        RUNS[("ingest_runs")]
    end

    API["api (FastAPI)<br/>/api/v1 and /health"]
    WEB["web (nginx + React)<br/>Linecheck website"]

    GTFS --> LOAD --> STATIC
    VP_FEED --> POLL
    TU_FEED --> POLL
    STATIC --> POLL
    POLL --> POSITIONS
    POLL --> LATEST
    POSITIONS --> DERIVE
    STATIC --> DERIVE
    DERIVE --> EVENTS --> AGG --> HOURLY
    RET -.-> POSITIONS
    RET -.-> EVENTS
    LATEST --> API
    HOURLY --> API
    RUNS --> API
    API --> WEB
```

Every job takes a Postgres advisory lock (one per job and agency) so two workers never run the same job at once, and records each run in `ingest_runs`, which `/health` and the Status page read.

One database holds every agency: each table has an `agency` column at the front of its primary key, so the same route, trip, or stop id can exist in two agencies without colliding. Each agency is processed in its own time zone.

## API

A region is a city (`boston`, `los-angeles`); an agency is one timetable and set of live feeds within it (`mbta`, `lametro-bus`, `lametro-rail`).

| Endpoint | What it returns |
|---|---|
| `GET /api/v1/regions` | The cities covered, their agencies, and whether each agency's live feeds are connected. |
| `GET /api/v1/regions/{region}/routes` | Every route in the city's timetables with its colors, in display order. Optional `route_type` filter. |
| `GET /api/v1/regions/{region}/live` | The city's network right now: severity counts, median and worst delay, and the same per mode. |
| `GET /api/v1/regions/{region}/rankings` | The city's routes ordered from most to least reliable by `on_time`, `delay`, or `headway`, with `days`, `min_samples`, `route_type`, and `limit` filters. |
| `GET /api/v1/agencies/{agency}/routes/{route_id}/live` | Vehicles currently on the route with estimated delay, severity, and stop name, a route summary, and data age. |
| `GET /api/v1/agencies/{agency}/routes/{route_id}/historical` | All 168 cells of a local day-of-week by hour-of-day grid, plus a period summary. Optional `direction_id`, `start_date`, `end_date`. |
| `GET /api/v1/regions/{region}/alerts` | Service alerts the city's agencies have in force right now, newest first, with each alert's cause, effect, text, and affected lines. |
| `GET /api/v1/agencies/{agency}/routes/{route_id}/alerts` | Alerts in force now affecting one line, including the agency's service-wide ones. |
| `GET /api/v1/jobs/summary` | How each background job has been doing over a window, grouped by job and agency: run counts by outcome, success rate, duration percentiles, rows written, and the most recent failure. |
| `GET /api/v1/jobs/history` | Run counts per hour over a window, with every hour returned so an hour with no runs is explicit. |
| `GET /api/v1/jobs/runs` | Individual runs, newest first, filtered by job, agency, and outcome, with paging and a total. |
| `GET /health` | Database status and the state of every background job per agency (ok, failing, stale, never_run, or not_configured when an API key is missing). |

Interactive documentation is served at `http://localhost:8000/docs`.

### Example responses

These are real MBTA responses from a local run on Monday, September 14, 2026, captured at 5:21 PM Boston time after about an hour of collecting data, before Los Angeles was added (the endpoints have since moved under regions and agencies, and responses now also carry `agency`). In that hour the worker stored 45,065 vehicle positions and derived 17,033 stop arrivals, 8,395 of them with a measured headway.

`GET /api/v1/agencies/mbta/routes/Red/live` (summary and first vehicle):

```json
{
  "route_id": "Red",
  "as_of": "2026-09-14T21:21:00Z",
  "data_age_seconds": 43,
  "stale": false,
  "summary": {
    "vehicle_count": 21,
    "vehicles_with_delay": 21,
    "median_delay_seconds": 269,
    "max_delay_seconds": 918,
    "severity": "on_time",
    "severity_counts": { "on_time": 11, "early": 0, "minor": 9, "major": 1, "severe": 0, "unknown": 0 }
  },
  "vehicles": [
    {
      "vehicle_id": "R-548B9B1F",
      "label": "1922",
      "direction_id": 0,
      "stop_id": "70097",
      "current_status": "INCOMING_AT",
      "delay_seconds": 269,
      "severity": "on_time"
    }
  ]
}
```

`GET /api/v1/regions/boston/rankings?days=1&min_samples=30&limit=3` (first three routes):

```json
{
  "metric": "on_time",
  "days": 1,
  "min_samples": 30,
  "period_start": "2026-09-13T21:00:00Z",
  "period_end": "2026-09-14T21:00:00Z",
  "excluded_routes": 26,
  "routes": [
    { "rank": 1, "route_id": "80", "on_time_percentage": 100.0, "avg_abs_delay_seconds": 137.5, "sample_count": 71 },
    { "rank": 2, "route_id": "556", "on_time_percentage": 100.0, "avg_abs_delay_seconds": 207.0, "sample_count": 37 },
    { "rank": 3, "route_id": "222", "on_time_percentage": 99.16, "avg_abs_delay_seconds": 77.2, "sample_count": 119 }
  ]
}
```

Fields not relevant to the example are omitted; the interactive documentation lists every field.

## How the numbers are computed

- **Live delay**: feeds do not reliably include a delay value, so it is the predicted arrival at the vehicle's next stop minus that stop's scheduled time. Trips added outside the timetable get no estimate rather than a guess.
- **Arrival times**: a snapshot says "in transit to stop 5" or "stopped at stop 7", never when a stop was reached. When a vehicle is caught stopped at a stop, its arrival is the midpoint between the two snapshots around it; when it passed a stop between snapshots, the time is interpolated using the timetable. The error is at most one poll interval.
- **Service day**: GTFS times can pass 24:00 (a 25:10 trip runs at 1:10 AM but belongs to the previous day), so every scheduled time is tied to its service date.
- **On time** means between 1 minute early and 5 minutes late by default. All thresholds are configurable.
- **Combining hours** weights each hour by the number of observations behind it, so percentages match what you would get from the raw events.
- **Rankings** leave out routes with fewer than `min_samples` observations (200 by default) so a route seen a handful of times cannot top the list by luck.

The details, including edge cases, are in [docs/DESIGN.md](docs/DESIGN.md) and on the website's How it works page.

## Quick start

Requires Docker. For local development you also need [uv](https://docs.astral.sh/uv/) and Node.js 24.

Run everything in containers:

```bash
docker compose up --build
```

This starts PostgreSQL, applies migrations, then runs the API on port 8000, the worker, and the website on port 8080 (`http://localhost:8080`). The worker loads every agency's timetable (a few minutes; LA Metro's bus timetable is the largest), starts polling the agencies whose live feeds are connected, derives stop arrivals after five minutes, and aggregates hourly statistics at 15 minutes past each hour, so rankings and the weekly grid fill in over the first hours of running.

Or run the pieces locally against the Compose database:

```bash
cp .env.example .env
docker compose up -d db                      # Postgres on host port 5434
uv sync
uv run alembic upgrade head
uv run python -m app.gtfs.static_loader      # load every agency's timetable (--agency mbta for one)
uv run uvicorn app.api.main:app --reload     # API at http://localhost:8000/docs
uv run python -m app.worker.scheduler        # background jobs

cd web && npm ci && npm run dev              # website at http://localhost:5173
```

To rebuild hourly statistics for recent hours, for example after the worker was stopped:

```bash
uv run python -m app.pipeline.aggregate --hours 48
```

## Configuration

Every setting can be overridden with an environment variable of the same name. The full list is in [.env.example](.env.example); the most useful ones:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://transit:transit@localhost:5434/transit` | Database connection |
| `ENABLED_REGIONS` | `["boston","los-angeles","la-municipal","orange-county"]` | Cities to follow |
| `POLL_INTERVAL_SECONDS` | `60` | How often live feeds are polled |
| `ON_TIME_EARLY_SECONDS` / `ON_TIME_LATE_SECONDS` | `-60` / `300` | On-time window |
| `SEVERITY_MAJOR_SECONDS` / `SEVERITY_SEVERE_SECONDS` | `600` / `1200` | Live severity cutoffs |
| `FREQUENT_HEADWAY_SECONDS` | `900` | Planned headway at or below which excess wait is computed |
| `RANKING_MIN_SAMPLES` | `200` | Minimum observations for a route to be ranked |
| `RETENTION_DAYS` | `14` | Days of raw vehicle positions kept |
| `STOP_EVENTS_RETENTION_DAYS` | `90` | Days of stop arrivals kept |
| `HOURLY_PERFORMANCE_RETENTION_DAYS` | `400` | Days of hourly statistics kept |

## Development

```bash
uv run pytest                                        # unit and integration tests
uv run ruff check . && uv run ruff format --check .  # lint and formatting
uv run mypy app                                      # strict type checking
cd web && npm run lint && npm run build              # website lint, type check, and build
```

Integration tests create and migrate a separate `transit_test` database automatically and are skipped when Postgres is not reachable. Tests never call live agency endpoints: they use a small hand-written timetable and recorded feed snapshots in `tests/fixtures`, loaded as more than one agency to check that agencies never mix. GitHub Actions runs linting, type checking, migrations, and the full test suite against PostgreSQL 16, and lints and builds the website, on every push.

## Project layout

```
app/api/        FastAPI app, routers, and response schemas
app/core/       settings, logging, and job health rules
app/db/         SQLAlchemy models, sessions, and partition helpers
app/gtfs/       static timetable loader and realtime feed polling
app/metrics/    pure functions: delay, arrivals, headway, hourly aggregation, rankings
app/pipeline/   jobs that build stop_events and hourly statistics, and retention
app/worker/     scheduler and job wrappers
alembic/        database migrations
tests/          unit and integration tests with fixtures
web/            Linecheck website (React, TypeScript, Vite, Tailwind, shadcn/ui)
docs/           design document and images
```

## Limitations

- Cancelled trips are not recorded yet, so no statistic counts them.
- Trips an agency adds outside the timetable (common for MBTA subway service and shuttles) get no delay estimate and no stop arrivals.
- Arrival times are estimates bounded by the polling interval, not exact door-open times.
- Direction names are not loaded yet, so the website shows "Direction 0" and "Direction 1".
- Foothill Transit, Culver CityBus, and Metrolink are not covered: their live feeds need a key or an approved request to the agency.
- Torrance Transit's timetable host answers 403 unless the request carries browser headers, so its agency entry sends them (`BROWSER_HEADERS` in `app/core/agencies.py`).
- Big Blue Bus is not covered: its live feed and its timetable use different trip ids and different route ids, so no delay, arrival, or ranking can be calculated from them.

## Data sources

Transit data comes from the public GTFS and GTFS-Realtime feeds of the Massachusetts Bay Transportation Authority, the Los Angeles County Metropolitan Transportation Authority (LA Metro's live data through Swiftly), LADOT Transit, Long Beach Transit, Torrance Transit, and the Orange County Transportation Authority. Map data is from OpenStreetMap contributors. This project is not affiliated with or endorsed by any of these agencies.
