from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.agents.document_review.application.service import DocumentReviewService, _annotation
from src.api.routers import document_reviews, research_copilot
from src.main import app


@pytest.fixture
def isolated_document_review_api(tmp_path, monkeypatch):
    actor = {"actor_id": "alice"}
    monkeypatch.setitem(app.dependency_overrides, research_copilot.current_actor, lambda: actor)
    monkeypatch.setattr(
        research_copilot,
        "v2_service",
        SimpleNamespace(require_membership=lambda *_args, **_kwargs: {"project_role": "owner"}),
    )
    monkeypatch.setattr(research_copilot, "v2_repository", SimpleNamespace(audit=lambda *_args, **_kwargs: None))
    review_service = DocumentReviewService(
        settings=SimpleNamespace(
            paper_storage_dir=str(tmp_path),
            document_review_storage_dir="",
            document_review_max_file_size_mb=20,
            document_review_max_pdf_pages=60,
            document_review_link_timeout_seconds=1,
        )
    )
    review_service._link_annotations = lambda _content: asyncio.sleep(0, result=[])

    async def ai_annotations(content: str):
        if "Text  here." not in content:
            return []
        return [
            _annotation(
                content,
                annotation_type="suggest",
                aspect="clarity",
                comment="Câu này có thể viết rõ ràng hơn.",
                exact="Text  here.",
                suggested_fix="Text here.",
            )
        ]

    review_service._ai_annotations = ai_annotations
    monkeypatch.setattr(document_reviews, "service", lambda: review_service)
    return review_service


@pytest.mark.asyncio
async def test_project_document_review_requires_review_of_each_annotation(client, isolated_document_review_api):
    project_id = "project_1"
    response = await client.post(
        f"/api/v1/projects/{project_id}/document-reviews",
        files={
            "document": ("paper.tex", b"\\documentclass{article}\nText  here. \\cite{missing}", "application/x-tex")
        },
    )

    assert response.status_code == 201, response.text
    review = response.json()
    warning = next(item for item in review["annotations"] if item["type"] == "warning")
    suggestion = next(item for item in review["annotations"] if item["type"] == "suggest")
    assert "suggested_fix" not in warning

    accepted = await client.patch(
        f"/api/v1/projects/{project_id}/document-reviews/{review['review_id']}/annotations/{suggestion['annotation_id']}",
        json={"action": "accept"},
    )
    assert accepted.status_code == 200
    assert "Text here" in accepted.json()["content"]

    rejected = await client.patch(
        f"/api/v1/projects/{project_id}/document-reviews/{review['review_id']}/annotations/{warning['annotation_id']}",
        json={"action": "accept"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "DOCUMENT_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_pdf_review_can_be_reanalyzed_after_upload(client, isolated_document_review_api):
    project_id = "project_1"
    review = await isolated_document_review_api.create(
        project_id, "paper.tex", b"\\documentclass{article}\nNo automatic issues."
    )
    review["source_format"] = "pdf"
    isolated_document_review_api._write(review)

    response = await client.post(f"/api/v1/projects/{project_id}/document-reviews/{review['review_id']}/reanalyze")

    assert response.status_code == 200, response.text
    assert response.json()["annotations"][0]["aspect"] == "pdf_conversion"


@pytest.mark.asyncio
async def test_claim_verification_endpoint_returns_reviewable_evidence(client, isolated_document_review_api):
    project_id = "project_1"
    review = await isolated_document_review_api.create(
        project_id,
        "paper.tex",
        b"\\documentclass{article}\nQMugs is a molecular dataset \\cite{qmugs}.",
    )

    async def verify(review_id: str):
        record = isolated_document_review_api.get(review_id)
        record["annotations"].append(
            _annotation(
                record["content"],
                annotation_type="verification",
                aspect="claim_citation",
                comment="The abstract supports this claim.",
                exact="QMugs is a molecular dataset \\cite{qmugs}.",
                evidence={
                    "verdict": "supported",
                    "confidence": 0.9,
                    "source_scope": "abstract",
                    "evidence_quotes": ["QMugs is a molecular dataset."],
                },
            )
        )
        isolated_document_review_api._write(record)
        return record

    isolated_document_review_api.verify_claim_citations = verify
    response = await client.post(f"/api/v1/projects/{project_id}/document-reviews/{review['review_id']}/verify-claims")

    assert response.status_code == 200, response.text
    finding = next(item for item in response.json()["annotations"] if item["type"] == "verification")
    assert finding["evidence"]["verdict"] == "supported"
    assert "suggested_fix" not in finding
