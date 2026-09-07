"""Probe each configured Gemini key without exposing credentials.

This is an operational diagnostic only; it does not modify the application or
benchmark artifacts.  One tiny request is sent per configured candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path


async def _probe(index: int, candidate, semaphore: asyncio.Semaphore) -> dict:
    endpoint = candidate.endpoint
    async with semaphore:
        try:
            response = await asyncio.wait_for(
                candidate.ainvoke("Reply with exactly OK."), timeout=20.0
            )
            return {
                "index": index,
                "provider": endpoint.provider,
                "model": endpoint.model,
                "status": "ok",
                "response_type": type(response).__name__,
            }
        except asyncio.TimeoutError:
            return {
                "index": index,
                "provider": endpoint.provider,
                "model": endpoint.model,
                "status": "timeout",
                "error": "probe exceeded 20s",
            }
        except Exception as exc:  # noqa: BLE001 - diagnostic must continue per key
            message = " ".join(str(exc).split())[:240]
            return {
                "index": index,
                "provider": endpoint.provider,
                "model": endpoint.model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": message,
            }


async def main(concurrency: int) -> list[dict]:
    from src.services.llm import get_llm, get_llm_fallbacks

    candidates = [get_llm(), *get_llm_fallbacks()]
    semaphore = asyncio.Semaphore(max(1, concurrency))
    return await asyncio.gather(*(_probe(i + 1, candidate, semaphore) for i, candidate in enumerate(candidates)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe configured Gemini keys; never prints API keys.")
    parser.add_argument("--concurrency", type=int, default=1, help="Requests in flight (default: 1).")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()
    results = asyncio.run(main(args.concurrency))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.output:
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
