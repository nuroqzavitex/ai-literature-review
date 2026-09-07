"""Langfuse integration for LangChain/LangGraph LLM observability."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.config import get_settings


@lru_cache(maxsize=1)
def get_langfuse_callback():
    """Return a LangChain callback only when Langfuse has been configured."""
    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler()


def langfuse_graph_config(*, job_id: str, operation: str) -> dict[str, Any] | None:
    """Configure one Langfuse trace at the root of a graph execution.

    LangGraph propagates this runnable config to its nodes and their nested
    LangChain calls, so LLM invocations become children of the graph trace
    rather than independent node-level traces.
    """
    callback = get_langfuse_callback()
    if callback is None:
        return None
    return {
        "callbacks": [callback],
        "run_name": "literature_review_graph",
        "metadata": {
            "langfuse_session_id": job_id,
            "langfuse_tags": ["litreview", "graph", operation],
            "litreview_operation": operation,
        },
    }
