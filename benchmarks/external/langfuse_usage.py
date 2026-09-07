"""Lấy token và chi phí thật của từng lượt review từ Langfuse.

Đây là mảnh còn thiếu của nhóm kinh tế đơn vị. `performance.cost_per_review()`
vốn đã nhận `usage`, nhưng chưa có nguồn dữ liệu nào rót vào — nên báo cáo luôn
in "chưa đo được" ở đúng con số mà nhà đầu tư hỏi đầu tiên.

Vì sao lấy hậu kỳ thay vì đo trong lúc chạy: pipeline gọi LLM ở hàng chục chỗ
qua LangGraph, và cộng token thủ công ở từng chỗ vừa dễ sót vừa dễ đếm trùng.
Langfuse đã gom sẵn theo `sessionId` = `job_id` — chỉ cần đọc lại. Cách này
cũng giữ đúng ranh giới runner/report của bộ đo: chạy lượt benchmark không
đụng gì tới Langfuse, và chi phí có thể lấy về sau mà không phải chạy lại.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_DEFAULT_HOST = "https://cloud.langfuse.com"


def credentials() -> tuple[str, str, str] | None:
    """Trả (host, public_key, secret_key) nếu Langfuse đã được cấu hình."""
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public or not secret:
        return None
    return os.environ.get("LANGFUSE_BASE_URL", _DEFAULT_HOST).strip().rstrip("/"), public, secret


def summarise_trace(trace: dict[str, Any]) -> dict[str, Any] | None:
    """Gộp các lời gọi LLM của một trace thành một bản ghi usage.

    Trả None khi trace không có generation nào — không có gì để đo thì nói là
    chưa đo được, chứ không báo 0 đồng.
    """
    generations = [
        observation for observation in trace.get("observations") or []
        if observation.get("type") == "GENERATION"
    ]
    if not generations:
        return None
    total_cost = sum(float(g.get("calculatedTotalCost") or 0) for g in generations)
    total_tokens = sum(int((g.get("usage") or {}).get("total") or 0) for g in generations)
    # Chi phí bằng 0 gần như luôn nghĩa là Langfuse chưa biết bảng giá của model
    # này, chứ không phải lượt chạy đó miễn phí. In "$0.0000" ra báo cáo là một
    # con số sai trông rất thuyết phục — thà báo chưa đo được.
    if total_cost <= 0:
        return {
            "total_cost_usd": None,
            "total_tokens": total_tokens,
            "call_count": len(generations),
            "unmeasured_reason": (
                f"Langfuse ghi nhận {len(generations)} lời gọi nhưng chi phí = 0 — "
                "nhiều khả năng model chưa có bảng giá trong Langfuse"
            ),
        }
    return {
        "total_cost_usd": total_cost,
        "total_tokens": total_tokens,
        "call_count": len(generations),
        "models": sorted({str(g.get("model")) for g in generations if g.get("model")}),
    }


async def fetch_job_usage(
    job_id: str, *, client: httpx.AsyncClient, host: str, auth: tuple[str, str],
) -> dict[str, Any] | None:
    """Đọc usage của một job qua REST API của Langfuse (`sessionId` = `job_id`)."""
    listing = await client.get(
        f"{host}/api/public/traces", params={"sessionId": job_id, "limit": 50}, auth=auth,
    )
    listing.raise_for_status()
    traces = listing.json().get("data") or []
    if not traces:
        return None
    merged: dict[str, Any] = {"total_cost_usd": 0.0, "total_tokens": 0, "call_count": 0, "models": []}
    seen_any = False
    for stub in traces:
        detail = await client.get(f"{host}/api/public/traces/{stub['id']}", auth=auth)
        detail.raise_for_status()
        summary = summarise_trace(detail.json())
        if not summary:
            continue
        seen_any = True
        merged["total_tokens"] += summary.get("total_tokens") or 0
        merged["call_count"] += summary.get("call_count") or 0
        merged["models"] = sorted(set(merged["models"]) | set(summary.get("models") or []))
        if summary.get("total_cost_usd"):
            merged["total_cost_usd"] += summary["total_cost_usd"]
        elif summary.get("unmeasured_reason"):
            merged.setdefault("unmeasured_reason", summary["unmeasured_reason"])
    if not seen_any:
        return None
    if not merged["total_cost_usd"]:
        merged["total_cost_usd"] = None
    return merged


async def backfill_run_dir(run_dir: Any, runs: list[dict[str, Any]]) -> tuple[int, str]:
    """Gắn `usage` vào từng bản ghi trong `runs.json`.

    Ghi thẳng vào nhật ký chạy để `report` (vốn thuần, không mạng) đọc được mà
    không cần biết Langfuse tồn tại — và để số chi phí đi kèm artifact, kiểm lại
    được về sau.
    """
    creds = credentials()
    if creds is None:
        return 0, (
            "chưa cấu hình LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY — "
            "lệnh này phải chạy trong container để thấy .env của backend"
        )
    host, public, secret = creds
    filled = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for record in runs:
            job_id = record.get("job_id")
            if not job_id:
                continue
            try:
                usage = await fetch_job_usage(job_id, client=client, host=host, auth=(public, secret))
            except Exception as exc:
                record["usage_error"] = f"{type(exc).__name__}: {exc}"[:200]
                continue
            if usage:
                record["usage"] = usage
                filled += 1
    return filled, "OK"
