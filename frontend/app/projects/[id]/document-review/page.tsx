"use client";

import Link from "next/link";
import { useAuth } from "@clerk/nextjs";
import { ChangeEvent, use, useCallback, useRef, useState } from "react";

type ClaimCitationEvidence = {
  verdict: "supported" | "partially_supported" | "contradicted" | "unverifiable";
  confidence: number;
  citation_label: string;
  doi?: string;
  source_scope: "abstract" | "metadata_only";
  paper?: { title?: string; authors?: string[]; year?: number; url?: string };
  evidence_quotes?: string[];
  atomic_subclaims?: string[];
  limitations?: string[];
};

type Annotation = {
  annotation_id: string;
  type: "suggest" | "warning" | "verification";
  anchor: { exact: string; prefix?: string; suffix?: string };
  aspect: string;
  comment: string;
  suggested_fix?: string;
  evidence?: ClaimCitationEvidence | Record<string, unknown>;
  status: "pending" | "accepted" | "rejected" | "dismissed";
};

type Review = {
  review_id: string;
  filename: string;
  title: string;
  source_format: "pdf" | "tex" | "tex_bundle";
  extraction_method: "llamaparse" | "pypdf" | "latex" | "unknown";
  content: string;
  annotations: Annotation[];
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
const ASPECT_LABELS: Record<string, string> = {
  clarity: "Rõ nghĩa",
  grammar: "Ngữ pháp",
  terminology: "Thuật ngữ",
  flow: "Mạch văn",
  redundancy: "Trùng lặp",
  academic_tone: "Văn phong học thuật",
  broken_link: "Liên kết lỗi",
  citation_not_found: "Không tìm thấy trích dẫn",
  missing_asset: "Thiếu tệp hình",
  pdf_conversion: "Đối chiếu bản gốc",
  extraction_artifact: "Ký tự trích xuất lỗi",
  claim_citation: "Đối chiếu luận điểm – trích dẫn",
};

const VERDICT_LABELS: Record<ClaimCitationEvidence["verdict"], string> = {
  supported: "Được hỗ trợ",
  partially_supported: "Hỗ trợ một phần",
  contradicted: "Mâu thuẫn",
  unverifiable: "Chưa thể kiểm chứng",
};

function claimEvidence(annotation: Annotation): ClaimCitationEvidence | undefined {
  if (annotation.type !== "verification" || !annotation.evidence) return undefined;
  const evidence = annotation.evidence as ClaimCitationEvidence;
  return evidence.verdict ? evidence : undefined;
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "Không thể hoàn tất yêu cầu. Hãy thử lại.";
}

export default function DocumentReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { getToken } = useAuth();
  const { id: projectId } = use(params);
  const [review, setReview] = useState<Review>();
  const [content, setContent] = useState("");
  const [selection, setSelection] = useState("");
  const [explanation, setExplanation] = useState("");
  const [rewrite, setRewrite] = useState<{ oldText: string; newText: string }>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const token = await getToken();
    const headers = new Headers(init.headers);
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(`${API}${path}`, { ...init, headers, cache: "no-store" });
    if (!response.ok) {
      const body = await response.json().catch(() => null) as { detail?: { message?: string } | string } | null;
      const detail = typeof body?.detail === "string" ? body.detail : body?.detail?.message;
      throw new Error(detail || `Yêu cầu thất bại (HTTP ${response.status}).`);
    }
    return response.json() as Promise<T>;
  }, [getToken]);

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !projectId) return;
    setBusy(true); setError(""); setExplanation(""); setRewrite(undefined);
    try {
      const form = new FormData(); form.append("document", file);
      const next = await request<Review>(`/projects/${projectId}/document-reviews`, { method: "POST", body: form });
      setReview(next); setContent(next.content);
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); event.target.value = ""; }
  };

  const sync = async () => {
    if (!review || !projectId) return;
    setSaving(true);
    try {
      const next = await request<Review>(`/projects/${projectId}/document-reviews/${review.review_id}/content`, {
        method: "PUT", body: JSON.stringify({ content }),
      });
      setReview(next); setContent(next.content);
    } finally { setSaving(false); }
  };

  const reanalyze = async () => {
    if (!review || !projectId) return;
    setBusy(true); setError("");
    try {
      await sync();
      const next = await request<Review>(`/projects/${projectId}/document-reviews/${review.review_id}/reanalyze`, { method: "POST" });
      setReview(next); setContent(next.content);
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); }
  };

  const verifyClaims = async () => {
    if (!review || !projectId) return;
    setBusy(true); setVerifying(true); setError("");
    try {
      await sync();
      const next = await request<Review>(`/projects/${projectId}/document-reviews/${review.review_id}/verify-claims`, { method: "POST" });
      setReview(next); setContent(next.content);
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); setVerifying(false); }
  };

  const decide = async (annotation: Annotation, action: "accept" | "reject" | "dismiss") => {
    if (!review || !projectId) return;
    setBusy(true); setError("");
    try {
      await sync();
      const next = await request<Review>(`/projects/${projectId}/document-reviews/${review.review_id}/annotations/${annotation.annotation_id}`, {
        method: "PATCH", body: JSON.stringify({ action }),
      });
      setReview(next); setContent(next.content);
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); }
  };

  const selectedText = () => {
    const node = editorRef.current;
    if (!node) return undefined;
    const start = node.selectionStart;
    const end = node.selectionEnd;
    const text = node.value.slice(start, end);
    setSelection(text); setExplanation(""); setRewrite(undefined);
    return {
      selected_text: text,
      prefix: node.value.slice(Math.max(0, start - 32), start),
      suffix: node.value.slice(end, end + 32),
    };
  };

  const revealAnnotation = (annotation: Annotation) => {
    const node = editorRef.current;
    if (!node) return;
    const { exact, prefix = "", suffix = "" } = annotation.anchor;
    const candidates: number[] = [];
    let cursor = node.value.indexOf(exact);
    while (cursor >= 0) {
      candidates.push(cursor);
      cursor = node.value.indexOf(exact, cursor + exact.length);
    }
    const start = candidates.length === 1 ? candidates[0] : candidates.find((position) => {
      const before = node.value.slice(Math.max(0, position - prefix.length), position);
      const after = node.value.slice(position + exact.length, position + exact.length + suffix.length);
      return (!prefix || before === prefix) && (!suffix || after === suffix);
    });
    if (start === undefined) {
      setError("Đoạn được đánh dấu đã thay đổi. Hãy rà soát lại tài liệu để cập nhật cảnh báo.");
      return;
    }
    setError("");
    node.focus();
    node.setSelectionRange(start, start + exact.length);
    setSelection(exact);
    const scrollRange = Math.max(0, node.scrollHeight - node.clientHeight);
    node.scrollTop = node.value.length ? scrollRange * (start / node.value.length) : 0;
  };

  const aiAction = async (kind: "explain" | "rewrite") => {
    if (!review || !projectId) return;
    const selectionContext = selectedText();
    const text = selectionContext?.selected_text ?? "";
    if (!text) { setError("Hãy bôi chọn một đoạn trong tài liệu trước."); return; }
    setBusy(true); setError("");
    try {
      await sync();
      const next = await request<{ explanation?: string; old_text?: string; new_text?: string }>(`/projects/${projectId}/document-reviews/${review.review_id}/${kind}`, {
        method: "POST", body: JSON.stringify({ selected_text: text, prefix: selectionContext?.prefix ?? "", suffix: selectionContext?.suffix ?? "" }),
      });
      if (kind === "explain") {
        setExplanation(next.explanation ?? ""); setRewrite(undefined);
      } else {
        setRewrite({ oldText: next.old_text ?? text, newText: next.new_text ?? "" });
        setExplanation("");
      }
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); }
  };

  const applyRewrite = async () => {
    if (!review || !projectId || !rewrite) return;
    setBusy(true); setError("");
    try {
      await sync();
      const next = await request<Review>(`/projects/${projectId}/document-reviews/${review.review_id}/apply`, {
        method: "POST", body: JSON.stringify({ old_text: rewrite.oldText, new_text: rewrite.newText }),
      });
      setReview(next); setContent(next.content); setSelection(""); setRewrite(undefined);
    } catch (cause) { setError(messageFrom(cause)); }
    finally { setBusy(false); }
  };

  const pending = review?.annotations.filter((item) => item.status === "pending") ?? [];
  return <main className="document-review-page">
    <header className="document-review-header">
      <Link href={projectId ? `/workspace?project=${projectId}` : "/workspace"}>← Không gian nghiên cứu</Link>
      <span>Document review</span>
    </header>

    <section className="document-review-intro">
      <h1>Rà soát bản thảo nghiên cứu</h1>
      <p>Tải lên PDF, LaTeX hoặc gói Overleaf. Hệ thống giữ các cảnh báo để bạn tự quyết định, và chỉ tự áp dụng những gợi ý có thay thế rõ ràng.</p>
      <label className={`document-upload ${busy ? "is-busy" : ""}`}>
        <input type="file" accept=".pdf,.tex,.zip,application/pdf,application/zip" onChange={upload} disabled={busy || !projectId} />
        <strong>{busy ? "Đang đọc tài liệu…" : "Chọn tài liệu để rà soát"}</strong>
        <span>PDF · TEX · ZIP Overleaf · tối đa 20 MB</span>
      </label>
      {error && <p className="document-review-error" role="alert">{error}</p>}
    </section>

    {review && <section className="document-review-workspace" aria-label="Document review workspace">
      <div className="document-editor-column">
        <div className="document-title-row"><div><h2>{review.title}</h2><span>{review.filename} · {review.source_format.toUpperCase()} · {review.extraction_method === "llamaparse" ? "LlamaParse" : review.extraction_method === "pypdf" ? "pypdf fallback" : "LaTeX gốc"}</span></div><div className="document-title-actions"><button className="verify-claims" onClick={() => void verifyClaims()} disabled={saving || busy}>{verifying ? "Đang kiểm chứng…" : "Kiểm chứng trích dẫn"}</button><button onClick={() => void reanalyze()} disabled={saving || busy}>Rà soát lại</button><button onClick={() => void sync()} disabled={saving || busy}>{saving ? "Đang lưu…" : "Lưu nội dung"}</button></div></div>
        <textarea ref={editorRef} value={content} onChange={(event) => setContent(event.target.value)} onSelect={selectedText} spellCheck={false} aria-label="Editable document content" />
        <div className="document-selection-actions"><span>{selection ? `${selection.length} ký tự đã chọn` : "Bôi chọn văn bản để dùng trợ lý AI"}</span><button onClick={() => void aiAction("explain")} disabled={busy}>Giải thích</button><button onClick={() => void aiAction("rewrite")} disabled={busy}>Viết lại</button></div>
        {explanation && <div className="document-ai-result"><strong>Giải thích</strong><p>{explanation}</p></div>}
        {rewrite && <div className="document-ai-result"><strong>Đề xuất viết lại</strong><div className="document-suggestion-diff"><p><span>Đoạn gốc</span>{rewrite.oldText}</p><p className="replacement"><span>Đề xuất</span>{rewrite.newText}</p></div><button onClick={() => void applyRewrite()} disabled={busy}>Áp dụng thay thế</button></div>}
      </div>
      <aside className="document-annotations">
        <div><h2>Điểm cần rà soát</h2><span>{pending.length} đang chờ</span></div>
        {pending.length === 0 ? <p className="document-empty">Không còn annotation đang chờ. Bạn vẫn có thể chỉnh sửa và lưu bản thảo.</p> : pending.map((item) => {
          const evidence = claimEvidence(item);
          const itemLabel = item.type === "verification" ? "Kiểm chứng" : item.type === "warning" ? "Cảnh báo" : "Gợi ý";
          return <article className={`document-annotation ${item.type} ${evidence?.verdict ?? ""}`} key={item.annotation_id}>
            <strong>{itemLabel} · {ASPECT_LABELS[item.aspect] ?? item.aspect}</strong>
            {evidence && <div className="document-verdict-row">
              <span>{VERDICT_LABELS[evidence.verdict]}</span>
            </div>}
            <p>{item.comment}</p>
            {item.type === "suggest" ? <div className="document-suggestion-diff"><p><span>Đoạn gốc</span>{item.anchor.exact}</p><p className="replacement"><span>Đề xuất</span>{item.suggested_fix}</p></div> : evidence ? <div className="document-verification-evidence">
              <div className="document-warning-excerpt"><span>Luận điểm</span><blockquote title={item.anchor.exact}>{item.anchor.exact}</blockquote></div>
              <p className="document-source-title"><span>[{evidence.citation_label}]</span> {evidence.paper?.title || evidence.doi || "Chưa phân giải được nguồn"}{evidence.paper?.year ? ` (${evidence.paper.year})` : ""}</p>
              {evidence.evidence_quotes?.map((quote) => <blockquote className="document-evidence-quote" key={quote}>{quote}</blockquote>)}
              {evidence.limitations?.[0] && <p className="document-verification-limit">{evidence.limitations[0]}</p>}
              {evidence.paper?.url && <a className="document-source-link" href={evidence.paper.url} target="_blank" rel="noreferrer">Mở nguồn</a>}
            </div> : <div className="document-warning-excerpt"><span>Đoạn cần kiểm tra</span><blockquote title={item.anchor.exact}>{item.anchor.exact}</blockquote></div>}
            <div className="document-annotation-actions"><button className="document-anchor-action" onClick={() => revealAnnotation(item)} disabled={busy}>Xem trong bản thảo</button>{item.type === "suggest" && <button className="accept" onClick={() => void decide(item, "accept")} disabled={busy}>Chấp nhận</button>}<button onClick={() => void decide(item, "reject")} disabled={busy}>{item.type === "suggest" ? "Từ chối" : "Đã kiểm tra"}</button><button className="quiet" onClick={() => void decide(item, "dismiss")} disabled={busy}>Bỏ qua</button></div>
          </article>;
        })}
      </aside>
    </section>}
  </main>;
}
