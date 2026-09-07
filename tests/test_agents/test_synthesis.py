"""Integration tests for synthesis node claim/gap/theme logic.

Covers:
- Synthesized claims are returned with valid IDs
- Max 5 themes and >= 2 papers/theme enforcement
- Gap coverage completeness validation
- Gap absolute wording rejection
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.litreview.domain.models import AgentState
from src.agents.litreview.prompts.synthesis import (
    GapCoverage as SynthGapCoverage,
)
from src.agents.litreview.prompts.synthesis import (
    SynthesisResult,
    SynthesizedGap,
    SynthesizedTheme,
)
from src.agents.litreview.workflow.nodes import synthesize_claims_node, validate_grounding_node


def _make_papers(n):
    return [
        {
            "paper_id": f"p{i}",
            "title": f"Paper {i}",
            "authors": [f"Author {i}"],
            "year": 2024,
            "doi": f"10.1234/{i}",
            "url": f"https://openalex.org/W{i}",
            "abstract": f"Abstract {i}",
            "cited_by_count": 10,
            "is_open_access": True,
        }
        for i in range(1, n + 1)
    ]


def _make_claims(papers):
    return [
        {
            "claim_id": f"claim_{i}",
            "claim_type": "contribution",
            "text": f"Claim text {i}",
            "supporting_paper_ids": [papers[i - 1]["paper_id"]],
            "evidence": [
                {
                    "paper_id": papers[i - 1]["paper_id"],
                    "quote": "evidence",
                    "section": "abstract",
                }
            ],
            "validation_status": "valid",
            "validation_errors": [],
        }
        for i in range(1, len(papers) + 1)
    ]


@pytest.fixture()
def base_state():
    papers = _make_papers(12)
    claims = _make_claims(papers)
    return {
        "topic": "test topic",
        "original_topic": "test topic",
        "papers": papers,
        "claims": claims,
    }


async def _run_synthesis(base_state, mock_result):
    """Helper that patches LLM chain and runs synthesize_claims_node."""
    mock_chain = AsyncMock()
    mock_chain.ainvoke = AsyncMock(return_value=mock_result)

    with (
        patch("src.agents.litreview.workflow.nodes.get_llm") as mock_llm,
        patch("src.agents.litreview.workflow.nodes.get_synthesis_prompt") as mock_prompt,
    ):
        # Make prompt | llm return our mock_chain
        mock_prompt.return_value.__or__ = lambda self, other: mock_chain
        mock_llm.return_value.with_structured_output.return_value = MagicMock()

        return await synthesize_claims_node(base_state)


@pytest.mark.asyncio
async def test_grounding_retries_429_claims_with_three_concurrent_calls(monkeypatch):
    papers = _make_papers(7)
    candidates = _make_claims(papers)
    attempts: dict[str, int] = {}
    initial_active = 0
    initial_peak = 0
    retry_active = 0
    retry_peak = 0
    retry_claim_ids = {f"claim_{index}" for index in range(1, 5)}

    class FakeEntailmentInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, *, trace_context=None):
            nonlocal initial_active, initial_peak, retry_active, retry_peak
            claim_id = trace_context["claim_id"]
            attempts[claim_id] = attempts.get(claim_id, 0) + 1
            is_retry = attempts[claim_id] > 1
            if is_retry:
                retry_active += 1
                retry_peak = max(retry_peak, retry_active)
            else:
                initial_active += 1
                initial_peak = max(initial_peak, initial_active)
            await asyncio.sleep(0.01)
            if is_retry:
                retry_active -= 1
            else:
                initial_active -= 1
            if not is_retry and claim_id in retry_claim_ids:
                raise RuntimeError("Error code: 429 - too many concurrent requests")
            return SimpleNamespace(entails=True, verdict="supported", reason="")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeEntailmentInvoker)
    monkeypatch.setattr(
        "src.agents.litreview.workflow.nodes.get_settings",
        lambda: SimpleNamespace(qdrant_enabled=False, litreview_claim_validation_concurrency=5),
    )
    monkeypatch.setattr(
        "src.agents.litreview.workflow.nodes.validate_summary",
        lambda **_kwargs: SimpleNamespace(passed=True, issues=[]),
    )
    monkeypatch.setattr("src.agents.litreview.workflow.nodes._CLAIM_VALIDATION_429_BACKOFF_SECONDS", 0)

    result = await validate_grounding_node(
        {"papers": papers, "claim_candidates": candidates, "original_topic": "test topic"}
    )

    assert len(result["claims"]) == 7
    assert initial_peak == 5
    assert retry_peak == 3
    assert all(attempts[claim_id] == 2 for claim_id in retry_claim_ids)
    assert "GROUNDING_ENTAILMENT_429_RETRY:claims=4:concurrency=3" in result["validation_warnings"]


class TestSynthesizeClaimsReturnsClaims:
    @pytest.mark.asyncio
    async def test_returns_claims_key(self, base_state):
        """Synthesis node must return 'claims' so theme/gap claim_ids exist."""
        themes = [
            SynthesizedTheme(
                title="Theme 1",
                summary="Summary of theme 1",
                supporting_paper_ids=["p1", "p2", "p3"],
            )
        ]
        mock_result = SynthesisResult(themes=themes, potential_gaps=[])
        result = await _run_synthesis(base_state, mock_result)

        assert "claim_candidates" in result
        # 1 theme summary claim candidate
        assert len(result["claim_candidates"]) == 1
        # Theme summary claim has supporting_paper_ids
        theme_claim = result["claim_candidates"][0]
        assert "supporting_paper_ids" in theme_claim
        assert len(theme_claim["supporting_paper_ids"]) >= 2


class TestThemeLimits:
    @pytest.mark.asyncio
    async def test_max_5_themes(self, base_state):
        """Only first 5 valid themes are kept."""
        themes = [
            SynthesizedTheme(
                title=f"Theme {i}",
                summary=f"Summary {i}",
                supporting_paper_ids=["p1", "p2"],
            )
            for i in range(8)
        ]
        mock_result = SynthesisResult(themes=themes, potential_gaps=[])
        result = await _run_synthesis(base_state, mock_result)

        assert len(result["themes"]) == 5

    @pytest.mark.asyncio
    async def test_theme_needs_2_papers(self, base_state):
        """Theme with only 1 valid paper is skipped."""
        themes = [
            SynthesizedTheme(
                title="Weak theme",
                summary="Summary",
                supporting_paper_ids=["p1"],
            )
        ]
        mock_result = SynthesisResult(themes=themes, potential_gaps=[])
        result = await _run_synthesis(base_state, mock_result)

        assert len(result["themes"]) == 0


class TestGapCoverageValidation:
    @pytest.mark.asyncio
    async def test_incomplete_coverage_rejected(self, base_state):
        """Gap with coverage for only 3 out of 12 papers is rejected."""
        coverage = [
            SynthGapCoverage(paper_id="p1", mentioned=False, evidence_quote=""),
            SynthGapCoverage(paper_id="p2", mentioned=False, evidence_quote=""),
            SynthGapCoverage(paper_id="p3", mentioned=False, evidence_quote=""),
        ]
        gaps = [
            SynthesizedGap(
                aspect="scalability",
                scope_statement="Missing aspect",
                coverage=coverage,
            )
        ]
        mock_result = SynthesisResult(themes=[], potential_gaps=gaps)
        result = await _run_synthesis(base_state, mock_result)

        assert len(result["potential_gaps"]) == 0

    @pytest.mark.asyncio
    async def test_absolute_wording_rejected(self, base_state):
        """Gap with absolute wording is rejected even with full coverage."""
        papers = base_state["papers"]
        coverage = [SynthGapCoverage(paper_id=p["paper_id"], mentioned=False, evidence_quote="") for p in papers]
        gaps = [
            SynthesizedGap(
                aspect="scalability",
                scope_statement="No study has ever examined scalability.",
                coverage=coverage,
            )
        ]
        mock_result = SynthesisResult(themes=[], potential_gaps=gaps)
        result = await _run_synthesis(base_state, mock_result)

        assert len(result["potential_gaps"]) == 0

    @pytest.mark.asyncio
    async def test_valid_gap_accepted(self, base_state):
        """Correctly formed gap with full coverage passes."""
        papers = base_state["papers"]
        coverage = [SynthGapCoverage(paper_id=p["paper_id"], mentioned=False, evidence_quote="") for p in papers]
        gaps = [
            SynthesizedGap(
                aspect="explainability",
                scope_statement="Limited coverage of explainability.",
                coverage=coverage,
            )
        ]
        mock_result = SynthesisResult(themes=[], potential_gaps=gaps)
        result = await _run_synthesis(base_state, mock_result)

        assert len(result["potential_gaps"]) == 1
        gap = result["potential_gaps"][0]
        assert gap["papers_checked"] == 12
        assert len(gap["coverage"]) == 12
        # Scope statement follows the template
        assert "Trong 12 bài" in gap["scope_statement"]
        assert "explainability" in gap["scope_statement"]


@pytest.mark.asyncio
async def test_regression_dangling_themes_are_removed():
    state = AgentState(
        synthesis_completed=True,
        papers=[],
        claims=[
            {
                "claim_id": "valid_claim",
                "claim_type": "contribution",
                "text": "Valid text",
                "supporting_paper_ids": [],
                "evidence": [],
                "validation_status": "valid",
                "validation_errors": [],
            }
        ],
        claim_candidates=[
            {
                "claim_id": "invalid_theme_claim",
                "claim_type": "theme",
                "text": "Theme text",
                "supporting_paper_ids": [],  # Missing support
                "evidence": [],
            }
        ],
        themes=[
            {
                "theme_id": "theme_1",
                "title": "Invalid Theme",
                "summary_claim_id": "invalid_theme_claim",
                "supporting_paper_ids": [],
            }
        ],
    )
    # validate_grounding_node validates claim_candidates
    # The invalid_theme_claim will be rejected.
    # Therefore, the theme should be removed from state["themes"]
    new_state = await validate_grounding_node(state)
    assert len(new_state["themes"]) == 0
    assert len(new_state["claims"]) == 1  # only valid_claim remains


@pytest.mark.asyncio
async def test_regression_claim_revision_duplicates():
    state = AgentState(
        synthesis_completed=True,
        papers=[],
        claims=[
            {
                "claim_id": "claim_to_revise",
                "claim_type": "contribution",
                "text": "Old text",
                "supporting_paper_ids": [],
                "evidence": [],
                "validation_status": "valid",
                "validation_errors": [],
            }
        ],
        claim_candidates=[
            {
                "claim_id": "claim_to_revise",  # Same ID!
                "claim_type": "contribution",
                "text": "New text",
                "supporting_paper_ids": [],
                "evidence": [],  # It will fail validation due to no evidence, but let's see if it replaces
            }
        ],
    )
    new_state = await validate_grounding_node(state)
    # The new candidate fails validation, so it's in rejected_claims.
    # The dictionary replacement will mean valid_claims drops it because it's rejected, OR it replaces and gets rejected!
    # Wait, if it fails validation, it goes to rejected_claims, so it's NOT in valid_claims.
    # Thus, the old claim is successfully overwritten and then rejected, so valid_claims should be empty.
    assert len(new_state["claims"]) == 0
    assert len(new_state["rejected_claims"]) == 1


@pytest.mark.asyncio
async def test_zero_valid_claims_request_one_grounding_revision_before_fallback():
    state = AgentState(
        papers=[
            {
                "paper_id": "p1",
                "title": "Paper 1",
                "abstract": "Direct evidence.",
                "url": "https://example.test/p1",
            }
        ],
        claim_candidates=[
            {
                "claim_id": "claim_recoverable",
                "claim_type": "contribution",
                "text": "An initially unsupported claim.",
                "supporting_paper_ids": ["p1"],
                "evidence": [],
            }
        ],
        grounding_revision_attempt=0,
        max_claim_revision_attempts=1,
    )

    new_state = await validate_grounding_node(state)

    assert new_state["claims"] == []
    assert new_state["revision_source"] == "grounding"
    assert new_state["decisions"][-1]["action"] == "revise_claims"


@pytest.mark.asyncio
async def test_regression_theme_missing_evidence_rejected():
    state = AgentState(
        synthesis_completed=True,
        papers=[{"paper_id": "p1"}, {"paper_id": "p2"}],
        claims=[],
        claim_candidates=[
            {
                "claim_id": "theme_claim",
                "claim_type": "theme",
                "text": "Theme text",
                "supporting_paper_ids": ["p1", "p2"],
                "evidence": [
                    {"paper_id": "p1", "quote": "Quote from p1", "section": "abstract"}
                ],  # Missing evidence for p2
            }
        ],
    )
    new_state = await validate_grounding_node(state)
    assert len(new_state["rejected_claims"]) == 1
    assert "Theme is missing evidence quotes" in new_state["rejected_claims"][0]["validation_errors"][0]


@pytest.mark.asyncio
async def test_regression_gap_fabricated_quote_rejected():
    # Gap quote validation should not drop errors
    state = AgentState(
        synthesis_completed=True,
        papers=[{"paper_id": f"p{i}", "abstract": "abstract text", "url": f"http://p{i}"} for i in range(10)],
        claims=[],
        potential_gaps=[
            {
                "gap_id": "gap_1",
                "claim_id": "gap_claim",
                "aspect": "test",
                "papers_checked": 10,
                "coverage": [
                    {"paper_id": f"p{i}", "mentioned": (i == 0), "evidence_quote": "FAKE QUOTE"} for i in range(10)
                ],
                "scope_statement": "statement",
            }
        ],
        claim_candidates=[
            {
                "claim_id": "gap_claim",
                "claim_type": "potential_gap",
                "text": "Gap text",
                "supporting_paper_ids": ["p0"],
                "evidence": [{"paper_id": "p0", "quote": "FAKE QUOTE", "section": "abstract"}],
            }
        ],
    )
    new_state = await validate_grounding_node(state)
    assert len(new_state["rejected_claims"]) == 1
    assert "không tìm thấy trong abstract" in new_state["rejected_claims"][0]["validation_errors"][0]
