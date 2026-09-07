from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.agents.document_review.application.service import (
    DocumentReviewConflictError,
    DocumentReviewError,
    DocumentReviewService,
    _annotation,
    _pdf_artifact_lines,
)


def _service(tmp_path):
    service = DocumentReviewService(
        settings=SimpleNamespace(
            paper_storage_dir=str(tmp_path),
            document_review_storage_dir="",
            document_review_max_file_size_mb=20,
            document_review_max_pdf_pages=60,
            document_review_link_timeout_seconds=1,
        )
    )
    service._link_annotations = lambda _content: asyncio.sleep(0, result=[])
    return service


def _with_ai_suggestion(service, exact: str, replacement: str):
    async def suggest(content: str):
        return [
            _annotation(
                content,
                annotation_type="suggest",
                aspect="clarity",
                comment="Câu này có thể viết rõ ràng hơn.",
                exact=exact,
                suggested_fix=replacement,
            )
        ]

    service._ai_annotations = suggest


@pytest.mark.asyncio
async def test_tex_review_finds_deterministic_issues_and_preserves_warning_invariant(tmp_path):
    service = _service(tmp_path)
    _with_ai_suggestion(service, "Two  spaces.", "Two spaces.")
    review = await service.create(
        "project_1",
        "paper.tex",
        b"\\documentclass{article}\n\\begin{document}\nTwo  spaces. \\cite{missing}. \\includegraphics{plot}\n\\end{document}\n",
    )

    suggestions = [item for item in review["annotations"] if item["type"] == "suggest"]
    warnings = [item for item in review["annotations"] if item["type"] == "warning"]
    assert review["source_format"] == "tex"
    assert suggestions[0]["suggested_fix"] == "Two spaces."
    assert {item["aspect"] for item in warnings} == {"citation_not_found", "missing_asset"}
    assert all("suggested_fix" not in item for item in warnings)


@pytest.mark.asyncio
async def test_tex_review_recognizes_embedded_bibitems(tmp_path):
    service = _service(tmp_path)
    service._ai_annotations = lambda _content: asyncio.sleep(0, result=[])
    content = b"""\\documentclass{article}
\\begin{document}
Supported \\cite{known}; unsupported \\cite{missing}.
\\begin{thebibliography}{9}
\\bibitem{known} Known source.
\\end{thebibliography}
\\end{document}
"""

    review = await service.create("project_1", "paper.tex", content)

    missing_keys = {
        item["evidence"]["citation_key"] for item in review["annotations"] if item["aspect"] == "citation_not_found"
    }
    assert missing_keys == {"missing"}


@pytest.mark.asyncio
async def test_accepting_suggestion_updates_content_but_warning_cannot_be_accepted(tmp_path):
    service = _service(tmp_path)
    _with_ai_suggestion(service, "A  B", "A and B")
    review = await service.create("project_1", "paper.tex", b"\\documentclass{article}\nA  B \\cite{missing}")
    suggestion = next(item for item in review["annotations"] if item["type"] == "suggest")
    warning = next(item for item in review["annotations"] if item["type"] == "warning")

    accepted = service.update_annotation(review["review_id"], suggestion["annotation_id"], "accept")

    assert "A and B" in accepted["content"]
    assert (
        next(item for item in accepted["annotations"] if item["annotation_id"] == suggestion["annotation_id"])["status"]
        == "accepted"
    )
    with pytest.raises(DocumentReviewConflictError):
        service.update_annotation(review["review_id"], warning["annotation_id"], "accept")


@pytest.mark.asyncio
async def test_unsupported_upload_is_rejected(tmp_path):
    with pytest.raises(DocumentReviewError, match="Only PDF"):
        await _service(tmp_path).create("project_1", "notes.txt", b"plain text")


@pytest.mark.asyncio
async def test_pdf_conversion_always_creates_a_manual_review_annotation(tmp_path):
    service = _service(tmp_path)
    service._ai_annotations = lambda _content: asyncio.sleep(0, result=[])
    annotations = await service._annotations(
        "Converted PDF text has a missing □ symbol and mergedwordRLC.", set(), set(), "pdf"
    )

    assert {item["aspect"] for item in annotations} == {"pdf_conversion", "extraction_artifact"}
    assert all(item["type"] == "warning" for item in annotations)


def test_pdf_artifact_detection_ignores_normal_case_boundaries_and_deduplicates():
    content = "OpenAI and eGFR are valid terms.\nDamaged □ symbol.\nDamaged   □   symbol.\nLost � glyph."

    assert _pdf_artifact_lines(content) == ["Damaged □ symbol.", "Lost � glyph."]


@pytest.mark.asyncio
async def test_doi_verification_warns_only_when_openalex_returns_no_match(tmp_path, monkeypatch):
    closed = False

    class SearchService:
        async def lookup_doi(self, doi: str):
            assert doi == "10.1000/missing"
            return []

        async def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr("src.agents.document_review.application.service.AcademicSearchService", SearchService)
    annotations = await _service(tmp_path)._citation_annotations("Reference: https://doi.org/10.1000/missing.")

    assert closed
    assert len(annotations) == 1
    assert annotations[0]["aspect"] == "citation_not_found"
    assert annotations[0]["anchor"]["exact"] == "10.1000/missing"
    assert "suggested_fix" not in annotations[0]


@pytest.mark.asyncio
async def test_doi_provider_failure_does_not_accuse_the_citation(tmp_path, monkeypatch):
    class SearchService:
        async def lookup_doi(self, _doi: str):
            raise RuntimeError("provider unavailable")

        async def close(self):
            pass

    monkeypatch.setattr("src.agents.document_review.application.service.AcademicSearchService", SearchService)

    annotations = await _service(tmp_path)._citation_annotations("doi:10.1000/unavailable")

    assert annotations == []


@pytest.mark.asyncio
async def test_ai_reviewer_returns_directly_applicable_suggestions(tmp_path, monkeypatch):
    class Candidate:
        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _prompt):
            return {
                "suggestions": [
                    {
                        "exact": "The result is very very important.",
                        "suggested_fix": "The result is important.",
                        "aspect": "redundancy",
                        "comment": "Loại bỏ từ lặp để câu gọn hơn.",
                    }
                ]
            }

    monkeypatch.setattr("src.agents.document_review.application.service.get_llm", lambda **_kwargs: Candidate())
    annotations = await _service(tmp_path)._ai_annotations("The result is very very important.")

    assert annotations[0]["type"] == "suggest"
    assert annotations[0]["suggested_fix"] == "The result is important."


def test_critic_response_keeps_valid_issue_when_another_item_is_malformed(tmp_path):
    issues = _service(tmp_path)._json_array(
        SimpleNamespace(
            content=json.dumps(
                [
                    {
                        "aspect": "clarity",
                        "quote": "Valid quote",
                        "comment": "Make this claim precise.",
                        "suggested_fix": "Precise quote",
                    },
                    {"aspect": "invented", "quote": "Bad", "comment": "Invalid aspect"},
                ]
            )
        )
    )

    assert [issue.quote for issue in issues] == ["Valid quote"]


@pytest.mark.asyncio
async def test_pdf_prefers_llamaparse_and_retains_source_file(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.settings.document_review_llamaparse_api_key = "test-key"
    service.settings.document_review_llamaparse_base_url = "https://parser.example"
    service.settings.document_review_llamaparse_tier = "agentic"
    service.settings.document_review_llamaparse_timeout_seconds = 30
    requests = {}

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Client:
        def __init__(self, **_kwargs):
            self.posted = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            requests["post"] = (url, kwargs)
            return Response({"id": "parse-job"})

        def get(self, url, **kwargs):
            return Response(
                {
                    "job": {"status": "COMPLETED"},
                    "markdown": {"pages": [{"markdown": "# Converted by LlamaParse\n\n$R = 1$"}]},
                }
            )

    monkeypatch.setattr("src.agents.document_review.application.service.httpx.Client", Client)
    review = await service.create("project_1", "paper.pdf", b"%PDF-1.7 placeholder")

    assert review["extraction_method"] == "llamaparse"
    assert review["content"].startswith("# Converted by LlamaParse")
    assert review["source_file_available"] is True
    assert (service._directory(review["review_id"]) / "source.pdf").read_bytes().startswith(b"%PDF")
    assert requests["post"][0] == "https://parser.example/api/v2/parse/upload"
    assert json.loads(requests["post"][1]["data"]["configuration"])["tier"] == "agentic"


@pytest.mark.asyncio
async def test_rewrite_uses_selection_anchor_and_ignores_model_old_text(tmp_path, monkeypatch):
    temperatures = []
    service = _service(tmp_path)
    service._ai_annotations = lambda _content: asyncio.sleep(0, result=[])
    review = await service.create("project_1", "paper.tex", b"\\documentclass{article}\\nOriginal passage.")

    class Candidate:
        native_schema_supported = True

        def with_structured_output(self, _schema):
            return self

        async def ainvoke(self, _prompt):
            return {"old_text": "model echo is ignored", "new_text": "Rewritten passage."}

    def get_candidate(*, temperature=None):
        temperatures.append(temperature)
        return Candidate()

    monkeypatch.setattr("src.agents.document_review.application.service.get_llm", get_candidate)
    rewritten = await service.rewrite(review["review_id"], "Original passage.", "article}\\n", "")

    assert rewritten == "Rewritten passage."
    assert temperatures == [0.5]
    with pytest.raises(DocumentReviewConflictError):
        await service.rewrite(review["review_id"], "Original passage.", "wrong context", "")
