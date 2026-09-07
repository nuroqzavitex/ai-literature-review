import type { Page, Route } from "@playwright/test";

export const PROJECT_ID = "prj_sandbox_e2e";
const now = "2026-08-23T10:00:00Z";

function reply(route: Route, body: unknown, status = 200, contentType = "application/json") {
  return route.fulfill({ status, contentType, body: contentType === "application/json" ? JSON.stringify(body) : String(body) });
}

const capabilities = {
  schema_version: "sandbox_capabilities.v1", enabled: true, available: true, demo_mode: false,
  modes: { hypothesis: true, data_analysis: true }, ai_enabled: true,
  graph_context_enabled: true, result_interpretation_enabled: true, supported_dataset_formats: ["csv", "xlsx", "parquet"],
  max_dataset_bytes: 52_428_800, run_polling_supported: true, project_role: "owner",
};

type Fixture = Record<string, unknown>;
type HypothesisFixture = Fixture & { hypothesis_id: string; status: string };
type PlanFixture = Fixture & { status: string };

function session(mode: string, id = `ses-${mode}`) {
  return { session_id: id, project_id: PROJECT_ID, mode, entrypoint: "manual", source_resource_id: null, title: `${mode} E2E`, initial_question: null, status: "draft", creator_id: "clerk-e2e", context_snapshot_id: "ctx-1", context_hash: "a".repeat(64), created_at: now, updated_at: now };
}

export async function useHypothesisApi(page: Page, options: { seedOldSession?: boolean } = {}) {
  const sessions: Array<ReturnType<typeof session>> = options.seedOldSession ? [session("hypothesis", "ses-hypothesis-old")] : [];
  const hypotheses: HypothesisFixture[] = [];
  const experiments: Fixture[] = [];
  let handoffDataset: Fixture | null = null;
  await page.route(`**/api/v1/projects/${PROJECT_ID}/sandbox/**`, async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname; const method = route.request().method();
    if (path.endsWith("/capabilities")) return reply(route, capabilities);
    if (path.endsWith("/sandbox-sessions") && method === "GET") return reply(route, sessions);
    if (/\/sandbox-sessions\/[^/]+\/discard$/.test(path) && method === "POST") { const sessionId = path.split("/").at(-2); const index = sessions.findIndex((item) => item.session_id === sessionId); const discarded = { ...sessions[index], status: "discarded", updated_at: now }; if (index >= 0) sessions.splice(index, 1); return reply(route, discarded); }
    if (path.endsWith("/datasets") && method === "GET") return reply(route, handoffDataset ? [handoffDataset] : []);
    if (path.endsWith("/datasets") && method === "POST") { handoffDataset = { dataset_id: "dataset-mismatch", project_id: PROJECT_ID, filename: "unrelated.csv", media_type: "text/csv", size_bytes: 24, content_hash: "9".repeat(64), classification: "non_sensitive", status: "validated", created_at: now }; return reply(route, handoffDataset, 201); }
    if (path.endsWith("/profiles") && method === "GET") return reply(route, []);
    if (path.endsWith("/profile") && method === "POST") return reply(route, { profile_id: "profile-mismatch", dataset_id: "dataset-mismatch", project_id: PROJECT_ID, version: 1, profiler_version: "deterministic.v1", content_hash: "9".repeat(64), row_count: 1, column_count: 2, columns: [{ name: "city", dtype: "string", missing_count: 0, missing_ratio: 0, unique_count: 1, distribution: {} }, { name: "temperature", dtype: "float64", missing_count: 0, missing_ratio: 0, unique_count: 1, distribution: {} }], profile_hash: "8".repeat(64), created_at: now }, 201);
    if (path.endsWith("/analysis-questions") && method === "GET") return reply(route, []);
    if (path.endsWith("/analysis-plans") && method === "GET") return reply(route, []);
    if (path.endsWith("/open-session")) { const input = JSON.parse(route.request().postData() ?? "{}"); const value = { ...session(input.mode, input.mode === "data_analysis" ? "ses-analysis-handoff" : undefined), ...input, source_resource_id: input.mode === "hypothesis" ? "report-v1" : null }; sessions.push(value); return reply(route, value, 201); }
    if (path.endsWith("/hypotheses") && method === "GET") return reply(route, hypotheses);
    if (path.endsWith("/hypotheses") && method === "POST") { const value = { hypothesis_id: `hyp-${hypotheses.length + 1}`, session_id: sessions[0].session_id, version: hypotheses.length + 1, status: "draft", evidence_status: "verified", statement: "Graph evidence suggests method A improves outcome B", rationale: "Pinned GraphRAG evidence supports a falsifiable draft.", supporting_evidence_refs: ["claim-1"], counterevidence_refs: [], assumptions: ["Comparable cohorts"], falsification_criteria: ["No measurable difference"], required_data: ["Outcome B"], limitations: ["Small evidence set"], created_at: now }; hypotheses.push(value); return reply(route, value, 201); }
    if (path.endsWith("/experiments") && method === "GET") return reply(route, experiments);
    if (path.endsWith("/experiments") && method === "POST") { const value = { experiment_id: "exp-1", session_id: sessions[0].session_id, hypothesis_id: hypotheses[0].hypothesis_id, version: 1, status: "draft", objective: "Test method A against baseline", independent_variables: ["method"], dependent_variables: ["outcome"], controls: ["baseline"], data_requirements: [], method_candidates: ["controlled comparison"], evaluation_metrics: ["mean difference"], assumption_checks: ["independence"], stopping_criteria: ["power reached"], risks: [], created_at: now }; experiments.push(value); return reply(route, value, 201); }
    if (path.endsWith("/review") && path.includes("/hypotheses/")) { hypotheses[0].status = JSON.parse(route.request().postData() ?? "{}").decision; return reply(route, hypotheses[0]); }
    if (path.endsWith("/context")) return reply(route, { schema_version: "research_context.v1", context_id: "ctx-1", project_id: PROJECT_ID, source_type: "graphrag_answer", source_resource_id: "report-v1", graph_version_id: "report-v1", shared_graph_version_id: null, content_hash: "a".repeat(64), source_status: "active", created_at: now });
    return reply(route, { detail: { error_code: "UNMOCKED", message: `${method} ${path}` } }, 501);
  });
}

export async function useAnalysisApi(
  page: Page,
  options: { interpretationInitiallyUnavailable?: boolean } = {},
) {
  const valueSession = session("data_analysis"); const sessions = [valueSession]; let dataset: Fixture | null = null; let profile: Fixture | null = null; let question: Fixture | null = null; let plan: PlanFixture | null = null; let runPolls = 0; let interpretationPolls = 0; let interpretationGenerated = !options.interpretationInitiallyUnavailable; let runStatus = "queued";
  const run = () => ({ run_id: "run-1", operation_id: "operation-1", project_id: PROJECT_ID, dataset_id: "dataset-1", plan_id: "plan-1", plan_version: 1, code_version_id: "code-1", status: runStatus, error_code: null, created_at: now, updated_at: now });
  await page.route(`**/api/v1/projects/${PROJECT_ID}/sandbox/**`, async (route) => {
    const url = new URL(route.request().url()); const path = url.pathname; const method = route.request().method();
    if (path.endsWith("/capabilities")) return reply(route, capabilities);
    if (path.endsWith("/sandbox-sessions") && method === "GET") return reply(route, sessions);
    if (/\/sandbox-sessions\/[^/]+\/discard$/.test(path) && method === "POST") { const sessionId = path.split("/").at(-2); const index = sessions.findIndex((item) => item.session_id === sessionId); const discarded = { ...sessions[index], status: "discarded", updated_at: now }; if (index >= 0) sessions.splice(index, 1); return reply(route, discarded); }
    if (path.endsWith("/open-session") && method === "POST") { const input = JSON.parse(route.request().postData() ?? "{}"); const opened = { ...session("data_analysis", `ses-analysis-${sessions.length + 1}`), ...input, created_at: "2026-08-23T11:00:00Z", updated_at: "2026-08-23T11:00:00Z" }; sessions.push(opened); return reply(route, opened, 201); }
    if (path.endsWith("/datasets") && method === "GET") return reply(route, dataset ? [dataset] : []);
    if (path.endsWith("/datasets") && method === "POST") { dataset = { dataset_id: "dataset-1", project_id: PROJECT_ID, filename: "sales.csv", media_type: "text/csv", size_bytes: 48, content_hash: "e".repeat(64), classification: "non_sensitive", status: "validated", created_at: now }; return reply(route, dataset, 201); }
    if (path.endsWith("/profiles") && method === "GET") return reply(route, profile ? [profile] : []);
    if (path.endsWith("/profile") && method === "POST") { profile = { profile_id: "profile-1", dataset_id: "dataset-1", project_id: PROJECT_ID, version: 1, profiler_version: "deterministic.v1", content_hash: "e".repeat(64), row_count: 3, column_count: 2, columns: [{ name: "fruit name", dtype: "string", missing_count: 0, missing_ratio: 0, unique_count: 3, distribution: { top: "apple" } }, { name: "count sold", dtype: "int64", missing_count: 0, missing_ratio: 0, unique_count: 3, distribution: { min: 1, max: 3 } }], profile_hash: "f".repeat(64), created_at: now }; return reply(route, profile, 201); }
    if (path.endsWith("/analysis-questions") && method === "GET") return reply(route, question ? [question] : []);
    if (path.endsWith("/analysis-questions") && method === "POST") { const input = JSON.parse(route.request().postData() ?? "{}"); question = { ...input, question_id: "question-1", project_id: PROJECT_ID, dataset_id: "dataset-1", profile_version: 1, context_hash: null, version: 1, status: "draft", created_at: now }; return reply(route, question, 201); }
    if (path.endsWith("/analysis-plans") && method === "GET") return reply(route, plan ? [plan] : []);
    if (path.endsWith("/analysis-plans") && method === "POST") { plan = { plan_id: "plan-1", project_id: PROJECT_ID, dataset_id: "dataset-1", question_id: "question-1", question_version: 1, profile_version: 1, context_snapshot_id: null, context_hash: null, version: 1, status: "draft", objective: "describe", research_question: "Describe sales by fruit", outcome_columns: ["count sold"], predictor_columns: [], group_columns: ["fruit name"], covariate_columns: [], method: "Descriptive aggregation", method_rationale: "Deterministic grouped summary", preprocessing_steps: ["Validate columns"], assumption_checks: ["Row count"], evaluation_metrics: ["mean"], limitations: ["Small sample"], plan_hash: "1".repeat(64), prompt_version: "analysis.plan_generation.v1", created_at: now }; return reply(route, plan, 201); }
    if (path.endsWith("/review") && path.includes("analysis-plans")) {
      if (!plan) return reply(route, { detail: { error_code: "PLAN_NOT_FOUND" } }, 404);
      plan.status = JSON.parse(route.request().postData() ?? "{}").decision;
      return reply(route, { decision_id: "decision-1", project_id: PROJECT_ID, plan_id: "plan-1", plan_version: 1, reviewer_id: "clerk-e2e", decision: plan.status, comment: null, idempotency_key: route.request().headers()["idempotency-key"], created_at: now });
    }
    if (path.endsWith("/runs") && method === "GET") return reply(route, runStatus ? [run()] : []);
    if (path.endsWith("/runs") && method === "POST") { runStatus = "queued"; return reply(route, { operation_id: "operation-1", resource_id: "run-1", status: "queued", status_url: "/run-1" }, 202); }
    if (path.endsWith("/sandbox-runs/run-1/code")) return reply(route, { code_version_id: "code-1", code_id: "code-1", run_id: "run-1", plan_id: "plan-1", plan_version: 1, version: 1, source_code: "import pandas as pd\nfrom sandbox_sdk import load_dataset, emit_result\n\ndf = load_dataset()\nemit_result({'analyzed_row_count': len(df)})\n", code_hash: "5".repeat(64), prompt_version: "analysis.code_generation.v1", status: "approved", revision_count: 0, created_at: now });
    if (path.endsWith("/sandbox-runs/run-1") && method === "GET") { runPolls += 1; if (!["approved", "rejected"].includes(runStatus)) runStatus = runPolls < 2 ? "running" : "result_review_waiting"; return reply(route, run()); }
    if (path.endsWith("/status-history")) return reply(route, [{ history_id: "h1", run_id: "run-1", project_id: PROJECT_ID, from_status: null, to_status: "queued", changed_by: "worker", reason: "run_queued", created_at: now }, { history_id: "h2", run_id: "run-1", project_id: PROJECT_ID, from_status: "running", to_status: runStatus, changed_by: "worker", reason: "validated", created_at: now }]);
    if (path.endsWith("/artifacts")) return reply(route, [{ artifact_id: "artifact-result", run_id: "run-1", artifact_type: "result", filename: "analysis_result.json", content_hash: "2".repeat(64), size_bytes: 128, download_url: `/api/v1/projects/${PROJECT_ID}/sandbox/sandbox-runs/run-1/artifacts/artifact-result` }]);
    if (path.endsWith("/validation")) return reply(route, { validation_id: "validation-1", project_id: PROJECT_ID, run_id: "run-1", result_hash: "3".repeat(64), status: "validated", errors: [], warnings: [], validator_version: "validator.v1", created_at: now });
    if (path.endsWith("/interpretation") && method === "POST") {
      interpretationGenerated = true;
      return reply(route, { interpretation_id: "interpretation-1", project_id: PROJECT_ID, run_id: "run-1", validation_id: "validation-1", prompt_version: "analysis.result_interpretation.v1", narrative: ["Phân tích cho thấy số giờ ngủ có liên hệ với thời gian phản ứng."], numeric_claims: [{ statement: "Hệ số hồi quy ước lượng là", value: -24.63519, locator: "/statistical_results/0/effect_size" }, { statement: "Giá trị p của hệ số là", value: 0.00000012, locator: "/statistical_results/0/p_value" }, { statement: "Khoảng tin cậy 95% dao động từ", value: -26.663, locator: "/statistical_results/0/confidence_interval/0" }, { statement: "đến", value: -22.607, locator: "/statistical_results/0/confidence_interval/1" }], limitations: [], citation_ids: ["citation-1", "citation-2", "citation-3", "citation-4"], created_at: now });
    }
    if (path.endsWith("/interpretation")) {
      if (!interpretationGenerated) return reply(route, { detail: { error_code: "RESULT_INTERPRETATION_GENERATION_FAILED", message: "Interpretation generation failed" } }, 503);
      interpretationPolls += 1;
      if (interpretationPolls <= 2) return reply(route, { detail: { error_code: "RESULT_INTERPRETATION_NOT_FOUND", message: "Interpretation is still being generated" } }, 404);
      return reply(route, { interpretation_id: "interpretation-1", project_id: PROJECT_ID, run_id: "run-1", validation_id: "validation-1", prompt_version: "analysis.result_interpretation.v1", narrative: ["Phân tích cho thấy số giờ ngủ có liên hệ với thời gian phản ứng."], numeric_claims: [{ statement: "Hệ số hồi quy ước lượng là", value: -24.63519, locator: "/statistical_results/0/effect_size" }, { statement: "Giá trị p của hệ số là", value: 0.00000012, locator: "/statistical_results/0/p_value" }, { statement: "Khoảng tin cậy 95% dao động từ", value: -26.663, locator: "/statistical_results/0/confidence_interval/0" }, { statement: "đến", value: -22.607, locator: "/statistical_results/0/confidence_interval/1" }], limitations: [], citation_ids: ["citation-1", "citation-2", "citation-3", "citation-4"], created_at: now });
    }
    if (path.endsWith("/citations")) return reply(route, ["effect_size", "p_value", "confidence_interval/0", "confidence_interval/1"].map((locator, index) => ({ citation_id: `citation-${index + 1}`, project_id: PROJECT_ID, dataset_id: "dataset-1", dataset_hash: "e".repeat(64), profile_version: 1, plan_id: "plan-1", plan_version: 1, run_id: "run-1", artifact_id: "artifact-result", artifact_type: "result", locator: `/statistical_results/0/${locator}`, value_hash: String(index + 4).repeat(64), validation_status: "validated", created_at: now })));
    if (path.endsWith("/review") && path.includes("sandbox-runs")) { runStatus = JSON.parse(route.request().postData() ?? "{}").decision; return reply(route, { run_status: runStatus }); }
    if (path.endsWith("/reproducibility-bundle")) return reply(route, { bundle_id: "bundle-1", project_id: PROJECT_ID, run_id: "run-1", dataset_hash: "e".repeat(64), profile_hash: "f".repeat(64), research_context_hash: null, plan_hash: "1".repeat(64), plan_decision_id: "decision-1", action_proposal_id: null, code_hash: "5".repeat(64), prompt_version: "analysis.code_generation.v1", model_route_audit_id: "audit-1", image_digest: `sha256:${"6".repeat(64)}`, package_manifest_hash: "7".repeat(64), random_seed: 42, result_hash: "3".repeat(64), artifact_hashes: ["2".repeat(64)], bundle_hash: "8".repeat(64), sealed_at: now });
    if (path.includes("/artifacts/artifact-result")) return reply(route, "{}", 200, "application/json");
    return reply(route, { detail: { error_code: "UNMOCKED", message: `${method} ${path}` } }, 501);
  });
}
