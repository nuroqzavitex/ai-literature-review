"""Shared result type for every benchmark metric.

Design rule: a metric never reports a bare number. It reports the number plus
the numerator/denominator it came from and the concrete items that failed, so
any reader can audit the claim instead of trusting it. A benchmark whose
numbers cannot be traced back to raw artifacts is a marketing slide, not
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Unit = Literal["ratio", "count", "seconds", "usd", "tokens"]


@dataclass
class MetricResult:
    """One measured number, with everything needed to audit it."""

    name: str
    value: float | None
    unit: Unit
    numerator: float | None = None
    denominator: float | None = None
    detail: str = ""
    # Concrete failing items. This is what turns "97%" into a reviewable claim:
    # a reader can open any failure and check it by hand.
    failures: list[dict[str, Any]] = field(default_factory=list)
    # Set when the metric could not be computed (missing data, provider down).
    # Never silently return 0.0 for "not measured" — that reads as a real
    # result and quietly poisons every average built on top of it.
    unmeasured_reason: str | None = None

    @property
    def measured(self) -> bool:
        return self.unmeasured_reason is None and self.value is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "detail": self.detail,
            "failure_count": len(self.failures),
            "failures": self.failures[:20],
            "measured": self.measured,
            "unmeasured_reason": self.unmeasured_reason,
        }

    def format_value(self) -> str:
        if not self.measured:
            return "chưa đo được"
        assert self.value is not None
        if self.unit == "ratio":
            base = f"{self.value * 100:.1f}%"
        elif self.unit == "seconds":
            base = f"{self.value:.1f}s"
        elif self.unit == "usd":
            base = f"${self.value:.4f}"
        elif self.unit == "tokens":
            base = f"{self.value:,.0f} tokens"
        else:
            base = f"{self.value:g}"
        if self.denominator:
            base += f" ({self.numerator:g}/{self.denominator:g})"
        return base


def ratio(
    name: str,
    numerator: int,
    denominator: int,
    *,
    detail: str = "",
    failures: list[dict[str, Any]] | None = None,
    empty_reason: str = "không có mục nào để đo",
) -> MetricResult:
    """Build a ratio metric, treating an empty denominator as unmeasured.

    0/0 is not 0% and not 100% — reporting either would invent a result the run
    never produced.
    """
    if denominator == 0:
        return MetricResult(
            name=name, value=None, unit="ratio", numerator=0, denominator=0,
            detail=detail, unmeasured_reason=empty_reason,
        )
    return MetricResult(
        name=name,
        value=numerator / denominator,
        unit="ratio",
        numerator=numerator,
        denominator=denominator,
        detail=detail,
        failures=failures or [],
    )
