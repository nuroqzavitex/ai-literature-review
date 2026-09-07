import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app

# AsyncSqliteSaver relies on aiosqlite's worker thread.  The application runs
# under uvicorn[standard] on Linux, which selects uvloop; use the same event-loop
# implementation in tests so the checkpoint pause/resume path is exercised in
# the production-like runtime rather than hanging on Python 3.12's selector loop.
try:
    import uvloop
except ImportError:  # pragma: no cover - Windows does not support uvloop.
    pass
else:
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock
