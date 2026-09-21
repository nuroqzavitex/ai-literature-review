# Repository Guidelines

## Project Structure & Module Organization

The Python 3.12 backend lives in `src/`: FastAPI routes are under `src/api/routers/`, agent workflows under `src/agents/`, shared integrations under `src/services/`, and schemas under `src/models/`. The isolated research sandbox and its own test suite live in `src/research_sandbox_service/`. Repository-wide backend tests are grouped by concern in `tests/` (`test_api/`, `test_agents/`, `test_services/`, and `v2/`). The Next.js 16/React 19 application is in `frontend/app/`; Playwright scenarios are in `frontend/e2e/`. Database changes belong in `alembic/versions/` or `supabase/migrations/`, as appropriate. Keep documentation in `docs/` and evaluation tooling/data in `benchmarks/` and `eval/`.

## Build, Test, and Development Commands

- `uv sync` installs backend dependencies from `pyproject.toml` and `uv.lock`.
- `uv run uvicorn src.main:app --reload --port 8000` starts the API locally.
- `docker compose up --build` starts the complete local stack, including frontend and data services.
- `pytest tests/ -v --cov=src --cov-fail-under=60` runs the core suite with the CI coverage gate.
- `pytest src/research_sandbox_service/tests/ -q` runs the sandbox suite.
- `ruff check src/ tests/` and `ruff format --check src/ tests/` reproduce Python CI checks.
- From `frontend/`, run `npm ci`, `npm run dev`, `npm run check`, and `npm run test:e2e` for installation, development, static checks, and browser tests.

## Coding Style & Naming Conventions

Use four-space indentation, double quotes, and a 120-character line limit for Python; Ruff enforces imports, naming, modernization, linting, and formatting. Use `snake_case` for modules/functions and `PascalCase` for classes. TypeScript uses two spaces, semicolons, double quotes, strict typing, and Next.js ESLint rules. React components use `PascalCase`; route directories and utility files should follow the existing lowercase naming patterns.

## Testing Guidelines

Pytest discovers `test_*.py`; name tests `test_<behavior>` and use `pytest-asyncio` for async paths. Add tests beside the relevant suite and keep default PR tests deterministic. Mark live-network checks `external`, browser tests `browser`, and adjudicated evaluations `gold`. Maintain at least 60% backend coverage. Playwright specs use `*.spec.ts`.

## Commit & Pull Request Guidelines

History favors short, imperative subjects with optional Conventional Commit prefixes, such as `docs: update directory structure` or `refactor: restructure research-sandbox`. Keep commits focused. PRs should explain the problem and solution, list verification commands, link relevant issues, and include screenshots for UI changes. Call out migrations, new environment variables, or operational impact; ensure CI passes before review.

## Security & Configuration

Copy `.env.example` to `.env` and never commit credentials, provider keys, database URLs, or Clerk/Sandbox secrets. Document new settings in `.env.example` with safe placeholder values.
