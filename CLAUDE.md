# Urban Public Transit Reliability & Delay Monitor

Portfolio project. Polls GTFS-Realtime feeds (vehicle positions and trip updates) for two regions, Boston (MBTA) and Los Angeles (LA Metro bus and rail), matches them against each agency's static GTFS schedule to detect delays and headway gaps, aggregates hourly reliability metrics per route and direction, and serves them through a REST API. Full design, schema, and rationale are in [docs/DESIGN.md](docs/DESIGN.md). Read it only when a task needs details not covered here.

**Status:** milestones M0 through M5 are done, plus the Linecheck website in `web/` and multi-agency support (Los Angeles). LA Metro live feeds need `LA_METRO_API_KEY` in `.env` (the owner adds it; never paste or commit the key). Open items are listed under "Open items" in docs/DESIGN.md.

## Stack
- Python 3.12, managed with `uv`
- FastAPI + Pydantic v2 (API), pydantic-settings (config)
- SQLAlchemy 2 + psycopg 3, Alembic migrations, PostgreSQL 16
- APScheduler (single `worker` process), httpx, `gtfs-realtime-bindings`
- pytest, ruff, mypy; Docker Compose (`db`, `migrate`, `api`, `worker`, `web`); GitHub Actions CI
- Website (`web/`): React 19, TypeScript, Vite, Tailwind CSS v4, shadcn/ui, TanStack Query, React Router, Leaflet with OpenStreetMap tiles; fonts bundled locally with Fontsource; served by nginx in Docker

## Commands
```bash
cp .env.example .env                             # first time only
docker compose up -d db                          # Postgres on host port 5434 (5432 and 5433 are taken)
uv sync                                          # install deps
uv run alembic upgrade head                      # apply migrations
uv run alembic revision --autogenerate -m "msg"  # new migration
uv run uvicorn app.api.main:app --reload         # API on :8000
uv run python -m app.worker.scheduler            # background jobs
uv run python -m app.gtfs.static_loader          # load every agency's static GTFS now (--agency SLUG, --file PATH, --force)
uv run python -m app.pipeline.aggregate --hours 48  # rebuild hourly performance for recent hours (--agency SLUG)
uv run pytest                                    # all tests
uv run ruff check . && uv run mypy app           # lint + types

cd web && npm ci                                 # website dependencies
npm run dev                                      # website on :5173, proxies /api and /health to :8000
npm run lint && npm run build                    # website lint, type check, production build
docker compose up --build                        # everything; website on :8080, API on :8000
```

## Layout
```
app/core/config.py     settings from env (enabled regions, feed URLs, LA Metro API key, on-time window, retention days)
app/core/agencies.py   the agency and region registry (mbta; lametro-bus, lametro-rail) built from settings
app/core/job_health.py rules for when a job counts as ok, failing, stale, never_run, or not_configured (/health)
app/db/                models.py, session.py, partitions.py (daily vehicle_positions partitions)
app/gtfs/              static_loader.py (GTFS zip), realtime.py (fetch + protobuf decode), realtime_ingest.py (poll_once)
app/metrics/           delay.py, arrivals.py, headway.py, aggregate.py (pure functions)
app/pipeline/          stop_events.py, aggregate.py, retention.py (database orchestration for derived tables)
app/worker/            scheduler.py, jobs.py (load_static_gtfs, poll_realtime, derive_stop_events, aggregate_hourly, retention)
app/api/               main.py, dependencies.py (require_agency, require_region), routers/, schemas/
alembic/               migrations
tests/unit, tests/integration, tests/fixtures/*.pb (recorded feed snapshots); tests/agencies.py looks up agencies
web/src/router.tsx     addresses: /, /status, /how-it-works, /privacy, /terms, and /:region/(lines|rankings), /:region/lines/:agency/:routeId(/history)
web/src/pages/         one component per page (Home, RegionHome, Lines, LineLive, LineHistory, Rankings, Status, Methodology, Privacy, Terms, NotFound)
web/src/components/    shared pieces (layout/SiteLayout with city switcher, layout/RegionLayout, common, WeeklyGrid, VehicleMap, LineHeader); ui/ holds shadcn/ui primitives
web/src/lib/           api.ts (types + fetch), queries.ts (TanStack Query hooks), regions.ts (useRegion, linePath), format.ts, grid.ts, site.ts
web/nginx.conf         production routing: /api and /health to the api container, everything else to index.html
```

## Domain rules
- GTFS ids (`route_id`, `trip_id`, `stop_id`, `vehicle_id`) are **text**, never integers.
- Agencies: every table has an `agency` slug first in its primary key, and ids are only unique within an agency. Every query, upsert, delete, and API lookup must filter or key on agency. A region (`boston`, `los-angeles`) is what the website shows as a city and holds one or more agencies; API paths use `/regions/{region}` for city-wide views and `/agencies/{agency}/routes/{route_id}` for one route.
- Schedule times are seconds after "noon minus 12h" on `service_date`, and can exceed 86400 (e.g. 25:10:00). Always carry `service_date` with them.
- Local computations use the agency's own time zone (`Agency.timezone`: `America/New_York` for the MBTA, `America/Los_Angeles` for LA Metro); the global `TIMEZONE` setting is only for jobs that are not per agency. Every stored timestamp is `timestamptz` in UTC.
- An agency whose feeds need a key (LA Metro) only gets live jobs scheduled when the key is set; without it `/health` reports those jobs as `not_configured` (not a failure) and API responses carry `realtime_configured: false`.
- MBTA feeds usually omit `delay`. Delay = observed or predicted arrival − scheduled arrival, matched on `trip_id` + `stop_sequence`.
- On-time window comes from config (default −60s to +300s). Never hardcode it.
- Frequent routes (scheduled headway ≤ 15 min) are also judged on headway adherence and excess wait time.
- Severity (config-driven): `on_time` inside the window, `early` before it, `minor` late up to 10 min, `major` up to 20 min, `severe` beyond, `unknown` with no estimate. Route severity uses the median delay of vehicles with an estimate.
- MBTA realtime feeds have no `delay` field and often omit the vehicle's `start_date`. Many subway trips are `ADDED` with no timetable, so their delay is `None` (never guess), and they produce no `stop_events`.
- Feeds never say when a vehicle reached a stop. `app/metrics/arrivals.py` estimates it between polls: the midpoint when a vehicle is caught stopped at the stop, schedule-weighted interpolation when it passed the stop between polls. The first stop of a trip never gets an arrival. Headway compares consecutive arrivals at the same route, direction, and stop.
- Hourly buckets are UTC hours; `day_of_week` (0 = Monday) and `hour_of_day` are local time. Combining hours weights delay figures by `sample_count` and headway figures by `headway_sample_count`.
- Rankings (both directions combined) skip routes below `min_samples`: `on_time` highest share first, `delay` smallest average absolute delay first, `headway` lowest headway CV first. The database only sums; averaging and ordering live in `app/metrics/aggregate.py`.
- Cancelled trips are not recorded yet, so no metric may claim to count them.

## Conventions
- Every function, method, and class (including tests, fixtures, and nested helpers) gets a `#` comment directly above its `def` or `class` line. Explain in plain English what it does and why, plus any non-obvious behavior (edge cases, locking, units). The owner reads these to understand the code later, so write for someone new to the project. Update the comment whenever the code changes. In TypeScript use `//` comments the same way, above every function, component, and hook, including the shadcn/ui files in `web/src/components/ui`.
- Website data comes only from the API through `web/src/lib/queries.ts`. Every page handles loading, error (with a working retry), and empty states, and never shows a number the API did not return.
- Database lookups by many keys at once must pass the keys as arrays and join with `unnest`, never as a literal `(a, b) IN ((...), ...)` list: at full daytime service those lists reach thousands of entries and Postgres fails with "stack depth limit exceeded".
- Metric logic lives in `app/metrics` as pure functions with unit tests. No DB or network calls there.
- All DB writes are idempotent: `INSERT ... ON CONFLICT` on each table's unique key, or (for recomputed aggregates) delete and rewrite a time window inside one transaction. Jobs must be safe to re-run.
- Every worker job takes a Postgres advisory lock (named `job_id(job, agency)`, e.g. `poll_realtime:mbta`) and logs to `ingest_runs` with its agency.
- `vehicle_positions` is range-partitioned by UTC day (`vehicle_positions_pYYYYMMDD`). The poller and the retention job create partitions (`app/db/partitions.py`), the retention job drops expired ones, and Alembic ignores them. Never `DELETE` rows from it.
- Retention (daily job, all config-driven): vehicle_positions 14 days, stop_events 90 days, route_hourly_performance 400 days (so a full-year `/historical` range still has data), ingest_runs 30 days, vehicle_latest 24 hours. Other tables are deleted from in small batches, each in its own transaction.
- A new scheduled job must be added to `expected_jobs` and `job_max_ages` in `app/core/job_health.py`, or `/health` will not report it (a unit test checks that scheduled jobs match `expected_jobs`).
- Schema changes go only through Alembic migrations.
- Tests never hit live agency endpoints. Use `tests/fixtures`. To test agency separation, load the same fixture as two agencies (`loaded_feed` and `loaded_la_rail_feed`).
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
