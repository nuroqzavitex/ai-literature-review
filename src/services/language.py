"""Shared response-language detection helpers."""

from __future__ import annotations

import re

VIETNAMESE_CHARS = frozenset("àáạảãâầấậẩẫèéẹẻẽêềếệểễòóọỏõôồốộổỗùúụủũưừứựửữìíịỉĩỳýỵỷỹđơ")
VIETNAMESE_WORDS = frozenset(
    {
        "tôi",
        "bạn",
        "cho",
        "các",
        "bài",
        "báo",
        "về",
        "và",
        "là",
        "được",
        "nghiên",
        "cứu",
        "tổng",
        "hợp",
        "giải",
        "thích",
        "tìm",
    }
)


def response_language(topic: str) -> str:
    """Return the output language required for a user topic.

    The detector is deliberately conservative: Vietnamese diacritics or common
    Vietnamese words win; otherwise the LLM must reply in the language it sees.
    """
    lower = topic.lower()
    if sum(char in VIETNAMESE_CHARS for char in lower) >= 1:
        return "Vietnamese"
    words = set(re.findall(r"[\w]+", lower, flags=re.UNICODE))
    return "Vietnamese" if len(words & VIETNAMESE_WORDS) >= 2 else "the same language as the user's topic"
