"""Compatibility facade for research-gap job service."""

from src.agents.research_gap.application.service import (
    AcademicSearchService,
    HyDEQuery,
    ResearchGapJobService,
    get_llm,
    get_settings,
    rank_papers,
)

__all__ = [
    "AcademicSearchService",
    "HyDEQuery",
    "ResearchGapJobService",
    "get_llm",
    "get_settings",
    "rank_papers",
]
