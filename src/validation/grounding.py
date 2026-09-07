"""Grounding Validation — chống bịa nguồn và claim sai.

OWNER: Member 3
INTERFACE: Leader gọi hàm `validate_summary()` từ Node `summarize_matrix`.

Luồng kiểm tra (3 lớp bảo vệ):
  Layer 1 — Evidence Quote Check  : Câu trích dẫn (evidence_quote) có xuất hiện
                                    trong abstract gốc không?
  Layer 2 — Absolute Wording Check: Loại bỏ các khẳng định tuyệt đối nguy hiểm
                                    ("no study has ever", "never been researched").
  Layer 3 — Citation Integrity    : DOI / URL có đúng định dạng và khớp với
                                    paper_id không?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ─── Từ khóa tuyệt đối cần reject ────────────────────────────────────────────
_ABSOLUTE_WORDING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bno (study|research|paper|work) has (ever )?(examined|studied|investigated|explored)\b", re.I),
    re.compile(r"\bnever (been )?(researched|studied|examined|investigated)\b", re.I),
    re.compile(r"\bno existing (literature|research|study)\b", re.I),
]

# ─── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Kết quả kiểm tra cho 1 bài báo."""

    paper_id: str
    passed: bool
    issues: list[str] = field(default_factory=list)


# ─── Layer 1: Evidence Quote Check ───────────────────────────────────────────


def check_evidence_quote(evidence_quote: str, abstract: str) -> str | None:
    """Kiểm tra xem evidence_quote có xuất hiện trong abstract không.

    Returns:
        None nếu pass. Chuỗi mô tả lỗi nếu fail.
    """
    if not evidence_quote or evidence_quote.strip().lower() in ("", "n/a", "not stated in abstract"):
        return "evidence_quote không được để trống"

    # Substring match (case-insensitive, strip whitespace)
    quote_clean = " ".join(evidence_quote.lower().split())
    abstract_clean = " ".join(abstract.lower().split())

    if quote_clean not in abstract_clean:
        short = evidence_quote[:80]
        return f"evidence_quote không tìm thấy trong abstract: «{short}…»"

    return None


# ─── Layer 2: Absolute Wording Check ─────────────────────────────────────────


def check_absolute_wording(text: str) -> str | None:
    """Phát hiện khẳng định tuyệt đối trong contribution / limitations.

    Returns:
        None nếu pass. Chuỗi mô tả lỗi nếu fail.
    """
    for pattern in _ABSOLUTE_WORDING_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"Khẳng định tuyệt đối bị loại: «{match.group()}»"
    return None


# ─── Layer 3: Citation Integrity Check ───────────────────────────────────────


def check_citation_integrity(paper_id: str, doi: str | None, url: str) -> str | None:
    """Kiểm tra cơ bản DOI format và OpenAlex URL.

    Returns:
        None nếu pass. Chuỗi mô tả lỗi nếu fail.
    """
    if doi and not re.match(r"^10\.\d{4,}/\S+$", doi):
        return f"DOI sai định dạng: {doi}"

    if url and "openalex.org" in url:
        expected_suffix = paper_id.upper()
        if expected_suffix not in url.upper():
            return f"OpenAlex URL không khớp paper_id '{paper_id}': {url}"

    return None


# ─── Public Interface ─────────────────────────────────────────────────────────


def validate_summary(
    paper_id: str,
    abstract: str,
    evidence_quote: str,
    contribution: str,
    limitations: str,
    doi: str | None,
    url: str,
) -> ValidationResult:
    """Chạy toàn bộ 3 lớp kiểm tra cho 1 bài báo.

    Args:
        paper_id      : ID bài báo (ví dụ: "W2741809807")
        abstract      : Nội dung abstract gốc
        evidence_quote: Câu trích dẫn bằng chứng do LLM trích xuất
        contribution  : Mô tả đóng góp do LLM tổng hợp
        limitations   : Mô tả hạn chế do LLM tổng hợp
        doi           : DOI của bài báo (có thể None)
        url           : URL OpenAlex của bài báo

    Returns:
        ValidationResult với passed=True nếu không có vấn đề gì.
    """
    issues: list[str] = []

    # Layer 1
    err = check_evidence_quote(evidence_quote, abstract)
    if err:
        issues.append(err)

    # Layer 2
    for text_field in (contribution, limitations):
        err = check_absolute_wording(text_field)
        if err:
            issues.append(err)

    # Layer 3
    err = check_citation_integrity(paper_id, doi, url)
    if err:
        issues.append(err)

    return ValidationResult(
        paper_id=paper_id,
        passed=len(issues) == 0,
        issues=issues,
    )
