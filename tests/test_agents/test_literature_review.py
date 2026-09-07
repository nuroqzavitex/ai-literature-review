import pytest

from src.agents.litreview.prompts.literature_review import LiteratureReviewDraft
from src.agents.litreview.workflow.nodes import (
    _canonicalize_review_citations,
    _fallback_literature_review,
    _parse_markdown_literature_review,
    _repair_review_citations,
    _repair_review_structure,
    _review_citations_are_valid,
    compose_literature_review_node,
)


@pytest.mark.asyncio
async def test_compose_review_uses_valid_claims_when_no_theme_survives(monkeypatch):
    captured = {}
    draft = LiteratureReviewDraft(
        title="RAG and factual reliability",
        abstract="The reviewed evidence supports scoped factual-reliability gains. [[1]]",
        introduction="RAG grounds generation in retrieved evidence in the reviewed corpus. [[1]]",
        sections=[
            {
                "title": "Evidence-grounded generation",
                "paragraphs": [
                    "Retrieved external knowledge is associated with better grounding. [[1]]",
                    "The reported effect is scoped to the evaluated system. [[2]]",
                ],
                "supporting_paper_ids": ["1", "2"],
            }
        ],
        conclusion="Within this corpus, the findings support evidence-grounded generation. [[1]]",
        limitations="The available evidence remains limited to the selected papers. [[2]]",
    )

    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, inputs, **_kwargs):
            captured.update(inputs)
            return draft

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await compose_literature_review_node(
        {
            "original_topic": "Does RAG improve factual reliability?",
            "response_language": "Vietnamese",
            "themes": [],
            "papers": [
                {"paper_id": "P1", "title": "Paper one", "abstract": "Evidence one."},
                {"paper_id": "P2", "title": "Paper two", "abstract": "Evidence two."},
            ],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "RAG improves grounding in the reported evaluation.",
                    "supporting_paper_ids": ["P1", "P2"],
                    "evidence": [
                        {"paper_id": "P1", "quote": "Evidence one."},
                        {"paper_id": "P2", "quote": "Evidence two."},
                    ],
                    "validation_status": "valid",
                }
            ],
        }
    )

    assert "Evidence bundle: contribution" in captured["themes_text"]
    assert "Citation [[1]] | Paper ID: P1" in captured["papers_text"]
    assert "Abstract (context only; not a validated claim): Evidence one." in captured["papers_text"]
    assert captured["response_language"] == "English"
    assert captured["citation_feedback"] == "No previous draft. Follow the citation contract exactly."
    assert result["literature_review"]["title"] == "RAG and factual reliability"
    assert "[[P1]]" in result["literature_review"]["introduction"]


@pytest.mark.asyncio
async def test_compose_review_passes_citation_errors_to_retry(monkeypatch):
    attempts = []
    invalid_draft = LiteratureReviewDraft(
        title="Emergency triage review",
        abstract="The review summarizes the available evidence without a citation.",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Accuracy and speed",
                "paragraphs": ["The extracted claims report improvements in accuracy and speed."],
                "supporting_paper_ids": ["1"],
            }
        ],
        conclusion="The extracted claims support a qualified finding.",
        limitations="The report is limited to the reviewed corpus.",
    )
    valid_draft = LiteratureReviewDraft(
        title="Emergency triage review",
        abstract="The review summarizes the available evidence. [[1]]",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Accuracy and speed",
                "paragraphs": ["The extracted claims report improvements in accuracy and speed. [[1]]"],
                "supporting_paper_ids": ["1"],
            }
        ],
        conclusion="The extracted claims support a qualified finding.",
        limitations="The report is limited to the reviewed corpus.",
    )

    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, inputs, **_kwargs):
            attempts.append(dict(inputs))
            return invalid_draft if len(attempts) == 1 else valid_draft

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await compose_literature_review_node(
        {
            "original_topic": "How does AI improve emergency triage?",
            "themes": [],
            "papers": [{"paper_id": "P1", "title": "Paper one", "abstract": "Evidence one."}],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "AI improves emergency triage in the reported evaluation.",
                    "supporting_paper_ids": ["P1"],
                    "evidence": [{"paper_id": "P1", "quote": "Evidence one."}],
                    "validation_status": "valid",
                }
            ],
        }
    )

    assert len(attempts) == 2
    assert attempts[0]["citation_feedback"] == "No previous draft. Follow the citation contract exactly."
    assert "abstract has no traceable citation" in attempts[1]["citation_feedback"]
    assert "section 'Accuracy and speed' has no traceable citation" in attempts[1]["citation_feedback"]
    assert result["literature_review"]["abstract"].endswith("[[P1]]")
    assert not any("FALLBACK" in warning for warning in result["source_warnings"])


@pytest.mark.asyncio
async def test_compose_review_repairs_partial_citation_structure_without_fallback(monkeypatch):
    draft = LiteratureReviewDraft(
        title="Emergency triage review",
        abstract="The review summarizes the available evidence.",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Supported finding",
                "paragraphs": ["The study reports a relevant finding. [[1]]"],
                "supporting_paper_ids": ["2"],
            },
            {
                "title": "Unsupported finding",
                "paragraphs": ["This section has no traceable citation."],
                "supporting_paper_ids": ["2"],
            },
        ],
        conclusion="The findings are limited to the reviewed corpus.",
        limitations="The evidence base is small.",
    )

    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            return draft

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await compose_literature_review_node(
        {
            "original_topic": "How does AI improve emergency triage?",
            "themes": [],
            "papers": [
                {"paper_id": "P1", "title": "Paper one", "abstract": "Evidence one."},
                {"paper_id": "P2", "title": "Paper two", "abstract": "Evidence two."},
            ],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "AI supports emergency triage in the reported evaluation.",
                    "supporting_paper_ids": ["P1"],
                    "evidence": [{"paper_id": "P1", "quote": "Evidence one."}],
                    "validation_status": "valid",
                }
            ],
        }
    )

    review = result["literature_review"]
    assert [section["title"] for section in review["sections"]] == ["Supported finding"]
    assert review["sections"][0]["supporting_paper_ids"] == ["P1"]
    assert review["abstract"].endswith("[[P1]]")
    assert not any("LITERATURE_REVIEW_FALLBACK" in item for item in result["source_warnings"])
    assert any("LITERATURE_REVIEW_CITATION_REPAIRED" in item for item in result["source_warnings"])


@pytest.mark.asyncio
async def test_compose_review_returns_claim_based_draft_when_citation_validation_fails(monkeypatch):
    draft = LiteratureReviewDraft(
        title="Emergency triage review",
        abstract="The extracted claims indicate improvements in emergency triage.",
        introduction="The report is based on the selected studies.",
        sections=[
            {
                "title": "Accuracy and speed",
                "paragraphs": ["The extracted claims report improvements in accuracy and speed."],
                "supporting_paper_ids": ["P1"],
            }
        ],
        conclusion="The extracted claims support a qualified finding.",
        limitations="The report is limited to the reviewed corpus.",
    )

    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            return draft

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await compose_literature_review_node(
        {
            "original_topic": "How does AI improve emergency triage?",
            "themes": [],
            "papers": [{"paper_id": "P1", "title": "Paper one", "abstract": "Evidence one."}],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "AI improves emergency triage in the reported evaluation.",
                    "supporting_paper_ids": ["P1"],
                    "evidence": [{"paper_id": "P1", "quote": "Evidence one."}],
                    "validation_status": "valid",
                }
            ],
        }
    )

    review = result["literature_review"]
    assert review["title"] == "Emergency triage review"
    assert review["sections"][0]["title"] == "Accuracy and speed"
    assert any(
        warning.startswith("LITERATURE_REVIEW_CITATION_VALIDATION_BYPASSED:") for warning in result["source_warnings"]
    )
    assert not any("LITERATURE_REVIEW_FALLBACK" in warning for warning in result["source_warnings"])


@pytest.mark.asyncio
async def test_compose_review_keeps_an_evidence_limited_report_when_no_claim_is_valid():
    result = await compose_literature_review_node(
        {
            "original_topic": "Does AI improve emergency triage?",
            "themes": [],
            "papers": [
                {
                    "paper_id": "P1",
                    "title": "Triage study",
                    "abstract": "A triage model was evaluated in an emergency department.",
                }
            ],
            "claims": [],
        }
    )

    review = result["literature_review"]
    assert review["title"].startswith("Evidence-Limited Literature Review")
    assert "[[P1]]" in review["sections"][0]["paragraphs"][0]
    assert "LITERATURE_REVIEW_EVIDENCE_LIMITED:NO_VALIDATED_CLAIMS" in result["source_warnings"]


@pytest.mark.asyncio
async def test_compose_review_hides_json_validation_errors_behind_a_natural_fallback(monkeypatch):
    class FailingInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            raise ValueError("Model returned invalid JSON")

    async def failing_markdown(*_args, **_kwargs):
        raise TimeoutError("Markdown provider unavailable")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FailingInvoker)
    monkeypatch.setattr(
        "src.agents.litreview.workflow.nodes._compose_markdown_literature_review",
        failing_markdown,
    )
    result = await compose_literature_review_node(
        {
            "original_topic": "Does AI improve emergency triage?",
            "themes": [],
            "papers": [
                {
                    "paper_id": "P1",
                    "title": "Triage study",
                    "abstract": "A triage model was evaluated in an emergency department.",
                }
            ],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "The model was evaluated in emergency triage.",
                    "supporting_paper_ids": ["P1"],
                    "evidence": [{"paper_id": "P1", "quote": "A triage model was evaluated."}],
                    "validation_status": "valid",
                }
            ],
        }
    )

    review = result["literature_review"]
    assert "invalid JSON" not in review["introduction"]
    assert "LITERATURE_REVIEW_FALLBACK:ValueError:Model returned invalid JSON" in result["source_warnings"]
    assert (
        "LITERATURE_REVIEW_MARKDOWN_FALLBACK_FAILED:TimeoutError:Markdown provider unavailable"
        in result["source_warnings"]
    )


@pytest.mark.asyncio
async def test_compose_review_uses_markdown_when_structured_json_fails(monkeypatch):
    class FailingInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            raise ValueError("Model returned invalid JSON")

    async def markdown_review(*_args, **_kwargs):
        return (
            {
                "title": "Natural Markdown review",
                "abstract": "The validated claims support a scoped finding. [[P1]]",
                "introduction": "The reviewed corpus provides the relevant research context.",
                "sections": [
                    {
                        "title": "Main finding",
                        "paragraphs": ["The model was evaluated in emergency triage. [[P1]]"],
                        "supporting_paper_ids": ["P1"],
                    }
                ],
                "conclusion": "The available evidence supports a qualified conclusion.",
                "limitations": "The result is limited to the selected corpus.",
            },
            0,
        )

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FailingInvoker)
    monkeypatch.setattr(
        "src.agents.litreview.workflow.nodes._compose_markdown_literature_review",
        markdown_review,
    )
    result = await compose_literature_review_node(
        {
            "original_topic": "Does AI improve emergency triage?",
            "themes": [],
            "papers": [
                {"paper_id": "P1", "title": "Triage study", "abstract": "Evidence one."},
                {"paper_id": "P2", "title": "Context study", "abstract": "Context only."},
            ],
            "claims": [
                {
                    "claim_id": "claim_1",
                    "claim_type": "contribution",
                    "text": "The model was evaluated in emergency triage.",
                    "supporting_paper_ids": ["P1"],
                    "evidence": [{"paper_id": "P1", "quote": "Evidence one."}],
                    "validation_status": "valid",
                }
            ],
        }
    )

    assert result["literature_review"]["title"] == "Natural Markdown review"
    assert "[[P2]]" not in result["literature_review"]["limitations"]
    assert any(
        warning.startswith("LITERATURE_REVIEW_MARKDOWN_FALLBACK:ValueError:") for warning in result["source_warnings"]
    )
    assert not any(warning.startswith("LITERATURE_REVIEW_FALLBACK:") for warning in result["source_warnings"])


def test_markdown_review_parser_builds_sections_and_removes_unknown_citations():
    markdown = """# Tổng quan GNN
## Tóm tắt
Các claim hợp lệ cho thấy một kết quả có điều kiện. [[1, 2]]

## Giới thiệu
Corpus cung cấp bối cảnh trực tiếp cho câu hỏi nghiên cứu. [[1]]

## Hiệu quả mô hình
GNN khai thác cấu trúc quan hệ trong dữ liệu. [[1]]

Kết quả ngoài corpus không được giữ lại. [[99]]

## Kết luận
Bằng chứng hỗ trợ một kết luận thận trọng. [[2]]

## Hạn chế
Kết quả chỉ áp dụng cho các nghiên cứu đã chọn.
"""

    review, repair_count = _parse_markdown_literature_review(
        markdown,
        topic="GNN có cải thiện phát hiện gian lận không?",
        citation_aliases={"1": "P1", "2": "P2"},
        paper_ids={"P1", "P2"},
    )

    assert review["title"] == "Tổng quan GNN"
    assert review["abstract"].endswith("[[P1]] [[P2]]")
    assert review["sections"][0]["supporting_paper_ids"] == ["P1"]
    assert "[[99]]" not in review["sections"][0]["paragraphs"][1]
    assert repair_count == 1


def test_review_citation_normalization_accepts_common_model_aliases():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The evidence is scoped to the reviewed studies. [1]",
        introduction="The corpus includes directly relevant evidence. [[Paper 1]]",
        sections=[
            {
                "title": "Findings",
                "paragraphs": ["One source reports the relevant finding. [[P1]]"],
                "supporting_paper_ids": ["R1"],
            }
        ],
        conclusion="The reviewed evidence supports a qualified conclusion. [[1]]",
        limitations="The corpus does not establish evidence beyond its selected papers.",
    )

    normalized = _canonicalize_review_citations(review, {"1": "paper_1"})

    assert "[[paper_1]]" in normalized.abstract
    assert "[[paper_1]]" in normalized.introduction
    assert normalized.sections[0].supporting_paper_ids == ["paper_1"]
    assert _review_citations_are_valid(normalized, {"paper_1"})


def test_review_citation_normalization_repairs_malformed_citation_lists():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The evidence is scoped to the reviewed studies. [[1], [2]]",
        introduction="The corpus includes directly relevant evidence. [[1]]",
        sections=[
            {
                "title": "Findings",
                "paragraphs": ["One source reports the relevant finding. [[2]]"],
                "supporting_paper_ids": ["1", "2"],
            }
        ],
        conclusion="The reviewed evidence supports a qualified conclusion. [[1]]",
        limitations="The corpus does not establish evidence beyond its selected papers.",
    )

    normalized = _canonicalize_review_citations(review, {"1": "paper_1", "2": "paper_2"})

    assert "[[paper_1]], [[paper_2]]" in normalized.abstract
    assert _review_citations_are_valid(normalized, {"paper_1", "paper_2"})


def test_review_citation_normalization_expands_grouped_aliases():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The evidence comes from both studies. [[1, 2]]",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Findings",
                "paragraphs": ["Both studies report relevant findings. [1; 2]"],
                "supporting_paper_ids": ["1", "2"],
            }
        ],
        conclusion="The findings are limited to the reviewed corpus.",
        limitations="The evidence base is small.",
    )

    normalized = _canonicalize_review_citations(review, {"1": "paper_1", "2": "paper_2"})

    assert normalized.abstract.endswith("[[paper_1]] [[paper_2]]")
    assert normalized.sections[0].paragraphs[0].endswith("[[paper_1]] [[paper_2]]")
    assert _review_citations_are_valid(normalized, {"paper_1", "paper_2"})


def test_review_structure_keeps_sourced_sections_and_drops_uncited_sections():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The review summarizes the available evidence.",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Supported finding",
                "paragraphs": ["The study reports a relevant finding. [[paper_1]]"],
                "supporting_paper_ids": ["paper_2"],
            },
            {
                "title": "Unsupported finding",
                "paragraphs": ["This section has no traceable citation."],
                "supporting_paper_ids": ["paper_2"],
            },
        ],
        conclusion="The findings are limited to the reviewed corpus.",
        limitations="The evidence base is small.",
    )

    repaired, repair_count = _repair_review_structure(review, {"paper_1", "paper_2"})

    assert repair_count == 3
    assert [section.title for section in repaired.sections] == ["Supported finding"]
    assert repaired.sections[0].supporting_paper_ids == ["paper_1"]
    assert repaired.abstract.endswith("[[paper_1]]")
    assert _review_citations_are_valid(repaired, {"paper_1", "paper_2"})


def test_review_structure_does_not_invent_sources_when_every_section_is_uncited():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The review summarizes the available evidence.",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Unsupported finding",
                "paragraphs": ["This section has no traceable citation."],
                "supporting_paper_ids": ["paper_1"],
            }
        ],
        conclusion="The findings are limited to the reviewed corpus.",
        limitations="The evidence base is small.",
    )

    repaired, repair_count = _repair_review_structure(review, {"paper_1"})

    assert repair_count == 1
    assert repaired == review
    assert not _review_citations_are_valid(repaired, {"paper_1"})


def test_citation_repair_does_not_assign_a_default_paper_to_uncited_prose():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The evidence is scoped to the reviewed studies. [[paper_1]]",
        introduction="This sentence has no citation and must be rewritten by the model.",
        sections=[
            {
                "title": "Findings",
                "paragraphs": ["One source reports the relevant finding. [[paper_1]]"],
                "supporting_paper_ids": ["paper_1"],
            }
        ],
        conclusion="The reviewed evidence supports a qualified conclusion. [[paper_1]]",
        limitations="The corpus does not establish evidence beyond its selected papers.",
    )

    repaired, _ = _repair_review_citations(review, {"paper_1"})

    assert "[[paper_1]]" not in repaired.introduction
    assert _review_citations_are_valid(repaired, {"paper_1"})


def test_citation_validation_rejects_a_findings_section_without_a_source():
    review = LiteratureReviewDraft(
        title="Review",
        abstract="The evidence is scoped to the reviewed studies. [[paper_1]]",
        introduction="The corpus provides relevant context.",
        sections=[
            {
                "title": "Findings",
                "paragraphs": ["This finding has no source."],
                "supporting_paper_ids": ["paper_1"],
            }
        ],
        conclusion="The corpus supports a qualified conclusion.",
        limitations="The corpus is limited.",
    )

    assert not _review_citations_are_valid(review, {"paper_1"})


def test_fallback_review_uses_english_evidence_not_localized_claim_text():
    review = _fallback_literature_review(
        "How does AI support emergency medicine?",
        [],
        [
            {
                "claim_id": "claim_1",
                "claim_type": "contribution",
                "text": "AI giúp bác sĩ đưa ra quyết định tốt hơn.",
                "supporting_paper_ids": ["paper_1"],
                "evidence": [{"paper_id": "paper_1", "quote": "AI supports clinical decision-making."}],
                "validation_status": "valid",
            }
        ],
        {"paper_1"},
        "Vietnamese scope disclaimer",
    )

    assert "AI giúp" not in review["sections"][0]["paragraphs"][0]
    assert "AI supports clinical decision-making." in review["sections"][0]["paragraphs"][0]
    assert review["sections"][0]["title"] == "Reported Benefits"


def test_fallback_review_adds_context_from_reviewed_paper_abstracts():
    review = _fallback_literature_review(
        "How does AI support emergency medicine?",
        [],
        [],
        {"paper_1"},
        "",
        related_papers=[
            {
                "paper_id": "paper_1",
                "abstract": "A triage model was evaluated in an emergency department. It improved calibration.",
            }
        ],
    )

    context = next(
        section for section in review["sections"] if section["title"] == "Related Context from Reviewed Papers"
    )
    assert "A triage model was evaluated in an emergency department." in context["paragraphs"][0]
    assert "[[paper_1]]" in context["paragraphs"][0]


def test_fallback_review_uses_vietnamese_for_a_vietnamese_prompt():
    review = _fallback_literature_review(
        "AI hỗ trợ chẩn đoán cấp cứu như thế nào?",
        [],
        [],
        {"paper_1"},
        "",
        "Vietnamese",
    )

    assert review["title"].startswith("Tổng quan tài liệu")
    assert review["introduction"].startswith("Bản tổng hợp này")
