"""Strict deterministic validation for sandbox result artifacts.

This module intentionally has no AI dependency: a failed result never becomes a
prompt payload.  It validates the compact structured result before any prose is
generated or reviewed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from sandbox_service.domain.analysis_plans import AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetProfile
from sandbox_service.domain.results import AnalysisResult


class ResultValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class ValidatedResult:
    result: AnalysisResult
    result_hash: str
    warnings: tuple[str, ...] = ()


class ResultValidator:
    """Deterministic schema, privacy, and scientific consistency checks."""

    VERSION = "result_validator.v1"
    _PATH_OR_SECRET = re.compile(
        r"(?:[A-Za-z]:[\\/]|(?:^|\s)\.\.?[\\/]|/(?:home|etc|var|tmp|proc|sys|users?)/|\\\\|"
        r"(?:api[_-]?key|secret|password|token)\s*[=:])",
        re.IGNORECASE,
    )
    _CAUSAL = re.compile(r"\b(caus(?:e|es|ed|al)|caused by|leads? to|drives?)\b", re.IGNORECASE)
    _NUMERIC = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")

    def validate(
        self,
        *,
        raw_result: bytes,
        plan: AnalysisPlanVersion,
        profile: DatasetProfile,
        artifact_filenames: set[str],
    ) -> ValidatedResult:
        errors: list[str] = []
        try:
            parsed = json.loads(raw_result.decode("utf-8"), parse_constant=self._reject_non_finite)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ResultValidationError([f"analysis_result.json is not strict JSON: {exc}"]) from exc
        if not isinstance(parsed, dict):
            raise ResultValidationError(["analysis_result.json must be a JSON object"])
        self._scan_safe(parsed, path="$", errors=errors)
        try:
            result = AnalysisResult.model_validate(parsed)
        except ValidationError as exc:
            errors.append(f"analysis_result.json violates schema: {exc.errors(include_url=False)}")
            result = None
        if result is not None:
            self._scientific_checks(
                result=result,
                plan=plan,
                profile=profile,
                artifact_filenames=artifact_filenames,
                errors=errors,
            )
        if errors:
            raise ResultValidationError(errors)
        return ValidatedResult(
            result=result,
            result_hash=hashlib.sha256(self._canonical_json(parsed)).hexdigest(),
        )

    @staticmethod
    def _reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value!r} is prohibited")

    @classmethod
    def _scan_safe(cls, value: Any, *, path: str, errors: list[str]) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f"{path} contains NaN or Infinity")
        elif isinstance(value, str) and cls._PATH_OR_SECRET.search(value):
            errors.append(f"{path} contains a path or secret-like value")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._scan_safe(item, path=f"{path}[{index}]", errors=errors)
        elif isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    errors.append(f"{path} contains a non-string key")
                cls._scan_safe(item, path=f"{path}.{key}", errors=errors)

    def _scientific_checks(
        self,
        *,
        result: AnalysisResult,
        plan: AnalysisPlanVersion,
        profile: DatasetProfile,
        artifact_filenames: set[str],
        errors: list[str],
    ) -> None:
        if result.objective != plan.objective.value:
            errors.append("result objective does not match the approved plan")
        if result.input_row_count != profile.row_count:
            errors.append("input_row_count does not match the pinned dataset profile")
        if result.analyzed_row_count > result.input_row_count:
            errors.append("analyzed_row_count cannot exceed input_row_count")
        if not result.assumption_checks:
            errors.append("at least one assumption check is required")
        if not self._methods_compatible(result.method, plan.method):
            errors.append("result method does not match the approved plan")
        allowed_metrics = {self._normalized(metric) for metric in plan.evaluation_metrics}
        emitted_metrics = {self._normalized(metric.name) for metric in result.metrics}
        if emitted_metrics and allowed_metrics and not emitted_metrics.issubset(allowed_metrics):
            errors.append("result metrics are not approved by the analysis plan")
        unknown_artifacts = set(result.artifact_refs) - artifact_filenames
        if unknown_artifacts:
            errors.append("result references artifacts that were not collected")
        for item in result.statistical_results:
            if "p_value" in item:
                if "effect_size" not in item or "confidence_interval" not in item:
                    errors.append("statistical results with p_value require effect_size and confidence_interval")
                else:
                    self._validate_statistical_result(item=item, errors=errors)
        if plan.objective.value == "predict":
            self._prediction_checks(result=result, plan=plan, errors=errors)
        if plan.objective.value == "associate" and any(self._CAUSAL.search(text) for text in result.narrative):
            errors.append("association results must not be narrated as causal conclusions")
        if any(self._NUMERIC.search(text) for text in result.narrative):
            errors.append("numeric narrative requires a separately cited result locator")

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.lower())

    def _methods_compatible(self, result_method: str, approved_method: str) -> bool:
        result_norm, plan_norm = self._normalized(result_method), self._normalized(approved_method)
        return bool(result_norm and plan_norm and (result_norm in plan_norm or plan_norm in result_norm))

    @staticmethod
    def _prediction_checks(*, result: AnalysisResult, plan: AnalysisPlanVersion, errors: list[str]) -> None:
        diagnostics = result.prediction_diagnostics
        if diagnostics is None:
            errors.append("prediction results require prediction_diagnostics")
            return
        expected_target = set(plan.outcome_columns)
        if diagnostics.target_column not in expected_target:
            errors.append("prediction target does not match the approved outcome column")
        normalized_target = diagnostics.target_column.casefold().strip()
        normalized_features = {feature.casefold().strip() for feature in diagnostics.feature_columns}
        if normalized_target in normalized_features:
            errors.append("target leakage: target column is present in feature_columns")
        if diagnostics.train_row_count <= 0 or diagnostics.test_row_count <= 0:
            errors.append("prediction split requires non-empty train and test partitions")
        if diagnostics.train_row_count + diagnostics.test_row_count != result.analyzed_row_count:
            errors.append("train/test row counts must equal analyzed_row_count")
        if diagnostics.train_row_ids is not None and diagnostics.test_row_ids is not None:
            train_ids, test_ids = diagnostics.train_row_ids, diagnostics.test_row_ids
            if len(train_ids) != diagnostics.train_row_count or len(test_ids) != diagnostics.test_row_count:
                errors.append("train/test row identifier counts do not match their partitions")
            if len(set(train_ids)) != len(train_ids) or len(set(test_ids)) != len(test_ids):
                errors.append("train/test row identifiers must be unique within each partition")
            if set(train_ids) & set(test_ids):
                errors.append("train/test contamination: overlapping row identifiers")

    @staticmethod
    def _validate_statistical_result(*, item: dict[str, Any], errors: list[str]) -> None:
        p_value = item.get("p_value")
        effect_size = item.get("effect_size")
        interval = item.get("confidence_interval")
        if (
            not isinstance(p_value, (int, float))
            or isinstance(p_value, bool)
            or not math.isfinite(float(p_value))
            or not 0 <= float(p_value) <= 1
        ):
            errors.append("p_value must be a finite number between 0 and 1")
        if (
            not isinstance(effect_size, (int, float))
            or isinstance(effect_size, bool)
            or not math.isfinite(float(effect_size))
        ):
            errors.append("effect_size must be a finite number")
            return
        if (
            not isinstance(interval, list)
            or len(interval) != 2
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in interval
            )
        ):
            errors.append("confidence_interval must contain two finite numeric bounds")
            return
        lower, upper = float(interval[0]), float(interval[1])
        if lower > upper:
            errors.append("confidence_interval lower bound cannot exceed upper bound")
        elif not lower <= float(effect_size) <= upper:
            errors.append("effect_size must lie inside confidence_interval")

    @staticmethod
    def _canonical_json(value: dict[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
