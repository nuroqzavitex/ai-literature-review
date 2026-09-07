"""Tra lại từng paper trong corpus ở API gốc — chứng minh corpus là thật.

Các chỉ số trust khác chứng minh *nhất quán nội bộ* (quote khớp abstract đang
lưu, citation có trong corpus). Riêng lớp này trả lời câu hỏi mạnh hơn: chính
corpus đó có tồn tại thật ở nhà cung cấp không — gọi lại OpenAlex / Semantic
Scholar / arXiv theo tiền tố ``paper_id``.

Chạy hậu kỳ như ``costs``: kết quả tra được ghi vào ``runs.json`` (field
``source_check``), còn ``report`` giữ thuần offline và chỉ đọc kết quả đã lưu.
Một lỗi mạng khi tra là lỗi của bên kiểm tra, không được tính chống sản phẩm:
những ID tra không được (lỗi hạ tầng, hoặc tiền tố lạ) bị loại khỏi mẫu số và
ghi kèm lý do, thay vì quy thành "nguồn bịa".
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

# arXiv DOI/ID có hậu tố phiên bản ("2509.07887v1") mà API không nhận.
_ARXIV_VERSION = re.compile(r"v\d+$")


def endpoint_for(paper_id: str) -> tuple[str, str] | None:
    """(provider, url) cho một paper_id — thuần, không mạng, test được offline."""
    pid = str(paper_id or "").strip()
    if pid.startswith("W") and pid[1:].isdigit():
        return "openalex", f"https://api.openalex.org/works/{pid}"
    if pid.startswith("arxiv:"):
        aid = _ARXIV_VERSION.sub("", pid[len("arxiv:"):])
        return "arxiv", f"https://export.arxiv.org/api/query?id_list={aid}"
    if pid.startswith("s2:"):
        return (
            "semantic_scholar",
            f"https://api.semanticscholar.org/graph/v1/paper/{pid[3:]}?fields=paperId",
        )
    if pid.startswith("doi:"):
        return "openalex", f"https://api.openalex.org/works/doi:{pid[4:]}"
    return None


async def resolve_paper(
    client: httpx.AsyncClient, paper_id: str, *, retries: int = 2,
) -> bool | None:
    """True/False khi nguồn gốc khẳng định có/không; None khi không tra được.

    ``None`` dùng cho: tiền tố lạ (không biết tra ở đâu) và mọi HTTP status
    ngoài 200/404 sau khi đã retry (rate limit, 5xx) — những trường hợp đó
    nói về phía kiểm tra hoặc nhà cung cấp, không nói về sản phẩm.

    429 được retry với backoff vì Semantic Scholar Limit không cần key thỉnh
    thoảng từ chối cả requ chỉ sau 1 giây — bỏ cuộc ngay sẽ bỏ sót phần lớn
    corpus S2 chỉ vì phía kiểm tra bị throttle.
    """
    endpoint = endpoint_for(paper_id)
    if endpoint is None:
        return None
    provider, url = endpoint
    for attempt in range(retries + 1):
        response = await client.get(url)
        if response.status_code == 404:
            return False
        if response.status_code == 200:
            # arXiv trả 200 kèm một entry "Error" cho ID không tồn tại.
            if provider == "arxiv":
                return "<title>Error</title>" not in response.text
            return True
        if response.status_code == 429 and attempt < retries:
            retry_after = response.headers.get("Retry-After")
            pause = float(retry_after) if retry_after else 2.0 * (attempt + 1)
            await asyncio.sleep(min(pause, 10.0))
            continue
        return None
    return None


async def backfill_run_dir(run_dir: Path, runs: list[dict[str, Any]], *, limit: int = 30) -> tuple[int, str]:
    """Tra corpus của từng lượt hoàn tất rồi ghi ``source_check`` vào runs.json."""
    filled = 0
    attempted = 0
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "litreview-benchmark/1.0"},
        follow_redirects=True,
    ) as client:
        for record in runs:
            if record.get("outcome") != "completed":
                continue
            artifact_name = record.get("artifact")
            result: dict[str, Any] = {}
            if artifact_name and (run_dir / artifact_name).exists():
                result = json.loads((run_dir / artifact_name).read_text(encoding="utf-8")).get("result") or {}
            paper_ids = [str(p.get("paper_id")) for p in result.get("papers") or []][:limit]
            if not paper_ids:
                continue
            attempted += 1
            check: dict[str, Any] = {"resolved": 0, "not_found": [], "errors": []}
            last_semantic_call = 0.0
            for paper_id in paper_ids:
                endpoint = endpoint_for(paper_id)
                # Semantic Scholar Limit không cần key ~1 req/s — chờ thêm để
                # không tự tạo lỗi 429 rồi quy oan cho corpus.
                if endpoint and endpoint[0] == "semantic_scholar":
                    wait = 1.5 - (time.monotonic() - last_semantic_call)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    last_semantic_call = time.monotonic()
                try:
                    found = await resolve_paper(client, paper_id)
                except Exception as exc:
                    check["errors"].append(f"{paper_id}: {type(exc).__name__}: {exc}"[:150])
                    continue
                if found is True:
                    check["resolved"] += 1
                elif found is False:
                    check["not_found"].append(paper_id)
                else:
                    check["errors"].append(f"{paper_id}: không tra được (tiền tố lạ hoặc lỗi nhà cung cấp)")
            record["source_check"] = check
            if check["resolved"] or check["not_found"]:
                filled += 1
            print(
                f"  {record.get('topic_id')}: tra được {check['resolved']}, "
                f"không tồn tại {len(check['not_found'])}, lỗi kiểm tra {len(check['errors'])}",
                flush=True,
            )
    if attempted:
        target = run_dir / "runs.json"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
    if filled:
        return filled, "OK"
    if attempted:
        return 0, "đã tra nhưng không xác nhận được nguồn nào; xem source_check.errors"
    return 0, "không có lượt hoàn tất nào có corpus để tra"
