"""Trust metrics — can this system be believed?

This is the product's core claim: every statement traces to a real source.
These metrics try to falsify that claim. They are deliberately the harshest
family in the suite, because a research tool that invents citations is worse
than no tool at all.

All functions are pure: they take the review-result JSON the API already
returns and compute from it. No running system required, so a saved artifact
can be re-audited months later.
"""

from __future__ import annotations

import re
from typing import Any

from benchmarks.metrics.base import MetricResult, ratio


def _normalize(text: str) -> str:
    """Collapse whitespace so a quote is compared on words, not formatting.

    PDF and abstract extraction differ in line breaks and double spaces; those
    differences are not fabrication and must not be counted as one.
    """
    return " ".join(str(text or "").split()).casefold()


def _corpus_paper_ids(result: dict[str, Any]) -> set[str]:
    ids = {str(p.get("paper_id")) for p in result.get("papers") or []}
    ids |= {str(r.get("paper_id")) for r in result.get("references") or []}
    return {i for i in ids if i and i != "None"}


def fabricated_citation_rate(result: dict[str, Any]) -> MetricResult:
    """Share of cited paper_ids that do not exist in the retrieved corpus.

    A non-zero value means the model referenced a paper the pipeline never
    fetched — the clearest possible fabrication signal, and one that needs no
    network call to detect.
    """
    corpus = _corpus_paper_ids(result)
    cited: list[tuple[str, str]] = []
    for claim in result.get("claims") or []:
        claim_id = str(claim.get("claim_id"))
        for paper_id in claim.get("supporting_paper_ids") or []:
            cited.append((claim_id, str(paper_id)))
        for item in claim.get("evidence") or []:
            cited.append((claim_id, str(item.get("paper_id"))))

    failures = [
        {"claim_id": claim_id, "paper_id": paper_id, "reason": "không có trong corpus đã truy xuất"}
        for claim_id, paper_id in cited
        if paper_id and paper_id not in corpus
    ]
    metric = ratio(
        "Trích dẫn bịa (fabricated citations)",
        numerator=len(failures),
        denominator=len(cited),
        detail="Tỷ lệ paper_id được trích dẫn nhưng KHÔNG tồn tại trong corpus. Mục tiêu: 0%.",
        failures=failures,
        empty_reason="không có trích dẫn nào trong kết quả",
    )
    return metric


def quote_verifiability(result: dict[str, Any]) -> MetricResult:
    """Share of evidence quotes found verbatim in the source text we hold.

    Only quotes whose source text is present in the artifact are counted.
    A full-text quote whose full text was not saved is reported as
    *unverifiable*, never as a pass or a fail — claiming to have verified
    something we could not read is exactly the dishonesty this suite exists
    to prevent.
    """
    abstracts = {
        str(p.get("paper_id")): _normalize(p.get("abstract", ""))
        for p in result.get("papers") or []
    }
    checked = 0
    passed = 0
    unverifiable = 0
    failures: list[dict[str, Any]] = []

    for claim in result.get("claims") or []:
        for item in claim.get("evidence") or []:
            quote = _normalize(item.get("quote", ""))
            paper_id = str(item.get("paper_id"))
            if not quote:
                continue
            source = abstracts.get(paper_id, "")
            # A full-text quote legitimately will not appear in the abstract;
            # without the stored full text there is nothing to check against.
            if not source or item.get("source_level") == "full_text":
                unverifiable += 1
                continue
            checked += 1
            if quote in source:
                passed += 1
            else:
                failures.append({
                    "claim_id": claim.get("claim_id"),
                    "paper_id": paper_id,
                    "quote": item.get("quote", "")[:160],
                    "reason": "không tìm thấy nguyên văn trong abstract nguồn",
                })

    metric = ratio(
        "Trích dẫn kiểm chứng được (verbatim)",
        numerator=passed,
        denominator=checked,
        detail=(
            "Tỷ lệ quote khớp NGUYÊN VĂN với nguồn đang lưu. Quote lấy từ full text "
            "mà artifact không lưu toàn văn được loại khỏi mẫu số — không kiểm được "
            "offline thì không cho qua, cũng không tính trượt."
        ),
        failures=failures,
        empty_reason="không có quote nào kiểm được offline",
    )
    return metric


def claim_grounding_rate(result: dict[str, Any]) -> MetricResult:
    """Share of accepted claims carrying at least one non-empty quote.

    A claim marked valid with no quote behind it is an unsupported assertion
    wearing a validated badge.
    """
    claims = [
        c for c in result.get("claims") or []
        if c.get("validation_status") == "valid"
        # A potential_gap asserts an absence — the corpus itself is the
        # evidence, so it carries no quote by design. Demanding one flags
        # correct behaviour as a defect.
        and c.get("claim_type") != "potential_gap"
    ]
    grounded = 0
    failures: list[dict[str, Any]] = []
    for claim in claims:
        quotes = [q for q in claim.get("evidence") or [] if str(q.get("quote") or "").strip()]
        if quotes:
            grounded += 1
        else:
            failures.append({
                "claim_id": claim.get("claim_id"),
                "claim_type": claim.get("claim_type"),
                "text": str(claim.get("text", ""))[:160],
                "reason": "claim hợp lệ nhưng không có quote nào",
            })
    return ratio(
        "Claim có bằng chứng",
        numerator=grounded,
        denominator=len(claims),
        detail=(
            "Tỷ lệ claim được đánh dấu hợp lệ mà thực sự kèm ít nhất một trích dẫn. "
            "Claim loại `potential_gap` (khẳng định sự VẮNG MẶT) không được tính, "
            "vì bằng chứng của nó là chính corpus chứ không phải một quote."
        ),
        failures=failures,
        empty_reason="không có claim hợp lệ nào",
    )


def negative_control(
    *, papers: int, valid_claims: int, pipeline_outcome: str = "", refusal_kind: str | None = None,
) -> MetricResult:
    """Nonsense in must produce nothing out.

    The strongest single guard against a system that always finds something.
    Without it, a pipeline that hallucinates confidently scores well on every
    other metric.

    Judged on *output emptiness*, but an empty output produced by an
    infrastructure crash (``refusal_kind="infrastructure_error"``) does NOT
    count as a pass: a DB outage that happened to yield nothing proves nothing
    about honesty — counting it would let a completely broken pipeline score
    100% here. Only a clean completion or an explicit refusal does.
    """
    clean = papers == 0 and valid_claims == 0
    infra_crash = clean and refusal_kind == "infrastructure_error"
    passed = clean and not infra_crash
    refusal_note = f" Pipeline kết thúc ở trạng thái `{pipeline_outcome}`." if pipeline_outcome else ""
    if infra_crash:
        refusal_note += " Phân loại: lỗi hạ tầng, không phải từ chối có chủ đích."
    return MetricResult(
        name="Kiểm soát âm (chủ đề vô nghĩa)",
        value=1.0 if passed else 0.0,
        unit="ratio",
        numerator=1 if passed else 0,
        denominator=1,
        detail=(
            "Chủ đề vô nghĩa PHẢI trả về rỗng — dừng bằng cách nào không quan trọng, "
            f"miễn là không bịa. Thực tế: {papers} bài, {valid_claims} claim hợp lệ.{refusal_note}"
        ),
        failures=[] if passed else [{
            "reason": (
                "lỗi hạ tầng mà output rỗng — không chứng minh được từ chối có chủ đích"
                if infra_crash else "bịa kết quả cho chủ đề không tồn tại"
            ),
            "papers": papers, "valid_claims": valid_claims,
        }],
    )


def source_resolvability(runs: list[dict[str, Any]]) -> MetricResult | None:
    """Share of corpus papers that exist at the real upstream provider.

    Pure: reads the ``source_check`` results that ``verify-sources`` (external/
    source_check.py) fetched and stored in runs.json — so a report stays
    offline-reproducible while the network part lives in one auditable place.

    Papers the checker could not query (provider hiccup, unknown ID prefix)
    are excluded from the denominator and listed with a reason: a failed
    lookup says nothing about the product and must not masquerade as either
    a pass or a fabrication.
    """
    resolved = 0
    not_found: list[dict[str, Any]] = []
    errors: list[str] = []
    for record in runs:
        check = record.get("source_check") or {}
        resolved += int(check.get("resolved") or 0)
        not_found.extend(
            {"topic_id": record.get("topic_id"), "paper_id": paper_id, "reason": "không tra được ở nguồn gốc"}
            for paper_id in check.get("not_found") or []
        )
        errors.extend(f"{record.get('topic_id')}: {item}" for item in check.get("errors") or [])
    if resolved == 0 and not not_found:
        if errors:
            return MetricResult(
                name="Nguồn tra cứu được thật", value=None, unit="ratio",
                detail=f"Tra không được paper nào — {len(errors)} lỗi phía kiểm tra/nhà cung cấp.",
                unmeasured_reason="mọi lượt tra đều lỗi — chạy lại verify-sources",
            )
        return None  # verify-sources chưa chạy cho thư mục này
    detail = "Tỷ lệ paper trong corpus tồn tại thật khi gọi lại API nguồn (OpenAlex / Semantic Scholar / arXiv)."
    if errors:
        detail += f" {len(errors)} ID không tra được đã loại khỏi mẫu số (lỗi kiểm tra, không tính vào kết quả)."
    return ratio(
        "Nguồn tra cứu được thật",
        numerator=resolved,
        denominator=resolved + len(not_found),
        detail=detail,
        failures=not_found,
        empty_reason="không có paper nào tra được",
    )


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_INLINE_CITATION = re.compile(r"\[\[([^\[\]]+)\]\]")


def _review_blocks(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the review prose which makes factual claims, with locations.

    Titles/headings are deliberately excluded: a heading is not an assertion
    that needs a paper citation.  Every remaining populated review field is a
    block that a reader can open and audit in the saved artifact.
    """
    review = result.get("literature_review") or {}
    if not isinstance(review, dict):
        return []
    blocks: list[tuple[str, str]] = []
    for field in ("abstract", "introduction", "conclusion", "limitations"):
        text = str(review.get(field) or "").strip()
        if text:
            blocks.append((field, text))
    for section_index, section in enumerate(review.get("sections") or [], start=1):
        if not isinstance(section, dict):
            continue
        for paragraph_index, paragraph in enumerate(section.get("paragraphs") or [], start=1):
            text = str(paragraph or "").strip()
            if text:
                blocks.append((f"sections[{section_index}].paragraphs[{paragraph_index}]", text))
    return blocks


def review_citation_validity(result: dict[str, Any]) -> MetricResult:
    """Check that every ``[[paper_id]]`` in the final review exists in corpus.

    Unlike :func:`fabricated_citation_rate`, this examines the prose the user
    actually reads, not the intermediate claim objects.  It proves citation
    traceability only; semantic entailment remains the RAGAS Faithfulness
    judge's job.
    """
    blocks = _review_blocks(result)
    if not blocks:
        return MetricResult(
            name="Citation review trỏ tới paper đã lấy",
            value=None,
            unit="ratio",
            unmeasured_reason="artifact không có literature_review để kiểm citation",
        )
    corpus = _corpus_paper_ids(result)
    cited = [
        (location, paper_id.strip())
        for location, text in blocks
        for paper_id in _INLINE_CITATION.findall(text)
        if paper_id.strip()
    ]
    unknown = [
        {"location": location, "paper_id": paper_id, "reason": "citation review không có trong corpus đã lấy"}
        for location, paper_id in cited
        if paper_id not in corpus
    ]
    return ratio(
        "Citation review trỏ tới paper đã lấy",
        numerator=len(cited) - len(unknown),
        denominator=len(cited),
        detail=(
            "Kiểm từng `[[paper_id]]` trong bản literature review cuối có thuộc corpus trả về hay không. "
            "Đây là tính toàn vẹn định danh, không tự khẳng định câu văn được suy ra đúng."
        ),
        failures=unknown,
        empty_reason="bản review không có citation `[[paper_id]]` nào",
    )


def review_evidence_coverage(result: dict[str, Any]) -> MetricResult:
    """Share of factual review blocks citing a corpus paper with checked evidence.

    A citation is counted as evidence-backed when that paper has at least one
    non-empty quote attached to a valid final claim.  This gives a deterministic
    trace from final prose -> paper -> extracted evidence.  It intentionally
    does not claim the quote entails every sentence in the block; RAGAS
    Faithfulness evaluates that semantic relation separately.
    """
    blocks = _review_blocks(result)
    if not blocks:
        return MetricResult(
            name="Đoạn review có evidence truy vết được",
            value=None,
            unit="ratio",
            unmeasured_reason="artifact không có literature_review để kiểm evidence",
        )
    evidence_papers = {
        str(evidence.get("paper_id") or "").strip()
        for claim in result.get("claims") or []
        if claim.get("validation_status") == "valid"
        for evidence in claim.get("evidence") or []
        if str(evidence.get("paper_id") or "").strip() and str(evidence.get("quote") or "").strip()
    }
    covered = 0
    failures: list[dict[str, Any]] = []
    for location, text in blocks:
        cited = {paper_id.strip() for paper_id in _INLINE_CITATION.findall(text) if paper_id.strip()}
        backed = sorted(cited & evidence_papers)
        if backed:
            covered += 1
            continue
        failures.append({
            "location": location,
            "cited_paper_ids": sorted(cited),
            "reason": (
                "đoạn review không có citation" if not cited
                else "citation review không nối được tới evidence quote của claim hợp lệ"
            ),
        })
    return ratio(
        "Đoạn review có evidence truy vết được",
        numerator=covered,
        denominator=len(blocks),
        detail=(
            "Mỗi đoạn factual (abstract/introduction/sections/conclusion/limitations) phải có ít nhất một "
            "`[[paper_id]]` mà cùng paper đó có evidence quote ở claim hợp lệ. Đây là traceability, "
            "không phải chứng minh entailment ở mức câu."
        ),
        failures=failures,
        empty_reason="bản review không có đoạn nào để kiểm",
    )


def evidence_density(result: dict[str, Any]) -> MetricResult:
    """Average number of distinct supporting papers per accepted claim.

    Separates "cited once, weakly" from "corroborated across the corpus".
    """
    claims = [c for c in result.get("claims") or [] if c.get("validation_status") == "valid"]
    if not claims:
        return MetricResult(
            name="Số nguồn/claim", value=None, unit="count",
            detail="", unmeasured_reason="không có claim hợp lệ nào",
        )
    total = sum(len({str(p) for p in (c.get("supporting_paper_ids") or [])}) for c in claims)
    return MetricResult(
        name="Số nguồn/claim",
        value=total / len(claims),
        unit="count",
        numerator=total,
        denominator=len(claims),
        detail="Trung bình số bài báo khác nhau chống lưng cho mỗi claim.",
    )
