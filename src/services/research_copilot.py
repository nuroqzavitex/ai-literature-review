"""Compatibility facade for research copilot service."""

from src.agents.litreview.application.copilot import (
    QdrantVectorStore,
    V2Service,
    get_settings,
    validate_grounding_node,
)

__all__ = [
    "QdrantVectorStore",
    "V2Service",
    "get_settings",
    "validate_grounding_node",
]
