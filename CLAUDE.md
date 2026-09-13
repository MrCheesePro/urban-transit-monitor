# Urban Public Transit Reliability & Delay Monitor

Portfolio project. Polls MBTA GTFS-Realtime feeds (vehicle positions and trip updates), matches them against the static GTFS schedule to detect delays and headway gaps, aggregates hourly reliability metrics per route and direction, and serves them through a REST API. Full design, schema, and rationale are in [docs/DESIGN.md](docs/DESIGN.md). Read it only when a task needs details not covered here.

**Current milestone:** M3 (trip matching, `stop_events`, observed arrivals, headway). M0, M1, and M2 are done. Milestones M0–M5 are listed in docs/DESIGN.md.

## Stack
- Python 3.12, managed with `uv`
- FastAPI + Pydantic v2 (API), pydantic-settings (config)
- SQLAlchemy 2 + psycopg 3, Alembic migrations, PostgreSQL 16
- APScheduler (single `worker` process), httpx, `gtfs-realtime-bindings`
- pytest, ruff, mypy; Docker Compose (`db`, `api`, `worker`); GitHub Actions CI

## Commands
```bash
cp .env.example .env                             # first time only
docker compose up -d db                          # Postgres on host port 5434 (5432 and 5433 are taken)
uv sync                                          # install deps
uv run alembic upgrade head                      # apply migrations
uv run alembic revision --autogenerate -m "msg"  # new migration
uv run uvicorn app.api.main:app --reload         # API on :8000
uv run python -m app.worker.scheduler            # background jobs
uv run python -m app.gtfs.static_loader          # load MBTA static GTFS now (--file PATH, --force)
uv run pytest                                    # all tests
uv run ruff check . && uv run mypy app           # lint + types
```

## Layout
```
app/core/config.py     settings from env (feed URLs, on-time window, retention days)
app/db/                models.py, session.py
app/gtfs/              static_loader.py (GTFS zip), realtime.py (fetch + protobuf decode)
app/metrics/           matching.py, delay.py, headway.py, aggregate.py (pure functions)
app/worker/            scheduler.py, jobs.py (poll_realtime, aggregate_hourly, load_static_gtfs, retention)
app/api/               main.py, routers/, schemas/
alembic/               migrations
tests/unit, tests/integration, tests/fixtures/*.pb (recorded feed snapshots)
```

## Domain rules
- GTFS ids (`route_id`, `trip_id`, `stop_id`, `vehicle_id`) are **text**, never integers.
- Schedule times are seconds after "noon minus 12h" on `service_date`, and can exceed 86400 (e.g. 25:10:00). Always carry `service_date` with them.
- Local computations use `America/New_York`. Every stored timestamp is `timestamptz` in UTC.
- MBTA feeds usually omit `delay`. Delay = observed or predicted arrival − scheduled arrival, matched on `trip_id` + `stop_sequence`.
- On-time window comes from config (default −60s to +300s). Never hardcode it.
- Frequent routes (scheduled headway ≤ 15 min) are also judged on headway adherence and excess wait time.
- CANCELED trips are excluded from delay averages and counted separately.
- Severity (config-driven): `on_time` inside the window, `early` before it, `minor` late up to 10 min, `major` up to 20 min, `severe` beyond, `unknown` with no estimate. Route severity uses the median delay of vehicles with an estimate.
- MBTA realtime feeds have no `delay` field and often omit the vehicle's `start_date`. Many subway trips are `ADDED` with no timetable, so their delay is `None` (never guess).
- Rankings weight by `sample_count` and skip routes below `min_samples`.

## Conventions
- Every function, method, and class (including tests, fixtures, and nested helpers) gets a `#` comment directly above its `def` or `class` line. Explain in plain English what it does and why, plus any non-obvious behavior (edge cases, locking, units). The owner reads these to understand the code later, so write for someone new to the project. Update the comment whenever the code changes.
- Metric logic lives in `app/metrics` as pure functions with unit tests. No DB or network calls there.
- All DB writes are idempotent: `INSERT ... ON CONFLICT` on each table's unique key. Jobs must be safe to re-run.
- Every worker job takes a Postgres advisory lock and logs to `ingest_runs`.
- `vehicle_positions` is range-partitioned by UTC day (`vehicle_positions_pYYYYMMDD`). The poller creates partitions as needed (`app/db/partitions.py`), the retention job (M5) drops old ones, and Alembic ignores them. Never `DELETE` rows from it.
- Schema changes go only through Alembic migrations.
- Tests never hit live MBTA endpoints. Use `tests/fixtures`.
- API routes are versioned under `/api/v1`. Responses use Pydantic schemas from `app/api/schemas`.

## Frontend and content rules (any website, dashboard, or docs page)
These are hard rules. Do not break them, even if a template or library does it by default.

- No `vercel.app` URL. Use a custom domain for anything public.
- No "Made with Lovable" badge, tag, or similar builder branding.
- No one-page site. Use real separate pages with their own routes.
- Required pages: Privacy Policy and Terms & Conditions, both linked in the footer of every page.
- No color gradients of any kind (no purple gradients, no gradient backgrounds, buttons, borders, or text). Solid colors only.
- No special color or gradient on hero text. Hero headings use the normal body text color.
- No vague hero copy ("Transform your commute", "The future of transit"). The hero says exactly what the product does, e.g. "Live MBTA delay and headway data by route".
- No AI-generated or stock "slop" photos. Use real screenshots, real maps, or real charts from this project's data.
- No text-only logos. Make a real logo mark (SVG).
- No missing or default favicon. Ship a custom favicon made from the logo mark.
- No emoji used as icons. Use an SVG icon set (e.g. Lucide) or custom SVGs.
- No cursive or script fonts.
- No scroll-triggered animations (fade-in or slide-in on scroll, parallax).
- No fake reviews or testimonials, no fake visitor counts, no customer or user counts, no invented metrics. Every number shown must come from real data in the database or API.
- No broken buttons or dead links. Every button and link must go somewhere real or be removed.
- No em dashes anywhere: UI copy, docs, comments, commit messages. Use commas, colons, parentheses, or separate sentences.

## Token-saving workflow
- `/find <symbol>` locates code (file:line only) before reading files.
- `/review-lite` reviews the diff, `/test-lite` shows only test failures, `/commit` commits.
- Run `/recap` before ending a session or compacting, and `/recall` at the start of the next one.
