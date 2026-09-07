import type {
  AnalysisCode,
  AnalysisArtifact,
  AnalysisCitation,
  AnalysisPlan,
  AnalysisPlanDecision,
  AnalysisQuestion,
  AnalysisQuestionClarification,
  AnalysisQuestionInput,
  Dataset,
  DatasetProfile,
  ExperimentDraft,
  HypothesisDraft,
  OpenSandboxSessionInput,
  QueuedRun,
  ReproducibilityBundle,
  ResearchContextSnapshot,
  ResultInterpretation,
  ResultValidation,
  RunStatusHistory,
  SandboxCapabilities,
  SandboxErrorDetail,
  SandboxRun,
  SandboxSession,
} from "../_types/sandbox";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export class SandboxApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: SandboxErrorDetail,
    public readonly retryAfterSeconds?: number,
  ) {
    super(detail.message);
    this.name = "SandboxApiError";
  }
}

export type SandboxTokenProvider = (refresh?: boolean) => Promise<string | null>;

function uuidV4() {
  return globalThis.crypto.randomUUID();
}

function errorDetail(body: unknown, status: number, correlationId: string | null): SandboxErrorDetail {
  const root = body && typeof body === "object" ? body as Record<string, unknown> : {};
  const raw = root.detail;
  if (raw && typeof raw === "object") {
    const detail = raw as Record<string, unknown>;
    return {
      error_code: String(detail.error_code ?? detail.code ?? `HTTP_${status}`),
      message: String(detail.message ?? detail.error_code ?? detail.code ?? `Yêu cầu thất bại (HTTP ${status}).`),
      retryable: detail.retryable === true,
      details: detail.details && typeof detail.details === "object" ? detail.details as Record<string, unknown> : {},
      correlation_id: String(detail.correlation_id ?? correlationId ?? "") || null,
    };
  }
  return {
    error_code: `HTTP_${status}`,
    message: typeof raw === "string" ? raw : `Yêu cầu thất bại (HTTP ${status}).`,
    retryable: false,
    details: {},
    correlation_id: correlationId,
  };
}

export class SandboxClient {
  private readonly base: string;

  constructor(private readonly projectId: string, private readonly getToken: SandboxTokenProvider) {
    this.base = `${API}/projects/${encodeURIComponent(projectId)}/sandbox`;
  }

  private async request<T>(path: string, init: RequestInit = {}, options: { idempotent?: boolean; response?: "json" | "blob" } = {}): Promise<T> {
    const correlationId = uuidV4();
    const headers = new Headers(init.headers);
    if (!(init.body instanceof FormData) && init.body !== undefined) headers.set("Content-Type", "application/json");
    headers.set("Accept", options.response === "blob" ? "*/*" : "application/json");
    headers.set("X-Correlation-Id", correlationId);
    if (options.idempotent) headers.set("Idempotency-Key", uuidV4());

    const send = async (refresh = false) => {
      const token = await this.getToken(refresh);
      if (!token) throw new SandboxApiError(401, {
        error_code: "AUTH_REQUIRED",
        message: "Phiên đăng nhập chưa sẵn sàng. Hãy đăng nhập lại rồi thử lại.",
        retryable: false,
        details: {},
        correlation_id: correlationId,
      });
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(`${this.base}/${path.replace(/^\/+/, "")}`, { ...init, headers, cache: "no-store" });
    };

    let response = await send();
    if (response.status === 401) response = await send(true);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = errorDetail(body, response.status, response.headers.get("X-Correlation-Id") ?? correlationId);
      const retry = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
      throw new SandboxApiError(response.status, detail, Number.isFinite(retry) ? retry : undefined);
    }
    if (options.response === "blob") return await response.blob() as T;
    if (response.status === 204) return undefined as T;
    return await response.json() as T;
  }

  capabilities = () => this.request<SandboxCapabilities>("capabilities");
  openSession = (payload: OpenSandboxSessionInput) => this.request<SandboxSession>("open-session", { method: "POST", body: JSON.stringify(payload) });
  listSessions = () => this.request<SandboxSession[]>("sandbox-sessions");
  discardSession = (sessionId: string) => this.request<SandboxSession>(`sandbox-sessions/${sessionId}/discard`, { method: "POST", body: "{}" });
  getSessionContext = (sessionId: string) => this.request<ResearchContextSnapshot | null>(`sandbox-sessions/${sessionId}/context`);

  listHypotheses = (sessionId: string) => this.request<HypothesisDraft[]>(`sandbox-sessions/${sessionId}/hypotheses`);
  createHypothesis = (sessionId: string, question: string | undefined, outputLanguage: "vi" | "en") => this.request<HypothesisDraft>(`sandbox-sessions/${sessionId}/hypotheses`, { method: "POST", body: JSON.stringify({ question: question || null, output_language: outputLanguage }) });
  reviewHypothesis = (sessionId: string, hypothesisId: string, decision: "reviewed" | "rejected") => this.request<HypothesisDraft>(`sandbox-sessions/${sessionId}/hypotheses/${hypothesisId}/review`, { method: "POST", body: JSON.stringify({ decision }) }, { idempotent: true });
  listExperiments = (sessionId: string) => this.request<ExperimentDraft[]>(`sandbox-sessions/${sessionId}/experiments`);
  createExperiment = (sessionId: string, hypothesisId: string, outputLanguage: "vi" | "en") => this.request<ExperimentDraft>(`sandbox-sessions/${sessionId}/experiments`, { method: "POST", body: JSON.stringify({ hypothesis_id: hypothesisId, output_language: outputLanguage }) });

  listDatasets = () => this.request<Dataset[]>("datasets");
  uploadDataset = (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return this.request<Dataset>("datasets", { method: "POST", body: form, headers: { "X-Dataset-Classification": "non_sensitive" } });
  };
  deleteDataset = (datasetId: string) => this.request<Dataset>(`datasets/${datasetId}`, { method: "DELETE" });
  profileDataset = (datasetId: string) => this.request<DatasetProfile>(`datasets/${datasetId}/profile`, { method: "POST", body: "{}" });
  listDatasetProfiles = (datasetId: string) => this.request<DatasetProfile[]>(`datasets/${datasetId}/profiles`);
  getDatasetProfile = (datasetId: string, version: number) => this.request<DatasetProfile>(`datasets/${datasetId}/profiles/${version}`);
  createAnalysisQuestion = (datasetId: string, payload: AnalysisQuestionInput) => this.request<AnalysisQuestion | AnalysisQuestionClarification>(`datasets/${datasetId}/analysis-questions`, { method: "POST", body: JSON.stringify(payload) });
  listAnalysisQuestions = (datasetId: string) => this.request<AnalysisQuestion[]>(`datasets/${datasetId}/analysis-questions`);
  createAnalysisPlan = (datasetId: string, questionId: string, profileVersion: number) => this.request<AnalysisPlan>(`datasets/${datasetId}/analysis-plans`, { method: "POST", body: JSON.stringify({ question_id: questionId, profile_version: profileVersion }) });
  listAnalysisPlans = (datasetId: string) => this.request<AnalysisPlan[]>(`datasets/${datasetId}/analysis-plans`);
  reviewAnalysisPlan = (planId: string, version: number, decision: "in_review" | "approved" | "rejected" | "changes_requested", comment?: string) => this.request<AnalysisPlanDecision>(`analysis-plans/${planId}/versions/${version}/review`, { method: "POST", body: JSON.stringify({ decision, comment: comment || null }) }, { idempotent: true });
  listRuns = (planId: string, version: number) => this.request<SandboxRun[]>(`analysis-plans/${planId}/versions/${version}/runs`);
  createRun = (planId: string, version: number, randomSeed = 42) => this.request<QueuedRun>(`analysis-plans/${planId}/versions/${version}/runs`, { method: "POST", body: JSON.stringify({ random_seed: randomSeed }) }, { idempotent: true });
  getRun = (runId: string) => this.request<SandboxRun>(`sandbox-runs/${runId}`);
  getRunCode = (runId: string) => this.request<AnalysisCode>(`sandbox-runs/${runId}/code`);
  cancelRun = (runId: string) => this.request<SandboxRun>(`sandbox-runs/${runId}/cancel`, { method: "POST", body: "{}" });
  getRunHistory = (runId: string) => this.request<RunStatusHistory[]>(`sandbox-runs/${runId}/status-history`);
  getArtifacts = (runId: string) => this.request<AnalysisArtifact[]>(`sandbox-runs/${runId}/artifacts`);
  getArtifactContent = (downloadUrl: string) => {
    const pathname = new URL(downloadUrl, globalThis.location.origin).pathname;
    const projectMarker = `/projects/${encodeURIComponent(this.projectId)}/`;
    const projectPath = pathname.includes(projectMarker) ? pathname.split(projectMarker).pop() ?? "" : "";
    const path = projectPath.startsWith("sandbox/") ? projectPath.slice("sandbox/".length) : projectPath;
    if (!path.startsWith("sandbox-runs/")) throw new Error("Artifact download URL nằm ngoài phạm vi Sandbox của project.");
    return this.request<Blob>(path, {}, { response: "blob" });
  };
  getValidation = (runId: string) => this.request<ResultValidation>(`sandbox-runs/${runId}/validation`);
  getInterpretation = (runId: string) => this.request<ResultInterpretation>(`sandbox-runs/${runId}/interpretation`);
  generateInterpretation = (runId: string) => this.request<ResultInterpretation>(`sandbox-runs/${runId}/interpretation`, { method: "POST", body: "{}" });
  getCitations = (runId: string) => this.request<AnalysisCitation[]>(`sandbox-runs/${runId}/citations`);
  reviewResult = (runId: string, decision: "approved" | "rejected", comment?: string) => this.request<{ run_status: "approved" | "rejected" }>(`sandbox-runs/${runId}/review`, { method: "POST", body: JSON.stringify({ decision, comment: comment || null }) }, { idempotent: true });
  getReproducibilityBundle = (runId: string) => this.request<ReproducibilityBundle>(`sandbox-runs/${runId}/reproducibility-bundle`);
}
