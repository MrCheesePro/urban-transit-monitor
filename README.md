# Urban Public Transit Reliability & Delay Monitor

Monitors MBTA GTFS-Realtime feeds, detects delays and headway gaps against the published schedule, and serves hourly route reliability metrics over a REST API.

Status: **M3 complete (observed stop arrivals, delay, and headway in `stop_events`), M4 next**. See [docs/DESIGN.md](docs/DESIGN.md) for architecture, schema, and milestones.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run alembic upgrade head
uv run python -m app.gtfs.static_loader      # load the MBTA timetable (about a minute)
uv run uvicorn app.api.main:app --reload     # http://localhost:8000/docs
uv run python -m app.worker.scheduler        # background jobs
```

Or run everything in containers:

```bash
docker compose up --build
```

## Development

```bash
uv run pytest                     # unit + integration (integration skips without Postgres)
uv run ruff check . && uv run ruff format --check .
uv run mypy app
```
