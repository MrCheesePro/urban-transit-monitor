# Linecheck: Urban Public Transit Reliability & Delay Monitor

A backend service and website that watch the MBTA's live vehicle feeds, work out how late each bus and train is against the published timetable, reconstruct when vehicles actually reached each stop, and turn that into hourly on-time and headway statistics you can explore by line, hour, and day of week.

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
| Home | Vehicles reporting across the network right now, split by severity and mode, plus the most and least reliable lines of the past 24 hours |
| Lines | Every MBTA route grouped by mode, with search |
| Line live | A map and table of the line's vehicles with delay and stop names, refreshed every 30 seconds |
| Line history | Period totals and a weekly grid of on-time share, typical delay, or spacing by day and hour |
| Rankings | Lines ranked by on-time share, delay, or even spacing, with period, mode, and minimum-sample filters |
| Status | Whether each background job is running on schedule |
| How it works, Privacy Policy, Terms & Conditions | How every figure is calculated, and the site's policies |

![Red Line live page with map and vehicle delays](docs/images/website-line-live.png)

![Rankings page](docs/images/website-rankings.png)

## Architecture

```mermaid
flowchart LR
    subgraph MBTA["MBTA open data"]
        GTFS["Static GTFS zip (timetable)"]
        VP_FEED["VehiclePositions.pb"]
        TU_FEED["TripUpdates.pb"]
    end

    subgraph WORKER["worker process (APScheduler)"]
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

Every job takes a Postgres advisory lock so two workers never run the same job at once, and records each run in `ingest_runs`, which `/health` and the Status page read.

## API

| Endpoint | What it returns |
|---|---|
| `GET /api/v1/routes` | Every route in the loaded timetable with its MBTA colors, in display order. Optional `route_type` filter. |
| `GET /api/v1/routes/{route_id}/live` | Vehicles currently on the route with estimated delay, severity, and stop name, a route summary, and data age. |
| `GET /api/v1/routes/{route_id}/historical` | All 168 cells of a local day-of-week by hour-of-day grid, plus a period summary. Optional `direction_id`, `start_date`, `end_date`. |
| `GET /api/v1/performance/rankings` | Routes ordered from most to least reliable by `on_time`, `delay`, or `headway`, with `days`, `min_samples`, `route_type`, and `limit` filters. |
| `GET /api/v1/system/live` | The whole network right now: severity counts, median and worst delay, and the same per mode. |
| `GET /health` | Database status and the state of every background job (ok, failing, stale, never_run). |

Interactive documentation is served at `http://localhost:8000/docs`.

### Example responses

These are real responses from a local run on Monday, September 14, 2026, captured at 5:21 PM Boston time after about an hour of collecting data. In that hour the worker stored 45,065 vehicle positions and derived 17,033 stop arrivals, 8,395 of them with a measured headway.

`GET /api/v1/routes/Red/live` (summary and first vehicle):

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

`GET /api/v1/performance/rankings?days=1&min_samples=30&limit=3` (first three routes):

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

- **Live delay**: MBTA feeds do not include a delay value, so it is the predicted arrival at the vehicle's next stop minus that stop's scheduled time. Trips added outside the timetable get no estimate rather than a guess.
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

This starts PostgreSQL, applies migrations, then runs the API on port 8000, the worker, and the website on port 8080 (`http://localhost:8080`). The worker loads the MBTA timetable (about a minute), starts polling immediately, derives stop arrivals after five minutes, and aggregates hourly statistics at 15 minutes past each hour, so rankings and the weekly grid fill in over the first hours of running.

Or run the pieces locally against the Compose database:

```bash
cp .env.example .env
docker compose up -d db                      # Postgres on host port 5434
uv sync
uv run alembic upgrade head
uv run python -m app.gtfs.static_loader      # load the MBTA timetable
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

Integration tests create and migrate a separate `transit_test` database automatically and are skipped when Postgres is not reachable. Tests never call live MBTA endpoints: they use a small hand-written timetable and recorded feed snapshots in `tests/fixtures`. GitHub Actions runs linting, type checking, migrations, and the full test suite against PostgreSQL 16, and lints and builds the website, on every push.

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
- Trips the MBTA adds outside the timetable (common for subway service and shuttles) get no delay estimate and no stop arrivals.
- Arrival times are estimates bounded by the polling interval, not exact door-open times.
- Direction names are not loaded yet, so the website shows "Direction 0" and "Direction 1".

## Data source

Transit data comes from the Massachusetts Bay Transportation Authority's public GTFS and GTFS-Realtime feeds. Map data is from OpenStreetMap contributors. This project is not affiliated with or endorsed by the MBTA.
