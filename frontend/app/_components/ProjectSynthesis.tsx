"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
import LanguageToggle from "./LanguageToggle";
import { useLanguage } from "./language-context";
import { authenticatedJson } from "../_lib/authenticated-fetch";
import type { Json, Project, Review, Version } from "./workspace-types";


type SourceReport = { review: Review; version: Version; selected: boolean };
type SourceCitation = { citation_id: string; title: string; quote: string; source_url: string; paper_id: string };
type ChatTurn = { role: "user" | "assistant"; text: string; citations?: SourceCitation[] };

function initials(name?: string | null) {
  return (name ?? "LR").split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
}

function citationsFrom(value: unknown): SourceCitation[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const citation = item as Record<string, unknown>;
    const sourceUrl = typeof citation.source_url === "string" ? citation.source_url : "";
    if (!sourceUrl) return [];
    return [{
      citation_id: typeof citation.citation_id === "string" ? citation.citation_id : `source-${index + 1}`,
      paper_id: typeof citation.paper_id === "string" ? citation.paper_id : "",
      title: typeof citation.title === "string" ? citation.title : "Nguồn nghiên cứu",
      quote: typeof citation.quote === "string" ? citation.quote : "",
      source_url: sourceUrl,
    }];
  });
}

export default function ProjectSynthesis({ projectId }: { projectId: string }) {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const { t } = useLanguage();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [sourceReports, setSourceReports] = useState<SourceReport[]>([]);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [loadingSources, setLoadingSources] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState("");

  const api = useCallback(
    (path: string, init?: RequestInit) =>
      authenticatedJson<Json>(getToken, path, init, { signInMessage: t("common.sign_in_to_view") }),
    [getToken, t],
  );

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void (async () => {
      setLoadingSources(true);
      setError("");
      try {
        const [projectListBody, projectBody, reviewsBody, versionsBody] = await Promise.all([
          api("/projects"),
          api(`/projects/${projectId}`),
          api(`/projects/${projectId}/reviews`),
          api(`/projects/${projectId}/report-versions`),
        ]);
        const loadedProject = {
          ...(projectBody.project as Project),
          project_role: (projectBody.membership as { project_role: Project["project_role"] }).project_role,
        };
        setProject(loadedProject);
        setProjects((projectListBody.items ?? []) as Project[]);
        const versions = (versionsBody.items ?? []) as Version[];
        const approved = ((reviewsBody.items ?? []) as Review[])
          .filter((review) => review.status === "approved")
          .flatMap((review) => {
            const version = versions.find((item) => item.job_id === review.job_id || item.report_version_id === review.report_version_id);
            return version ? [{ review, version, selected: false }] : [];
          });
        setSourceReports(approved);
        setTurns([]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setLoadingSources(false);
      }
    })();
  }, [api, isLoaded, isSignedIn, projectId]);

  const selectedSources = useMemo(() => sourceReports.filter((source) => source.selected), [sourceReports]);
  const projectOptions = useMemo(() => {
    const byId = new Map(projects.map((item) => [item.project_id, item]));
    if (project) byId.set(project.project_id, project);
    return Array.from(byId.values());
  }, [project, projects]);

  function toggleSource(jobId: string) {
    setSourceReports((current) => current.map((source) => source.review.job_id === jobId ? { ...source, selected: !source.selected } : source));
    setTurns([]);
  }

  async function ask(event?: FormEvent) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || !selectedSources.length || asking) return;
    setQuestion("");
    setAsking(true);
    setError("");
    setTurns((current) => [...current, { role: "user", text }]);
    try {
      const body = await api(`/projects/${projectId}/source-chat`, {
        method: "POST",
        body: JSON.stringify({ job_ids: selectedSources.map((source) => source.review.job_id), text }),
      });
      const answer = typeof body.answer === "string" ? body.answer : "Chưa thể tạo câu trả lời từ các nguồn đã chọn.";
      setTurns((current) => [...current, { role: "assistant", text: answer, citations: citationsFrom(body.citations) }]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setAsking(false);
    }
  }

  function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask();
    }
  }

  if (!isLoaded) return <main className="mock-loading">Đang tải trợ lý nguồn…</main>;
  if (!isSignedIn) return <main className="mock-loading"><p>{t("synthesis.sign_in")}</p><Link className="btn-primary" href="/auth">{t("common.sign_in")} →</Link></main>;

  return (
    <div className="v2-shell synthesis-shell">
      <header className="v2-header">
        <Link className="v2-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{t("common.research_desk")}</small></span></Link>
        <nav className="v2-nav source-project-nav"><Link href="/dashboard">{t("common.projects")}</Link><span>›</span><label><span className="source-project-label">Project</span><select value={projectId} onChange={(event) => router.push(`/projects/${event.target.value}/synthesis`)}><option value={projectId}>{project?.name ?? "Đang tải project…"}</option>{projectOptions.filter((item) => item.project_id !== projectId).map((item) => <option key={item.project_id} value={item.project_id}>{item.name}</option>)}</select></label><span>›</span><span className="source-chat-current">Hỏi nguồn đã duyệt</span></nav>
        <div className="v2-header-end"><LanguageToggle /><span className="v2-user">{initials(user?.fullName)}</span><UserButton /></div>
      </header>

      {error && <button className="mock-alert" onClick={() => setError("")}>{error}</button>}
      <div className="proj-nav-tabs"><Link className="pnav-tab" href={`/workspace?project=${projectId}`}>{t("synthesis.research_questions")}</Link><span className="pnav-tab active">Hỏi nguồn đã duyệt</span></div>

      <div className="synth-body source-chat-body">
        <aside className="synth-sources-col">
          <div className="synth-sources-head"><h3>Báo cáo đã duyệt</h3><p>Chọn một hoặc nhiều luồng nghiên cứu. Chatbot chỉ truy xuất các bài báo đã index trong những luồng này.</p></div>
          <div className="synth-sources-scroll">
            {loadingSources && <p className="source-empty">Đang tải báo cáo…</p>}
            {!loadingSources && !sourceReports.length && <p className="source-empty">Project này chưa có báo cáo đã duyệt để dùng làm nguồn.</p>}
            {sourceReports.map((source) => (
              <button key={source.review.job_id} type="button" className={`synth-source-item source-chat-source ${source.selected ? "selected" : ""}`} onClick={() => toggleSource(source.review.job_id)} aria-pressed={source.selected}>
                <span className={`si-checkbox ${source.selected ? "checked" : "unchecked"}`} aria-hidden="true">{source.selected && <svg viewBox="0 0 24 24" fill="none"><path d="m5 12 4.2 4.2L19 6.7" /></svg>}</span>
                <span className="source-chat-source-copy"><span className="si-title">{source.review.topic || "Luồng nghiên cứu"}</span><span className="si-meta"><span className="claim-verdict ok">Đã duyệt</span><span>v{source.version.version_number}</span></span></span>
              </button>
            ))}
          </div>
          <div className="synth-sources-footer"><strong>{selectedSources.length}/{sourceReports.length} nguồn đã chọn</strong><p>Thay đổi nguồn sẽ bắt đầu một cuộc hội thoại mới để giữ đúng phạm vi bằng chứng.</p><Link href={`/workspace?project=${projectId}`} className="btn-secondary source-chat-back">← {t("common.back_to_workspace")}</Link></div>
        </aside>

        <main className="synth-main-col source-chat-main">
          <div className="synth-status-banner"><div className="synth-sb-icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v13.5A2.5 2.5 0 0 1 17.5 19H4z"/><path d="M7 7h9M7 11h6"/></svg></div><div><strong>Trợ lý tài liệu đã duyệt</strong><span>{selectedSources.length ? `Đang hỏi trong ${selectedSources.length} báo cáo đã duyệt; mỗi ý trả lời có citation tới bài báo.` : "Chọn nguồn ở cột bên trái để bắt đầu một câu hỏi có căn cứ."}</span></div></div>
          <section className="source-chat-thread" aria-live="polite">
            {!selectedSources.length ? <div className="source-chat-empty"><h1>Chọn corpus trước khi hỏi.</h1><p>Không có báo cáo chưa duyệt, ghi chú nháp hoặc nguồn ngoài project nào được đưa vào câu trả lời.</p></div> : !turns.length ? <div className="source-chat-empty"><h1>Bạn muốn kiểm chứng điều gì?</h1><p>Ví dụ: “Các nghiên cứu đã chọn nói gì về độ chính xác và nguy cơ thiên lệch?”</p><div className="source-chat-selected">{selectedSources.map((source) => <span key={source.review.job_id}>{source.review.topic || source.review.job_id.slice(0, 8)}</span>)}</div></div> : turns.map((turn, index) => <article key={`${turn.role}-${index}`} className={`source-chat-turn ${turn.role}`}><div className="source-chat-turn-label">{turn.role === "user" ? "Bạn" : "Trợ lý · nguồn đã duyệt"}</div><p>{turn.text}</p>{turn.citations?.length ? <div className="source-chat-citations">{turn.citations.map((citation, citationIndex) => <a key={citation.citation_id} href={citation.source_url} target="_blank" rel="noreferrer" title={citation.quote}>[S{citationIndex + 1}] {citation.title || citation.paper_id} ↗</a>)}</div> : null}</article>)}
            {asking && <article className="source-chat-turn assistant source-chat-thinking"><div className="source-chat-turn-label">Trợ lý · đang truy xuất</div><p><i></i><i></i><i></i> Đang đối chiếu bằng chứng đã index…</p></article>}
          </section>
          <form className="source-chat-composer" onSubmit={ask}><label htmlFor="source-chat-question">Câu hỏi cho các nguồn đã chọn</label><textarea id="source-chat-question" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={submitOnEnter} disabled={!selectedSources.length || asking} placeholder={selectedSources.length ? "Hỏi một câu có thể trả lời từ các báo cáo đã duyệt…" : "Chọn ít nhất một báo cáo đã duyệt trước"} /><div><span>Enter để gửi · Shift + Enter xuống dòng</span><button type="submit" disabled={!selectedSources.length || !question.trim() || asking}>{asking ? "Đang tìm…" : "Hỏi nguồn"} <b>↑</b></button></div></form>
        </main>
      </div>
    </div>
  );
}
