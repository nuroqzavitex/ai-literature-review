"""Fixed-path dataset and artifact helpers for the isolated runtime only."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd


DEFAULT_MAX_OUTPUT_BYTES = 50 * 1024 * 1024
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def load_dataset() -> pd.DataFrame:
    """Load the single runner-staged dataset; caller cannot supply a path."""
    path = _dataset_path()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    if suffix == ".parquet":
        return pd.read_parquet(path, engine="pyarrow")
    raise ValueError("Staged dataset format is not supported")


def emit_result(result_dict: dict[str, Any]) -> Path:
    """Write the sole structured result document as bounded valid JSON."""
    if not isinstance(result_dict, dict):
        raise TypeError("emit_result accepts a dictionary")
    _assert_json_safe(result_dict)
    payload = (
        json.dumps(
            result_dict,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    return _write_bytes(_output_root() / "analysis_result.json", payload)


def emit_table(name: str, df: pd.DataFrame) -> Path:
    """Write a bounded CSV table below the fixed tables output directory."""
    _validate_name(name)
    if not isinstance(df, pd.DataFrame):
        raise TypeError("emit_table accepts a pandas DataFrame")
    safe_frame = df.copy()
    for column in safe_frame.columns:
        if pd.api.types.is_object_dtype(safe_frame[column]) or pd.api.types.is_string_dtype(safe_frame[column]):
            safe_frame[column] = safe_frame[column].map(_neutralize_formula)
    payload = safe_frame.to_csv(index=False).encode("utf-8")
    return _write_bytes(_output_root() / "tables" / f"{name}.csv", payload)


def emit_chart(name: str, figure: Any) -> Path:
    """Write a PNG through a fixed chart path, then validate its signature and size."""
    _validate_name(name)
    if not hasattr(figure, "savefig"):
        raise TypeError("emit_chart accepts a matplotlib-compatible figure")
    target = _safe_target(_output_root() / "charts" / f"{name}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".png.tmp")
    figure.savefig(temp, format="png")
    payload = temp.read_bytes()
    temp.unlink(missing_ok=True)
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Chart renderer did not produce a PNG artifact")
    return _write_bytes(target, payload)


def _dataset_path() -> Path:
    value = os.environ.get("SANDBOX_DATASET_PATH")
    if not value:
        raise RuntimeError("Sandbox dataset staging path is not configured")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("Sandbox dataset path is unsafe")
    return path.resolve(strict=True)


def _output_root() -> Path:
    value = os.environ.get("SANDBOX_OUTPUT_DIR")
    if not value:
        raise RuntimeError("Sandbox output directory is not configured")
    root = Path(value)
    if not root.is_absolute() or root.is_symlink():
        raise RuntimeError("Sandbox output directory is unsafe")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=True)


def _max_output_bytes() -> int:
    raw = os.environ.get("SANDBOX_MAX_OUTPUT_BYTES", str(DEFAULT_MAX_OUTPUT_BYTES))
    try:
        limit = int(raw)
    except ValueError as exc:
        raise RuntimeError("Sandbox output byte limit is invalid") from exc
    if limit <= 0:
        raise RuntimeError("Sandbox output byte limit must be positive")
    return limit


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _ARTIFACT_NAME.fullmatch(name):
        raise ValueError("Artifact name must be a simple traversal-free identifier")


def _safe_target(target: Path) -> Path:
    root = _output_root()
    candidate = target.resolve(strict=False)
    if root not in candidate.parents:
        raise ValueError("Artifact path escapes the sandbox output directory")
    return candidate


def _write_bytes(target: Path, payload: bytes) -> Path:
    target = _safe_target(target)
    existing_size = sum(
        item.stat().st_size
        for item in _output_root().rglob("*")
        if item.is_file() and not item.is_symlink()
    )
    previous_size = target.stat().st_size if target.exists() and target.is_file() else 0
    if existing_size - previous_size + len(payload) > _max_output_bytes():
        raise ValueError("Artifact output exceeds the configured byte limit")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_symlink():
        raise ValueError("Artifact target must not be a symlink")
    temporary = target.with_name(f".{target.name}.tmp")
    if temporary.exists() and temporary.is_symlink():
        raise ValueError("Temporary artifact target must not be a symlink")
    temporary.write_bytes(payload)
    temporary.replace(target)
    return target


def _neutralize_formula(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _assert_json_safe(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Result JSON cannot contain NaN or Infinity")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Result JSON keys must be strings")
            _assert_json_safe(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_json_safe(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError("Result JSON contains a non-serializable value")
