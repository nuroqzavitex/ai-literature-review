"""Constrained I/O API exposed to generated analysis code."""

from sandbox_sdk.io import emit_chart, emit_result, emit_table, load_dataset
from sandbox_sdk.result_contract import emit_analysis_result

__all__ = [
    "load_dataset",
    "emit_result",
    "emit_analysis_result",
    "emit_table",
    "emit_chart",
]
