"""Profile tabular datasets deterministically from bytes using pinned parsers."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from typing import Any

import pandas as pd

from sandbox_service.domain.datasets import DatasetColumnProfile, DatasetProfile
from sandbox_service.domain.errors import DatasetValidationFailed


class DeterministicDatasetProfiler:
    VERSION = "dataset_profiler.v1"
    TOP_VALUE_LIMIT = 10

    def profile(
        self,
        *,
        dataset_id: str,
        project_id: str,
        version: int,
        content_hash: str,
        media_type: str,
        data: bytes,
    ) -> DatasetProfile:
        frame = self._read_frame(data=data, media_type=media_type)
        columns = [self._profile_column(name, frame[name], len(frame)) for name in frame.columns]
        payload = {
            "dataset_id": dataset_id,
            "project_id": project_id,
            "version": version,
            "profiler_version": self.VERSION,
            "content_hash": content_hash,
            "row_count": len(frame),
            "column_count": len(frame.columns),
            "columns": [column.model_dump(mode="json") for column in columns],
        }
        profile_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        return DatasetProfile(**payload, profile_hash=profile_hash)

    def _read_frame(self, *, data: bytes, media_type: str) -> pd.DataFrame:
        try:
            if media_type == "text/csv":
                return pd.read_csv(BytesIO(data))
            if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                return pd.read_excel(BytesIO(data), engine="openpyxl")
            if media_type == "application/vnd.apache.parquet":
                return pd.read_parquet(BytesIO(data), engine="pyarrow")
        except Exception as exc:
            raise DatasetValidationFailed("Dataset could not be deterministically profiled") from exc
        raise DatasetValidationFailed("Dataset media type is not profileable")

    def _profile_column(self, name: str, series: pd.Series, row_count: int) -> DatasetColumnProfile:
        missing_count = int(series.isna().sum())
        non_null = series.dropna()
        distribution: dict[str, Any]
        if pd.api.types.is_numeric_dtype(series):
            values = pd.to_numeric(non_null, errors="coerce").dropna()
            distribution = {
                "kind": "numeric",
                "count": int(values.count()),
                "min": self._number_or_none(values.min()),
                "max": self._number_or_none(values.max()),
                "mean": self._number_or_none(values.mean()),
                "median": self._number_or_none(values.median()),
                "std": self._number_or_none(values.std(ddof=1)),
            }
        elif pd.api.types.is_datetime64_any_dtype(series):
            distribution = {
                "kind": "datetime",
                "min": self._json_scalar(non_null.min()) if not non_null.empty else None,
                "max": self._json_scalar(non_null.max()) if not non_null.empty else None,
            }
        else:
            counts = non_null.astype(str).value_counts(dropna=True)
            ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))[: self.TOP_VALUE_LIMIT]
            distribution = {
                "kind": "categorical",
                "top_values": [{"value": value, "count": int(count)} for value, count in ordered],
            }
        return DatasetColumnProfile(
            name=str(name),
            dtype=str(series.dtype),
            missing_count=missing_count,
            missing_ratio=round(missing_count / row_count, 12) if row_count else 0.0,
            unique_count=int(non_null.nunique(dropna=True)),
            distribution=distribution,
        )

    @staticmethod
    def _number_or_none(value: Any) -> int | float | None:
        if pd.isna(value):
            return None
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric

    @staticmethod
    def _json_scalar(value: Any) -> str | int | float | bool | None:
        if pd.isna(value):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
