"use client";

import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import LanguageToggle from "./LanguageToggle";
import { useLanguage } from "./language-context";
import type { Assignment, Project, Review, ReviewFeedback } from "./workspace-types";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
const configured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);
const ACTIVE = new Set(["queued", "running", "resuming"]);

/** Bộ icon dùng chung cho bàn nghiên cứu: một khung 16, một độ dày nét. */
function Icon({ name }: { name: "arrow" | "plus" | "synthesis" }) {
  const path = {
    arrow: "M3 8h10M9 4l4 4-4 4",
    plus: "M8 3v10M3 8h10",
    synthesis: "M11.5 3.5h-7l4 4.5-4 4.5h7",
  }[name];
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"
         fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square">
      <path d={path} />
    </svg>
  );
}

function state(reviews: Review[]) {
  if (reviews.some((review) => ACTIVE.has(review.status))) return "running";
  if (reviews.some((review) => review.status === "hitl_waiting" || review.status === "changes_requested")) return "review";
  return "done";
}

function DeskHomeData() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { t } = useLanguage();
  const [projects, setProjects] = useState<Project[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [reviewsByProject, setReviewsByProject] = useState<Record<string, Review[]>>({});
  const [feedback, setFeedback] = useState<ReviewFeedback[]>([]);
  const [error, setError] = useState("");

  const headers = useCallback(async () => {
    let token = await getToken();
    if (!token) token = await getToken({ skipCache: true });
    if (!token) throw new Error(t("common.sign_in_to_view"));
    return { Authorization: `Bearer ${token}` };
  }, [getToken, t]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void (async () => {
      try {
        const authHeaders = await headers();
        const [projectResponse, assignmentResponse] = await Promise.all([
          fetch(`${API}/projects`, { headers: authHeaders }),
          fetch(`${API}/review-assignments`, { headers: authHeaders }),
        ]);
        const projectBody = await projectResponse.json().catch(() => ({}));
        const assignmentBody = await assignmentResponse.json().catch(() => ({}));
        if (!projectResponse.ok) throw new Error(projectBody?.detail?.message ?? projectBody?.detail?.code ?? t("common.load_projects"));
        if (!assignmentResponse.ok) throw new Error(assignmentBody?.detail?.message ?? assignmentBody?.detail?.code ?? t("common.load_reviewer_queue"));

        const items = (projectBody.items ?? []) as Project[];
        setProjects(items);
        setAssignments((assignmentBody.items ?? []) as Assignment[]);
        const reviewEntries = await Promise.all(
          items.map(async (project) => {
            const response = await fetch(`${API}/projects/${project.project_id}/reviews`, { headers: authHeaders });
            const body = await response.json().catch(() => ({}));
            return [project.project_id, response.ok ? (body.items ?? []) as Review[] : []] as const;
          })
        );
        setReviewsByProject(Object.fromEntries(reviewEntries));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
  }, [headers, isLoaded, isSignedIn, t]);

  const hasActiveReview = useMemo(
    () => Object.values(reviewsByProject).flat().some((review) => ACTIVE.has(review.status)),
    [reviewsByProject]
  );

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !hasActiveReview) return;
    let cancelled = false;
    const refreshReviews = async () => {
      try {
        const authHeaders = await headers();
        const entries = await Promise.all(projects.map(async (project) => {
          const response = await fetch(`${API}/projects/${project.project_id}/reviews`, { headers: authHeaders });
          const body = await response.json().catch(() => ({}));
          return [project.project_id, response.ok ? (body.items ?? []) as Review[] : []] as const;
        }));
        if (!cancelled) setReviewsByProject(Object.fromEntries(entries));
      } catch {
        // Keep the last known state; the next poll can recover.
      }
    };
    const timer = window.setInterval(() => void refreshReviews(), 4500);
    return () => { cancelled = true; window.clearInterval(timer); };
    // `reviewsByProject` CỐ TÌNH không nằm trong danh sách phụ thuộc. Vòng lặp
    // này tự ghi vào đúng state đó, mà Object.fromEntries luôn trả về object
    // mới kể cả khi dữ liệu y hệt — để nó vào đây thì mỗi lần poll lại huỷ và
    // dựng lại interval. `hasActiveReview` mới là thứ quyết định nên poll hay
    // dừng, và nó là boolean nên chỉ đổi khi trạng thái thật sự đổi.
  }, [headers, isLoaded, isSignedIn, projects, hasActiveReview]);

  const active = useMemo(
    () => projects.find((project) => (reviewsByProject[project.project_id] ?? []).some((review) => ACTIVE.has(review.status))) ?? projects[0],
    [projects, reviewsByProject]
  );
  const activeProjectId = active?.project_id;

  useEffect(() => {
    if (!isLoaded || !isSignedIn || !activeProjectId) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`${API}/projects/${activeProjectId}/review-feedback`, { headers: await headers() });
        const body = await response.json().catch(() => ({}));
        if (!cancelled) setFeedback(response.ok ? (body.items ?? []) as ReviewFeedback[] : []);
      } catch {
        if (!cancelled) setFeedback([]);
      }
    })();
    return () => { cancelled = true; };
  }, [activeProjectId, headers, isLoaded, isSignedIn]);

  if (!isLoaded) return <main className="mock-loading">{t("common.loading_projects")}</main>;
  if (!isSignedIn) return <main className="mock-loading"><p>{t("common.sign_in_to_view")}</p><Link className="btn-primary" href="/auth">{t("common.sign_in")} →</Link></main>;

  return (
    <DeskHomeView
      projects={projects}
      assignments={assignments}
      reviewsByProject={reviewsByProject}
      feedback={feedback}
      error={error}
      slotAvatar={<UserButton appearance={{ elements: { avatarBox: "desk-user-avatar" } }} />}
    />
  );
}

/**
 * Phần HIỂN THỊ của bàn nghiên cứu, tách khỏi phần lấy dữ liệu.
 *
 * Tách ra vì hai lý do. Một: khâu gọi API và khâu dựng giao diện là hai việc
 * khác nhau, trộn chung thì không kiểm được cái nào. Hai: toàn bộ trang này
 * nằm sau đăng nhập, nên trước đây không có cách nào xem giao diện mà không
 * có phiên Clerk thật — mọi thay đổi bố cục đều phải sửa mù.
 */
export type DeskView = {
  projects: Project[];
  assignments: Assignment[];
  reviewsByProject: Record<string, Review[]>;
  feedback: ReviewFeedback[];
  error?: string;
  slotAvatar?: React.ReactNode;
};

export function DeskHomeView({ projects, assignments, reviewsByProject, feedback, error, slotAvatar }: DeskView) {
  const { lang, t } = useLanguage();
  const active = projects.find((project) => (reviewsByProject[project.project_id] ?? []).some((review) => ACTIVE.has(review.status))) ?? projects[0];
  const runningCount = Object.values(reviewsByProject).flat().filter((review) => ACTIVE.has(review.status)).length;
  const total = String(projects.length).padStart(2, "0");
  const activeReviews = active ? reviewsByProject[active.project_id] ?? [] : [];
  const activeThread = activeReviews.find((review) => ACTIVE.has(review.status)) ?? activeReviews[0];
  const pendingAssignments = assignments.filter((assignment) => assignment.status === "assigned");
  const stateText = (value: string) => value === "running" ? t("dashboard.state_running") : value === "review" ? t("dashboard.state_review") : t("dashboard.state_done");
  const queueLabel = (value: string) => value === "hitl_waiting" ? t("dashboard.state_review") : value === "changes_requested" ? t("report_reader.changes_needed") : value;
  const feedbackLabel = (value: string) => ({ approve: t("report_reader.approved"), narrow: t("report_reader.narrow_gap"), reject: t("report_reader.reject"), request_more_evidence: t("report_reader.more_evidence") }[value] ?? value.replaceAll("_", " "));

  return (
    <div className="v2-shell">
      <header className="v2-header">
        {/* Logo về trang giới thiệu. Trước đây trỏ "/dashboard" — tức chính
            trang đang đứng, nên bấm vào không đi đâu cả. */}
        <Link className="v2-logo" href="/"><span className="v2-mark" aria-hidden="true"><span>L</span></span><span><strong>LitReview</strong><small>{t("common.research_desk")}</small></span></Link>
        <nav className="v2-nav"><Link className="active" href="/dashboard">{t("nav.desk")}</Link><a href="#registry">{t("nav.projects")}</a><Link href="/workspace">{t("nav.reports")}</Link></nav>
        <div className="v2-header-end">
          {/* Chip "⌘ K TÌM KIẾM" đã bị gỡ: toàn bộ frontend không có handler
              phím tắt nào cho tìm kiếm, nên nó hứa một tính năng không tồn tại.
              Chỉ giữ lại phần đếm tiến trình — thứ phản ánh trạng thái thật. */}
          {runningCount > 0 && (
            <span className="v2-running" title={t("common.running")}>
              <i aria-hidden="true" />{runningCount} {t("common.running").toUpperCase()}
            </span>
          )}
          <LanguageToggle />
          <Link className="btn-primary" href="/projects/new">{t("dashboard.new_project")}</Link>
          {/* Trước đây là <span> chữ cái tắt, bấm không được, và dashboard
              KHÔNG có lối đăng xuất nào. UserButton cho menu tài khoản thật,
              đồng thời khớp với đầu trang giới thiệu. */}
          {slotAvatar}
        </div>
      </header>

      <main className="desk">
        <section className="desk-intro">
          <div><div className="eyebrow">{t("dashboard.eyebrow")}</div><h1>{t("dashboard.title")}</h1><p>{t("dashboard.intro")}</p></div>
          <div className="date-block"><span>{t("dashboard.today")}</span><strong>{new Intl.DateTimeFormat(lang === "vi" ? "vi-VN" : "en-US", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date())}</strong><span>{t("dashboard.projects_running", undefined, { projects: projects.length, running: runningCount })}</span></div>
        </section>
        {error && <p className="mock-alert">{error}</p>}

        <div className="desk-grid">
          <section>
            <div className="panel-title"><h2>{t("dashboard.open_file")}</h2><Link href={active ? `/workspace?project=${active.project_id}${activeThread ? `&job=${activeThread.job_id}` : ""}` : "/workspace"}>{t("common.view_workspace")}</Link></div>
            {active ? (
              <article className="focus-file">
                <div className="file-number"><span>{t("dashboard.file")} 01 / {active.project_id.slice(0, 9).toUpperCase()}</span><span className={activeThread && ACTIVE.has(activeThread.status) ? "live-label" : "folio"}>{activeThread ? stateText(state(activeReviews)) : t("common.ready")}</span></div>
                <h3>{active.name}</h3>
                <p>{activeThread?.topic || active.description || t("dashboard.dossier_ready")}</p>
                <div className="file-metrics">
                  <div className="metric"><strong>{String(activeReviews.length).padStart(2, "0")}</strong><span>{t("dashboard.questions")}</span></div>
                  <div className="metric"><strong>{activeReviews.filter((review) => ACTIVE.has(review.status)).length}</strong><span>{t("common.running")}</span></div>
                  <div className="metric"><strong>{activeReviews.filter((review) => review.status === "hitl_waiting").length}</strong><span>{t("dashboard.waiting_approval")}</span></div>
                  <div className="metric"><strong>{activeReviews.filter((review) => review.status === "approved").length}/{activeReviews.length}</strong><span>{t("dashboard.approved_reports")}</span></div>
                </div>
                <div className="file-foot">
                  <span className="folio">{active.project_role.toUpperCase()}</span>
                  <small>{activeThread ? t("dashboard.state_status", undefined, { state: stateText(state(activeReviews)) }) : t("dashboard.no_thread")}</small>
                  {/* Ba nút gom vào một nhóm. Trước đây chúng là con trực tiếp
                      của .file-foot, mà class này được khai hai lần mâu thuẫn
                      (mock-home dựng hàng ngang, mock-polish đè thành cột), nên
                      hai nút phụ phải vá bằng marginTop inline còn nút chính thì
                      không — đó chính là chỗ nhìn thấy lệch. */}
                  <div className="file-actions">
                    <Link className="btn-primary" href={`/workspace?project=${active.project_id}${activeThread ? `&job=${activeThread.job_id}` : ""}`}>{t("dashboard.continue_file")}</Link>
                    <Link className="btn-secondary" href={`/projects/${active.project_id}/synthesis`}>{t("nav.synthesis")}</Link>
                    <Link className="btn-secondary" href={`/projects/${active.project_id}/members`}>{t("dashboard.manage_members")}</Link>
                  </div>
                </div>
              </article>
            ) : <article className="focus-file empty-dossier"><h3>{t("dashboard.no_file_title")}</h3><p>{t("dashboard.no_file_body")}</p><Link className="btn-primary" href="/projects/new">{t("dashboard.new_file")}</Link></article>}
          </section>

          <aside className="review-queue">
            <div className="queue-head"><div><div className="eyebrow">{t("dashboard.decisions_needed")}</div><h2>{t("dashboard.review_queue")}</h2></div><span className="queue-count">{String(pendingAssignments.length).padStart(2, "0")}</span></div>
            {pendingAssignments.slice(0, 3).map((assignment) => <Link className="review-item" href={`/workspace?project=${assignment.project_id}&job=${assignment.job_id}${assignment.report_version_id ? `&report=${assignment.report_version_id}` : ""}`} key={assignment.assignment_id}><div className="meta"><span>{assignment.project_name}</span><span>·</span><span>{queueLabel(assignment.review_status)}</span></div><h3>{assignment.topic}</h3><p>{t("dashboard.assigned_by", undefined, { name: assignment.requested_by })}</p></Link>)}
            <div className="queue-empty">{pendingAssignments.length ? t("dashboard.queue_help") : t("dashboard.queue_empty")}</div>
          </aside>
        </div>

        {feedback.length > 0 && (
          <section className="feedback-section">
            <div className="panel-title"><h2>{t("dashboard.recent_feedback")}</h2><span>{t("dashboard.items", undefined, { count: feedback.length })}</span></div>
            {feedback.slice(0, 5).map((item) => <article className="feedback-item" key={item.feedback_id}><span className={`feedback-decision ${item.verdict}`}>{feedbackLabel(item.verdict)}</span><p>{item.note || t("common.no_note")}</p><small>{new Date(item.created_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US")}</small></article>)}
          </section>
        )}

        <section className="registry" id="registry">
          <div className="registry-head"><div><div className="eyebrow">{t("dashboard.registry")}</div><h2>{t("dashboard.registry_title")}</h2><p>{t("dashboard.registry_intro")}</p></div><span className="folio">{t("dashboard.dossiers", undefined, { count: total, year: new Date().getFullYear() })}</span></div>
          <div className="registry-list">
            {projects.map((project, index) => {
              const reviews = reviewsByProject[project.project_id] ?? [];
              const projectState = state(reviews);
              return <div className="registry-row-wrap" key={project.project_id}><Link className="registry-row" href={`/workspace?project=${project.project_id}`}><span className="reg-no">{String(index + 1).padStart(3, "0")}</span><span className="reg-name"><strong>{project.name}</strong><span>{project.description || t("dashboard.no_description")}</span></span><span className="reg-note">{t("dashboard.question_approved", undefined, { questions: reviews.length, approved: reviews.filter((review) => review.status === "approved").length })}</span><span className={`reg-status ${projectState}`}><i />{reviews.length ? stateText(projectState) : t("common.ready")}</span><span className="reg-time">{new Date(project.updated_at).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US")}</span><span className="reg-arrow"><Icon name="arrow" /></span></Link><Link className="reg-synth-chip" href={`/projects/${project.project_id}/synthesis`} aria-label={t("nav.synthesis")} title={t("nav.synthesis")}><Icon name="synthesis" /></Link></div>;
            })}
            <Link className="new-record" href="/projects/new"><b><Icon name="plus" /></b><span>{t("dashboard.new_record")}</span></Link>
          </div>
        </section>
      </main>
    </div>
  );
}

export default function DeskHome() {
  return configured ? <DeskHomeData /> : <DeskHomeUnavailable />;
}

function DeskHomeUnavailable() {
  const { t } = useLanguage();
  return <main className="mock-loading"><p>{t("dashboard.no_projects_auth")}</p><Link className="btn-primary" href="/auth">{t("common.sign_in")} →</Link></main>;
}
