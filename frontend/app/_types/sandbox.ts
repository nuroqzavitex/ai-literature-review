export type SandboxMode = "hypothesis" | "data_analysis";
export type SandboxEntrypoint = "manual" | "graphrag_answer" | "validated_candidate" | "experiment_proposal";
export type SandboxSessionStatus = "draft" | "context_ready" | "active" | "waiting_for_user" | "completed" | "discarded" | "stale" | "failed";

export type SandboxCapabilities = {
  schema_version: "sandbox_capabilities.v1";
  enabled: boolean;
  available: boolean;
  demo_mode: boolean;
  modes: Record<SandboxMode, boolean>;
  ai_enabled: boolean;
  graph_context_enabled: boolean;
  result_interpretation_enabled: boolean;
  supported_dataset_formats: Array<"csv" | "xlsx" | "parquet">;
  max_dataset_bytes: number;
  run_polling_supported: true;
  project_role?: "owner" | "researcher" | "reviewer" | string;
  reason?: "disabled" | "not_configured" | null;
};

export type SandboxErrorDetail = {
  error_code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
  correlation_id?: string | null;
};

export type OpenSandboxSessionInput = {
  mode: SandboxMode;
  entrypoint: SandboxEntrypoint;
  source_resource_id?: string;
  source_parent_id?: string;
  title: string;
  initial_question?: string;
};

export type SandboxSession = {
  session_id: string;
  project_id: string;
  mode: SandboxMode;
  entrypoint: SandboxEntrypoint;
  source_resource_id: string | null;
  title: string;
  initial_question: string | null;
  status: SandboxSessionStatus;
  creator_id: string;
  context_snapshot_id: string | null;
  context_hash: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchContextSnapshot = {
  schema_version: "research_context.v1";
  context_id: string;
  project_id: string;
  source_type: SandboxEntrypoint;
  source_resource_id: string | null;
  graph_version_id: string | null;
  shared_graph_version_id: string | null;
  content_hash: string;
  source_status: string;
  created_at: string;
};

export type DraftStatus = "draft" | "reviewed" | "rejected" | "superseded";
export type HypothesisDraft = {
  hypothesis_id: string;
  session_id: string;
  version: number;
  status: DraftStatus;
  evidence_status: "verified" | "unverified" | "insufficient_evidence";
  statement: string;
  rationale: string;
  supporting_evidence_refs: string[];
  counterevidence_refs: string[];
  assumptions: string[];
  falsification_criteria: string[];
  required_data: string[];
  limitations: string[];
  created_at: string;
};

export type ExperimentDraft = {
  experiment_id: string;
  session_id: string;
  hypothesis_id: string;
  version: number;
  status: DraftStatus;
  objective: string;
  independent_variables: string[];
  dependent_variables: string[];
  controls: string[];
  data_requirements: string[];
  method_candidates: string[];
  evaluation_metrics: string[];
  assumption_checks: string[];
  stopping_criteria: string[];
  risks: string[];
  created_at: string;
};

export type Dataset = {
  dataset_id: string;
  project_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  content_hash: string;
  classification: "non_sensitive" | "unknown" | "restricted";
  status: "staged" | "validated" | "rejected" | "deleted";
  created_at: string;
};

export type DatasetColumnProfile = {
  name: string;
  dtype: string;
  missing_count: number;
  missing_ratio: number;
  unique_count: number;
  distribution: Record<string, unknown>;
};

export type DatasetProfile = {
  profile_id: string;
  dataset_id: string;
  project_id: string;
  version: number;
  profiler_version: string;
  content_hash: string;
  row_count: number;
  column_count: number;
  columns: DatasetColumnProfile[];
  profile_hash: string;
  created_at: string;
};

export type AnalysisObjective = "describe" | "compare" | "associate" | "predict";
export type AnalysisQuestionInput = {
  objective: AnalysisObjective;
  research_question: string;
  outcome_columns: string[];
  predictor_columns: string[];
  group_columns: string[];
  covariate_columns: string[];
  preferred_metrics: string[];
  study_design?: string;
  repeated_measures?: boolean;
  hypothesis?: string;
  context_snapshot_id?: string;
  output_language: "vi" | "en";
};

export type AnalysisQuestion = AnalysisQuestionInput & {
  question_id: string;
  project_id: string;
  dataset_id: string;
  profile_version: number | null;
  context_hash: string | null;
  version: number;
  status: "draft" | "question_incomplete";
  created_at: string;
};

export type AnalysisQuestionClarification = {
  status: "question_incomplete";
  question_id: string | null;
  missing_fields: string[];
  clarification_questions: string[];
};

export type AnalysisPlanStatus = "draft" | "in_review" | "approved" | "rejected" | "changes_requested" | "superseded";
export type AnalysisPlan = {
  plan_id: string;
  project_id: string;
  dataset_id: string;
  question_id: string;
  question_version: number;
  profile_version: number;
  context_snapshot_id: string | null;
  context_hash: string | null;
  version: number;
  status: AnalysisPlanStatus;
  objective: AnalysisObjective;
  research_question: string;
  outcome_columns: string[];
  predictor_columns: string[];
  group_columns: string[];
  covariate_columns: string[];
  output_language: "vi" | "en";
  method: string;
  method_rationale: string;
  preprocessing_steps: string[];
  assumption_checks: string[];
  evaluation_metrics: string[];
  limitations: string[];
  plan_hash: string;
  prompt_version: "analysis.plan_generation.v1";
  created_at: string;
};

export type AnalysisPlanDecision = {
  decision_id: string;
  project_id: string;
  plan_id: string;
  plan_version: number;
  reviewer_id: string;
  decision: AnalysisPlanStatus;
  comment: string | null;
  idempotency_key: string;
  created_at: string;
};

export type RunStatus = "pending_approval" | "queued" | "running" | "completed_unvalidated" | "validation_failed" | "result_review_waiting" | "approved" | "rejected" | "failed" | "timed_out" | "policy_rejected" | "cancelled";
export type SandboxRun = {
  run_id: string;
  operation_id: string;
  project_id: string;
  dataset_id: string;
  plan_id: string;
  plan_version: number;
  code_version_id: string;
  status: RunStatus;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

export type AnalysisCode = {
  code_version_id: string;
  code_id: string;
  run_id: string;
  plan_id: string;
  plan_version: number;
  version: number;
  source_code: string;
  code_hash: string;
  prompt_version: "analysis.code_generation.v1" | "analysis.code_revision.v1";
  status: "draft" | "policy_rejected" | "approved" | "superseded";
  revision_count: number;
  created_at: string;
};

export type QueuedRun = { operation_id: string; resource_id: string; status: "queued"; status_url: string };
export type RunStatusHistory = { history_id: string; run_id: string; project_id: string; from_status: RunStatus | null; to_status: RunStatus; changed_by: string; reason: string | null; created_at: string };
export type AnalysisArtifact = { artifact_id: string; run_id: string; artifact_type: "result" | "table" | "chart" | "diagnostic"; filename: string; content_hash: string; size_bytes: number; download_url: string };
export type ResultValidation = { validation_id: string; project_id: string; run_id: string; result_hash: string | null; status: "validated" | "failed"; errors: string[]; warnings: string[]; validator_version: string; created_at: string };
export type NumericClaim = { statement: string; value: number; locator: string };
export type ResultInterpretation = { interpretation_id: string; project_id: string; run_id: string; validation_id: string; prompt_version: "analysis.result_interpretation.v1"; narrative: string[]; numeric_claims: NumericClaim[]; limitations: string[]; citation_ids: string[]; created_at: string };
export type AnalysisCitation = { citation_id: string; project_id: string; dataset_id: string; dataset_hash: string; profile_version: number | null; plan_id: string; plan_version: number; run_id: string; artifact_id: string; artifact_type: string; locator: string; value_hash: string; validation_status: "validated" | "reviewed"; created_at: string };
export type ReproducibilityBundle = { bundle_id: string; project_id: string; run_id: string; dataset_hash: string; profile_hash: string; research_context_hash: string | null; plan_hash: string; plan_decision_id: string; action_proposal_id: string | null; code_hash: string; prompt_version: string; model_route_audit_id: string; image_digest: string; package_manifest_hash: string; random_seed: number; result_hash: string; artifact_hashes: string[]; bundle_hash: string; sealed_at: string };
