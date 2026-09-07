"""Domain routers for the literature engine and Research Copilot."""

from src.api.routers.literature_reviews import router as literature_reviews_router
from src.api.routers.research_copilot import router as research_copilot_router

__all__ = ["literature_reviews_router", "research_copilot_router"]
