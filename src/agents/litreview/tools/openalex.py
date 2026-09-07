"""Academic multi-source search tool.

OWNER: Member 2 / Leader
TECHNICAL CONTRACT SPEC: Mục 5.2

    @tool
    async def search_academic_sources(query: str, limit: int = 10) -> list[Paper]:
        \"\"\"Tìm paper có metadata + abstract từ các nguồn học thuật.\"\"\"

Chỉ được gọi từ `search_academic_sources_node`.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from src.agents.litreview.domain.models import Paper
from src.services.academic_search import AcademicSearchService, OpenAlexError

logger = logging.getLogger(__name__)


@tool
async def search_academic_sources(query: str, limit: int = 10) -> list[Paper]:
    """Tìm paper có metadata + abstract trên OpenAlex, Semantic Scholar và arXiv.

    Args:
        query: Từ khóa hoặc chủ đề nghiên cứu (tiếng Anh).
        limit: Số lượng bài báo tối đa cần lấy (mặc định 10, max 20).

    Returns:
        Danh sách các dictionary tuân thủ TypedDict `Paper`.
    """
    service = AcademicSearchService()
    try:
        papers, warnings = await service.search_all_sources(query, limit)
        if papers:
            logger.info(f"Academic multi-source search found {len(papers)} papers for query: '{query}'")
            return papers
        logger.warning(f"All academic sources returned 0 papers for query: '{query}'. Warnings: {warnings}")
        return []
    except OpenAlexError as exc:
        logger.error(f"OpenAlex Typed Error: {exc}")
        raise  # Propagate to graph node
    except Exception as exc:
        logger.error(f"Error calling OpenAlex API: {exc}")
        raise OpenAlexError(f"Unexpected error: {exc}") from exc
    finally:
        await service.close()
