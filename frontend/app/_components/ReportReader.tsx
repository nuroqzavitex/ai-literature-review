"use client";

import Link from "next/link";
import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import { FormEvent, useCallback, useEffect, useState } from "react";
import LanguageToggle from "./LanguageToggle";
import { useLanguage } from "./language-context";
import { authenticatedJson } from "../_lib/authenticated-fetch";
import type {
  ActionProposal,
  Claim,
  Citation,
  Conversation,
  Gap,
  JobTrace,
  Json,
  Memory,
  Message,
  Reference,
  Report,
  ReviewResult,
  Version,
} from "./workspace-types";

function initials(name?: string | null) {
  return (name ?? "LR")
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function sourceLink(url: unknown, paperId?: string) {
  if (typeof url === "string") {
    try {
      const parsed = new URL(url.trim());
      if (parsed.protocol === "https:") return parsed.href;
    } catch {
      // Use the permanent OpenAlex record when older data has a bad URL.
    }
  }
  return paperId && /^W\d+$/.test(paperId) ? `https://openalex.org/${paperId}` : null;
}

function ArticleText({ text, sources }: { text: string; sources: Reference[] }) {
  return (
    <>
      {text.split(/(\[\[[A-Za-z0-9_.:-]+\]\])/g).map((part, index) => {
        const match = /^\[\[([A-Za-z0-9_.:-]+)\]\]$/.exec(part);
        if (!match) return <span key={index}>{part}</span>;
        const paperId = match[1];
        const source = sources.find((item) => item.paper_id === paperId);
        const referenceNumber = sources.findIndex((item) => item.paper_id === paperId) + 1;
        const url = sourceLink(source?.url, paperId);
        const label = referenceNumber > 0 ? `[${referenceNumber}]` : `[${paperId}]`;
        return url ? <a key={index} href={url} target="_blank" rel="noreferrer" className="article-citation">{label}</a> : <span key={index} className="article-citation">{label}</span>;
      })}
    </>
  );
}
function normalizeMessage(value: unknown): Message | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (
    typeof item.message_id !== "string" ||
    (item.role !== "user" && item.role !== "assistant") ||
    typeof item.text !== "string"
  )
    return null;
  return {
    message_id: item.message_id,
    role: item.role,
    message_type: typeof item.message_type === "string" ? item.message_type : "message",
    text: item.text,
    citations: Array.isArray(item.citations)
      ? (item.citations as unknown[])
          .map((c): Citation | null => {
            if (!c || typeof c !== "object") return null;
            const ci = c as Record<string, unknown>;
            if (typeof ci.quote !== "string") return null;
            return {
              citation_id: typeof ci.citation_id === "string" ? ci.citation_id : undefined,
              paper_id: typeof ci.paper_id === "string" ? ci.paper_id : undefined,
              quote: ci.quote,
              source_url: typeof ci.source_url === "string" ? ci.source_url : undefined,
            };
          })
          .filter((c): c is Citation => c !== null)
      : [],
    context_artifact_ids: Array.isArray(item.context_artifact_ids)
      ? item.context_artifact_ids.filter((id): id is string => typeof id === "string")
      : [],
  };
}

type ReportTab = "conclusion" | "matrix" | "claims" | "refs";
type RightTab = "copilot" | "review" | "gaps" | "memory" | "trace";

function memoryText(content: Json, empty: string) {
  const values = Object.values(content).filter((value): value is string | number | boolean =>
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
  );
  if (values.length) return values.join(" · ");
  const serialized = JSON.stringify(content);
  return serialized === "{}" ? empty : serialized;
}

function gapLabel(status: string, t: ReturnType<typeof useLanguage>["t"]) {
  return (
    {
      candidate: t("report_reader.needs_check"),
      pending_review: t("common.pending"),
      supported_in_searched_corpus: t("report_reader.supported"),
      partially_supported: t("report_reader.more_evidence"),
      contradicted: t("report_reader.counterevidence", undefined, { count: 1 }),
      reviewer_approved: t("report_reader.approved"),
      reviewer_narrowed: t("report_reader.narrow_gap"),
      reviewer_rejected: t("report_reader.reject"),
      insufficient_coverage: t("report_reader.more_evidence"),
      insufficient_evidence: t("report_reader.more_evidence"),
    } as Record<string, string>
  )[status] ?? status;
}

// ── Evidence Matrix ──────────────────────────────────────────────────────────
function EvidenceMatrix({ claims, sources, t }: { claims: Claim[]; sources: Reference[]; t: ReturnType<typeof useLanguage>["t"] }) {
  if (!claims?.length)
    return <p className="source-empty" style={{ padding: "20px 0" }}>{t("report_reader.claims_empty")}</p>;
  return (
    <div style={{ overflowX: "auto", marginTop: "16px" }}>
      <table className="ev-matrix" style={{ width: "100%", borderCollapse: "collapse", fontSize: "12.5px", border: "1px solid var(--rule)" }}>
        <thead>
          <tr style={{ background: "var(--ink)", color: "#f5efe5" }}>
            <th style={{ padding: "10px 12px", textAlign: "left", fontFamily: "'IBM Plex Mono',monospace", fontSize: "10px", fontWeight: 500 }}>{t("synthesis.claim")}</th>
            <th style={{ padding: "10px 12px", textAlign: "left", fontFamily: "'IBM Plex Mono',monospace", fontSize: "10px", fontWeight: 500 }}>{t("report_reader.sources")}</th>
            <th style={{ padding: "10px 12px", textAlign: "left", fontFamily: "'IBM Plex Mono',monospace", fontSize: "10px", fontWeight: 500 }}>{t("report_reader.evidence")}</th>
            <th style={{ padding: "10px 12px", textAlign: "left", fontFamily: "'IBM Plex Mono',monospace", fontSize: "10px", fontWeight: 500 }}>{t("common.review")}</th>
          </tr>
        </thead>
        <tbody>
          {claims.flatMap((claim) =>
            claim.evidence.length
              ? claim.evidence.map((ev, i) => {
                  const src = sources?.find((s) => s.paper_id === ev.paper_id);
                  const fullText = ev.source_level === "full_text";
                  const sourceUrl = sourceLink(src?.url, ev.paper_id);
                  const verdict = claim.evidence_verdict ?? (fullText ? "supported" : "uncertain");
                  const verdictStyle = verdict === "supported"
                    ? { background: "var(--green-soft)", color: "#15803d", label: t("report_reader.supported") }
                    : verdict === "partial"
                      ? { background: "#fef3c7", color: "#92400e", label: "PARTIAL" }
                      : verdict === "unsupported"
                        ? { background: "#fee2e2", color: "#b91c1c", label: "UNSUPPORTED" }
                        : { background: "#fef3c7", color: "#92400e", label: "REVIEW REQUIRED" };
                  return (
                    <tr key={`${claim.claim_id}-${i}`} style={{ borderBottom: "1px solid var(--rule)" }}>
                      {i === 0 && (
                        <td rowSpan={claim.evidence.length} style={{ padding: "10px 12px", verticalAlign: "top", color: "var(--g700)", lineHeight: 1.5, fontFamily: "'Source Serif 4',serif", maxWidth: "220px" }}>
                          {claim.text}
                        </td>
                      )}
                      <td style={{ padding: "10px 12px", verticalAlign: "top" }}>
                        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer" style={{ display: "block", fontWeight: 600, color: "var(--g800)", marginBottom: "3px", fontSize: "12px" }}>{src?.title ?? ev.paper_id}</a> : <div style={{ fontWeight: 600, color: "var(--g800)", marginBottom: "3px", fontSize: "12px" }}>{src?.title ?? ev.paper_id}</div>}
                        {src?.authors && (
                          <div style={{ fontSize: "10.5px", color: "var(--g500)", fontFamily: "'IBM Plex Mono',monospace" }}>
                            {src.authors.slice(0, 2).join(", ")}{src.year ? ` · ${src.year}` : ""}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "10px 12px", color: "var(--g600)", fontStyle: "italic", lineHeight: 1.5, verticalAlign: "top", fontSize: "11.5px" }}>
                        <span style={{ display: "block", marginBottom: "5px", color: fullText ? "#166534" : "#92400e", fontFamily: "'IBM Plex Mono',monospace", fontSize: "9.5px", fontStyle: "normal", fontWeight: 700, letterSpacing: ".03em" }}>
                          {fullText ? "FULL TEXT PASSAGE" : "ABSTRACT-ONLY FALLBACK"}{ev.document_id ? ` · ${ev.document_id}` : ""}
                        </span>
                        {ev.quote}
                      </td>
                      <td style={{ padding: "10px 12px", verticalAlign: "top" }}>
                        <span style={{ display: "inline-block", padding: "3px 7px", background: verdictStyle.background, color: verdictStyle.color, fontSize: "10.5px", fontWeight: 700, fontFamily: "'IBM Plex Mono',monospace" }}>
                          {verdictStyle.label}
                        </span>
                      </td>
                    </tr>
                  );
                })
              : [
                  <tr key={claim.claim_id} style={{ borderBottom: "1px solid var(--rule)" }}>
                    <td style={{ padding: "10px 12px", color: "var(--g700)", fontFamily: "'Source Serif 4',serif" }}>{claim.text}</td>
                    <td colSpan={3} style={{ padding: "10px 12px", color: "var(--g400)", fontStyle: "italic", fontSize: "11.5px" }}>{t("report_reader.evidence_empty")}</td>
                  </tr>,
                ]
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Main ReportReader component ───────────────────────────────────────────────
interface ReportReaderProps {
  projectId: string;
  reportId: string;
}

export default function ReportReader({ projectId, reportId }: ReportReaderProps) {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const { lang, t } = useLanguage();

  const [report, setReport] = useState<Report | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string>("");
  const [projectRole, setProjectRole] = useState<string>("researcher");

  const [reportTab, setReportTab] = useState<ReportTab>("conclusion");
  const [rightTab, setRightTab] = useState<RightTab>("copilot");

  const [claimChecks, setClaimChecks] = useState<Record<string, "supported" | "unsupported">>({});
  const [referenceChecks, setReferenceChecks] = useState<Record<string, "valid" | "invalid">>({});
  const [reportNote, setReportNote] = useState("");

  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [pendingActions, setPendingActions] = useState<ActionProposal[]>([]);
  const [gapBusy, setGapBusy] = useState<string | null>(null);
  const [gapVerdicts, setGapVerdicts] = useState<Record<string, "approve" | "narrow" | "reject" | "request_more_evidence">>({});
  const [gapNotes, setGapNotes] = useState<Record<string, string>>({});
  const [gapStatements, setGapStatements] = useState<Record<string, string>>({});
  const [trace, setTrace] = useState<JobTrace | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  // ── API helper ──
  const api = useCallback(
    (path: string, init?: RequestInit) =>
      authenticatedJson<Json>(getToken, path, init, { signInMessage: t("common.sign_in_to_view") }),
    [getToken, t]
  );

  // ── Load data ──
  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void (async () => {
      try {
        // Load project info
        const projBody = await api(`/projects/${projectId}`);
        setProjectName((projBody.project as { name: string }).name ?? "");
        setProjectRole(
          (projBody.membership as { project_role: string })?.project_role ?? "researcher"
        );

        // Load version
        const vBody = await api(`/projects/${projectId}/report-versions/${reportId}`);
        const v = vBody.report_version as Version;
        setVersion(v);
        setReport(v.report ?? null);
        setJobId(v.job_id ?? null);

        // Load report-scoped data that depends on the linked review job.
        if (v.job_id) {
          try {
            const [rBody, gapBody] = await Promise.all([
              api(`/reviews/${v.job_id}`),
              api(`/reviews/${v.job_id}/gaps`),
            ]);
            const result = rBody as unknown as ReviewResult;
            setReviewResult(result);
            setJobStatus(result.status);
            setGaps((gapBody.items ?? []) as Gap[]);
            if (result.claims) setReport(result);
          } catch {
            // The report can still be displayed when a job artifact is unavailable.
          }
          void api(`/reviews/${v.job_id}/trace`)
            .then((body) => setTrace(body as unknown as JobTrace))
            .catch(() => setTrace(null));
        }

        try {
          const memBody = await api(`/projects/${projectId}/memories`);
          setMemories((memBody.items ?? []) as Memory[]);
        } catch {
          // Memory is not available to reviewer-only memberships.
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
  }, [api, isLoaded, isSignedIn, projectId, reportId]);

  const activeReport = reviewResult ?? report;
  const claims = activeReport?.claims ?? [];
  const sources = activeReport?.references ?? [];
  const literatureReview = activeReport?.literature_review;
  const articleLabels = activeReport?.response_language === "Vietnamese"
    ? { abstract: "Tóm tắt", introduction: "Giới thiệu", conclusion: "Kết luận", limitations: "Phạm vi và hạn chế" }
    : { abstract: "Abstract", introduction: "Introduction", conclusion: "Conclusion", limitations: "Scope and limitations" };
  const evidenceCount = claims.reduce((t, c) => t + c.evidence.length, 0);
  const canReview = projectRole === "owner" || projectRole === "researcher";
  const isApproved = jobStatus === "approved";
  const isHITL = jobStatus === "hitl_waiting";
  const hasChangesReq = jobStatus === "changes_requested";

  async function withBusy(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function submitReview(decision: "approve" | "request_changes") {
    if (!jobId || !activeReport) return;
    if (decision === "request_changes" && !Object.values(claimChecks).includes("unsupported")) {
      setError(t("report_reader.require_unsupported"));
      return;
    }
    await withBusy(async () => {
      await api(`/projects/${projectId}/reviews/${jobId}/review`, {
        method: "POST",
        body: JSON.stringify({
          decisions: claims.map((c) => ({
            claim_id: c.claim_id,
            verdict: claimChecks[c.claim_id] ?? "supported",
            note: "",
          })),
          reference_checks: sources.map((s) => ({
            paper_id: s.paper_id,
            verdict: referenceChecks[s.paper_id] ?? "valid",
            note: "",
          })),
          report_decision: decision,
          report_note: reportNote,
        }),
      });
      setJobStatus(decision === "approve" ? "approved" : "changes_requested");
      setNotice(decision === "approve" ? t("report_reader.report_approved") : t("report_reader.agent_changes"));
    });
  }

  async function addPendingAction(actionId: string) {
    const body = await api(`/action-proposals/${actionId}`);
    const action = body.action as ActionProposal | undefined;
    if (!action || action.status !== "proposed") return;
    setPendingActions((current) =>
      current.some((item) => item.action_id === action.action_id) ? current : [...current, action]
    );
  }

  async function runGapAction(gapId: string, work: () => Promise<void>) {
    setGapBusy(gapId);
    setError("");
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setGapBusy(null);
    }
  }

  async function countersearchGap(gap: Gap) {
    await runGapAction(gap.gap_id, async () => {
      const body = await api(`/gaps/${gap.gap_id}/countersearch`, {
        method: "POST",
        body: JSON.stringify({
          report_version_id: gap.report_version_id,
          query: (gap.counter_search_query ?? gap.scoped_statement).slice(0, 300),
          limit: 10,
        }),
      });
      const action = body.action as ActionProposal | undefined;
      if (action?.action_id) setPendingActions((current) => [...current, action]);
      setNotice(t("report_reader.action_created"));
    });
  }

  async function reviewGap(gap: Gap) {
    const verdict = gapVerdicts[gap.gap_id] ?? "request_more_evidence";
    const revisedStatement = gapStatements[gap.gap_id]?.trim();
    if (verdict === "narrow" && !revisedStatement) {
      setError(t("report_reader.require_narrow"));
      return;
    }
    await runGapAction(gap.gap_id, async () => {
      const body = await api(`/gaps/${gap.gap_id}/review`, {
        method: "POST",
        body: JSON.stringify({
          report_version_id: gap.report_version_id,
          verdict,
          revised_statement: revisedStatement || undefined,
          note: gapNotes[gap.gap_id] ?? "",
        }),
      });
      const updated = body.gap as Gap | undefined;
      if (updated) setGaps((current) => current.map((item) => item.gap_id === updated.gap_id ? updated : item));
      setNotice(t("report_reader.gap_saved"));
    });
  }

  async function updateMemory(memoryId: string, operation: "confirm" | "delete") {
    await withBusy(async () => {
      if (operation === "confirm") {
        const body = await api(`/projects/${projectId}/memories/${memoryId}/confirm`, { method: "POST" });
        const updated = body.memory as Memory | undefined;
        if (updated) setMemories((current) => current.map((item) => item.memory_id === memoryId ? updated : item));
        setNotice(t("report_reader.memory_confirmed"));
      } else {
        await api(`/projects/${projectId}/memories/${memoryId}`, { method: "DELETE" });
        setMemories((current) => current.filter((item) => item.memory_id !== memoryId));
        setNotice(t("report_reader.memory_deleted"));
      }
    });
  }

  async function decideAction(action: ActionProposal, decision: "approve" | "reject") {
    await withBusy(async () => {
      const body = await api(`/action-proposals/${action.action_id}/${decision}`, {
        method: "POST",
        headers: decision === "approve" ? { "Idempotency-Key": crypto.randomUUID() } : undefined,
        body: JSON.stringify(
          decision === "approve"
            ? { expected_status: "proposed", expected_base_report_version_id: action.base_report_version_id ?? null }
            : { expected_status: "proposed", reason: t("report_reader.reject") }
        ),
      });
      const updated = body.action as ActionProposal | undefined;
      setPendingActions((current) => current.filter((item) => item.action_id !== action.action_id));
      setNotice(
        decision === "approve"
          ? t("report_reader.action_approved", undefined, { action: updated?.action_type ?? t("report_reader.action_proposal") })
          : t("report_reader.action_rejected")
      );
    });
  }

  async function ensureConversation() {
    if (conversation) return conversation;
    const body = await api(`/projects/${projectId}/conversations`, {
      method: "POST",
      body: JSON.stringify({ initial_report_version_id: reportId }),
    });
    const created = body.conversation as Conversation;
    setConversation(created);
    const history = await api(`/conversations/${created.conversation_id}/messages`);
    const loadedMessages = ((history.items ?? []) as unknown[])
      .map(normalizeMessage)
      .filter((m): m is Message => m !== null);
    setMessages(loadedMessages);
    await Promise.all(
      loadedMessages
        .filter((message) => message.message_type === "action_proposal")
        .flatMap((message) => message.context_artifact_ids ?? [])
        .map((actionId) => addPendingAction(actionId).catch(() => undefined))
    );
    return created;
  }

  async function sendMessage(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    const text = question.trim();
    setQuestion("");
    const optimistic: Message = {
      message_id: crypto.randomUUID(),
      role: "user",
      message_type: "user_message",
      text,
      citations: [],
    };
    await withBusy(async () => {
      const activeConv = await ensureConversation();
      setMessages((cur) => [...cur, optimistic]);
      const body = await api(`/conversations/${activeConv.conversation_id}/messages`, {
        method: "POST",
        body: JSON.stringify({
          client_message_id: optimistic.message_id,
          text,
          expected_report_version_id: reportId,
        }),
      });
      const assistant = normalizeMessage(body.assistant_message);
      if (assistant) {
        setMessages((cur) => [...cur, assistant]);
        if (assistant.message_type === "action_proposal") {
          await Promise.all(
            (assistant.context_artifact_ids ?? []).map((actionId) => addPendingAction(actionId).catch(() => undefined))
          );
        }
      }
    });
  }

  if (!isLoaded) return <main className="mock-loading">{t("report_reader.loading")}</main>;
  if (!isSignedIn)
    return (
      <main className="mock-loading">
        <p>{t("report_reader.sign_in")}</p>
        <Link className="btn-primary" href="/auth">{t("common.sign_in")} →</Link>
      </main>
    );

  return (
    <div className="v2-shell report-reader-shell">
      {/* ── Header ── */}
      <header className="v2-header">
        <Link className="v2-logo" href="/">
          <span className="v2-mark" aria-hidden="true"><span>L</span></span>
          <span>
            <strong>LitReview</strong>
            <small>{t("common.research_desk")}</small>
          </span>
        </Link>
        <nav className="v2-nav">
          {/* Breadcrumb path */}
          <Link href="/dashboard">{t("common.projects")}</Link>
          <span style={{ color: "var(--g400)", fontSize: 12 }}>›</span>
          <Link href={`/workspace?project=${projectId}`}>{projectName || projectId.slice(0, 8)}</Link>
          <span style={{ color: "var(--g400)", fontSize: 12 }}>›</span>
          <span style={{ color: "var(--ink)", fontWeight: 600, fontSize: 13 }}>
            {t("common.report")} v{version?.version_number ?? "—"}
          </span>
        </nav>
        <div className="v2-header-end">
          {isApproved && (
            <span className="report-status-badge approved">{t("report_reader.approved")}</span>
          )}
          {isHITL && (
            <span className="report-status-badge hitl">{t("report_reader.pending_review")}</span>
          )}
          {hasChangesReq && (
            <span className="report-status-badge changes">{t("report_reader.changes_needed")}</span>
          )}
          <LanguageToggle />
          <span className="v2-user">{initials(user?.fullName)}</span>
          <UserButton />
        </div>
      </header>

      {error && (
        <button className="mock-alert" onClick={() => setError("")}>{error}</button>
      )}
      {notice && (
        <button className="mock-alert mock-notice" onClick={() => setNotice("")}>{notice}</button>
      )}

      {/* ── 2-col body ── */}
      <div className="report-body-2col">
        {/* ── LEFT: Report Reader ── */}
        <div className="rep-col">
          {/* Tabs */}
          <div className="rep-tabs">
            {(
              [
                ["conclusion", t("report_reader.conclusion")],
                ["matrix", t("report_reader.matrix")],
                ["claims", `${t("common.claims")} (${claims.length})`],
                ["refs", `${t("report_reader.references")} (${sources.length})`],
              ] as [ReportTab, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                className={`rep-tab ${reportTab === key ? "active" : ""}`}
                onClick={() => setReportTab(key)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="rep-scroll">
            {/* Header */}
            <div className="rep-head">
              <div>
                <h2>{reviewResult?.topic ?? version?.change_reason ?? t("common.report")}</h2>
                <p>
                  {t("common.report")} v{version?.version_number ?? "—"} ·{" "}
                  {version ? new Date(version.created_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US") : ""}
                  {isApproved ? ` · ${t("common.approved")}` : ""}
                </p>
              </div>
              <button className="btn-secondary" type="button" onClick={() => window.print()} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
                </svg>
                {t("report_reader.export_pdf")}
              </button>
            </div>

            {/* ── Reviewer verdict card (if reviewed) ── */}
            {reviewResult?.review && (
              <div className={`reviewer-verdict-card ${reviewResult.review.report_decision === "approve" ? "approved" : "changes"}`}>
                <div className="rv-card-header">
                  <div className="rv-card-badge">
                    {reviewResult.review.report_decision === "approve" ? (
                      <>
                        <span className="rv-badge-dot green" />
                        <span className="rv-badge-label">{t("report_reader.reviewer_review")}</span>
                      </>
                    ) : (
                      <>
                        <span className="rv-badge-dot amber" />
                        <span className="rv-badge-label">{t("report_reader.reviewer_changes")}</span>
                      </>
                    )}
                  </div>
                  <span style={{ fontSize: 11, color: "var(--g500)" }}>
                    {new Date(reviewResult.review.reviewed_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US")}
                  </span>
                </div>
                {reviewResult.review.report_note && (
                  <p className="rv-card-note">{reviewResult.review.report_note}</p>
                )}
                {reviewResult.review_summary && (
                  <div className="rv-card-stats">
                    <div className="rv-stat">
                      <span className="rv-stat-val">{reviewResult.review_summary.supported_claims}</span>
                      <span className="rv-stat-lbl">{t("report_reader.supporting_claims")}</span>
                    </div>
                    <div className="rv-stat">
                      <span className="rv-stat-val">{reviewResult.review_summary.unsupported_claims}</span>
                      <span className="rv-stat-lbl">{t("report_reader.needs_check")}</span>
                    </div>
                    <div className="rv-stat">
                      <span className="rv-stat-val">{sources.length}</span>
                      <span className="rv-stat-lbl">{t("report_reader.sources")}</span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ── Tab content ── */}
            {reportTab === "conclusion" && (
              <>
                {literatureReview ? (
                  <article className="literature-review-article">
                    <header>
                      <h2>{literatureReview.title}</h2>
                      <section><h3>{articleLabels.abstract}</h3><p><ArticleText text={literatureReview.abstract} sources={sources} /></p></section>
                    </header>
                    <section><h3>{articleLabels.introduction}</h3><p><ArticleText text={literatureReview.introduction} sources={sources} /></p></section>
                    {literatureReview.sections.map((section) => (
                      <section key={section.title}>
                        <h3>{section.title}</h3>
                        {section.paragraphs.map((paragraph, index) => <p key={index}><ArticleText text={paragraph} sources={sources} /></p>)}
                      </section>
                    ))}
                    <section><h3>{articleLabels.conclusion}</h3><p><ArticleText text={literatureReview.conclusion} sources={sources} /></p></section>
                    <section className="literature-review-limitations"><h3>{articleLabels.limitations}</h3><p><ArticleText text={literatureReview.limitations} sources={sources} /></p></section>
                    {activeReport?.scope_disclaimer && <p className="conclusion-sub">{activeReport.scope_disclaimer}</p>}
                  </article>
                ) : claims.length > 0 && (
                  <div className="conclusion-card">
                    <div className="conclusion-label">{t("report_reader.short_answer")}</div>
                    <div className="conclusion-txt">{claims[0]?.text}</div>
                    {activeReport?.scope_disclaimer && (
                      <div className="conclusion-sub">{activeReport.scope_disclaimer}</div>
                    )}
                  </div>
                )}

                {/* Stats row */}
                <div className="fact-strip">
                  <div className="fact"><b>{sources.length}</b><span>{t("report_reader.sources")}</span></div>
                  <div className="fact"><b>{evidenceCount}</b><span>{t("report_reader.evidence")}</span></div>
                  <div className="fact"><b>{claims.length}</b><span>{t("common.claims")}</span></div>
                  <div className="fact"><b>{version?.version_number ?? "—"}</b><span>{t("common.version")}</span></div>
                </div>

                {/* Claims list */}
                <div style={{ marginTop: 24 }}>
                  <div className="sec-title">
                    <h3>{t("report_reader.supporting_claims")}</h3>
                    <span className="sec-count">{claims.length} {t("common.claims").toLocaleLowerCase(lang === "vi" ? "vi-VN" : "en-US")}</span>
                  </div>
                  {claims.map((claim, idx) => (
                    <div className="claim-card" key={claim.claim_id}>
                      <div className="claim-txt">{claim.text}</div>
                      {claim.evidence[0] && (
                        <div className="claim-quote">&ldquo;{claim.evidence[0].quote}&rdquo;</div>
                      )}
                      <div className="claim-meta">
                        <span className="claim-seq">{String(idx + 1).padStart(2, "0")}</span>
                        <span style={{ fontSize: 11, color: "var(--g500)" }}>
                          {t("report_reader.evidence_quotes", undefined, { count: claim.evidence.length })}
                        </span>
                        <span className={`claim-verdict ${claim.evidence_verdict === "unsupported" ? "fail" : claim.evidence_verdict === "supported" ? "ok" : "pending"}`}>
                          {claim.evidence_verdict === "supported" ? t("report_reader.supported") : claim.evidence_verdict === "partial" ? "PARTIAL" : claim.evidence_verdict === "unsupported" ? "UNSUPPORTED" : t("report_reader.needs_check")}
                        </span>
                      </div>
                    </div>
                  ))}
                  {!claims.length && (
                    <p className="source-empty">{t("report_reader.claims_empty")}</p>
                  )}
                </div>

                {/* Themes */}
                {(activeReport?.themes?.length ?? 0) > 0 && (
                  <div style={{ marginTop: 24 }}>
                    <div className="sec-title">
                      <h3>{t("report_reader.themes")}</h3>
                      <span className="sec-count">{activeReport!.themes!.length}</span>
                    </div>
                    {activeReport!.themes!.map((theme) => (
                      <div className="memo-row" key={theme.theme_id}>
                        <b>{theme.title}</b>
                        <span>{t("report_reader.papers")} {theme.supporting_paper_ids?.length ?? 0}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {reportTab === "matrix" && (
              <EvidenceMatrix claims={claims} sources={sources} t={t} />
            )}

            {reportTab === "claims" && (
              <div style={{ paddingBottom: 40 }}>
                {claims.map((claim, idx) => (
                  <div className="claim-card" key={claim.claim_id}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                      <span className="claim-seq">{String(idx + 1).padStart(2, "0")}</span>
                      <div className="claim-txt" style={{ margin: 0 }}>{claim.text}</div>
                    </div>
                    {claim.evidence.map((ev, i) => (
                      <div className="claim-quote" key={i}>&ldquo;{ev.quote}&rdquo;</div>
                    ))}
                    <div className="claim-meta">
                      <span style={{ fontSize: 11, color: "var(--g500)", fontFamily: "'IBM Plex Mono',monospace" }}>
                        {claim.evidence.length} {t("report_reader.evidence")}
                      </span>
                    </div>
                  </div>
                ))}
                {!claims.length && <p className="source-empty">{t("report_reader.claims_empty")}</p>}
              </div>
            )}

            {reportTab === "refs" && (
              <div className="source-list" style={{ paddingBottom: 40 }}>
                {sources.map((src, idx) => (
                  <article className="source" key={src.paper_id}>
                    <div className="source-top">
                      <span className="source-id">REF {String(idx + 1).padStart(2, "0")}</span>
                      <span className="source-score">{src.metadata_valid === false ? "CHECK" : "TRACEABLE"}</span>
                    </div>
                    <h3>{src.title}</h3>
                    <div className="authors">
                      {src.authors?.join(", ") || src.paper_id}
                      {src.year ? ` · ${src.year}` : ""}
                    </div>
                    <div className="source-foot">
                      <span>
                        {t("report_reader.evidence_quotes", undefined, { count: claims.flatMap((c) => c.evidence.filter((e) => e.paper_id === src.paper_id)).length })}
                      </span>
                      {sourceLink(src.url, src.paper_id) && (
                        <a href={sourceLink(src.url, src.paper_id)!} target="_blank" rel="noreferrer">{t("report_reader.check")}</a>
                      )}
                    </div>
                  </article>
                ))}
                {!sources.length && <p className="source-empty">{t("report_reader.references_empty")}</p>}
              </div>
            )}
          </div>
        </div>

        {/* ── RIGHT: Review / Copilot ── */}
        <div className="rep-right-col">
          {pendingActions.map((action) => (
            <section className="action-banner" key={action.action_id}>
              <div className="action-banner-label">{t("report_reader.action_proposal")}</div>
              <div className="action-banner-type">{action.action_type.replaceAll("_", " ")}</div>
              <p className="action-banner-reason">{action.reason}</p>
              {action.estimated_impact?.summary && (
                <p className="action-banner-impact">{action.estimated_impact.summary}</p>
              )}
              <div className="action-banner-btns">
                <button type="button" disabled={busy} onClick={() => void decideAction(action, "approve")}>{t("report_reader.agree")}</button>
                <button type="button" disabled={busy} onClick={() => void decideAction(action, "reject")}>{t("report_reader.reject")}</button>
              </div>
            </section>
          ))}

          {/* Tab switcher */}
          <div className="rep-right-tabs">
            <button
              className={`rep-right-tab ${rightTab === "copilot" ? "active" : ""}`}
              onClick={() => setRightTab("copilot")}
            >
              Copilot
            </button>
            <button
              className={`rep-right-tab ${rightTab === "gaps" ? "active" : ""}`}
              onClick={() => setRightTab("gaps")}
            >
              {t("report_reader.gaps", undefined, { count: gaps.length })}
            </button>
            {(isHITL || canReview) && (
              <button
                className={`rep-right-tab ${rightTab === "review" ? "active" : ""}`}
                onClick={() => setRightTab("review")}
              >
                {isHITL ? `⏳ ${t("common.review")}` : t("common.review")}
              </button>
            )}
            {canReview && (
              <button
                className={`rep-right-tab ${rightTab === "memory" ? "active" : ""}`}
                onClick={() => setRightTab("memory")}
              >
                {t("report_reader.memory", undefined, { count: memories.length })}
              </button>
            )}
          </div>

          {jobId && (
            <button className={`rep-right-tab ${rightTab === "trace" ? "active" : ""}`} onClick={() => setRightTab("trace")}>
              Trace {trace ? `(${trace.total_events})` : ""}
            </button>
          )}

          {rightTab === "trace" && (
            <div className="review-pane" style={{ flex: 1, overflowY: "auto", padding: "14px" }}>
              <p className="review-intro">Execution log for this research run. Sensitive prompt and response content is not shown here.</p>
              {!trace && <p className="source-empty">Trace log is unavailable for this run.</p>}
              {trace?.lifecycle_events.map((event) => (
                <article className="memory-item" key={event.id}>
                  <div className="memory-head"><b>{event.event_type.replaceAll("_", " ")}</b><span className="memory-badge neutral">{event.status}</span></div>
                  <p>{new Date(event.created_at).toLocaleString(lang === "vi" ? "vi-VN" : "en-US")}</p>
                </article>
              ))}
              {trace?.llm_events.map((event) => (
                <article className="memory-item" key={event.id}>
                  <div className="memory-head"><b>{event.node_name} · {event.event_type}</b><span className="memory-badge neutral">{event.status}</span></div>
                  <p>{event.provider} / {event.model} · attempt {event.attempt}{event.latency_ms != null ? ` · ${event.latency_ms} ms` : ""}</p>
                  {(event.tokens_prompt != null || event.tokens_completion != null) && <p>Tokens: {event.tokens_prompt ?? 0} in / {event.tokens_completion ?? 0} out</p>}
                  {event.error_message && <p className="source-empty">{event.error_type ? `${event.error_type}: ` : ""}{event.error_message}</p>}
                </article>
              ))}
            </div>
          )}

          {/* ── Copilot tab ── */}
          {rightTab === "copilot" && (
            <div className="copilot-pane" style={{ flex: 1, display: "flex", flexDirection: "column" }}>
              {/* Context selector */}
              <div className="copilot-ctx-card">
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--g500)", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 4 }}>
                  {t("report_reader.copilot_context")}
                </div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--ink)" }}>{t("report_reader.this_report")}</div>
                <div style={{ fontSize: 11.5, color: "var(--g500)", marginTop: 2 }}>
                  {claims.length} {t("common.claims")} · {sources.length} {t("report_reader.sources")}
                </div>
              </div>

              {/* Messages */}
              <div className="copilot-messages" style={{ flex: 1 }}>
                {messages.map((msg) => (
                  <article
                    className={msg.role === "user" ? "copilot-user" : "copilot-assistant"}
                    key={msg.message_id}
                  >
                    <p>{msg.text}</p>
                    {msg.citations.map((c, i) => (
                      sourceLink(c.source_url, c.paper_id) && <a href={sourceLink(c.source_url, c.paper_id)!} target="_blank" rel="noreferrer" key={i}>
                        {c.paper_id ?? "Source"}: {c.quote}
                      </a>
                    ))}
                  </article>
                ))}
                {!messages.length && (
                  <p className="source-empty">
                    {reportId
                      ? t("report_reader.ask_copilot")
                      : t("workspace.select_report_version")}
                  </p>
                )}
              </div>

              {/* Input */}
              <form className="copilot-form" onSubmit={sendMessage}>
                <textarea
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={t("report_reader.ask_summary")}
                  disabled={busy}
                />
                <button type="submit" disabled={!question.trim() || busy}>{t("report_reader.send")}</button>
              </form>
            </div>
          )}

          {rightTab === "gaps" && (
            <div className="gap-pane" style={{ flex: 1, overflowY: "auto", padding: 14 }}>
              <p className="review-intro">
                {t("report_reader.gap_intro")}
              </p>
              {gaps.map((gap) => {
                const verdict = gapVerdicts[gap.gap_id] ?? "request_more_evidence";
                const isFinal = ["reviewer_approved", "reviewer_narrowed", "reviewer_rejected"].includes(gap.status);
                const badgeClass = gap.status.includes("approved") || gap.status.includes("supported")
                  ? "approved"
                  : gap.status.includes("rejected") || gap.status === "contradicted"
                    ? "rejected"
                    : "pending";
                return (
                  <article className="gap-item" key={gap.gap_id}>
                    <div className="gap-item-top">
                      <span className={`gap-status-badge ${badgeClass}`}>{gapLabel(gap.status, t)}</span>
                      <span className="gap-coverage">{t("report_reader.papers_count", undefined, { count: gap.corpus_size ?? gap.coverage?.length ?? 0 })}</span>
                    </div>
                    <p className="gap-statement">{gap.scoped_statement}</p>
                    {gap.reviewer_rationale && <p className="gap-meta">{gap.reviewer_rationale}</p>}
                    {gap.confidence && <p className="gap-meta">Confidence: {gap.confidence}</p>}
                    {(gap.evidence_score != null || gap.novelty_score != null || gap.feasibility_score != null) && (
                      <div className="gap-quality-grid">
                        {[["Evidence", gap.evidence_score], ["Novelty", gap.novelty_score], ["Feasibility", gap.feasibility_score], ["Overall", gap.quality_score]].map(([label, score]) => (
                          <div className="gap-quality-score" key={String(label)}>
                            <span>{label}</span><strong>{score ?? "–"}</strong>
                            <i><b style={{ width: `${Math.max(0, Math.min(100, Number(score ?? 0)))}%` }} /></i>
                          </div>
                        ))}
                      </div>
                    )}
                    {gap.suggested_method && <p className="gap-meta">Suggested method: {gap.suggested_method}</p>}
                    {gap.falsification_condition && <p className="gap-meta">Falsification: {gap.falsification_condition}</p>}
                    {(gap.counterevidence_paper_ids?.length ?? 0) > 0 && (
                      <p className="gap-meta">{t("report_reader.counterevidence", undefined, { count: gap.counterevidence_paper_ids!.length })}</p>
                    )}
                    {!isFinal && canReview && (
                      <button
                        className="btn-secondary gap-countersearch-btn"
                        type="button"
                        disabled={gapBusy === gap.gap_id}
                        onClick={() => void countersearchGap(gap)}
                      >
                        {gapBusy === gap.gap_id ? t("report_reader.creating") : t("report_reader.countersearch")}
                      </button>
                    )}
                    {!isFinal && (canReview || isHITL) && (
                      <div className="gap-verdict-row">
                        <select
                          aria-label={t("report_reader.gap_decision")}
                          value={verdict}
                          disabled={gapBusy === gap.gap_id}
                          onChange={(event) => setGapVerdicts((current) => ({
                            ...current,
                            [gap.gap_id]: event.target.value as "approve" | "narrow" | "reject" | "request_more_evidence",
                          }))}
                        >
                          <option value="request_more_evidence">{t("report_reader.more_evidence")}</option>
                          <option value="approve">{t("report_reader.approve_gap")}</option>
                          <option value="narrow">{t("report_reader.narrow_gap")}</option>
                          <option value="reject">{t("report_reader.reject_gap")}</option>
                        </select>
                        <button
                          className="btn-primary"
                          type="button"
                          disabled={gapBusy === gap.gap_id}
                          onClick={() => void reviewGap(gap)}
                        >
                          {t("common.save")}
                        </button>
                      </div>
                    )}
                    {verdict === "narrow" && !isFinal && (
                      <textarea
                        className="gap-note"
                        value={gapStatements[gap.gap_id] ?? ""}
                        onChange={(event) => setGapStatements((current) => ({ ...current, [gap.gap_id]: event.target.value }))}
                        placeholder={t("report_reader.narrow_placeholder")}
                      />
                    )}
                    {!isFinal && (canReview || isHITL) && (
                      <input
                        className="gap-note"
                        value={gapNotes[gap.gap_id] ?? ""}
                        onChange={(event) => setGapNotes((current) => ({ ...current, [gap.gap_id]: event.target.value }))}
                        placeholder={t("report_reader.review_note")}
                      />
                    )}
                  </article>
                );
              })}
              {!gaps.length && <p className="source-empty">{t("report_reader.claims_empty")}</p>}
            </div>
          )}

          {rightTab === "memory" && (
            <div className="memory-pane" style={{ flex: 1, overflowY: "auto", padding: 14 }}>
              {Object.entries(
                memories.reduce<Record<string, Memory[]>>((groups, memory) => {
                  (groups[memory.memory_type] ??= []).push(memory);
                  return groups;
                }, {})
              ).map(([type, items]) => (
                <section key={type}>
                  <div className="memory-group-label">{type.replaceAll("_", " ")}</div>
                  {items.map((memory) => (
                    <article className={`memory-item ${memory.status === "superseded" ? "superseded" : ""}`} key={memory.memory_id}>
                      <p className="memory-content">{memoryText(memory.content, t("common.no_note"))}</p>
                      <div className="memory-meta">
                        <span className={`memory-badge ${memory.status === "active" ? "done" : memory.status === "proposed" ? "confirm" : "neutral"}`}>
                          {memory.status === "proposed" ? t("report_reader.confirm") : memory.status === "active" ? t("common.approved") : memory.status}
                        </span>
                        <span>{new Date(memory.created_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US")}</span>
                      </div>
                      <div className="memory-actions">
                        {memory.status === "proposed" && (
                          <button className="btn-primary" type="button" disabled={busy} onClick={() => void updateMemory(memory.memory_id, "confirm")}>{t("report_reader.confirm")}</button>
                        )}
                        {memory.status !== "superseded" && (
                          <button className="btn-secondary" type="button" disabled={busy} onClick={() => void updateMemory(memory.memory_id, "delete")}>{t("common.delete")}</button>
                        )}
                      </div>
                    </article>
                  ))}
                </section>
              ))}
              {!memories.length && <p className="source-empty">{t("report_reader.memory_empty")}</p>}
            </div>
          )}

          {/* ── Review tab ── */}
          {rightTab === "review" && (
            <div className="review-pane" style={{ flex: 1, overflowY: "auto", padding: "14px" }}>
              {isApproved ? (
                <div className="reviewer-verdict-card approved">
                  <div className="rv-card-header">
                    <span className="rv-badge-dot green" />
                    <span className="rv-badge-label">{t("report_reader.report_approved")}</span>
                  </div>
                  <p className="rv-card-note" style={{ margin: "8px 0 0" }}>
                    {reviewResult?.review?.report_note || t("common.no_note")}
                  </p>
                </div>
              ) : hasChangesReq ? (
                <div className="reviewer-verdict-card changes">
                  <div className="rv-card-header">
                    <span className="rv-badge-dot amber" />
                    <span className="rv-badge-label">{t("report_reader.reviewer_changes")}</span>
                  </div>
                  <p className="rv-card-note" style={{ margin: "8px 0 0" }}>
                    {reviewResult?.review?.report_note || t("report_reader.agent_changes")}
                  </p>
                </div>
              ) : (
                <>
                  <p className="review-intro">{t("report_reader.reviewer_intro")}</p>
                  {claims.map((claim) => (
                    <label className="review-check" key={claim.claim_id}>
                      <span>{claim.text}</span>
                      <select
                        value={claimChecks[claim.claim_id] ?? "supported"}
                        onChange={(e) =>
                          setClaimChecks((cur) => ({
                            ...cur,
                            [claim.claim_id]: e.target.value as "supported" | "unsupported",
                          }))
                        }
                      >
                        <option value="supported">{t("report_reader.supported")}</option>
                        <option value="unsupported">{t("report_reader.unsupported")}</option>
                      </select>
                    </label>
                  ))}
                  {sources.map((src) => (
                    <label className="review-check reference-check" key={src.paper_id}>
                      <span>{src.title}</span>
                      <select
                        value={referenceChecks[src.paper_id] ?? "valid"}
                        onChange={(e) =>
                          setReferenceChecks((cur) => ({
                            ...cur,
                            [src.paper_id]: e.target.value as "valid" | "invalid",
                          }))
                        }
                      >
                        <option value="valid">{t("report_reader.valid")}</option>
                        <option value="invalid">{t("report_reader.invalid")}</option>
                      </select>
                    </label>
                  ))}
                  <textarea
                    className="review-note"
                    value={reportNote}
                    onChange={(e) => setReportNote(e.target.value)}
                    placeholder={t("report_reader.report_note_placeholder")}
                  />
                  <div className="review-actions">
                    <button
                      className="btn-secondary"
                      disabled={busy}
                      onClick={() => void submitReview("request_changes")}
                    >
                      {t("workspace.request_changes")}
                    </button>
                    <button
                      className="btn-primary"
                      disabled={busy}
                      onClick={() => void submitReview("approve")}
                    >
                      {t("workspace.approve_report")}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
