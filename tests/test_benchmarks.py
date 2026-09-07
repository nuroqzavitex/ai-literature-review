"""Keep the benchmark harness itself under test.

A benchmark is measuring equipment. Equipment that drifts without anyone
noticing is worse than none, because its numbers keep being quoted. These
tests run offline and fast, so a broken metric fails in CI rather than in a
report someone is about to show an investor.
"""

from __future__ import annotations

import pytest

from benchmarks.metrics import coverage, performance, reliability, trust
from benchmarks.selftest import _CLEAN, _STATUS, _cases


@pytest.mark.parametrize("name,check,why", _cases(), ids=lambda value: None)
def test_benchmark_selftest_case(name: str, check, why: str) -> None:
    """Every planted defect must be caught, every clean input left alone."""
    assert check(), f"{name} — {why}"


def test_missing_data_is_never_reported_as_zero() -> None:
    """The failure mode that quietly poisons every average built on top of it."""
    for metric in (
        trust.claim_grounding_rate({"claims": []}),
        coverage.theme_recall(_CLEAN, []),
        performance.cost_per_review(_STATUS),
        performance.human_time_saved(_STATUS, manual_minutes=None),
        reliability.output_consistency([]),
    ):
        assert not metric.measured
        assert metric.value is None
        assert metric.unmeasured_reason, "phải nêu lý do chưa đo được, không để trống"


def test_every_ratio_metric_exposes_its_arithmetic() -> None:
    """A percentage without its numerator/denominator cannot be audited."""
    for metric in (
        trust.fabricated_citation_rate(_CLEAN),
        trust.claim_grounding_rate(_CLEAN),
        coverage.citation_reuse(_CLEAN),
    ):
        assert metric.measured
        assert metric.numerator is not None and metric.denominator is not None
        assert metric.denominator > 0
