"""Unit tests cho src/validation/grounding.py.

OWNER: Member 3
Chạy: pytest tests/test_validation/ -v
"""

from src.validation.grounding import (
    ValidationResult,
    check_absolute_wording,
    check_citation_integrity,
    check_evidence_quote,
    validate_summary,
)
from tests.fixtures.mock_papers import MOCK_PAPERS

# ─── Layer 1: Evidence Quote Check ───────────────────────────────────────────


class TestEvidenceQuoteCheck:
    def test_pass_when_quote_found_in_abstract(self):
        abstract = MOCK_PAPERS[0]["abstract"]
        quote = "based solely on attention mechanisms"
        assert check_evidence_quote(quote, abstract) is None

    def test_fail_when_quote_not_in_abstract(self):
        abstract = MOCK_PAPERS[0]["abstract"]
        quote = "this sentence does not appear anywhere in the abstract"
        result = check_evidence_quote(quote, abstract)
        assert result is not None
        assert "không tìm thấy" in result

    def test_fail_when_quote_is_empty(self):
        """Bài lý thuyết không có quote → báo lỗi do thiếu evidence_quote."""
        result = check_evidence_quote("", "any abstract text")
        assert result is not None
        assert "trống" in result

    def test_fail_when_quote_is_na(self):
        result = check_evidence_quote("N/A", "any abstract text")
        assert result is not None
        assert "trống" in result


# ─── Layer 2: Absolute Wording Check ─────────────────────────────────────────


class TestAbsoluteWordingCheck:
    def test_reject_no_study_has_ever(self):
        text = "No study has ever examined this combination."
        result = check_absolute_wording(text)
        assert result is not None
        assert "tuyệt đối" in result

    def test_reject_never_been_researched(self):
        text = "This topic has never been researched before."
        result = check_absolute_wording(text)
        assert result is not None

    def test_pass_for_normal_limitation(self):
        text = "The model struggles with long-context documents exceeding 512 tokens."
        assert check_absolute_wording(text) is None

    def test_pass_for_normal_contribution(self):
        text = "We achieve 28.4 BLEU on WMT 2014 English-to-German translation."
        assert check_absolute_wording(text) is None

    def test_reject_from_mock_paper_w005(self):
        """W005 có câu tuyệt đối trong abstract."""
        abstract_w005 = MOCK_PAPERS[4]["abstract"]
        result = check_absolute_wording(abstract_w005)
        assert result is not None


# ─── Layer 3: Citation Integrity Check ───────────────────────────────────────


class TestCitationIntegrityCheck:
    def test_pass_valid_doi(self):
        result = check_citation_integrity(
            paper_id="W001",
            doi="10.48550/arXiv.1706.03762",
            url="https://openalex.org/W001",
        )
        assert result is None

    def test_fail_invalid_doi_format(self):
        result = check_citation_integrity(
            paper_id="W001",
            doi="NOT_A_VALID_DOI",
            url="https://openalex.org/W001",
        )
        assert result is not None
        assert "DOI" in result

    def test_pass_when_doi_is_none(self):
        """DOI có thể None với bài không có DOI."""
        result = check_citation_integrity(
            paper_id="W001",
            doi=None,
            url="https://openalex.org/W001",
        )
        assert result is None

    def test_fail_url_mismatches_paper_id(self):
        result = check_citation_integrity(
            paper_id="W999",
            doi=None,
            url="https://openalex.org/W001",
        )
        assert result is not None
        assert "W999" in result


# ─── Full validate_summary Integration ───────────────────────────────────────


class TestValidateSummary:
    def test_clean_paper_passes_all_layers(self):
        """W001 (Attention Is All You Need) phải pass toàn bộ."""
        p = MOCK_PAPERS[0]
        result = validate_summary(
            paper_id=p["paper_id"],
            abstract=p["abstract"],
            evidence_quote="based solely on attention mechanisms",
            contribution="Proposes the Transformer, achieving 28.4 BLEU on WMT 2014.",
            limitations="Not stated in abstract",
            doi=p["doi"],
            url=p["url"],
        )
        assert isinstance(result, ValidationResult)
        assert result.passed is True
        assert result.issues == []

    def test_absolute_wording_fails_validation(self):
        """W005 có câu tuyệt đối → phải fail."""
        p = MOCK_PAPERS[4]
        result = validate_summary(
            paper_id=p["paper_id"],
            abstract=p["abstract"],
            evidence_quote="vanilla Transformers lag behind specialized models",
            contribution="No existing research has ever examined the combination of Mamba with financial data.",
            limitations="Future work should explore hybrid architectures.",
            doi=p["doi"],
            url=p["url"],
        )
        assert result.passed is False
        assert len(result.issues) > 0

    def test_fabricated_quote_fails_validation(self):
        """Quote bịa → phải fail Layer 1."""
        p = MOCK_PAPERS[0]
        result = validate_summary(
            paper_id=p["paper_id"],
            abstract=p["abstract"],
            evidence_quote="This quote was completely fabricated by the LLM.",
            contribution="Proposes the Transformer.",
            limitations="Not stated in abstract",
            doi=p["doi"],
            url=p["url"],
        )
        assert result.passed is False
        assert any("không tìm thấy" in issue for issue in result.issues)
