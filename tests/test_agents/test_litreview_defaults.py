from inspect import signature

from src.agents.litreview.prompts.literature_review import (
    LITERATURE_REVIEW_MARKDOWN_SYSTEM_PROMPT,
    LITERATURE_REVIEW_SYSTEM_PROMPT,
)
from src.agents.litreview.workflow.nodes import _fulltext_first_contexts
from src.config import Settings
from src.models.schemas.literature_reviews import LitReviewRequest
from src.models.schemas.research_copilot import (
    ApproveResearchPlanRequest,
    CreateProjectReviewRequest,
)


def test_literature_review_generation_defaults():
    assert signature(_fulltext_first_contexts).parameters["chunks_per_paper"].default == 4
    assert Settings.model_fields["litreview_fulltext_chunks_per_paper"].default == 4
    assert "1,800-2,400 words" in LITERATURE_REVIEW_SYSTEM_PROMPT
    assert "1,800-2,400 words" in LITERATURE_REVIEW_MARKDOWN_SYSTEM_PROMPT


def test_literature_review_requests_default_to_twenty_papers():
    assert LitReviewRequest.model_fields["max_results"].default == 20
    assert CreateProjectReviewRequest.model_fields["max_results"].default == 20
    assert ApproveResearchPlanRequest.model_fields["max_results"].default == 20
