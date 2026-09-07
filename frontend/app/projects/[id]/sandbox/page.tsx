"use client";

import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { FormEvent, KeyboardEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import LanguageToggle from "../../../_components/LanguageToggle";
import { useSandboxI18n } from "../../../_lib/sandbox-i18n";
import { SandboxApiError, SandboxClient } from "../../../_lib/sandbox-client";
import type {
  AnalysisCode,
  AnalysisArtifact,
  AnalysisCitation,
  AnalysisObjective,
  AnalysisPlan,
  AnalysisQuestion,
  AnalysisQuestionClarification,
  Dataset,
  DatasetProfile,
  ExperimentDraft,
  HypothesisDraft,
  OpenSandboxSessionInput,
  ReproducibilityBundle,
  ResultInterpretation,
  ResultValidation,
  RunStatus,
  RunStatusHistory,
  SandboxCapabilities,
  SandboxMode,
  SandboxRun,
  SandboxSession,
} from "../../../_types/sandbox";

const TERMINAL_RUNS = new Set<RunStatus>(["approved", "rejected", "validation_failed", "failed", "timed_out", "policy_rejected", "cancelled"]);
const SETTLED_EXECUTION = new Set<RunStatus>(["completed_unvalidated", "result_review_waiting", ...TERMINAL_RUNS]);
const RETRYABLE_RUNS = new Set<RunStatus>(["rejected", "validation_failed", "failed", "timed_out", "policy_rejected", "cancelled"]);
const SANDBOX_MODES: SandboxMode[] = ["hypothesis", "data_analysis"];
const INTERPRETATION_RETRY_DELAYS = [1000, 2000, 3000, 4000, 5000, 5000, 5000, 5000];
const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

type Notice = { tone: "error" | "success" | "info"; message: string; correlationId?: string | null };
type ProjectBreadcrumb = { project_id: string; name: string };
type PanelProps = { client: SandboxClient; session: SandboxSession; capabilities: SandboxCapabilities; notify: (notice: Notice) => void };
type HypothesisAnalysisHandoff = {
  schema_version: "hypothesis_analysis_handoff.v1";
  source_session_id: string;
  hypothesis_id: string;
  experiment_id: string | null;
  research_question: string;
  hypothesis: string;
  outcome_columns: string[];
  predictor_columns: string[];
  required_columns: string[];
  preferred_metrics: string[];
  created_at: string;
};
type AnalysisWorkspaceState = {
  schema_version: "analysis_workspace.v1";
  dataset_id: string;
  question_id?: string;
  plan_id?: string;
  plan_version?: number;
  run_id?: string;
};

function initials(name?: string | null) {
  return (name ?? "LR").split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function humanError(cause: unknown): Notice {
  if (cause instanceof SandboxApiError) {
    return { tone: "error", message: cause.detail.message, correlationId: cause.detail.correlation_id };
  }
  return { tone: "error", message: cause instanceof Error ? cause.message : "Có lỗi không xác định. Hãy thử lại." };
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

function dateTime(value: string, locale = "vi-VN") {
  return new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function readBrowserSetting(key: string) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function writeBrowserSetting(key: string, value: string | null) {
  try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch { /* The UI remains usable when browser storage is unavailable. */ }
}

function handoffStorageKey(projectId: string, sessionId: string) {
  return `research-sandbox:${projectId}:analysis-handoff:${sessionId}`;
}

function analysisWorkspaceStorageKey(projectId: string, sessionId: string) {
  return `research-sandbox:${projectId}:analysis-workspace:${sessionId}`;
}

function readAnalysisWorkspace(projectId: string, sessionId: string): AnalysisWorkspaceState | null {
  const raw = readBrowserSetting(analysisWorkspaceStorageKey(projectId, sessionId));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<AnalysisWorkspaceState>;
    return value.schema_version === "analysis_workspace.v1" && typeof value.dataset_id === "string"
      ? value as AnalysisWorkspaceState
      : null;
  } catch { return null; }
}

function writeAnalysisWorkspace(projectId: string, sessionId: string, value: AnalysisWorkspaceState) {
  writeBrowserSetting(analysisWorkspaceStorageKey(projectId, sessionId), JSON.stringify(value));
}

function readAnalysisHandoff(projectId: string, sessionId: string): HypothesisAnalysisHandoff | null {
  const raw = readBrowserSetting(handoffStorageKey(projectId, sessionId));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<HypothesisAnalysisHandoff>;
    return value.schema_version === "hypothesis_analysis_handoff.v1" && typeof value.research_question === "string"
      ? value as HypothesisAnalysisHandoff
      : null;
  } catch { return null; }
}

function normalizeColumnName(value: string) {
  return value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function resolveColumns(requested: string[], profile: DatasetProfile | null) {
  if (!profile) return { matched: [] as string[], missing: requested };
  const available = profile.columns.map((column) => ({ actual: column.name, normalized: normalizeColumnName(column.name) }));
  const matched: string[] = []; const missing: string[] = [];
  for (const requirement of [...new Set(requested.map((item) => item.trim()).filter(Boolean))]) {
    const normalized = normalizeColumnName(requirement);
    const found = available.find((column) => column.normalized === normalized)
      ?? available.find((column) => normalized.length >= 4 && (column.normalized.includes(normalized) || normalized.includes(column.normalized)));
    if (found) matched.push(found.actual); else missing.push(requirement);
  }
  return { matched: [...new Set(matched)], missing };
}

function splitList(value: string) {
  return value.split(",").map((part) => part.trim()).filter(Boolean);
}

function previewCsv(text: string, maxRows = 8, maxColumns = 8) {
  const rows: string[][] = []; let row: string[] = []; let field = ""; let quoted = false;
  for (let index = 0; index < text.length && rows.length < maxRows; index += 1) {
    const char = text[index];
    if (char === '"' && quoted && text[index + 1] === '"') { field += '"'; index += 1; }
    else if (char === '"') quoted = !quoted;
    else if (char === "," && !quoted) { if (row.length < maxColumns) row.push(field); field = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      if (row.length < maxColumns) row.push(field); if (row.some(Boolean)) rows.push(row); row = []; field = "";
    } else field += char;
  }
  if (rows.length < maxRows && (field || row.length)) { if (row.length < maxColumns) row.push(field); rows.push(row); }
  return rows;
}

type InterpretationClaim = ResultInterpretation["numeric_claims"][number];

function cleanClaimStatement(value: string) {
  return value.trim().replace(/\s+/g, " ").replace(/[.:;,\s]+$/g, "");
}

function confidenceIntervalPart(locator: string) {
  const match = locator.match(/^(.*(?:confidence[_-]?interval|confidenceInterval))[/.](0|1)$/i);
  return match ? { group: match[1], part: Number(match[2]) } : null;
}

function isPValueClaim(claim: InterpretationClaim) {
  return /p[_-]?value|p-value|giá trị p|p value/i.test(`${claim.locator} ${claim.statement}`);
}

function formatClaimValue(claim: InterpretationClaim, locale: string) {
  if (!Number.isFinite(claim.value)) return "—";
  if (isPValueClaim(claim)) return Math.abs(claim.value) < 0.001 ? "p < 0.001" : `p = ${claim.value.toFixed(3)}`;
  if (Number.isInteger(claim.value) && /(?:count|row|sample|n$)/i.test(claim.locator)) return claim.value.toLocaleString(locale);
  const normalized = Math.abs(claim.value) < 0.0005 ? 0 : claim.value;
  return normalized.toFixed(3);
}

function CitationBadge({ citation, number }: { citation: AnalysisCitation | undefined; number: number }) {
  const [open, setOpen] = useState(false);
  const { s } = useSandboxI18n();
  return <span className={`sandbox-citation-badge ${open ? "is-open" : ""}`}>
    <button type="button" aria-expanded={open} aria-label={s("citationAria", { number })} onClick={() => setOpen((value) => !value)}>[{number}]</button>
    <span className="sandbox-citation-popover" role="tooltip">
      {citation ? <><strong>{s("citationLabel", { number })}</strong><span>{s("citationSourcePosition")}</span><code>{citation.locator}</code><span>{s("citationVerificationHash")}</span><code>{citation.value_hash}</code></> : <><strong>{s("citationLabel", { number })}</strong><span>{s("citationSyncing")}</span></>}
    </span>
  </span>;
}

function InterpretationView({ interpretation, citations }: { interpretation: ResultInterpretation; citations: AnalysisCitation[] }) {
  const { locale, s } = useSandboxI18n();
  const citationFor = (claim: InterpretationClaim, fallbackIndex: number) => citations.find((item) => item.locator === claim.locator) ?? citations[fallbackIndex];
  const citationNumber = (citation: AnalysisCitation | undefined, fallbackIndex: number) => {
    const index = citation ? citations.findIndex((item) => item.citation_id === citation.citation_id) : -1;
    return (index >= 0 ? index : fallbackIndex) + 1;
  };
  const consumed = new Set<number>();
  const claimSegments: ReactNode[] = [];

  interpretation.numeric_claims.forEach((claim, index) => {
    if (consumed.has(index)) return;
    const intervalPart = confidenceIntervalPart(claim.locator);
    if (intervalPart) {
      const pairIndex = interpretation.numeric_claims.findIndex((candidate, candidateIndex) => {
        const candidatePart = confidenceIntervalPart(candidate.locator);
        return candidateIndex !== index && candidatePart?.group === intervalPart.group && candidatePart.part !== intervalPart.part;
      });
      if (pairIndex >= 0) {
        consumed.add(pairIndex);
        const pair = interpretation.numeric_claims[pairIndex];
        const lowerClaim = intervalPart.part === 0 ? claim : pair;
        const upperClaim = intervalPart.part === 1 ? claim : pair;
        const lowerIndex = intervalPart.part === 0 ? index : pairIndex;
        const upperIndex = intervalPart.part === 1 ? index : pairIndex;
        const lowerCitation = citationFor(lowerClaim, lowerIndex);
        const upperCitation = citationFor(upperClaim, upperIndex);
        claimSegments.push(<span className="sandbox-claim-sentence" key={`${intervalPart.group}-range`}>
          {cleanClaimStatement(lowerClaim.statement).replace(/\b(từ|from)$/i, "").trim()} <strong className="sandbox-claim-value">[{lowerClaim.value.toFixed(2)}, {upperClaim.value.toFixed(2)}]</strong>
          <CitationBadge citation={lowerCitation} number={citationNumber(lowerCitation, lowerIndex)}/>
          <CitationBadge citation={upperCitation} number={citationNumber(upperCitation, upperIndex)}/>.
        </span>);
        return;
      }
    }
    const citation = citationFor(claim, index);
    claimSegments.push(<span className="sandbox-claim-sentence" key={`${claim.locator}-${index}`}>
      {cleanClaimStatement(claim.statement)} <strong className="sandbox-claim-value">{formatClaimValue(claim, locale)}</strong>
      <CitationBadge citation={citation} number={citationNumber(citation, index)}/>.
    </span>);
  });

  return <article className="sandbox-interpretation">
    <h3>{s("interpretation")}</h3>
    {interpretation.narrative.length > 0 && <p>{interpretation.narrative.join(" ")}</p>}
    {claimSegments.length > 0 && <p className="sandbox-claim-prose">{claimSegments}</p>}
  </article>;
}

function Icon({ name, size = 18 }: { name: "flask" | "data" | "check" | "upload" | "download" | "play" | "stop" | "plus" | "shield" | "chevron" | "close" | "trash"; size?: number }) {
  const paths: Record<typeof name, ReactNode> = {
    flask: <><path d="M9 3h6M10 3v5l-5 9a2 2 0 0 0 1.8 3h10.4a2 2 0 0 0 1.8-3l-5-9V3"/><path d="M7.7 14h8.6"/></>,
    data: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></>,
    check: <path d="m5 12 4 4L19 6"/>, upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5"/><path d="M5 14v5h14v-5"/></>,
    download: <><path d="M12 4v12m0 0 5-5m-5 5-5-5"/><path d="M5 20h14"/></>, play: <path d="m8 5 11 7-11 7z"/>,
    stop: <rect x="6" y="6" width="12" height="12" rx="1"/>, plus: <path d="M12 5v14M5 12h14"/>,
    shield: <><path d="M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-5"/></>,
    chevron: <path d="m9 6 6 6-6 6"/>, close: <path d="M6 6l12 12M18 6 6 18"/>,
    trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13"/><path d="M10 11v5M14 11v5"/></>,
  };
  return <svg className="sandbox-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function StatusTag({ value }: { value: string }) {
  const { s } = useSandboxI18n();
  const labels: Record<string, ReturnType<typeof s>> = {
    draft: s("statusDraft"), context_ready: s("statusContextReady"), active: s("statusActive"), waiting_for_user: s("statusWaiting"),
    reviewed: s("statusReviewed"), rejected: s("statusRejected"), unverified: s("statusUnverified"), verified: s("statusVerified"),
    assessed: s("statusAssessed"), in_review: s("statusInReview"), approved: s("statusApproved"), changes_requested: s("statusChanges"),
    staged: s("statusStaged"), validated: s("statusValidated"), queued: s("statusQueued"), running: s("statusRunning"),
    completed_unvalidated: s("statusUnvalidated"), result_review_waiting: s("statusResultReview"), validation_failed: s("statusValidationFailed"),
    failed: s("statusFailed"), timed_out: s("statusTimedOut"), policy_rejected: s("statusPolicyRejected"), cancelled: s("statusCancelled"),
    completed: s("statusCompleted"), discarded: s("statusDiscarded"), stale: s("statusStale"),
  };
  return <span className={`sandbox-status status-${value}`}>{labels[value] ?? value.replaceAll("_", " ")}</span>;
}

function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return <div className="sandbox-empty"><span className="sandbox-empty-mark" aria-hidden="true"></span><h3>{title}</h3><p>{children}</p></div>;
}

function SessionNavigator({ mode, sessions, selectedId, onSelect, onNew, onDiscard, discarding }: {
  mode: SandboxMode;
  sessions: SandboxSession[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
  onNew: () => void;
  onDiscard: (session: SandboxSession) => void;
  discarding: boolean;
}) {
  const { locale, s } = useSandboxI18n();
  const labels: Record<SandboxMode, string> = { hypothesis: s("hypothesis"), data_analysis: s("analysis") };
  const modeSessions = useMemo(
    () => sessions.filter((item) => item.mode === mode && item.status !== "discarded").sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at)),
    [mode, sessions],
  );
  const openCount = modeSessions.filter((item) => !["discarded", "completed"].includes(item.status)).length;
  const selected = modeSessions.find((item) => item.session_id === selectedId);
  const deleteDisabled = !selected || selected.status === "completed" || discarding;

  return <section className="sandbox-session-navigator" aria-label={s("sessionsLabel", { mode: labels[mode] })}>
    <div className="sandbox-session-summary"><strong>{s("sessionsCount", { count: modeSessions.length })}</strong><span>{s("sessionsOpen", { mode: labels[mode], count: openCount })}</span></div>
    {modeSessions.length > 0 ? <label className="sandbox-session-picker"><span>{s("sessionViewing")}</span><select value={selectedId ?? ""} onChange={(event) => event.target.value ? onSelect(event.target.value) : onNew()}><option value="">{s("newSessionOption")}</option>{modeSessions.map((item) => <option key={item.session_id} value={item.session_id}>{item.title} · {item.status.replaceAll("_", " ")} · {dateTime(item.updated_at, locale)}</option>)}</select></label> : <p>{s("noSessions")}</p>}
    <div className="sandbox-session-actions">
      <button type="button" className="sandbox-new-session" onClick={onNew}><Icon name="plus"/>{s("newSession")}</button>
      <button type="button" className="sandbox-delete-session" disabled={deleteDisabled} title={selected?.status === "completed" ? s("deleteCompletedSession") : undefined} onClick={() => selected && onDiscard(selected)}><Icon name="trash"/>{discarding ? s("deletingSession") : s("deleteSession")}</button>
    </div>
  </section>;
}

function SessionGate({ mode, client, contextInput, onSession, notify }: { mode: SandboxMode; client: SandboxClient; contextInput: Partial<OpenSandboxSessionInput>; onSession: (value: SandboxSession) => void; notify: (notice: Notice) => void }) {
  const { s } = useSandboxI18n();
  const labels = { hypothesis: s("hypothesisNew"), data_analysis: s("analysisNew") };
  const [title, setTitle] = useState(contextInput.title ?? labels[mode]);
  const [question, setQuestion] = useState(contextInput.initial_question ?? "");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true);
    try {
      const session = await client.openSession({
        mode,
        entrypoint: contextInput.entrypoint ?? "manual",
        source_resource_id: contextInput.source_resource_id,
        source_parent_id: contextInput.source_parent_id,
        title: title.trim(),
        initial_question: question.trim() || undefined,
      });
      onSession(session);
      notify({ tone: "success", message: "Đã mở một session tách biệt. Không worker hay AI nào được tự động kích hoạt." });
    } catch (cause) { notify(humanError(cause)); } finally { setBusy(false); }
  }

  return <form className="sandbox-session-gate" onSubmit={submit}>
    <div><h2>{s("openSpace")}</h2><p>{s("openSpaceBody")}</p>{contextInput.entrypoint && contextInput.entrypoint !== "manual" && <p className="sandbox-context-source"><Icon name="shield"/>{s("signedContext")}</p>}</div>
    <label>{s("sessionName")}<input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={255}/></label>
    <label>{s("firstQuestion")} <span>{s("optional")}</span><textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3}/></label>
    <button className="sandbox-button primary" disabled={busy || !title.trim()}>{busy ? s("opening") : s("openSandbox")}</button>
  </form>;
}

function HypothesisPanel({ client, session, capabilities, notify, onTransfer }: PanelProps & { onTransfer: (handoff: HypothesisAnalysisHandoff) => Promise<void> }) {
  const { lang, locale, s } = useSandboxI18n();
  const [question, setQuestion] = useState(session.initial_question ?? "");
  const [hypotheses, setHypotheses] = useState<HypothesisDraft[]>([]);
  const [experiments, setExperiments] = useState<ExperimentDraft[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [selectedHypothesisId, setSelectedHypothesisId] = useState<string | null>(null);
  const current = hypotheses.find((item) => item.hypothesis_id === selectedHypothesisId) ?? hypotheses.at(-1);
  const currentExperiment = current ? experiments.filter((item) => item.hypothesis_id === current.hypothesis_id).at(-1) ?? null : null;

  const refresh = useCallback(async () => {
    const [drafts, plans] = await Promise.all([client.listHypotheses(session.session_id), client.listExperiments(session.session_id)]);
    setHypotheses(drafts); setExperiments(plans);
    setSelectedHypothesisId((selected) => selected && drafts.some((item) => item.hypothesis_id === selected) ? selected : drafts.at(-1)?.hypothesis_id ?? null);
  }, [client, session.session_id]);
  useEffect(() => { void refresh().catch((cause) => notify(humanError(cause))); }, [refresh, notify]);

  async function act(action: () => Promise<unknown>, message: string) {
    setBusy(true); try { await action(); await refresh(); notify({ tone: "success", message }); } catch (cause) { notify(humanError(cause)); } finally { setBusy(false); }
  }

  return <div className="sandbox-mode-layout">
    <aside className="sandbox-ledger">
      <h2>{s("hypothesisLedger")}</h2><p>{s("hypothesisLedgerBody")}</p>
      <label>{s("explorationQuestion")}<textarea rows={5} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={s("explorationPlaceholder")}/></label>
      <button className="sandbox-button primary" disabled={!capabilities.ai_enabled || busy} onClick={() => void act(() => client.createHypothesis(session.session_id, question, lang), s("createDraft"))}><Icon name="flask"/>{busy ? s("creatingDraft") : s("createDraft")}</button>
      {!capabilities.ai_enabled && <p className="sandbox-inline-note">{s("aiDisabledDrafts")}</p>}
      <div className="sandbox-version-list" aria-label={s("hypothesisVersions")}>{hypotheses.map((item) => <button type="button" key={item.hypothesis_id} aria-pressed={item.hypothesis_id === current?.hypothesis_id} className={item.hypothesis_id === current?.hypothesis_id ? "active" : ""} onClick={() => setSelectedHypothesisId(item.hypothesis_id)}><span>v{item.version}</span><strong>{item.statement}</strong><StatusTag value={item.status}/></button>)}</div>
    </aside>
    <section className="sandbox-workpaper">
      {!current ? <EmptyState title={s("noDraft")}>{s("noDraftBody")}</EmptyState> : <>
        <header className="sandbox-paper-head"><div><h1>{current.statement}</h1><p>{current.rationale}</p></div><div><StatusTag value={current.evidence_status}/><StatusTag value={current.status}/></div></header>
        <div className="sandbox-two-column">
          <section><h3>{s("falsification")}</h3><ul>{current.falsification_criteria.map((item) => <li key={item}>{item}</li>)}{!current.falsification_criteria.length && <li>{s("undefined")}</li>}</ul><h3>{s("requiredData")}</h3><ul>{current.required_data.map((item) => <li key={item}>{item}</li>)}</ul></section>
          <section className="sandbox-checklist"><h3>{s("limitationChecklist")}</h3><p>{s("limitationBody")}</p>{current.limitations.map((item, index) => <label key={item}><input type="checkbox" checked={checked[`${current.hypothesis_id}-${index}`] ?? false} onChange={(event) => setChecked((value) => ({ ...value, [`${current.hypothesis_id}-${index}`]: event.target.checked }))}/><span>{item}</span></label>)}{!current.limitations.length && <p>{s("noLimitations")}</p>}</section>
        </div>
        <div className="sandbox-review-bar"><span>{s("immutableDraft", { version: current.version, date: dateTime(current.created_at, locale) })}</span><div><button className="sandbox-button" disabled={busy || current.status !== "draft"} onClick={() => void act(() => client.reviewHypothesis(session.session_id, current.hypothesis_id, "rejected"), s("reject"))}>{s("reject")}</button><button className="sandbox-button primary" disabled={busy || current.status !== "draft" || (current.limitations.length > 0 && current.limitations.some((_, index) => !checked[`${current.hypothesis_id}-${index}`]))} onClick={() => void act(() => client.reviewHypothesis(session.session_id, current.hypothesis_id, "reviewed"), s("approve"))}><Icon name="check"/>{s("approve")}</button></div></div>
        <section className="sandbox-experiment"><div><h2>{s("experimentDesign")}</h2><p>{s("experimentBody")}</p></div><button className="sandbox-button" disabled={busy || !capabilities.ai_enabled} onClick={() => void act(() => client.createExperiment(session.session_id, current.hypothesis_id, lang), s("createDesign"))}><Icon name="plus"/>{s("createDesign")}</button>{experiments.filter((item) => item.hypothesis_id === current.hypothesis_id).map((item) => <article key={item.experiment_id}><h3>{item.objective}</h3><dl><div><dt>{s("method")}</dt><dd>{item.method_candidates.join(", ") || s("undefined")}</dd></div><div><dt>{s("metrics")}</dt><dd>{item.evaluation_metrics.join(", ") || s("undefined")}</dd></div><div><dt>{s("stopping")}</dt><dd>{item.stopping_criteria.join("; ") || s("undefined")}</dd></div></dl></article>)}</section>
        {current.status !== "rejected" && <section className="sandbox-analysis-handoff"><div><h2>{s("continueToAnalysis")}</h2><p>{s("continueToAnalysisBody")}</p>{currentExperiment && <small>{s("experimentVariables", { count: [...currentExperiment.independent_variables, ...currentExperiment.dependent_variables].length })}</small>}</div><button type="button" className="sandbox-button primary" disabled={busy} onClick={() => void onTransfer({ schema_version: "hypothesis_analysis_handoff.v1", source_session_id: session.session_id, hypothesis_id: current.hypothesis_id, experiment_id: currentExperiment?.experiment_id ?? null, research_question: currentExperiment?.objective || current.statement, hypothesis: current.statement, outcome_columns: currentExperiment?.dependent_variables ?? [], predictor_columns: currentExperiment?.independent_variables ?? [], required_columns: currentExperiment ? [...currentExperiment.independent_variables, ...currentExperiment.dependent_variables] : current.required_data, preferred_metrics: currentExperiment?.evaluation_metrics ?? [], created_at: new Date().toISOString() })}><Icon name="data"/>{s("continueToAnalysis")}</button></section>}
      </>}
    </section>
  </div>;
}

function ProfileView({ profile }: { profile: DatasetProfile }) {
  return <section className="sandbox-profile"><header><div><h2>Hồ sơ deterministic</h2><p>{profile.profiler_version} · hash {profile.profile_hash.slice(0, 12)}</p></div><dl><div><dt>Dòng</dt><dd>{profile.row_count.toLocaleString("vi-VN")}</dd></div><div><dt>Cột</dt><dd>{profile.column_count}</dd></div></dl></header><div className="sandbox-profile-table"><table><thead><tr><th>Tên cột</th><th>Kiểu</th><th>Thiếu</th><th>Duy nhất</th><th>Phân phối sơ bộ</th></tr></thead><tbody>{profile.columns.map((column) => <tr key={column.name}><td><strong>{column.name}</strong></td><td><code>{column.dtype}</code></td><td>{column.missing_count} <small>({Math.round(column.missing_ratio * 100)}%)</small></td><td>{column.unique_count}</td><td><code>{JSON.stringify(column.distribution).slice(0, 90)}</code></td></tr>)}</tbody></table></div></section>;
}

function ArtifactGallery({ client, artifacts, citations }: { client: SandboxClient; artifacts: AnalysisArtifact[]; citations: AnalysisCitation[] }) {
  const { s } = useSandboxI18n();
  const [previews, setPreviews] = useState<Record<string, { url?: string; rows?: string[][] }>>({});
  useEffect(() => {
    let active = true; const urls: string[] = [];
    void Promise.all(artifacts.filter((item) => item.artifact_type === "chart" || item.artifact_type === "table").map(async (item) => {
      const blob = await client.getArtifactContent(item.download_url);
      if (!active) return;
      if (item.artifact_type === "chart") { const url = URL.createObjectURL(blob); urls.push(url); setPreviews((value) => ({ ...value, [item.artifact_id]: { url } })); }
      else { const text = await blob.text(); setPreviews((value) => ({ ...value, [item.artifact_id]: { rows: previewCsv(text) } })); }
    })).catch(() => undefined);
    return () => { active = false; urls.forEach(URL.revokeObjectURL); };
  }, [artifacts, client]);

  async function download(item: AnalysisArtifact) { const blob = await client.getArtifactContent(item.download_url); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = item.filename; anchor.click(); URL.revokeObjectURL(url); }
  if (!artifacts.length) return null;
  const chartCount = artifacts.filter((item) => item.artifact_type === "chart").length;
  const tableCount = artifacts.filter((item) => item.artifact_type === "table").length;
  const typeLabel = (type: AnalysisArtifact["artifact_type"]) => ({ result: s("artifactResult"), table: s("artifactTable"), chart: s("artifactChart"), diagnostic: s("artifactDiagnostic") })[type];
  return <section className="sandbox-artifacts"><header className="sandbox-artifacts-heading"><div><h2>{s("artifactTitle")}</h2><p>{s("artifactSummary", { tables: tableCount, charts: chartCount, citations: citations.length })}</p></div></header>{chartCount === 0 && <p className="sandbox-inline-note">{s("legacyRunNoChart")}</p>}<div className="sandbox-artifact-grid">{artifacts.map((item) => <article key={item.artifact_id}><header><div><strong>{item.filename}</strong><span>{typeLabel(item.artifact_type)} · {formatBytes(item.size_bytes)}</span></div><button title={s("downloadArtifact")} aria-label={s("downloadNamedArtifact", { name: item.filename })} onClick={() => void download(item)}><Icon name="download"/></button></header>{previews[item.artifact_id]?.url && <img src={previews[item.artifact_id].url} alt={s("chartAlt", { name: item.filename })}/>} {previews[item.artifact_id]?.rows && <div className="sandbox-mini-table"><table><tbody>{previews[item.artifact_id].rows?.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody></table></div>}<div className="sandbox-citation-list">{citations.filter((citation) => citation.artifact_id === item.artifact_id).map((citation) => <details key={citation.citation_id}><summary>AnalysisCitation · {citation.locator}</summary><code>dataset {citation.dataset_hash.slice(0, 12)} · value {citation.value_hash.slice(0, 12)}</code></details>)}</div></article>)}</div></section>;
}

function PlanDialog({ plan, busy, onClose, onDecision }: { plan: AnalysisPlan; busy: boolean; onClose: () => void; onDecision: (decision: "approved" | "rejected" | "changes_requested", comment: string) => void }) {
  const [comment, setComment] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current; if (!dialog) return;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, []);
  return <dialog ref={dialogRef} aria-labelledby="plan-review-title" className="sandbox-plan-dialog" onCancel={(event) => { event.preventDefault(); onClose(); }} onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><button className="sandbox-dialog-close" onClick={onClose} aria-label="Đóng"><Icon name="close"/></button><h2 id="plan-review-title">Duyệt AnalysisPlan v{plan.version}</h2><p>Plan là bất biến sau khi tạo. Mọi quyết định được ghi append-only.</p><dl><div><dt>Phương pháp</dt><dd>{plan.method}</dd></div><div><dt>Lý do</dt><dd>{plan.method_rationale}</dd></div><div><dt>Metrics</dt><dd>{plan.evaluation_metrics.join(", ")}</dd></div><div><dt>Assumption checks</dt><dd>{plan.assumption_checks.join("; ")}</dd></div><div><dt>Giới hạn</dt><dd>{plan.limitations.join("; ")}</dd></div></dl><label>Nhận xét reviewer<textarea rows={4} value={comment} onChange={(event) => setComment(event.target.value)}/></label><div className="sandbox-dialog-actions"><button className="sandbox-button" disabled={busy} onClick={() => onDecision("rejected", comment)}>Từ chối</button><button className="sandbox-button" disabled={busy} onClick={() => onDecision("changes_requested", comment)}>Yêu cầu sửa</button><button className="sandbox-button primary" disabled={busy} onClick={() => onDecision("approved", comment)}><Icon name="check"/>Phê duyệt</button></div></dialog>;
}

const PYTHON_KEYWORDS = new Set([
  "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except",
  "False", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "None", "nonlocal", "not",
  "or", "pass", "raise", "return", "True", "try", "while", "with", "yield",
]);

function HighlightedPython({ source }: { source: string }) {
  const tokenPattern = /(#.*$|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g;
  const lines = source.split("\n");
  return <code>{lines.map((line, lineIndex) => <span className="sandbox-code-line" key={lineIndex}>{line.split(tokenPattern).filter(Boolean).map((token, tokenIndex) => {
    const className = token.startsWith("#") ? "comment" : token.startsWith('"') || token.startsWith("'") ? "string" : /^\d/.test(token) ? "number" : PYTHON_KEYWORDS.has(token) ? "keyword" : "";
    return <span className={className} key={tokenIndex}>{token}</span>;
  })}{lineIndex < lines.length - 1 ? "\n" : ""}</span>)}</code>;
}

function GeneratedPythonCode({ code, run, notify }: { code: AnalysisCode; run: SandboxRun; notify: (notice: Notice) => void }) {
  const [copied, setCopied] = useState(false);
  const { s } = useSandboxI18n();
  async function copy() {
    try {
      await navigator.clipboard.writeText(code.source_code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch (cause) { notify(humanError(cause)); }
  }
  return <section className="sandbox-generated-code" aria-labelledby="generated-python-title">
    <header><div><span className="sandbox-stage-index">2</span><div><h2 id="generated-python-title">{s("generatedCodeTitle")}</h2><p>{s("generatedCodeBody")}</p></div></div><button className="sandbox-button" type="button" onClick={() => void copy()}>{copied ? s("copiedCode") : s("copyCode")}</button></header>
    <div className="sandbox-code-meta"><code>{code.prompt_version}</code><span>hash {code.code_hash.slice(0, 16)}</span><StatusTag value={code.status}/><StatusTag value={run.status}/></div>
    <pre tabIndex={0} aria-label={s("codeAria")}><HighlightedPython source={code.source_code}/></pre>
  </section>;
}

function DataAnalysisPanel({ client, session, capabilities, notify, handoff }: PanelProps & { handoff: HypothesisAnalysisHandoff | null }) {
  const { lang, locale, s } = useSandboxI18n();
  const [datasets, setDatasets] = useState<Dataset[]>([]); const [dataset, setDataset] = useState<Dataset | null>(null); const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [objective, setObjective] = useState<AnalysisObjective>("describe"); const [questionText, setQuestionText] = useState(session.initial_question ?? "");
  const [outcomes, setOutcomes] = useState(""); const [predictors, setPredictors] = useState(""); const [groups, setGroups] = useState(""); const [metrics, setMetrics] = useState("");
  const [question, setQuestion] = useState<AnalysisQuestion | null>(null); const [clarification, setClarification] = useState<AnalysisQuestionClarification | null>(null);
  const [plans, setPlans] = useState<AnalysisPlan[]>([]); const [planDialog, setPlanDialog] = useState<AnalysisPlan | null>(null); const plan = plans.at(-1) ?? null;
  const [run, setRun] = useState<SandboxRun | null>(null); const [history, setHistory] = useState<RunStatusHistory[]>([]); const [artifacts, setArtifacts] = useState<AnalysisArtifact[]>([]);
  const [code, setCode] = useState<AnalysisCode | null>(null);
  const [validation, setValidation] = useState<ResultValidation | null>(null); const [interpretation, setInterpretation] = useState<ResultInterpretation | null>(null); const [interpretationState, setInterpretationState] = useState<"idle" | "loading" | "unavailable">("idle"); const [citations, setCitations] = useState<AnalysisCitation[]>([]); const [bundle, setBundle] = useState<ReproducibilityBundle | null>(null);
  const [busy, setBusy] = useState(""); const [restoring, setRestoring] = useState(false); const pollingDelay = useRef(1000); const skipNextRestore = useRef(false);
  const compatibility = useMemo(() => handoff && profile ? resolveColumns(handoff.required_columns, profile) : null, [handoff, profile]);
  const datasetMismatch = Boolean(compatibility?.missing.length);

  const resetWorkflowState = useCallback(() => {
    setProfile(null); setQuestion(null); setClarification(null); setPlans([]); setPlanDialog(null); setRun(null); setCode(null);
    setHistory([]); setArtifacts([]); setValidation(null); setInterpretation(null); setInterpretationState("idle"); setCitations([]); setBundle(null);
  }, []);

  function bindWorkspace(value: Omit<AnalysisWorkspaceState, "schema_version">) {
    writeAnalysisWorkspace(session.project_id, session.session_id, { schema_version: "analysis_workspace.v1", ...value });
  }

  function selectDataset(value: Dataset) {
    if (dataset?.dataset_id === value.dataset_id) return;
    resetWorkflowState();
    setDataset(value);
    bindWorkspace({ dataset_id: value.dataset_id });
  }

  const refreshDatasets = useCallback(async () => {
    const items = (await client.listDatasets()).filter((item) => item.status !== "deleted");
    const workspace = readAnalysisWorkspace(session.project_id, session.session_id);
    setDatasets(items);
    setDataset((current) => {
      const currentDataset = current && items.find((item) => item.dataset_id === current.dataset_id);
      if (currentDataset) return currentDataset;
      if (workspace) return items.find((item) => item.dataset_id === workspace.dataset_id) ?? null;
      return items
        .filter((item) => Date.parse(item.created_at) >= Date.parse(session.created_at))
        .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0] ?? null;
    });
  }, [client, session.created_at, session.project_id, session.session_id]);
  useEffect(() => { void refreshDatasets().catch((cause) => notify(humanError(cause))); }, [refreshDatasets, notify]);
  useEffect(() => {
    let active = true;
    if (skipNextRestore.current) { skipNextRestore.current = false; return () => { active = false; }; }
    resetWorkflowState();
    setObjective(handoff?.predictor_columns.length ? "associate" : "describe"); setQuestionText(handoff?.research_question ?? session.initial_question ?? "");
    setOutcomes(handoff?.outcome_columns.join(", ") ?? ""); setPredictors(handoff?.predictor_columns.join(", ") ?? ""); setGroups(""); setMetrics(handoff?.preferred_metrics.join(", ") ?? "");
    if (!dataset) { setRestoring(false); return () => { active = false; }; }
    setRestoring(true);
    void (async () => {
      const [savedProfiles, savedQuestions, savedPlans] = await Promise.all([
        client.listDatasetProfiles(dataset.dataset_id),
        client.listAnalysisQuestions(dataset.dataset_id),
        client.listAnalysisPlans(dataset.dataset_id),
      ]);
      if (!active) return;
      const workspace = readAnalysisWorkspace(session.project_id, session.session_id);
      const workspaceMatchesDataset = workspace?.dataset_id === dataset.dataset_id;
      const scopedPlans = workspace
        ? workspaceMatchesDataset && workspace.plan_id
          ? savedPlans.filter((item) => item.plan_id === workspace.plan_id && (!workspace.plan_version || item.version === workspace.plan_version))
          : []
        : savedPlans.filter((item) => Date.parse(item.created_at) >= Date.parse(session.created_at));
      const latestPlan = scopedPlans.at(-1) ?? null;
      const restoredQuestion = workspace
        ? workspaceMatchesDataset && workspace.question_id
          ? savedQuestions.find((item) => item.question_id === workspace.question_id) ?? null
          : null
        : (latestPlan
          ? savedQuestions.find((item) => item.question_id === latestPlan.question_id)
          : savedQuestions.filter((item) => Date.parse(item.created_at) >= Date.parse(session.created_at)).at(-1)) ?? null;
      const restoredProfile = (latestPlan
        ? savedProfiles.find((item) => item.version === latestPlan.profile_version)
        : null) ?? savedProfiles.at(-1) ?? null;
      setProfile(restoredProfile); setPlans(scopedPlans);
      if (restoredQuestion) {
        setObjective(restoredQuestion.objective); setQuestionText(restoredQuestion.research_question);
        setOutcomes(restoredQuestion.outcome_columns.join(", ")); setPredictors(restoredQuestion.predictor_columns.join(", "));
        setGroups(restoredQuestion.group_columns.join(", ")); setMetrics(restoredQuestion.preferred_metrics.join(", "));
        if (restoredQuestion.status === "question_incomplete") {
          setClarification({ status: "question_incomplete", question_id: restoredQuestion.question_id, missing_fields: [], clarification_questions: ["Câu hỏi đã lưu vẫn thiếu thông tin. Bổ sung các trường còn thiếu rồi kiểm tra lại."] });
        } else setQuestion(restoredQuestion);
      } else if (handoff && restoredProfile) {
        const resolvedOutcomes = resolveColumns(handoff.outcome_columns, restoredProfile);
        const resolvedPredictors = resolveColumns(handoff.predictor_columns, restoredProfile);
        setOutcomes([...resolvedOutcomes.matched, ...resolvedOutcomes.missing].join(", ")); setPredictors([...resolvedPredictors.matched, ...resolvedPredictors.missing].join(", "));
      }
      let restoredRunId: string | undefined;
      if (latestPlan && (workspace?.run_id || !workspace)) {
        const savedRuns = await client.listRuns(latestPlan.plan_id, latestPlan.version);
        const latestRun = workspace?.run_id
          ? savedRuns.find((item) => item.run_id === workspace.run_id) ?? null
          : savedRuns.filter((item) => Date.parse(item.created_at) >= Date.parse(session.created_at)).at(-1) ?? null;
        if (active) setRun(latestRun);
        if (latestRun) {
          restoredRunId = latestRun.run_id;
          const restoredCode = await client.getRunCode(latestRun.run_id).catch(() => null);
          if (active) setCode(restoredCode);
        }
      }
      if (active && !workspace && (restoredQuestion || latestPlan)) {
        writeAnalysisWorkspace(session.project_id, session.session_id, {
          schema_version: "analysis_workspace.v1",
          dataset_id: dataset.dataset_id,
          question_id: restoredQuestion?.question_id,
          plan_id: latestPlan?.plan_id,
          plan_version: latestPlan?.version,
          run_id: restoredRunId,
        });
      }
    })().catch((cause) => { if (active) notify(humanError(cause)); }).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, [client, dataset?.dataset_id, handoff, notify, resetWorkflowState, session.initial_question, session.project_id, session.session_id]);

  const loadOutputs = useCallback(async (runId: string) => {
    const [historyResult, artifactResult, validationResult, citationResult] = await Promise.allSettled([client.getRunHistory(runId), client.getArtifacts(runId), client.getValidation(runId), client.getCitations(runId)]);
    if (historyResult.status === "fulfilled") setHistory(historyResult.value); if (artifactResult.status === "fulfilled") setArtifacts(artifactResult.value); if (validationResult.status === "fulfilled") setValidation(validationResult.value); if (citationResult.status === "fulfilled") setCitations(citationResult.value);
  }, [client]);

  useEffect(() => {
    if (!run || !capabilities.result_interpretation_enabled || validation?.status !== "validated" || interpretation) return;
    const runId = run.run_id;
    let cancelled = false;
    let timer: number | undefined;
    let wake: (() => void) | undefined;
    const delay = (milliseconds: number) => new Promise<void>((resolve) => {
      wake = resolve;
      timer = window.setTimeout(() => { wake = undefined; resolve(); }, milliseconds);
    });
    async function loadInterpretation() {
      setInterpretationState("loading");
      for (let attempt = 0; attempt <= INTERPRETATION_RETRY_DELAYS.length && !cancelled; attempt += 1) {
        try {
          const result = await client.getInterpretation(runId);
          const latestCitations = await client.getCitations(runId).catch(() => null);
          if (cancelled) return;
          setInterpretation(result);
          if (latestCitations) setCitations(latestCitations);
          setInterpretationState("idle");
          return;
        } catch (cause) {
          if (cancelled) return;
          const pending = cause instanceof SandboxApiError && cause.status === 404 && cause.detail.error_code === "RESULT_INTERPRETATION_NOT_FOUND";
          if (!pending || attempt === INTERPRETATION_RETRY_DELAYS.length) {
            setInterpretationState("unavailable");
            return;
          }
          await delay(INTERPRETATION_RETRY_DELAYS[attempt]);
        }
      }
    }
    void loadInterpretation();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      wake?.();
    };
  }, [capabilities.result_interpretation_enabled, client, interpretation, run?.run_id, validation?.status]);

  useEffect(() => {
    if (!run || TERMINAL_RUNS.has(run.status) || run.status === "result_review_waiting" || run.status === "completed_unvalidated") { if (run && SETTLED_EXECUTION.has(run.status)) void loadOutputs(run.run_id); return; }
    let cancelled = false; pollingDelay.current = 1000;
    async function poll() { if (!run) return; try { const value = await client.getRun(run.run_id); if (cancelled) return; setRun(value); const stateHistory = await client.getRunHistory(run.run_id); if (!cancelled) setHistory(stateHistory); if (!TERMINAL_RUNS.has(value.status) && value.status !== "result_review_waiting" && value.status !== "completed_unvalidated") { const delay = pollingDelay.current; pollingDelay.current = Math.min(5000, Math.round(delay * 1.6)); window.setTimeout(poll, delay); } else { await loadOutputs(value.run_id); } } catch (cause) { if (!cancelled) notify(humanError(cause)); } }
    const timer = window.setTimeout(poll, pollingDelay.current); return () => { cancelled = true; window.clearTimeout(timer); };
  }, [client, loadOutputs, notify, run?.run_id, run?.status]);

  async function work(key: string, action: () => Promise<void>) { setBusy(key); try { await action(); } catch (cause) { notify(humanError(cause)); } finally { setBusy(""); } }
  async function upload(file: File) { if (file.size > capabilities.max_dataset_bytes) { notify({ tone: "error", message: `File vượt giới hạn ${formatBytes(capabilities.max_dataset_bytes)}.` }); return; } const ext = file.name.split(".").pop()?.toLowerCase(); if (!ext || !capabilities.supported_dataset_formats.includes(ext as "csv" | "xlsx" | "parquet")) { notify({ tone: "error", message: "Định dạng này không được Sandbox cho phép." }); return; } await work("upload", async () => { const value = await client.uploadDataset(file); bindWorkspace({ dataset_id: value.dataset_id }); await refreshDatasets(); if (handoff) skipNextRestore.current = true; resetWorkflowState(); setDataset(value); if (handoff) { const generatedProfile = await client.profileDataset(value.dataset_id); setProfile(generatedProfile); const resolvedOutcomes = resolveColumns(handoff.outcome_columns, generatedProfile); const resolvedPredictors = resolveColumns(handoff.predictor_columns, generatedProfile); setOutcomes([...resolvedOutcomes.matched, ...resolvedOutcomes.missing].join(", ")); setPredictors([...resolvedPredictors.matched, ...resolvedPredictors.missing].join(", ")); } notify({ tone: "success", message: handoff ? "Dataset đã được profile và đối soát với giả thuyết." : "Dataset đã được kiểm tra và stage; raw rows không được gửi cho AI." }); }); }
  async function makeProfile() { if (!dataset) return; await work("profile", async () => { setProfile(await client.profileDataset(dataset.dataset_id)); }); }
  async function clarify() { if (!dataset || datasetMismatch) return; await work("question", async () => { const value = await client.createAnalysisQuestion(dataset.dataset_id, { objective, research_question: questionText, hypothesis: handoff?.hypothesis, outcome_columns: splitList(outcomes), predictor_columns: splitList(predictors), group_columns: splitList(groups), covariate_columns: [], preferred_metrics: splitList(metrics), output_language: lang }); if (value.status === "question_incomplete") { setClarification(value as AnalysisQuestionClarification); setQuestion(null); } else { const readyQuestion = value as AnalysisQuestion; setQuestion(readyQuestion); setClarification(null); bindWorkspace({ dataset_id: dataset.dataset_id, question_id: readyQuestion.question_id }); } }); }
  async function createPlan() { if (!dataset || !profile || !question || datasetMismatch) return; await work("plan", async () => { const created = await client.createAnalysisPlan(dataset.dataset_id, question.question_id, profile.version); const scoped = (await client.listAnalysisPlans(dataset.dataset_id)).filter((item) => item.plan_id === created.plan_id); setPlans(scoped); bindWorkspace({ dataset_id: dataset.dataset_id, question_id: question.question_id, plan_id: created.plan_id, plan_version: created.version }); }); }
  async function decidePlan(decision: "approved" | "rejected" | "changes_requested", comment: string) { if (!planDialog || !dataset) return; await work("review", async () => { if (planDialog.status === "draft") await client.reviewAnalysisPlan(planDialog.plan_id, planDialog.version, "in_review", "Bắt đầu review trên frontend"); await client.reviewAnalysisPlan(planDialog.plan_id, planDialog.version, decision, comment); setPlans((await client.listAnalysisPlans(dataset.dataset_id)).filter((item) => item.plan_id === planDialog.plan_id)); setPlanDialog(null); notify({ tone: "success", message: decision === "approved" ? "AnalysisPlan đã được phê duyệt." : "Đã ghi quyết định reviewer." }); }); }
  async function createRun() { if (!plan || !dataset || datasetMismatch) return; await work("run", async () => { setCode(null); setHistory([]); setArtifacts([]); setValidation(null); setInterpretation(null); setInterpretationState("idle"); setCitations([]); setBundle(null); pollingDelay.current = 1000; const queued = await client.createRun(plan.plan_id, plan.version); const value = await client.getRun(queued.resource_id); bindWorkspace({ dataset_id: dataset.dataset_id, question_id: question?.question_id, plan_id: plan.plan_id, plan_version: plan.version, run_id: value.run_id }); setRun(value); const [runHistory, generatedCode] = await Promise.all([client.getRunHistory(value.run_id), client.getRunCode(value.run_id)]); setHistory(runHistory); setCode(generatedCode); notify({ tone: "success", message: "Đã tạo run mới. Mã Python bên dưới là phiên bản thực tế được gửi vào Docker Sandbox." }); }); }
  async function retryInterpretation() { if (!run) return; setInterpretationState("loading"); await work("interpretation", async () => { try { const result = await client.generateInterpretation(run.run_id); const latestCitations = await client.getCitations(run.run_id); setInterpretation(result); setCitations(latestCitations); setInterpretationState("idle"); } catch (cause) { setInterpretationState("unavailable"); throw cause; } }); }
  async function reviewResult(decision: "approved" | "rejected") { if (!run) return; await work("result-review", async () => { await client.reviewResult(run.run_id, decision); const value = await client.getRun(run.run_id); setRun(value); if (decision === "approved") setBundle(await client.getReproducibilityBundle(run.run_id)); }); }
  async function downloadBundle() { if (!run) return; const value = bundle ?? await client.getReproducibilityBundle(run.run_id); setBundle(value); const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `reproducibility-${run.run_id}.json`; anchor.click(); URL.revokeObjectURL(url); }

  return <div className="sandbox-analysis-layout">
    <aside className="sandbox-dataset-rail"><h2>Dataset</h2><p className="sandbox-dataset-scope">Dataset dùng chung trong project; tiến trình phân tích và kết quả được tách theo từng session.</p><label className={`sandbox-upload ${busy === "upload" ? "busy" : ""}`}><input type="file" accept=".csv,.parquet" disabled={Boolean(busy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); event.currentTarget.value = ""; }}/><Icon name="upload" size={22}/><strong>{busy === "upload" ? "Đang kiểm tra…" : "Tải CSV / Parquet"}</strong><span>Tối đa {formatBytes(capabilities.max_dataset_bytes)} · non-sensitive</span></label><div className="sandbox-dataset-list">{datasets.map((item) => <button key={item.dataset_id} className={dataset?.dataset_id === item.dataset_id ? "active" : ""} onClick={() => selectDataset(item)}><strong>{item.filename}</strong><span>{formatBytes(item.size_bytes)} · <StatusTag value={item.status}/></span></button>)}</div>{dataset && <button className="sandbox-button subtle" onClick={() => void work("delete", async () => { await client.deleteDataset(dataset.dataset_id); writeBrowserSetting(analysisWorkspaceStorageKey(session.project_id, session.session_id), null); resetWorkflowState(); setDataset(null); await refreshDatasets(); })}>Thu hồi quyền truy cập</button>}</aside>
    <main className="sandbox-analysis-main">
      {handoff && <section className="sandbox-handoff-context" aria-labelledby="handoff-title"><Icon name="flask" size={22}/><div><strong id="handoff-title">{s("handoffContextTitle")}</strong><p>{handoff.research_question}</p><small>{s("handoffVariables", { columns: handoff.required_columns.join(", ") || s("undefined") })}</small></div></section>}
      {!dataset ? <EmptyState title="Bắt đầu bằng dữ liệu đã phân loại">Chọn một file CSV hoặc Parquet không nhạy cảm. Validator kiểm tra loại file trước khi lưu.</EmptyState> : <>
        <nav className="sandbox-analysis-steps" aria-label={s("analysisProgress")}><span className="done"><b>1</b>{s("dataset")}</span><span className={profile ? "done" : "active"}><b>2</b>Profile</span><span className={question ? "done" : profile ? "active" : ""}><b>3</b>{s("question")}</span><span className={plan?.status === "approved" ? "done" : question ? "active" : ""}><b>4</b>{s("planReview")}</span><span className={run ? "active" : ""}><b>5</b>{s("runResults")}</span></nav>
        {restoring ? <section className="sandbox-analysis-section sandbox-restoring" aria-live="polite"><div><h1>{s("restoringProgress")}</h1><p>{s("restoringProgressBody")}</p></div></section> : !profile ? <section className="sandbox-analysis-section profile-start"><div><h1>{dataset.filename}</h1><p>Hash nội dung {dataset.content_hash.slice(0, 16)} · {formatBytes(dataset.size_bytes)}</p></div><button className="sandbox-button primary" disabled={Boolean(busy)} onClick={() => void makeProfile()}><Icon name="data"/>{busy === "profile" ? s("profiling") : s("deterministicProfile")}</button></section> : <>
          <ProfileView profile={profile}/>
          {handoff && compatibility && (datasetMismatch ? <div className="sandbox-dataset-mismatch" role="alert"><strong>{s("mismatchCode")}</strong><p>{s("mismatchBody", { columns: compatibility.missing.join(", ") })}</p><small>{s("mismatchHelp")}</small></div> : <div className="sandbox-dataset-match" role="status"><Icon name="check"/><span><strong>{s("datasetMatch")}</strong><small>{s("datasetMatchColumns", { columns: compatibility.matched.join(", ") })}</small></span></div>)}
          <section className="sandbox-question-builder"><header><h2>{s("clarifyQuestion")}</h2><p>{s("clarifyBody")}</p></header><div className="sandbox-form-grid"><label>{s("objective")}<select value={objective} onChange={(event) => setObjective(event.target.value as AnalysisObjective)}><option value="describe">{s("describe")}</option><option value="compare">{s("compare")}</option><option value="associate">{s("associate")}</option><option value="predict">{s("predict")}</option></select></label><label className="wide">{s("researchQuestion")}<textarea rows={3} value={questionText} onChange={(event) => setQuestionText(event.target.value)} required/></label><label>{s("outcomeColumns")}<input value={outcomes} onChange={(event) => setOutcomes(event.target.value)} placeholder="outcome_a, outcome_b"/></label><label>{s("predictorColumns")}<input value={predictors} onChange={(event) => setPredictors(event.target.value)} placeholder="age, treatment"/></label><label>{s("groupColumns")}<input value={groups} onChange={(event) => setGroups(event.target.value)} placeholder="cohort"/></label><label>{s("preferredMetrics")}<input value={metrics} onChange={(event) => setMetrics(event.target.value)} placeholder="mean, rmse"/></label></div><button className="sandbox-button" disabled={Boolean(busy) || !questionText.trim() || datasetMismatch} onClick={() => void clarify()}>{busy === "question" ? s("checking") : s("checkCompleteness")}</button>{clarification && <div className="sandbox-clarification"><strong>{s("clarificationRequired")}</strong><ul>{clarification.clarification_questions.map((item) => <li key={item}>{item}</li>)}</ul></div>}{question && <p className="sandbox-proof"><Icon name="check"/>{s("questionReadyProof", { version: question.version })}</p>}</section>
          {(question || plan) && <section className="sandbox-plan-section"><header><div><span className="sandbox-stage-index">1</span><div><h2>{s("analysisPlanTitle")}</h2><p>{s("analysisPlanPromptProof")}</p></div></div>{!plan && question && <button className="sandbox-button primary" disabled={Boolean(busy) || !capabilities.ai_enabled || datasetMismatch} onClick={() => void createPlan()}>{busy === "plan" ? s("generatingPlan") : s("generatePlan")}</button>}</header>{plan && <article className="sandbox-plan-sheet"><div><h3>{plan.method}</h3><StatusTag value={plan.status}/></div><p>{plan.method_rationale}</p><dl><div><dt>{s("preprocessing")}</dt><dd>{plan.preprocessing_steps.join("; ")}</dd></div><div><dt>{s("assumptionChecks")}</dt><dd>{plan.assumption_checks.join("; ")}</dd></div><div><dt>{s("planMetrics")}</dt><dd>{plan.evaluation_metrics.join(", ")}</dd></div></dl><footer><code>hash {plan.plan_hash.slice(0, 16)}</code>{plan.status !== "approved" && <button className="sandbox-button primary" onClick={() => setPlanDialog(plan)}>{s("openPlanReview")}</button>}{plan.status === "approved" && !run && <button className="sandbox-button primary" disabled={Boolean(busy) || datasetMismatch} onClick={() => void createRun()}><Icon name="play"/>{busy === "run" ? s("creatingRun") : s("createRun")}</button>}</footer></article>}</section>}
          {run && code && <GeneratedPythonCode code={code} run={run} notify={notify}/>}
          {run && <section className="sandbox-run-section"><header><div><span className="sandbox-stage-index">3</span><div><h2>{s("dockerStatusTitle")}</h2><p>Polling thích ứng {pollingDelay.current / 1000}s · tối đa 5s · tự dừng khi terminal.</p></div></div><StatusTag value={run.status}/></header><ol className="sandbox-timeline">{history.map((item) => <li key={item.history_id}><i></i><div><strong><StatusTag value={item.to_status}/></strong><span>{dateTime(item.created_at, locale)} · {item.reason || "State transition đã ghi nhận"}</span></div></li>)}</ol>{["queued", "running"].includes(run.status) && <button className="sandbox-button" disabled={Boolean(busy)} onClick={() => void work("cancel", async () => setRun(await client.cancelRun(run.run_id)))}><Icon name="stop"/>{s("cancelRun")}</button>}{RETRYABLE_RUNS.has(run.status) && <div className="sandbox-run-recovery" role="status"><div><strong>Run này đã dừng{run.error_code ? ` · ${run.error_code}` : ""}</strong><p>Bạn có thể tạo một run mới từ AnalysisPlan đã duyệt. Run thất bại này vẫn được giữ lại để truy vết.</p></div><button className="sandbox-button primary" disabled={Boolean(busy) || datasetMismatch} onClick={() => void createRun()}><Icon name="play"/>{busy === "run" ? s("creatingRun") : s("createNewRun")}</button></div>}</section>}
          {run && SETTLED_EXECUTION.has(run.status) && <section className="sandbox-output-stage"><header><span className="sandbox-stage-index">4</span><div><h2>{s("outputsTitle")}</h2><p>{s("outputsBody")}</p></div></header>{validation && <div className={`sandbox-validation ${validation.status}`}><strong>{validation.status === "validated" ? s("validationPassed") : s("validationBlocked")}</strong>{validation.errors.map((item) => <p key={item}>{item}</p>)}{validation.warnings.map((item) => <p key={item}>{s("warning", { message: item })}</p>)}</div>}{interpretation && <InterpretationView interpretation={interpretation} citations={citations}/>} {!interpretation && interpretationState !== "idle" && <div className={`sandbox-interpretation sandbox-interpretation-${interpretationState}`} role="status"><h3>{s("interpretation")}</h3><p>{interpretationState === "loading" ? s("interpretationLoading") : s("interpretationUnavailable")}</p>{interpretationState === "unavailable" && <button className="sandbox-button subtle" type="button" disabled={busy === "interpretation"} onClick={() => void retryInterpretation()}>{s("retryInterpretation")}</button>}</div>}<ArtifactGallery client={client} artifacts={artifacts} citations={citations}/>{run.status === "result_review_waiting" && <div className="sandbox-result-review"><div><h3>{s("resultDecision")}</h3><p>{s("resultDecisionBody")}</p></div><button className="sandbox-button" disabled={Boolean(busy)} onClick={() => void reviewResult("rejected")}>{s("reject")}</button><button className="sandbox-button primary" disabled={Boolean(busy)} onClick={() => void reviewResult("approved")}><Icon name="check"/>{s("approve")}</button></div>}{run.status === "approved" && <div className="sandbox-bundle"><div><Icon name="shield" size={24}/><span><strong>{s("bundleSealed")}</strong><small>{bundle ? `bundle hash ${bundle.bundle_hash.slice(0, 18)}` : "Tải gói để kiểm tra toàn bộ lineage hash"}</small></span></div><button className="sandbox-button primary" onClick={() => void downloadBundle()}><Icon name="download"/>{s("downloadBundle")}</button></div>}</section>}
        </>}
      </>}
    </main>
    {planDialog && <PlanDialog plan={planDialog} busy={busy === "review"} onClose={() => setPlanDialog(null)} onDecision={(decision, comment) => void decidePlan(decision, comment)}/>} 
  </div>;
}

export default function SandboxPage() {
  const params = useParams<{ id: string }>(); const projectId = params.id;
  const search = useSearchParams();
  const { locale, s } = useSandboxI18n();
  const { getToken, isLoaded, isSignedIn } = useAuth(); const { user } = useUser();
  const [capabilities, setCapabilities] = useState<SandboxCapabilities | null>(null); const [mode, setMode] = useState<SandboxMode>("hypothesis"); const [sessions, setSessions] = useState<SandboxSession[]>([]); const [selectedSessionIds, setSelectedSessionIds] = useState<Partial<Record<SandboxMode, string | null>>>({}); const [notice, setNotice] = useState<Notice | null>(null); const [loading, setLoading] = useState(true); const [discardingSessionId, setDiscardingSessionId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string | null>(null);
  const tokenProvider = useCallback(async (refresh = false) => { let token = await getToken(refresh ? { skipCache: true } : undefined); for (let attempt = 0; !token && attempt < 12; attempt += 1) { await new Promise((resolve) => window.setTimeout(resolve, 150)); token = await getToken({ skipCache: true }); } return token; }, [getToken]);
  const client = useMemo(() => new SandboxClient(projectId, tokenProvider), [projectId, tokenProvider]);
  const notify = useCallback((value: Notice) => setNotice(value), []);
  const requestedMode = SANDBOX_MODES.find((value) => value === search.get("mode"));
  const requestedSessionId = search.get("session");
  const requestedEntrypoint = (["manual", "graphrag_answer", "validated_candidate", "experiment_proposal"] as const).find((value) => value === search.get("entrypoint"));
  const contextInput = useMemo<Partial<OpenSandboxSessionInput>>(() => ({
    entrypoint: requestedEntrypoint ?? "manual",
    source_resource_id: search.get("source_resource_id") || undefined,
    source_parent_id: search.get("source_parent_id") || undefined,
    title: search.get("title") || undefined,
    initial_question: search.get("initial_question") || undefined,
  }), [requestedEntrypoint, search]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) { setProjectName(null); return; }
    let active = true;
    void tokenProvider().then(async (token) => {
      if (!token) return null;
      const response = await fetch(`${API}/projects`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (!response.ok) return null;
      const body = await response.json().catch(() => ({})) as { items?: ProjectBreadcrumb[] };
      return body.items?.find((project) => project.project_id === projectId)?.name ?? null;
    }).then((name) => { if (active) setProjectName(name); }).catch(() => { if (active) setProjectName(null); });
    return () => { active = false; };
  }, [isLoaded, isSignedIn, projectId, tokenProvider]);

  useEffect(() => { if (!isLoaded || !isSignedIn) return; let active = true; setLoading(true); void Promise.all([client.capabilities(), client.listSessions().catch(() => [])]).then(([caps, items]) => { if (!active) return; setCapabilities(caps); setSessions(items); const storedMode = readBrowserSetting(`research-sandbox:${projectId}:mode`) as SandboxMode | null; const first = requestedMode && caps.modes[requestedMode] ? requestedMode : storedMode && SANDBOX_MODES.includes(storedMode) && caps.modes[storedMode] ? storedMode : SANDBOX_MODES.find((item) => caps.modes[item]); if (first) setMode(first); const contextualLaunch = Boolean(!requestedSessionId && requestedMode && requestedEntrypoint && requestedEntrypoint !== "manual" && contextInput.source_resource_id); const selections: Partial<Record<SandboxMode, string | null>> = {}; SANDBOX_MODES.forEach((candidateMode) => { const available = items.filter((item) => item.mode === candidateMode && item.status !== "discarded").sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at)); const requestedSession = requestedSessionId ? available.find((item) => item.session_id === requestedSessionId) : undefined; const storedId = readBrowserSetting(`research-sandbox:${projectId}:session:${candidateMode}`); const storedSession = storedId ? available.find((item) => item.session_id === storedId) : undefined; const mustCreateFromContext = contextualLaunch && candidateMode === requestedMode; const preferred = mustCreateFromContext ? undefined : requestedSession ?? storedSession ?? available.find((item) => item.status !== "completed") ?? available[0]; selections[candidateMode] = preferred?.session_id ?? null; if (mustCreateFromContext) writeBrowserSetting(`research-sandbox:${projectId}:session:${candidateMode}`, null); }); setSelectedSessionIds(selections); if (first) syncUrl(first, selections[first] ?? null); }).catch((cause) => { if (!active) return; if (cause instanceof SandboxApiError && ["SANDBOX_FEATURE_DISABLED", "SANDBOX_DISABLED"].includes(cause.detail.error_code)) setCapabilities({ schema_version: "sandbox_capabilities.v1", enabled: false, available: false, demo_mode: false, reason: "disabled", modes: { hypothesis: false, data_analysis: false }, ai_enabled: false, graph_context_enabled: false, result_interpretation_enabled: false, supported_dataset_formats: ["csv", "parquet"], max_dataset_bytes: 50 * 1024 * 1024, run_polling_supported: true }); else setNotice(humanError(cause)); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [client, isLoaded, isSignedIn, projectId]);
  const selectedSessionId = selectedSessionIds[mode] ?? null;
  const session = selectedSessionId ? sessions.find((item) => item.mode === mode && item.session_id === selectedSessionId) ?? null : null;
  const analysisHandoff = useMemo(() => session?.mode === "data_analysis" ? readAnalysisHandoff(projectId, session.session_id) : null, [projectId, session]);
  function syncUrl(nextMode: SandboxMode, sessionId: string | null) { const query = new URLSearchParams(window.location.search); query.set("mode", nextMode); if (sessionId) query.set("session", sessionId); else query.delete("session"); window.history.replaceState(window.history.state, "", `${window.location.pathname}?${query.toString()}${window.location.hash}`); }
  function selectMode(value: SandboxMode) { setMode(value); writeBrowserSetting(`research-sandbox:${projectId}:mode`, value); syncUrl(value, selectedSessionIds[value] ?? null); }
  function selectSession(sessionId: string) { setSelectedSessionIds((value) => ({ ...value, [mode]: sessionId })); writeBrowserSetting(`research-sandbox:${projectId}:session:${mode}`, sessionId); syncUrl(mode, sessionId); }
  function startNewSession() { setSelectedSessionIds((value) => ({ ...value, [mode]: null })); writeBrowserSetting(`research-sandbox:${projectId}:session:${mode}`, null); syncUrl(mode, null); }
  function storeSession(value: SandboxSession) { setSessions((items) => [...items.filter((item) => item.session_id !== value.session_id), value]); setSelectedSessionIds((items) => ({ ...items, [value.mode]: value.session_id })); writeBrowserSetting(`research-sandbox:${projectId}:session:${value.mode}`, value.session_id); syncUrl(value.mode, value.session_id); }
  async function discardSession(value: SandboxSession) {
    if (!window.confirm(s("deleteSessionConfirm", { title: value.title }))) return;
    setDiscardingSessionId(value.session_id);
    try {
      await client.discardSession(value.session_id);
      const remaining = sessions.filter((item) => item.session_id !== value.session_id && item.mode === value.mode && item.status !== "discarded").sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at));
      const nextId = remaining.find((item) => item.status !== "completed")?.session_id ?? remaining[0]?.session_id ?? null;
      setSessions((items) => items.filter((item) => item.session_id !== value.session_id));
      setSelectedSessionIds((items) => ({ ...items, [value.mode]: nextId }));
      writeBrowserSetting(`research-sandbox:${projectId}:session:${value.mode}`, nextId);
      if (mode === value.mode) syncUrl(value.mode, nextId);
      notify({ tone: "success", message: s("deleteSessionDone") });
    } catch (cause) { notify(humanError(cause)); } finally { setDiscardingSessionId(null); }
  }
  async function transferToAnalysis(handoff: HypothesisAnalysisHandoff) {
    try {
      const value = await client.openSession({ mode: "data_analysis", entrypoint: "manual", title: `Phân tích · ${handoff.hypothesis.slice(0, 96)}`, initial_question: handoff.research_question });
      writeBrowserSetting(handoffStorageKey(projectId, value.session_id), JSON.stringify(handoff));
      setMode("data_analysis"); writeBrowserSetting(`research-sandbox:${projectId}:mode`, "data_analysis"); storeSession(value);
      notify({ tone: "success", message: "Đã mở session phân tích mới và điền mục tiêu từ giả thuyết." });
    } catch (cause) { notify(humanError(cause)); }
  }
  function moveModeFocus(event: KeyboardEvent<HTMLButtonElement>, current: SandboxMode) { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !capabilities) return; const available = SANDBOX_MODES.filter((item) => capabilities.modes[item]); const index = available.indexOf(current); const target = event.key === "Home" ? available[0] : event.key === "End" ? available.at(-1) : available[(index + (event.key === "ArrowRight" ? 1 : -1) + available.length) % available.length]; if (!target) return; event.preventDefault(); selectMode(target); window.requestAnimationFrame(() => document.getElementById(`sandbox-tab-${target}`)?.focus()); }

  if (!isLoaded || loading) return <main className="mock-loading">{s("loading")}</main>;
  if (!isSignedIn) return <main className="mock-loading"><p>{s("authRequired")}</p><Link className="btn-primary" href="/auth">{s("signIn")}</Link></main>;
  if (!capabilities?.enabled) return <div className="v2-shell"><header className="v2-header"><Link className="v2-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{s("desk")}</small></span></Link><div className="v2-header-end"><LanguageToggle/><UserButton/></div></header><main className="sandbox-disabled"><Icon name="shield" size={34}/><h1>{s("disabledTitle")}</h1><p>{s("disabledBody")}</p><Link className="sandbox-button primary" href={`/workspace?project=${projectId}`}>{s("backWorkspace")}</Link></main></div>;
  if (!capabilities.available) return <div className="v2-shell"><header className="v2-header"><Link className="v2-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{s("desk")}</small></span></Link><div className="v2-header-end"><LanguageToggle/><UserButton/></div></header><main className="sandbox-disabled"><Icon name="shield" size={34}/><h1>{s("unavailableTitle")}</h1><p>{s("unavailableBody")}</p><Link className="sandbox-button primary" href={`/workspace?project=${projectId}`}>{s("backWorkspace")}</Link></main></div>;

  const modeInfo: Array<{ id: SandboxMode; label: string; description: string; icon: "flask" | "data" }> = [
    { id: "hypothesis", label: s("hypothesis"), description: s("hypothesisDesc"), icon: "flask" },
    { id: "data_analysis", label: s("analysis"), description: s("analysisDesc"), icon: "data" },
  ];
  const projectBreadcrumb = projectName ?? `Project ${projectId.slice(0, 8)}`;

  return <div className="v2-shell sandbox-shell">
    <span hidden dangerouslySetInnerHTML={{ __html: "<!-- THESIS: Sandbox là sổ thực nghiệm có reviewer gate, không phải dashboard thẻ. OWN-WORLD: giấy ấm, mực xanh đen, rule mảnh, coral cho hành động có chủ đích; kế thừa LitReview. STORY: phát triển giả thuyết thành một phân tích dữ liệu có lineage. FIRST VIEWPORT: header sản phẩm, hai tab như mục sổ, trạng thái session và workpaper chiếm phần còn lại; hành động chính nằm trong đúng bước. FORM: experiment ledger workbench, grounded candidate 3, seed e8cd1db8. FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and docs/design/DESIGN.md -->" }}/>
    <header className="v2-header"><Link className="v2-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{s("desk")}</small></span></Link><nav className="v2-nav" aria-label="Breadcrumb"><Link href="/dashboard">{s("projects")}</Link><span className="sandbox-crumb"><Icon name="chevron" size={13}/></span><Link href={`/workspace?project=${projectId}`}>{projectBreadcrumb}</Link><span className="sandbox-crumb"><Icon name="chevron" size={13}/></span><span className="sandbox-current-crumb" aria-current="page">Sandbox</span></nav><div className="v2-header-end"><LanguageToggle/><span className="v2-user">{initials(user?.fullName)}</span><UserButton/></div></header>
    <header className="sandbox-titlebar"><div><h1>{s("title")}</h1><p>{s("subtitle")}</p></div><div className="sandbox-trust"><Icon name="shield"/><span><strong>{s("projectScoped")}{capabilities.demo_mode ? ` · ${s("demoLocal")}` : ""}</strong><small>{capabilities.project_role ?? "member"} · {capabilities.ai_enabled ? s("aiOn") : s("aiOff")}</small></span></div></header>
    <nav className="sandbox-mode-tabs" role="tablist" aria-label={s("modeLabel")}>{modeInfo.filter((item) => capabilities.modes[item.id]).map((item) => { const modeSessions = sessions.filter((value) => value.mode === item.id); const openCount = modeSessions.filter((value) => !["discarded", "completed"].includes(value.status)).length; return <button type="button" id={`sandbox-tab-${item.id}`} aria-controls="sandbox-active-panel" data-testid={`sandbox-mode-${item.id}`} key={item.id} role="tab" aria-label={`${item.label} · ${modeSessions.length} sessions`} aria-selected={mode === item.id} tabIndex={mode === item.id ? 0 : -1} className={mode === item.id ? "active" : ""} onKeyDown={(event) => moveModeFocus(event, item.id)} onClick={() => selectMode(item.id)}><Icon name={item.icon}/><span><strong>{item.label}</strong><small>{item.description}</small></span><em title={`${openCount} open sessions`}>{modeSessions.length}</em></button>; })}</nav>
    {notice && <div className={`sandbox-notice ${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"} aria-live="polite"><span>{notice.message}{notice.correlationId && <small>Correlation ID: {notice.correlationId}</small>}</span><button type="button" className="sandbox-notice-close" onClick={() => setNotice(null)} aria-label={s("closeNotice")}><Icon name="close"/></button></div>}
    <SessionNavigator mode={mode} sessions={sessions} selectedId={selectedSessionId} onSelect={selectSession} onNew={startNewSession} onDiscard={discardSession} discarding={discardingSessionId === selectedSessionId}/>
    <main id="sandbox-active-panel" className="sandbox-surface" role="tabpanel" aria-labelledby={`sandbox-tab-${mode}`}>{!session ? <SessionGate key={`${mode}:${contextInput.title ?? ""}:${contextInput.initial_question ?? ""}`} mode={mode} client={client} contextInput={contextInput} onSession={storeSession} notify={notify}/> : <><div className="sandbox-session-strip"><span><b>{session.title}</b><StatusTag value={session.status}/></span><code>{session.context_hash ? `context ${session.context_hash.slice(0, 12)}` : `session ${session.session_id.slice(0, 12)}`}</code><small>{s("updated", { date: dateTime(session.updated_at, locale) })}</small></div>{mode === "hypothesis" && <HypothesisPanel key={session.session_id} client={client} session={session} capabilities={capabilities} notify={notify} onTransfer={transferToAnalysis}/>} {mode === "data_analysis" && <DataAnalysisPanel key={session.session_id} client={client} session={session} capabilities={capabilities} notify={notify} handoff={analysisHandoff}/>}</>}</main>
  </div>;
}
