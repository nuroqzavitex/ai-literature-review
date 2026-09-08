"""Project-AI code generation from approved plan metadata only."""

from __future__ import annotations

import ast
import builtins
import hashlib
import logging
from typing import Any, Protocol
from uuid import uuid4

from sandbox_service.code_policy import CodePolicyChecker, CodePolicyViolation
from sandbox_service.domain.analysis_plans import AnalysisPlanDecision, AnalysisPlanStatus, AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetProfile
from sandbox_service.domain.errors import AnalysisPlanNotApproved, CodePolicyRejected
from sandbox_service.domain.execution import AnalysisCodeStatus, AnalysisCodeVersion, GeneratedCode
from sandbox_service.domain.ports import ProjectAIClient

LOGGER = logging.getLogger(__name__)


class CodeGenerationRepository(Protocol):
    async def get_analysis_plan(self, *, project_id: str, plan_id: str, version: int) -> AnalysisPlanVersion | None: ...

    async def get_dataset_profile(self, *, project_id: str, dataset_id: str, version: int) -> DatasetProfile | None: ...

    async def list_analysis_plan_decisions(self, *, project_id: str, plan_id: str, version: int) -> list[AnalysisPlanDecision]: ...

    async def save_analysis_code(self, code: AnalysisCodeVersion) -> AnalysisCodeVersion: ...

    async def get_analysis_code(self, *, project_id: str, code_version_id: str) -> AnalysisCodeVersion | None: ...

    async def list_analysis_codes_for_plan(self, *, project_id: str, plan_id: str, plan_version: int) -> list[AnalysisCodeVersion]: ...


class CodeGenerationService:
    MAX_REVISIONS = 1

    def __init__(
        self,
        *,
        repository: CodeGenerationRepository,
        ai_client: ProjectAIClient,
        policy_checker: CodePolicyChecker | None = None,
    ) -> None:
        self._repository = repository
        self._ai_client = ai_client
        self._policy = policy_checker or CodePolicyChecker()

    async def generate(
        self,
        *,
        project_id: str,
        plan_id: str,
        plan_version: int,
        correlation_id: str | None = None,
    ) -> tuple[AnalysisCodeVersion, AnalysisPlanDecision]:
        request_correlation_id = correlation_id or str(uuid4())
        plan, profile, decision = await self._approved_inputs(
            project_id=project_id, plan_id=plan_id, plan_version=plan_version
        )
        plan_payload = self._plan_payload(plan)
        profile_payload = profile.model_dump(mode="json")
        generated = await self._ai_client.invoke_structured(
            project_id=project_id,
            operation="code_generation",
            prompt_version="analysis.code_generation.v1",
            input_payload={
                "approved_plan": plan_payload,
                "dataset_profile": profile_payload,
                "sdk_contract": self._sdk_contract(),
            },
            output_schema=GeneratedCode,
            correlation_id=request_correlation_id,
        )
        source = GeneratedCode.model_validate(generated).source_code
        prompt_version = "analysis.code_generation.v1"
        revision_count = 0
        violations = self._scientific_result_contract_violations(
            source, plan=plan, profile=profile
        )
        if violations:
            LOGGER.warning(
                "generated_code_result_contract_revision project_id=%s plan_id=%s "
                "plan_version=%s correlation_id=%s violations=%s",
                project_id,
                plan.plan_id,
                plan.version,
                request_correlation_id,
                violations,
            )
            revised = await self._ai_client.invoke_structured(
                project_id=project_id,
                operation="code_revision",
                prompt_version="analysis.code_revision.v1",
                input_payload={
                    "approved_plan": plan_payload,
                    "dataset_profile": profile_payload,
                    "previous_code": source,
                    "recoverable_error": "; ".join(violations),
                    "sdk_contract": self._sdk_contract(),
                },
                output_schema=GeneratedCode,
                correlation_id=request_correlation_id,
            )
            source = GeneratedCode.model_validate(revised).source_code
            prompt_version = "analysis.code_revision.v1"
            revision_count = 1
            remaining = self._scientific_result_contract_violations(
                source, plan=plan, profile=profile
            )
            if remaining:
                raise CodePolicyRejected(
                    "Generated code still violates the scientific result contract: "
                    + "; ".join(remaining)
                )
        return await self._persist_checked_code(
            project_id=project_id,
            plan=plan,
            source=source,
            prompt_version=prompt_version,
            revision_count=revision_count,
            correlation_id=request_correlation_id,
        ), decision

    async def revise(
        self,
        *,
        project_id: str,
        code_version_id: str,
        recoverable_error: str,
        correlation_id: str | None = None,
    ) -> AnalysisCodeVersion:
        request_correlation_id = correlation_id or str(uuid4())
        previous = await self._repository.get_analysis_code(
            project_id=project_id, code_version_id=code_version_id
        )
        if previous is None:
            raise CodePolicyRejected("Code version is unavailable for revision")
        if previous.revision_count >= self.MAX_REVISIONS:
            raise CodePolicyRejected("Maximum code revisions has been reached")
        plan, profile, _ = await self._approved_inputs(
            project_id=project_id, plan_id=previous.plan_id, plan_version=previous.plan_version
        )
        generated = await self._ai_client.invoke_structured(
            project_id=project_id,
            operation="code_revision",
            prompt_version="analysis.code_revision.v1",
            input_payload={
                "approved_plan": self._plan_payload(plan),
                "dataset_profile": profile.model_dump(mode="json"),
                "previous_code": previous.source_code,
                "recoverable_error": recoverable_error[:4_000],
                "sdk_contract": self._sdk_contract(),
            },
            output_schema=GeneratedCode,
            correlation_id=request_correlation_id,
        )
        source = GeneratedCode.model_validate(generated).source_code
        violations = self._scientific_result_contract_violations(
            source, plan=plan, profile=profile
        )
        if violations:
            raise CodePolicyRejected(
                "Revised code violates the scientific result contract: "
                + "; ".join(violations)
            )
        return await self._persist_checked_code(
            project_id=project_id,
            plan=plan,
            source=source,
            prompt_version="analysis.code_revision.v1",
            revision_count=previous.revision_count + 1,
            code_id=previous.code_id,
            version=previous.version + 1,
            correlation_id=request_correlation_id,
        )

    async def _persist_checked_code(
        self,
        *,
        project_id: str,
        plan: AnalysisPlanVersion,
        source: str,
        prompt_version: str,
        revision_count: int,
        code_id: str | None = None,
        version: int = 1,
        correlation_id: str | None = None,
    ) -> AnalysisCodeVersion:
        try:
            self._policy.ensure_allowed(source)
        except CodePolicyViolation as exc:
            LOGGER.warning(
                "generated_code_policy_rejected project_id=%s plan_id=%s plan_version=%s "
                "prompt_version=%s correlation_id=%s violations=%s",
                project_id,
                plan.plan_id,
                plan.version,
                prompt_version,
                correlation_id,
                [
                    {
                        "rule": item.rule,
                        "line": item.line,
                        "column": item.column,
                        "message": item.message,
                    }
                    for item in exc.violations
                ],
            )
            rejected = AnalysisCodeVersion(
                code_id=code_id or str(uuid4()),
                project_id=project_id,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                version=version,
                source_code=source,
                code_hash=self._hash(source),
                prompt_version=prompt_version,  # type: ignore[arg-type]
                status=AnalysisCodeStatus.POLICY_REJECTED,
                revision_count=revision_count,
            )
            await self._repository.save_analysis_code(rejected)
            raise CodePolicyRejected("Generated code was rejected by static policy") from exc
        code = AnalysisCodeVersion(
            code_id=code_id or str(uuid4()),
            project_id=project_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            version=version,
            source_code=source,
            code_hash=self._hash(source),
            prompt_version=prompt_version,  # type: ignore[arg-type]
            status=AnalysisCodeStatus.APPROVED,
            revision_count=revision_count,
        )
        return await self._repository.save_analysis_code(code)

    async def _approved_inputs(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> tuple[AnalysisPlanVersion, DatasetProfile, AnalysisPlanDecision]:
        plan = await self._repository.get_analysis_plan(
            project_id=project_id, plan_id=plan_id, version=plan_version
        )
        if plan is None or plan.status is not AnalysisPlanStatus.APPROVED:
            raise AnalysisPlanNotApproved("An approved immutable analysis plan is required")
        decisions = await self._repository.list_analysis_plan_decisions(
            project_id=project_id, plan_id=plan_id, version=plan_version
        )
        decision = next((item for item in reversed(decisions) if item.decision is AnalysisPlanStatus.APPROVED), None)
        if decision is None:
            raise AnalysisPlanNotApproved("The plan does not have an approval decision")
        profile = await self._repository.get_dataset_profile(
            project_id=project_id, dataset_id=plan.dataset_id, version=plan.profile_version
        )
        if profile is None:
            raise AnalysisPlanNotApproved("The plan's immutable dataset profile is unavailable")
        return plan, profile, decision

    @staticmethod
    def _plan_payload(plan: AnalysisPlanVersion) -> dict[str, Any]:
        return {
            "plan_id": plan.plan_id,
            "version": plan.version,
            "plan_hash": plan.plan_hash,
            "objective": plan.objective.value,
            "research_question": plan.research_question,
            "outcome_columns": plan.outcome_columns,
            "predictor_columns": plan.predictor_columns,
            "group_columns": plan.group_columns,
            "covariate_columns": plan.covariate_columns,
            "method": plan.method,
            "preprocessing_steps": plan.preprocessing_steps,
            "assumption_checks": plan.assumption_checks,
            "evaluation_metrics": plan.evaluation_metrics,
            "limitations": plan.limitations,
            "output_language": plan.output_language,
        }

    @staticmethod
    def _sdk_contract() -> dict[str, Any]:
        return {
            "required": ["load_dataset", "emit_result", "emit_table", "emit_chart"],
            "result_path": "/workspace/output/analysis_result.json",
            "summary_table_path": "/workspace/output/tables/summary.csv",
            "analysis_chart_path": "/workspace/output/charts/analysis.png",
            "required_imports": ["pandas", "numpy", "json", "pathlib", "matplotlib.pyplot"],
            "dataframe_column_access": "df[col_name]",
            "inferential_result_rule": (
                "A statistical_results entry containing p_value must also contain "
                "effect_size and confidence_interval on the same scale. For a regression "
                "coefficient, use the coefficient as effect_size and model.conf_int() "
                "bounds for that coefficient."
            ),
            "association_chart_rule": (
                "For an association plan with exactly one numeric predictor and "
                "one numeric outcome, charts/analysis.png must contain both the "
                "observed scatter points and a fitted trend/regression line. Sort "
                "x values before drawing fitted values and label both series in the "
                "legend. Both scatter points and the fitted line must share the "
                "exact same scale as the outcome variable (do not apply inverse "
                "z-score transforms to predictions when y was not standardized). A "
                "scatter-only chart is incomplete."
            ),
        }

    @staticmethod
    def _scientific_result_contract_violations(
        source: str,
        *,
        plan: AnalysisPlanVersion | None = None,
        profile: DatasetProfile | None = None,
    ) -> list[str]:
        """Catch statically visible incomplete inferential result records.

        Runtime validation remains authoritative. This preflight catches the common
        model-generated dictionary form early enough to request the single allowed
        code revision before a Docker run is queued.
        """

        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError:
            return []  # The static code policy reports syntax failures separately.

        violations: list[str] = []
        emits_analysis_chart = any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "emit_chart")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "emit_chart")
            )
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "analysis"
            for node in ast.walk(tree)
        )
        if not emits_analysis_chart:
            violations.append(
                "generated code must emit charts/analysis.png via emit_chart('analysis', figure)"
            )
        if (
            plan is not None
            and profile is not None
            and CodeGenerationService._requires_association_trend_line(plan, profile)
            and not CodeGenerationService._has_fitted_trend_line(tree)
        ):
            violations.append(
                "association chart with one numeric predictor and outcome must draw a "
                "fitted trend/regression line in addition to observed scatter points"
            )
        violations.extend(CodeGenerationService._undefined_call_violations(tree))
        violations.extend(
            CodeGenerationService._statsmodels_prediction_design_violations(tree)
        )
        violations.extend(
            CodeGenerationService._unscaling_prediction_violations(tree)
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {
                key.value: value
                for key, value in zip(node.keys, node.values, strict=True)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            statistical_results = keys.get("statistical_results")
            if not isinstance(statistical_results, (ast.List, ast.Tuple)):
                continue
            for index, item in enumerate(statistical_results.elts):
                if not isinstance(item, ast.Dict):
                    continue
                item_keys = {
                    key.value
                    for key in item.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                if "p_value" in item_keys and not {
                    "effect_size",
                    "confidence_interval",
                }.issubset(item_keys):
                    violations.append(
                        f"statistical_results[{index}] has p_value but is missing "
                        "effect_size and/or confidence_interval"
                    )
        return violations

    @staticmethod
    def _undefined_call_violations(tree: ast.AST) -> list[str]:
        """Catch misspelled call roots that would otherwise fail only at runtime."""

        bound_names = set(dir(builtins))
        for node in ast.walk(tree):
            if isinstance(node, ast.alias):
                bound_names.add(node.asname or node.name.split(".", 1)[0])
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound_names.add(node.id)
            elif isinstance(node, ast.arg):
                bound_names.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound_names.add(node.name)

        undefined: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            root = CodeGenerationService._call_root_name(node.func)
            if root and root not in bound_names:
                undefined.setdefault(root, getattr(node, "lineno", 0))
        return [
            f"call at line {line} uses undefined name '{name}'"
            for name, line in undefined.items()
        ]

    @staticmethod
    def _statsmodels_prediction_design_violations(tree: ast.AST) -> list[str]:
        """Require an explicit intercept when constructing new prediction exog.

        ``statsmodels.add_constant`` may decide that a frame containing fixed
        covariate values already has a constant and omit the intercept. The fitted
        model then receives one fewer column during ``predict``.
        """

        prediction_names: set[str] = set()
        direct_design_calls: list[ast.Call] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "predict"
            ):
                continue
            arguments = list(node.args[:1]) + [
                keyword.value for keyword in node.keywords if keyword.arg == "exog"
            ]
            for argument in arguments:
                if isinstance(argument, ast.Name):
                    prediction_names.add(argument.id)
                elif CodeGenerationService._is_add_constant_call(argument):
                    direct_design_calls.append(argument)

        unsafe_lines = [
            getattr(call, "lineno", 0)
            for call in direct_design_calls
            if not CodeGenerationService._forces_added_constant(call)
        ]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(
                isinstance(target, ast.Name) and target.id in prediction_names
                for target in targets
            ):
                continue
            value = node.value
            if (
                CodeGenerationService._is_add_constant_call(value)
                and not CodeGenerationService._forces_added_constant(value)
            ):
                unsafe_lines.append(getattr(value, "lineno", 0))

        return [
            "statsmodels prediction design at line "
            f"{line} must call add_constant(..., has_constant='add') so predict "
            "receives the fitted model's intercept column"
            for line in dict.fromkeys(unsafe_lines)
        ]

    @staticmethod
    def _unscaling_prediction_violations(tree: ast.AST) -> list[str]:
        """Catch erroneous inverse z-score scaling applied to predict() results."""
        prediction_vars: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "predict"
                ):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    for target in targets:
                        if isinstance(target, ast.Name):
                            prediction_vars.add(target.id)

        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                has_pred = False
                has_std = False
                for child in (node.left, node.right):
                    if (
                        isinstance(child, ast.Name)
                        and child.id in prediction_vars
                    ) or (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "predict"
                    ):
                        has_pred = True
                    for subnode in ast.walk(child):
                        if (
                            isinstance(subnode, ast.Call)
                            and isinstance(subnode.func, ast.Attribute)
                            and subnode.func.attr == "std"
                        ):
                            has_std = True
                if has_pred and has_std:
                    line = getattr(node, "lineno", 0)
                    violations.append(
                        f"inverse z-score unscaling at line {line} must not be applied to predict() results when y is unscaled"
                    )
        return violations

    @staticmethod
    def _call_root_name(node: ast.AST) -> str | None:
        while isinstance(node, ast.Attribute):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    @staticmethod
    def _is_add_constant_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_constant"
        )

    @staticmethod
    def _forces_added_constant(call: ast.Call) -> bool:
        return any(
            keyword.arg == "has_constant"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "add"
            for keyword in call.keywords
        )

    @staticmethod
    def _requires_association_trend_line(
        plan: AnalysisPlanVersion, profile: DatasetProfile
    ) -> bool:
        if plan.objective.value != "associate":
            return False
        if len(plan.predictor_columns) != 1 or len(plan.outcome_columns) != 1:
            return False
        dtypes = {column.name: column.dtype.lower() for column in profile.columns}
        numeric_tokens = ("int", "float", "double", "number", "numeric", "decimal")
        return all(
            column_name in dtypes
            and any(token in dtypes[column_name] for token in numeric_tokens)
            for column_name in (plan.predictor_columns[0], plan.outcome_columns[0])
        )

    @staticmethod
    def _has_fitted_trend_line(tree: ast.AST) -> bool:
        """Recognize explicit line/regression drawing calls, not scatter-only plots."""

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"regplot", "lmplot", "lineplot", "axline"}:
                return True
            if node.func.attr != "plot":
                continue
            keywords = {
                keyword.arg: keyword.value
                for keyword in node.keywords
                if keyword.arg is not None
            }
            kind = keywords.get("kind")
            if isinstance(kind, ast.Constant) and kind.value == "scatter":
                continue
            linestyle = keywords.get("linestyle") or keywords.get("ls")
            if (
                isinstance(linestyle, ast.Constant)
                and str(linestyle.value).lower() in {"none", ""}
            ):
                continue
            return True
        return False

    @staticmethod
    def _hash(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()
