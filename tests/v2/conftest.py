"""Shared fixtures for all V2 test suites.

Design decisions aligned with test contract §3.2:
- Each test gets a fresh in-memory SQLite database (no shared state between tests).
- Fake clock and ID generator are injected so tests are deterministic.
- Actor matrix covers owner, researcher, reviewer (assigned + unassigned), outsider.
- Two sibling projects are created to catch missing project_id filters (SEC / IDOR).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

_COUNTER: int = 0


def _next_id(prefix: str = "id") -> str:
    """Return a stable, ordered fake ID for fixtures that need unique keys."""
    global _COUNTER  # noqa: PLW0603
    _COUNTER += 1
    return f"{prefix}_{_COUNTER:06d}"


def reset_counter() -> None:
    global _COUNTER  # noqa: PLW0603
    _COUNTER = 0


# ---------------------------------------------------------------------------
# Isolated SQLite database fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path):
    """Return a temporary SQLite path unique to each test invocation."""
    db_path = str(tmp_path / "v2_test.db")
    return db_path


# ---------------------------------------------------------------------------
# App client with isolated database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def v2_client(isolated_db, monkeypatch):
    """AsyncClient wired to a fresh in-memory FastAPI app instance.

    The PRODUCT_DATABASE_URL is overridden per test so V2 repository tables
    are created in an isolated file.  The V1 DATABASE_URL remains the default
    in-memory SQLite used by the V1 conftest client fixture.
    """
    monkeypatch.setenv("PRODUCT_DATABASE_URL", f"sqlite:///{isolated_db}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{isolated_db}")
    # Clear LRU-cached settings so env changes take effect.
    from src.config import get_settings

    get_settings.cache_clear()

    # Re-import app after env change so repositories pick up new DB path.
    import importlib

    import src.main as main_mod

    importlib.reload(main_mod)
    app = main_mod.app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Restore settings cache state for subsequent tests.
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# V2-isolated fixture: same pattern as test_v2_core.py v2_isolated
# Patches the global router-level singletons with fresh isolated instances.
# ---------------------------------------------------------------------------


@pytest.fixture()
def v2_isolated(tmp_path, monkeypatch):
    """Isolated V2 repository, job repository and service, wired into the router.

    Mirrors the pattern in tests/test_api/test_v2_core.py so V2 tests can
    use the same fixture without importing from test_v2_core.
    """
    from src.agents.litreview.application.copilot import V2Service
    from src.agents.litreview.infrastructure.repositories.copilot import V2Repository
    from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
    from src.api.routers import literature_reviews as routes
    from src.api.routers import research_copilot as v2_routes

    url = f"sqlite:///{tmp_path / 'v2_isolated.db'}"
    jobs = JobRepository(url)
    repository = V2Repository(url)
    job_service_mock = SimpleNamespace(run=AsyncMock(), resume=AsyncMock(), repository=jobs)
    service = V2Service(repository, jobs, job_service_mock)

    monkeypatch.setattr(v2_routes, "v2_repository", repository)
    monkeypatch.setattr(v2_routes, "v2_service", service)
    monkeypatch.setattr(v2_routes, "v1_repository", jobs)
    monkeypatch.setattr(v2_routes, "job_service", job_service_mock)
    monkeypatch.setattr(routes, "repository", jobs)
    monkeypatch.setattr(routes, "job_service", job_service_mock)

    # Also patch email service to avoid live Resend calls.
    import src.api.routers.research_copilot as _v2r

    monkeypatch.setattr(
        _v2r.invitation_email_service,
        "send_review_invitation",
        AsyncMock(return_value=SimpleNamespace(status="not_configured", provider_id=None, error=None)),
    )

    return repository, jobs, service


# ---------------------------------------------------------------------------
# V2 repository / service fixture (low-level, no HTTP)
# ---------------------------------------------------------------------------


@pytest.fixture()
def v2_repo(isolated_db):
    """Return a V2Repository bound to an isolated database.

    Useful for integration tests that operate below the HTTP layer.
    """
    import os

    os.environ["PRODUCT_DATABASE_URL"] = f"sqlite:///{isolated_db}"
    from src.config import get_settings

    get_settings.cache_clear()

    from src.agents.litreview.infrastructure.repositories.copilot import V2Repository

    repo = V2Repository()
    return repo


# ---------------------------------------------------------------------------
# Actor matrix
# ---------------------------------------------------------------------------

ACTOR_ALICE = "alice"  # project owner
ACTOR_BOB = "bob"  # researcher
ACTOR_REVIEWER = "rev_carol"  # assigned reviewer
ACTOR_OUTSIDER = "outsider"  # no membership in any project


@pytest.fixture()
def actor_matrix(v2_repo):
    """Create two projects with a full role matrix.

    Returns a SimpleNamespace with:
        .repo          – the V2Repository instance
        .project_a     – dict with project_id
        .project_b     – sibling project to catch missing project_id filters
        .owner_id      – ACTOR_ALICE (owner in project_a)
        .researcher_id – ACTOR_BOB  (researcher in project_a)
        .reviewer_id   – ACTOR_REVIEWER (reviewer in project_a)
        .outsider_id   – ACTOR_OUTSIDER (no membership anywhere)
    """
    repo = v2_repo

    # Bootstrap actors.
    for actor_id in [ACTOR_ALICE, ACTOR_BOB, ACTOR_REVIEWER, ACTOR_OUTSIDER]:
        repo.upsert_actor(
            actor_id=actor_id,
            email=f"{actor_id}@example.com",
            display_name=actor_id.capitalize(),
            provider="test",
        )

    project_a = repo.create_project(ACTOR_ALICE, "Project Alpha", "First project")
    project_b = repo.create_project(ACTOR_ALICE, "Project Beta", "Sibling project")

    repo.add_member(project_a["project_id"], ACTOR_BOB, "researcher")
    repo.add_member(project_a["project_id"], ACTOR_REVIEWER, "reviewer")
    # project_b intentionally has no other members.

    return SimpleNamespace(
        repo=repo,
        project_a=project_a,
        project_b=project_b,
        owner_id=ACTOR_ALICE,
        researcher_id=ACTOR_BOB,
        reviewer_id=ACTOR_REVIEWER,
        outsider_id=ACTOR_OUTSIDER,
    )


# ---------------------------------------------------------------------------
# HTTP-layer actor helpers (cookie-based session)
# ---------------------------------------------------------------------------


async def login_as(client: AsyncClient, actor_id: str, role: str = "researcher") -> None:
    """Bootstrap a session cookie for the given actor via the test-only endpoint."""
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"{role}:{actor_id}"})
    assert resp.status_code in (200, 201), f"Bootstrap failed for {actor_id}: {resp.text}"


async def logout(client: AsyncClient) -> None:
    await client.delete("/api/v1/auth/session")


# ---------------------------------------------------------------------------
# Null email transport (prevents live Resend calls in all V2 tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_live_email(monkeypatch):
    """Automatically stub Resend HTTP calls for every V2 test.

    Individual tests that need to assert email delivery behaviour can
    override `send_review_invitation` separately via monkeypatch.
    This fixture runs in addition to v2_isolated's own patching.
    """
    import src.api.routers.research_copilot as v2_routes

    try:
        monkeypatch.setattr(
            v2_routes.invitation_email_service,
            "send_review_invitation",
            AsyncMock(return_value=SimpleNamespace(status="not_configured", provider_id=None, error=None)),
        )
    except (AttributeError, TypeError):
        pass  # v2_isolated fixture may already have patched this
