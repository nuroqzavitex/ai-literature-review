"""Deterministic adapters for local product demos.

These adapters make the complete UI flow testable without an external model or
graph service. They never inspect raw dataset rows and deliberately refuse to
start unless the deployment opts into demo mode outside production.
"""

from __future__ import annotations

import json
import os
from typing import Any

from sandbox_service.domain.adoption import AdoptionProposal
from sandbox_service.integration.adoption_bridge import (
    AdoptionProposalBridge,
    CoreDraftProposal,
)


def _require_demo_mode() -> None:
    environment = os.getenv("SANDBOX_ENVIRONMENT", "development").strip().lower()
    enabled = os.getenv("SANDBOX_DEMO_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if environment == "production" or not enabled:
        raise RuntimeError(
            "development Sandbox adapters require SANDBOX_DEMO_MODE=true "
            "and SANDBOX_ENVIRONMENT=development|test"
        )


class DeterministicProjectAIClient:
    """Schema-shaped local responses; no network or model call is performed."""

    @staticmethod
    def _is_vietnamese(input_payload: dict[str, Any]) -> bool:
        language = input_payload.get("output_language")
        if language is None:
            for field in ("approved_plan", "analysis_question"):
                nested = input_payload.get(field)
                if isinstance(nested, dict) and nested.get("output_language"):
                    language = nested["output_language"]
                    break
        return str(language or "vi").strip().lower() != "en"

    async def invoke_structured(
        self,
        *,
        project_id: str,
        operation: str,
        prompt_version: str,
        input_payload: dict[str, Any],
        output_schema: type[Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        del project_id, prompt_version, output_schema, correlation_id
        vietnamese = self._is_vietnamese(input_payload)
        if operation == "hypothesis_generation":
            question = str(
                input_payload.get("research_question")
                or ("câu hỏi nghiên cứu" if vietnamese else "the research question")
            )
            context = input_payload.get("context") or {}
            evidence_refs = [str(item) for item in context.get("evidence_refs", [])][:5]
            return {
                "statement": (
                    f"Bản thảo demo có thể kiểm định cho câu hỏi: {question}"
                    if vietnamese
                    else f"Testable demo draft for the question: {question}"
                ),
                "rationale": (
                    "Giả thuyết này được tạo xác định từ metadata context đã ghim; "
                    "reviewer phải kiểm tra lại trước khi sử dụng."
                    if vietnamese
                    else "This hypothesis is generated deterministically from pinned context metadata; "
                    "a reviewer must verify it before use."
                ),
                "supporting_evidence_refs": evidence_refs,
                "counterevidence_refs": [],
                "assumptions": [
                    "Các tham chiếu context đại diện đủ cho phạm vi đang xem xét."
                    if vietnamese
                    else "The context references adequately represent the scope under review."
                ],
                "falsification_criteria": [
                    "Bác bỏ bản thảo nếu dữ liệu quan sát không phù hợp với hướng quan hệ dự kiến."
                    if vietnamese
                    else "Reject the draft if observed data do not support the expected direction."
                ],
                "required_data": [
                    "Dữ liệu định lượng phù hợp với biến kết quả và biến giải thích."
                    if vietnamese
                    else "Quantitative data matching the outcome and explanatory variables."
                ],
                "limitations": [
                    "Đây là nội dung demo xác định, không phải kết luận khoa học hoặc đầu ra mô hình thật."
                    if vietnamese
                    else "This deterministic demo content is not a scientific conclusion or live-model output."
                ],
            }
        if operation == "experiment_design":
            hypothesis = input_payload.get("hypothesis") or {}
            return {
                "objective": (
                    f"Kiểm định bản thảo: {hypothesis.get('statement', 'giả thuyết đã chọn')}"
                    if vietnamese
                    else f"Test the draft: {hypothesis.get('statement', 'selected hypothesis')}"
                ),
                "independent_variables": ["Biến giải thích do researcher xác nhận" if vietnamese else "Researcher-confirmed explanatory variable"],
                "dependent_variables": ["Biến kết quả do researcher xác nhận" if vietnamese else "Researcher-confirmed outcome variable"],
                "controls": ["Giữ cố định các điều kiện nền đã biết" if vietnamese else "Hold known background conditions constant"],
                "data_requirements": ["Dataset đã kiểm tra và profile bất biến" if vietnamese else "Validated dataset with an immutable profile"],
                "method_candidates": ["Thiết kế so sánh có đối chứng" if vietnamese else "Controlled comparative design"],
                "evaluation_metrics": ["Ước lượng hiệu ứng và độ bất định" if vietnamese else "Effect and uncertainty estimates"],
                "assumption_checks": ["Kiểm tra phân phối, dữ liệu thiếu và yếu tố gây nhiễu" if vietnamese else "Check distributions, missing data, and confounders"],
                "stopping_criteria": ["Dừng khi đạt tiêu chí dữ liệu đã duyệt trước" if vietnamese else "Stop when pre-approved data criteria are met"],
                "risks": ["Thiên lệch chọn mẫu và diễn giải quá mức" if vietnamese else "Selection bias and overinterpretation"],
            }
        if operation == "question_clarification":
            missing = [str(item) for item in input_payload.get("missing_fields", [])]
            return {
                "status": "question_incomplete",
                "question_id": None,
                "missing_fields": missing or ["research_question"],
                "clarification_questions": [
                    (f"Vui lòng xác nhận trường {field}." if vietnamese else f"Please confirm the {field} field.")
                    for field in (missing or ["research_question"])
                ],
            }
        if operation == "plan_generation":
            question = input_payload.get("analysis_question") or {}
            objective = str(question.get("objective") or "describe")
            method_by_objective = ({
                "describe": "Thống kê mô tả xác định",
                "compare": "So sánh nhóm theo kế hoạch",
                "associate": "Phân tích mối liên hệ không nhân quả",
                "predict": "Mô hình dự đoán với tập huấn luyện và kiểm tra tách biệt",
            } if vietnamese else {
                "describe": "Deterministic descriptive statistics",
                "compare": "Planned group comparison",
                "associate": "Non-causal association analysis",
                "predict": "Predictive model with separated training and test sets",
            })
            return {
                "method": method_by_objective.get(objective, method_by_objective["describe"]),
                "method_rationale": (
                    "Phương pháp demo bám sát objective và các cột do researcher chọn; "
                    "không suy đoán từ dữ liệu thô."
                    if vietnamese
                    else "The demo method follows the objective and researcher-selected columns without inferring from raw rows."
                ),
                "preprocessing_steps": ["Giữ nguyên dữ liệu đầu vào đã được stage an toàn" if vietnamese else "Preserve safely staged input data"],
                "assumption_checks": (["Dataset không rỗng", "Kiểm tra dữ liệu thiếu"] if vietnamese else ["Dataset is not empty", "Check missing data"]),
                "evaluation_metrics": list(question.get("preferred_metrics") or []),
                "limitations": ["Kế hoạch demo cần reviewer xác nhận trước khi chạy." if vietnamese else "The demo plan requires reviewer approval before execution."],
            }
        if operation in {"code_generation", "code_revision"}:
            plan = input_payload.get("approved_plan") or {}
            return {"source_code": self._analysis_source(plan)}
        if operation == "result_interpretation":
            return {
                "narrative": [
                    "Kết quả đã vượt qua kiểm tra cấu trúc và đang chờ reviewer diễn giải trong bối cảnh nghiên cứu."
                    if vietnamese
                    else "The result passed structural validation and awaits reviewer interpretation in the research context."
                ],
                "numeric_claims": [],
                "limitations": [
                    "Diễn giải demo không thay thế đánh giá thống kê hoặc đánh giá chuyên gia."
                    if vietnamese
                    else "The demo interpretation does not replace statistical or expert review."
                ],
            }
        raise RuntimeError(f"demo ProjectAIClient does not support operation: {operation}")

    @staticmethod
    def _analysis_source(plan: dict[str, Any]) -> str:
        objective = str(plan.get("objective") or "describe")
        method = str(plan.get("method") or "Thống kê mô tả xác định")
        vietnamese = str(plan.get("output_language") or "vi") == "vi"
        outcome_columns = [str(item) for item in plan.get("outcome_columns", [])]
        feature_columns = [str(item) for item in plan.get("predictor_columns", [])]
        requested_columns = list(
            dict.fromkeys(
                outcome_columns
                + feature_columns
                + [str(item) for item in plan.get("group_columns", [])]
                + [str(item) for item in plan.get("covariate_columns", [])]
            )
        )
        diagnostics = "None"
        if objective == "predict" and outcome_columns:
            diagnostics = (
                "{'target_column': "
                + json.dumps(outcome_columns[0], ensure_ascii=False)
                + ", 'feature_columns': "
                + json.dumps(feature_columns, ensure_ascii=False)
                + ", 'train_row_count': train_rows, 'test_row_count': test_rows}"
            )
        if objective == "associate" and len(feature_columns) == 1 and len(outcome_columns) == 1:
            chart_lines = [
                f"x_column = {json.dumps(feature_columns[0], ensure_ascii=False)}",
                f"y_column = {json.dumps(outcome_columns[0], ensure_ascii=False)}",
                "if x_column not in df.columns or y_column not in df.columns:",
                "    raise ValueError('Approved association columns are unavailable')",
                "plot_data = pd.DataFrame({'x': pd.to_numeric(df[x_column], errors='coerce'), 'y': pd.to_numeric(df[y_column], errors='coerce')}).dropna()",
                f"axis.scatter(plot_data['x'], plot_data['y'], alpha=0.7, label={json.dumps('Dữ liệu thực tế' if vietnamese else 'Observed data', ensure_ascii=False)})",
                "if len(plot_data) >= 2 and plot_data['x'].nunique() > 1:",
                "    trend_coefficients = np.polyfit(plot_data['x'], plot_data['y'], 1)",
                "    trend_x = np.sort(plot_data['x'].to_numpy())",
                "    trend_y = trend_coefficients[0] * trend_x + trend_coefficients[1]",
                f"    axis.plot(trend_x, trend_y, color='crimson', linewidth=2, label={json.dumps('Đường xu hướng' if vietnamese else 'Fitted trend', ensure_ascii=False)})",
                "else:",
                f"    axis.text(0.5, 0.5, {json.dumps('Không đủ dữ liệu để ước lượng đường xu hướng' if vietnamese else 'Insufficient data for a fitted trend', ensure_ascii=False)}, ha='center', va='center', transform=axis.transAxes)",
                f"axis.set_title({json.dumps('Mối liên hệ và đường xu hướng' if vietnamese else 'Association with fitted trend', ensure_ascii=False)})",
                "axis.set_xlabel(x_column)",
                "axis.set_ylabel(y_column)",
                "axis.legend()",
            ]
        else:
            chart_lines = [
                "if numeric_columns:",
                "    chart_column = numeric_columns[0]",
                "    df[chart_column].dropna().plot(kind='hist', bins=12, ax=axis)",
                f"    axis.set_title({json.dumps('Phân phối dữ liệu phân tích' if vietnamese else 'Analysis data distribution', ensure_ascii=False)})",
                "    axis.set_xlabel(chart_column)",
                "elif len(df.columns) > 0:",
                "    chart_column = str(df.columns[0])",
                "    df[chart_column].astype(str).value_counts().head(12).plot(kind='bar', ax=axis)",
                f"    axis.set_title({json.dumps('Tần suất nhóm dữ liệu' if vietnamese else 'Data category frequencies', ensure_ascii=False)})",
                "else:",
                "    chart_column = 'dataset'",
                "    axis.text(0.5, 0.5, 'No columns', ha='center', va='center')",
                "    axis.set_axis_off()",
            ]
        return "\n".join(
            [
                "import pandas as pd",
                "import numpy as np",
                "import json",
                "import pathlib",
                "import matplotlib.pyplot as plt",
                "from sandbox_sdk import load_dataset, emit_result, emit_table, emit_chart",
                "",
                "RESULT_PATH = pathlib.PurePosixPath('/workspace/output/analysis_result.json')",
                "SUMMARY_PATH = pathlib.PurePosixPath('/workspace/output/tables/summary.csv')",
                "CHART_PATH = pathlib.PurePosixPath('/workspace/output/charts/analysis.png')",
                "df = load_dataset()",
                f"requested_columns = {json.dumps(requested_columns, ensure_ascii=False)}",
                "available_columns = [col_name for col_name in requested_columns if col_name in df.columns]",
                "selected_series = {col_name: df[col_name] for col_name in available_columns}",
                "row_count = len(df)",
                "test_rows = max(1, row_count // 5) if row_count > 1 else 0",
                "train_rows = row_count - test_rows",
                "summary = df.describe(include='all').reset_index()",
                "summary_path = emit_table('summary', summary)",
                "numeric_columns = list(df.select_dtypes(include='number').columns)",
                "figure, axis = plt.subplots(figsize=(8, 5))",
                *chart_lines,
                "figure.tight_layout()",
                "chart_path = emit_chart('analysis', figure)",
                "plt.close(figure)",
                "result_path = emit_result({",
                "    'schema_version': 'analysis_result.v1',",
                f"    'objective': {json.dumps(objective)},",
                f"    'method': {json.dumps(method, ensure_ascii=False)},",
                "    'input_row_count': row_count,",
                "    'analyzed_row_count': row_count,",
                f"    'preprocessing_applied': [{json.dumps('Không biến đổi dữ liệu trong adapter demo' if vietnamese else 'No data transformations in the demo adapter', ensure_ascii=False)}],",
                "    'assumption_checks': [{'name': 'dataset_non_empty', 'passed': row_count > 0}],",
                "    'metrics': [],",
                "    'statistical_results': [],",
                "    'warnings': [],",
                f"    'limitations': [{json.dumps('Kết quả demo chỉ dùng để kiểm thử luồng sản phẩm' if vietnamese else 'Demo results are only for testing the product workflow', ensure_ascii=False)}],",
                "    'artifact_refs': ['tables/summary.csv', 'charts/analysis.png'],",
                f"    'narrative': [{json.dumps('Kết quả mô tả đã được tạo trong runtime cô lập' if vietnamese else 'Descriptive results were produced in the isolated runtime', ensure_ascii=False)}],",
                f"    'prediction_diagnostics': {diagnostics},",
                "})",
                "if str(summary_path) != str(SUMMARY_PATH) or str(chart_path) != str(CHART_PATH) or str(result_path) != str(RESULT_PATH):",
                "    raise RuntimeError('sandbox_sdk returned an unexpected artifact path')",
                "",
            ]
        )


class DeterministicGraphSnapshotReader:
    """Return a fresh read-only demo projection for any pinned demo version."""

    async def read_snapshot(
        self, *, project_id: str, graph_version_id: str, actor_id: str
    ) -> dict[str, Any]:
        del actor_id
        return {
            "project_id": project_id,
            "graph_version_id": graph_version_id,
            "nodes": [
                {"id": "paper-a", "type": "paper", "label": "Nghiên cứu nền"},
                {"id": "method-a", "type": "method", "label": "Phương pháp tham chiếu"},
                {"id": "outcome-a", "type": "outcome", "label": "Kết quả quan sát"},
            ],
            "edges": [
                {"source": "paper-a", "target": "method-a", "type": "uses"},
                {"source": "method-a", "target": "outcome-a", "type": "evaluates"},
            ],
        }


class _DemoCoreDraftSink:
    def __init__(self) -> None:
        self._drafts: dict[str, str] = {}

    async def create_draft(
        self,
        proposal: CoreDraftProposal,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> str:
        del actor_id, correlation_id
        key = idempotency_key or proposal.sandbox_proposal_id
        draft_id = self._drafts.get(key)
        if draft_id is None:
            draft_id = f"demo-draft-{proposal.sandbox_proposal_id}"
            self._drafts[key] = draft_id
        return draft_id


class _DemoCoreAdoptionRevalidator:
    async def is_current_and_authorized(
        self,
        *,
        project_id: str,
        proposal: AdoptionProposal,
        actor_id: str,
        source_bundle: dict[str, Any],
    ) -> bool:
        return (
            bool(actor_id)
            and bool(source_bundle)
            and proposal.project_id == project_id
        )


def create_demo_project_ai_client() -> DeterministicProjectAIClient:
    _require_demo_mode()
    return DeterministicProjectAIClient()


def create_demo_graph_snapshot_reader() -> DeterministicGraphSnapshotReader:
    _require_demo_mode()
    return DeterministicGraphSnapshotReader()


def create_demo_adoption_bridge() -> AdoptionProposalBridge:
    _require_demo_mode()
    return AdoptionProposalBridge(
        sink=_DemoCoreDraftSink(), revalidator=_DemoCoreAdoptionRevalidator()
    )
