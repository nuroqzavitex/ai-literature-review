import type { Conversation, JobStatus, Message, Review } from "../../_components/workspace-types";

const ANNOTATION_CONTEXT_MARKER = "\n\nCác đoạn tham chiếu được chọn:\n";

export type WorkspaceSession = Conversation & {
  updated_at?: string;
  created_at?: string;
  title?: string;
};

export function queuedFlowStatus(
  review: Pick<Review, "job_id" | "status">,
  executionMode: "review" | "autonomous",
): JobStatus {
  return {
    job_id: review.job_id,
    status: review.status,
    current_node: "queued",
    papers_found: 0,
    valid_claims: 0,
    search_attempt: 0,
    grounding_revision_attempt: 0,
    review_revision_attempt: 0,
    search_query: null,
    query_history: [],
    sub_queries: [],
    selected_paper_ids: [],
    hitl_stage: null,
    execution_mode: executionMode,
    last_decision: null,
    warnings: [],
    node_trace: [],
    papers: [],
    error: null,
  };
}

export function asWorkspaceMessage(value: unknown): Message | null {
  if (!value || typeof value !== "object") return null;

  const row = value as Record<string, unknown>;
  if (typeof row.message_id !== "string" || typeof row.text !== "string") return null;

  const [, annotationText] = row.text.split(ANNOTATION_CONTEXT_MARKER, 2);
  const annotations = annotationText
    ? annotationText
      .split(/\n\n(?=Annotation \d+:\n)/)
      .map((item) => item.replace(/^Annotation \d+:\n/, "").trim())
      .filter(Boolean)
    : [];

  return {
    message_id: row.message_id,
    client_message_id: typeof row.client_message_id === "string" ? row.client_message_id : null,
    role: row.role === "assistant" ? "assistant" : "user",
    message_type: typeof row.message_type === "string" ? row.message_type : "message",
    text: row.text,
    citations: Array.isArray(row.citations) ? row.citations as Message["citations"] : [],
    annotations,
  };
}

export function restoreResearchPrompts(items: Message[], reviews: Review[]): Message[] {
  const existingTopics = new Set(
    items.filter((item) => item.role === "user").map((item) => item.text.trim().toLowerCase()),
  );
  const missing = reviews
    .filter((review) => review.topic.trim() && !existingTopics.has(review.topic.trim().toLowerCase()))
    .map((review) => ({
      message_id: `research-topic:${review.job_id}`,
      client_message_id: `review:${review.job_id}`,
      role: "user" as const,
      message_type: "user_message",
      text: review.topic,
      citations: [],
    }));

  return [...missing, ...items];
}

export function persistentIdentifier(reference: { doi?: string | null; url?: string | null }) {
  const rawDoi = (reference.doi || reference.url?.match(/(?:https?:\/\/)?(?:dx\.)?doi\.org\/(10\.\d{4,9}\/[\-._;()\/:a-z0-9]+)/i)?.[1] || "")
    .replace(/^doi:\s*/i, "")
    .replace(/^(?:https?:\/\/)?(?:dx\.)?doi\.org\//i, "")
    .replace(/[.,;]+$/, "");
  if (/^10\.\d{4,9}\//i.test(rawDoi)) return { href: `https://doi.org/${rawDoi}`, label: `doi.org/${rawDoi}` };

  const arxivId = reference.url?.match(/arxiv\.org\/(?:abs|pdf)\/(\d{4}\.\d{4,5}(?:v\d+)?)/i)?.[1];
  return arxivId ? { href: `https://arxiv.org/abs/${arxivId}`, label: `arxiv.org/abs/${arxivId}` } : null;
}
