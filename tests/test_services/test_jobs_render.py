from src.agents.litreview.application.jobs import _render_report_message


def test_report_renderer_uses_literature_review_prose_and_inline_citations():
    result = {
        "original_topic": "LLM reliability",
        "response_language": "Vietnamese",
        "papers_count": 1,
        "claims": [
            {
                "claim_id": "claim_1",
                "text": "LLM có thể tạo ra thông tin không chính xác.",
                "validation_status": "valid",
                "supporting_paper_ids": ["paper_1"],
                "evidence": [{"paper_id": "paper_1", "quote": "Models can hallucinate.", "section": "abstract"}],
            }
        ],
        "themes": [],
        "literature_review": {
            "title": "Literature review: LLM reliability",
            "abstract": "Abstract",
            "introduction": "The reviewed papers address reliability [[paper_1]].",
            "sections": [
                {
                    "title": "Grounding",
                    "paragraphs": ["Grounding reduces unsupported outputs [[paper_1]]."],
                    "supporting_paper_ids": ["paper_1"],
                }
            ],
            "conclusion": "Evidence-backed generation improves reliability [[paper_1]].",
            "limitations": "The conclusion is limited to the reviewed corpus [[paper_1]].",
        },
        "scope_disclaimer": "Kết luận chỉ dựa trên corpus đã chọn.",
        "references": [
            {
                "paper_id": "paper_1",
                "title": "Grounding LLM outputs",
                "authors": ["Author"],
                "year": 2025,
                "url": "https://example.com/paper",
            }
        ],
    }

    output = _render_report_message(result)

    assert "## Giới thiệu" in output
    assert "## Grounding" in output
    assert "## Kết luận" in output
    assert "## Phạm vi và hạn chế" in output
    assert "## Tài liệu tham khảo" in output
    assert "[[cite:1:https://example.com/paper]]" in output
    assert "Luận điểm và bằng chứng trực tiếp" not in output
