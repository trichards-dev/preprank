# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

PrepRank — LHSAA high school sports power rankings with Monte Carlo playoff predictions. Subscription web + mobile product. A two-language monorepo: TypeScript (Next.js web) and Python (FastAPI API + simulation engine).

## Monorepo layout & the npm/Python split

This is the single most important thing to understand before running anything: **npm workspaces only cover `apps/web` and `packages/shared`.** The two Python projects are installed and run separately — they are NOT npm workspaces.

- `apps/web` — Next.js 14 App Router + Tailwind (npm workspace `@preprank/web`)
- `packages/shared` — shared TS types/constants (npm workspace)
- `apps/api` — FastAPI backend; install with `pip install -e ".[dev]"` from `apps/api`
- `packages/engine` — `preprank-engine`, the power-rating + Monte Carlo core (NumPy/SciPy); installed/tested independently
- `apps/mobile` — Expo React Native (early; uses mock data)
- `supabase/`, `scripts/`, `data/`, `docs/`

## Commands

Web / workspace (run from repo root):
- `npm install` — install web + shared
- `npm run dev:web` — Next.js dev on **port 3001**
- `npm run build:web` — production build (this is what Vercel runs: `cd apps/web && npm run build`)
- `npm run lint` — ESLint (next lint) on the web app

API (from `apps/api`, in its own venv):
- `pip install -e ".[dev]"`
- `npm run dev:api` from root **or** `uvicorn app.main:app --reload --port 8001`
- `pytest` — full API suite; single test: `pytest tests/test_routers_teams.py::test_name`
- `ruff check .` — lint

Engine (from `packages/engine`, own venv):
- `pip install -e ".[dev]"` then `pytest`

Database (local):
- `docker compose up -d` — local Postgres on 5432
- Alembic migrations live in `apps/api/alembic/` (`alembic upgrade head`)

## Tests need a seeded database

Most API tests are unit-level and pass against an empty DB, but the integration tests in `apps/api/tests/test_integration.py` (and `test_score_ingestion.py::test_recalculate_ratings`) assert that seed data exists — they fail with a misleading `assert 0 > 0` if the DB is empty. The full local/CI sequence is: start Postgres → `alembic upgrade head` → seed → run pytest.

Seeding loads `data/seed/2025_football_power_ratings_final.csv` (the 298 football teams/ratings) via `supabase/seed/seed.py`. Run it from the repo root with `DATABASE_URL` set:

```
python supabase/seed/seed.py --csv data/seed/2025_football_power_ratings_final.csv
```

The script seeds sports → schools → teams → power_ratings in one transaction and commits only at the end (a missing CSV aborts the whole thing). CI (`.github/workflows/ci.yml`) runs exactly this between migrations and tests — do not re-add `|| true` to that step; masking a seed failure produces the confusing downstream test errors.

## Port reality (a known footgun)

The dev ports are inconsistent across files — align them or local dev silently fails to connect:
- API dev script (`dev:api`) runs uvicorn on **8001**; the README example says 8000.
- The web client (`apps/web/src/lib/api.ts`) defaults its base URL to **`http://localhost:8002`**.

Set `NEXT_PUBLIC_API_URL` in `apps/web` to the port you actually run the API on (or change `dev:api`). Don't assume the defaults match.

## API architecture

- Entry: `apps/api/app/main.py`. Every router is mounted under **`/api/v1/*`** (schools, teams, games, ratings, simulations, auth, subscriptions, favorites, pickem, share, hype, scenarios). Health at `/health`. CORS origins come from `settings.CORS_ORIGINS`.
- DB layer (`app/database.py`): **synchronous** SQLAlchemy + psycopg2, `pool_pre_ping`, and `connect_args={"sslmode":"require"}` auto-added when `DATABASE_URL` contains "supabase". Do not reintroduce async/asyncpg (see archive caveat below).
- Auth: app-issued JWTs (python-jose + bcrypt pinned `<4.1.0` for passlib), 15-min access / 7-day refresh. Premium gating in `app/auth/premium.py`.
- The API consumes `packages/engine` for ratings/simulation math — keep simulation logic in the engine, not the routers.

## The web→API contract

`apps/web/src/lib/api.ts` is the single source of the frontend's API contract; `auth.tsx` handles login/register/me. Both expect `/api/v1/...` paths. If you change a route prefix in the API, update `api.ts` — they must match exactly.

## Deployment

- **Web:** Vercel project `preprank-web`, git-connected to this repo, **auto-deploys on push to `master`** (production branch is `master`, not `main`). Build = `cd apps/web && npm run build`.
- **API:** intended for a container host. `railway.json`, `fly.toml`, and `Dockerfile.api` all exist; the live API host is currently undecided/down — confirm before assuming an endpoint.

## Archive-branch caveat (avoid editing the wrong API)

The `archive/pre-consolidation` branch holds a **divergent, retired** API implementation: it uses a `/power-ratings` contract (no `/api/v1`), an async `asyncpg` engine, and a `models/` package instead of `app/models.py`. The canonical API on `master` is the `/api/v1` sync-SQLAlchemy one. If you encounter `power_ratings` routers or `create_async_engine`, you are looking at the old code — do not port its patterns forward.

## Skills to use on this project

- **`/software-design`** — the multi-agent design team (Product Manager, Solution Architect, DB Designer, Backend, Frontend, UX, Security, DevOps, QA, Claude AI Expert, Claude Code Expert). Invoke whenever this app needs a new architecture decision, a feature spec, a tech-stack/build-vs-buy evaluation, or a meaningful refactor that crosses multiple components. The 11 sub-agents run in parallel and produce a production-ready specification rather than a one-pass design. Don't reach for this for routine bug fixes or small changes — use it for the things that actually warrant the depth.
