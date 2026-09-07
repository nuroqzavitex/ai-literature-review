"""Deterministic normalization for AI-generated analysis result payloads.

Generated code is not trusted to reproduce the wire schema perfectly.  This
module reshapes common representation differences before the strict control
service validator runs.  It never invents numeric observations or bypasses the
scientific checks performed by ``ResultValidator``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from numbers import Integral, Real
from pathlib import Path
import re
from typing import Any

import numpy as np

from sandbox_sdk.io import emit_result


_OBJECTIVES = {"describe", "compare", "associate", "predict"}
_NUMERIC_TEXT = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
_ARTIFACT_REF = re.compile(
    r"^(?:analysis_result\.json|tables/[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.csv|"
    r"charts/[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.png)$"
)


def emit_analysis_result(
    result_dict: dict[str, Any],
    *,
    objective: str,
    method: str,
    preprocessing_steps: Sequence[str] = (),
    planned_assumption_checks: Sequence[str] = (),
    planned_metrics: Sequence[str] = (),
    planned_limitations: Sequence[str] = (),
) -> Path:
    """Normalize one generated payload and emit strict ``analysis_result.v1`` JSON.

    Plan-owned fields are supplied by the control service in generated code,
    so an LLM cannot change the approved objective or method.  Structural
    conversions only preserve model-provided values; unknown/extra fields are
    deliberately discarded.  The control service remains responsible for
    schema and scientific validation after execution.
    """

    if not isinstance(result_dict, dict):
        raise TypeError("emit_analysis_result accepts a dictionary")
    normalized_objective = str(objective).strip().lower()
    if normalized_objective not in _OBJECTIVES:
        raise ValueError("objective is not supported by analysis_result.v1")
    normalized_method = str(method).strip()
    if not normalized_method:
        raise ValueError("method must come from an approved analysis plan")

    input_row_count = _row_count(
        result_dict.get("input_row_count"),
        fallback=result_dict.get("analyzed_row_count"),
    )
    analyzed_row_count = _row_count(
        result_dict.get("analyzed_row_count"),
        fallback=input_row_count,
    )
    diagnostics = result_dict.get("prediction_diagnostics")
    if normalized_objective != "predict":
        diagnostics = None

    normalized = {
        "schema_version": "analysis_result.v1",
        "objective": normalized_objective,
        "method": normalized_method,
        "input_row_count": input_row_count,
        "analyzed_row_count": analyzed_row_count,
        "preprocessing_applied": _text_list(
            result_dict.get("preprocessing_applied"), fallback=preprocessing_steps
        ),
        "assumption_checks": _assumption_checks(
            result_dict.get("assumption_checks"), fallback=planned_assumption_checks
        ),
        "metrics": _metrics(result_dict.get("metrics"), fallback=planned_metrics),
        "statistical_results": _mapping_list(result_dict.get("statistical_results")),
        "warnings": _warnings(result_dict.get("warnings")),
        "limitations": _text_list(
            result_dict.get("limitations"), fallback=planned_limitations
        ),
        "artifact_refs": _artifact_refs(result_dict.get("artifact_refs")),
        "narrative": _narrative(result_dict.get("narrative")),
        "prediction_diagnostics": diagnostics,
    }
    json_ready = _json_value(normalized)
    if not isinstance(json_ready, dict):
        raise TypeError("normalized analysis result must be a dictionary")
    return emit_result(json_ready)


def _row_count(value: Any, *, fallback: Any) -> int:
    candidate = value if value is not None else fallback
    if isinstance(candidate, bool):
        raise TypeError("row count must be a non-negative integer")
    if isinstance(candidate, int) and candidate >= 0:
        return candidate
    raise TypeError("row count must be a non-negative integer")


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return list(value)
    return [value]


def _text_list(value: Any, *, fallback: Sequence[str] = ()) -> list[str]:
    items = _items(value)
    if not items:
        items = list(fallback)
    return [str(item).strip() for item in items if str(item).strip()]


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _items(value) if isinstance(item, Mapping)]


def _assumption_checks(
    value: Any, *, fallback: Sequence[str]
) -> list[dict[str, Any]]:
    items = _items(value)
    if not items:
        items = list(fallback)
    checks: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            check = dict(item)
            if not str(check.get("name") or "").strip():
                check["name"] = "reported_assumption_check"
            check.setdefault("passed", None)
            checks.append(check)
        elif str(item).strip():
            checks.append({"name": str(item).strip(), "passed": None})
    if not checks:
        checks.append({"name": "assumption_checks_not_reported", "passed": None})
    return checks


def _metrics(value: Any, *, fallback: Sequence[str]) -> list[dict[str, Any]]:
    items = _items(value)
    approved_names = {
        _normalized_label(str(name)): str(name).strip()
        for name in fallback
        if str(name).strip()
    }
    metrics: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            metric = dict(item)
            name = str(metric.get("name") or "").strip()
            if not name:
                continue
            normalized_name = _normalized_label(name)
            if approved_names and normalized_name not in approved_names:
                continue
            canonical_name = approved_names.get(normalized_name, name)
            raw_value = metric.get("value")
            scalar_value = _metric_scalar(raw_value)
            details = (
                dict(metric.get("details") or {})
                if isinstance(metric.get("details"), Mapping)
                else {"reported_details": str(metric.get("details"))}
            )
            if raw_value is not None and scalar_value is None:
                # Confidence intervals and other structured observations belong
                # in statistical_results. Keeping a list/dict in metrics.value
                # would violate the strict AnalysisMetric wire contract.
                details["non_scalar_value_omitted"] = True
            metrics.append(
                {
                    "name": canonical_name,
                    "value": scalar_value,
                    "details": details,
                }
            )
        elif str(item).strip():
            name = str(item).strip()
            normalized_name = _normalized_label(name)
            if approved_names and normalized_name not in approved_names:
                continue
            metrics.append(
                {
                    "name": approved_names.get(normalized_name, name),
                    "value": None,
                    "details": {"value_not_structured_by_generated_code": True},
                }
            )
    return metrics


def _metric_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, Integral, Real, Decimal, np.generic)):
        return value
    return None


def _normalized_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _artifact_refs(value: Any) -> list[str]:
    references: list[str] = []
    for item in _items(value):
        reference = str(item).strip().replace("\\", "/")
        for prefix in ("/workspace/output/", "workspace/output/"):
            if reference.startswith(prefix):
                reference = reference[len(prefix) :]
                break
        if _ARTIFACT_REF.fullmatch(reference) and reference not in references:
            references.append(reference)
    return references


def _narrative(value: Any) -> list[str]:
    # Runtime narrative is deliberately data-free. Numeric observations remain
    # in metrics/statistical_results so the interpretation service can attach
    # an AnalysisCitation before presenting them as prose.
    return [text for text in _text_list(value) if not _NUMERIC_TEXT.search(text)]


def _json_value(value: Any) -> Any:
    """Convert bounded scientific scalar values to strict JSON primitives."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, (Real, Decimal)):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Result JSON keys must be strings")
            converted[key] = _json_value(item)
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise TypeError("Result JSON contains an unsupported scientific value")


def _warnings(value: Any) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, Mapping):
            warnings.append(dict(item))
        elif str(item).strip():
            warnings.append({"message": str(item).strip()})
    return warnings
