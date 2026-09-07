"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useAuth, useUser, UserButton } from "@clerk/nextjs";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { JobStatus, Message, Project, Review, ReviewResult } from "./workspace-types";
import type { SandboxCapabilities } from "../_types/sandbox";
import { useLanguage } from "./language-context";
import { authenticatedJson } from "../_lib/authenticated-fetch";
import LanguageToggle from "./LanguageToggle";
import {
  asWorkspaceMessage,
  persistentIdentifier,
  queuedFlowStatus,
  restoreResearchPrompts,
  type WorkspaceSession as Session,
} from "../_features/workspace/model";

const configured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);
const ACTIVE = new Set(["queued", "running", "resuming", "hitl_waiting"]);
const DELETE_BLOCKING = new Set(["queued", "running", "resuming"]);
const PERSISTENT_IDENTIFIER = /((?:https?:\/\/)?(?:dx\.)?doi\.org\/10\.\d{4,9}\/[\-._;()/:a-z0-9]+|(?:https?:\/\/)?arxiv\.org\/(?:abs|pdf)\/\d{4}\.\d{4,5}(?:v\d+)?)/gi;
const ANNOTATION_CONTEXT_MARKER = "\n\nCác đoạn tham chiếu được chọn:\n";
const FLOW_STEPS = ["queued", "intent_guardrail", "plan_search", "review_subqueries", "waiting_for_subqueries", "search_academic_sources", "assess_sources", "refine_query", "screen_papers", "review_papers", "waiting_for_papers", "extract_evidence", "synthesize_claims", "validate_grounding", "revise_claims", "human_review", "hitl_review", "query_shaping", "gap_search", "gap_extraction", "gap_indexing", "topical_detector", "method_detector", "contradiction_detector", "origin_labeling", "verifier", "counter_evidence", "quality_scoring", "deduplicate", "synthesize", "finalize"];
const HIDDEN_FLOW_NODES = new Set(["analyze_research_gaps", "compose_literature_review"]);
const FLOW_LABELS: Record<string, string> = { queued: "Đang xếp hàng", intent_guardrail: "Phân loại yêu cầu", plan_search: "Lập kế hoạch tìm kiếm", review_subqueries: "Rà soát truy vấn", waiting_for_subqueries: "Chờ duyệt truy vấn", search_academic_sources: "Tìm kiếm nguồn học thuật", search_openalex: "Tìm kiếm nguồn học thuật", assess_sources: "Đánh giá nguồn", refine_query: "Tinh chỉnh truy vấn", screen_papers: "Xếp hạng bài báo", review_papers: "Rà soát bài báo", waiting_for_papers: "Chờ chọn bài báo", extract_evidence: "Trích xuất bằng chứng", synthesize_claims: "Tổng hợp luận điểm", validate_grounding: "Kiểm chứng luận điểm", revise_claims: "Hiệu chỉnh kết quả", human_review: "Chuẩn bị phản biện", hitl_review: "Chờ phản biện", query_shaping: "Chuẩn hoá truy vấn", gap_search: "Xây dựng và mở rộng corpus", gap_extraction: "Trích xuất bằng chứng cấu trúc", gap_indexing: "Chunk và embedding corpus", topical_detector: "Phát hiện gap chủ đề", method_detector: "Phát hiện gap phương pháp", contradiction_detector: "Phát hiện mâu thuẫn", origin_labeling: "Phân loại nguồn gốc gap", verifier: "Kiểm chứng atomic-NLI", counter_evidence: "Tìm phản bằng chứng", quality_scoring: "Chấm điểm chất lượng", deduplicate: "Loại trùng gap", synthesize: "Đóng gói báo cáo gap", finalize: "Hoàn thiện báo cáo" };
const FLOW_KEYS: Record<string, string> = { queued: "queued", intent_guardrail: "intent_guardrail", plan_search: "plan_search", review_subqueries: "review_subqueries", waiting_for_subqueries: "waiting_for_subqueries", search_academic_sources: "search_academic_sources", search_openalex: "search_academic_sources", assess_sources: "assess_sources", refine_query: "refine_query", screen_papers: "screen_papers", review_papers: "review_papers", waiting_for_papers: "waiting_for_papers", extract_evidence: "extract_evidence", synthesize_claims: "synthesize_claims", validate_grounding: "validate_grounding", revise_claims: "revise_claims", human_review: "human_review", hitl_review: "hitl_review", query_shaping: "query_shaping", gap_search: "gap_search", gap_extraction: "gap_extraction", gap_indexing: "gap_indexing", topical_detector: "topical_detector", method_detector: "method_detector", contradiction_detector: "contradiction_detector", origin_labeling: "origin_labeling", verifier: "verifier", counter_evidence: "counter_evidence", quality_scoring: "quality_scoring", deduplicate: "deduplicate", synthesize: "synthesize", finalize: "finalize" };

function flowLabel(node: string, t: ReturnType<typeof useLanguage>["t"]) {
  const key = FLOW_KEYS[node];
  return key ? t(`flow.${key}` as never, FLOW_LABELS[node] ?? node) : node;
}

const INLINE_FORMATTING = /(\*\*[^*\n]+?\*\*|\$(?:\\.|[^$\n])+\$|\\\((?:\\.|[^)\n])+\\\))/g;

function readableMath(value: string) {
  const symbols: Record<string, string> = {
    alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", theta: "θ",
    lambda: "λ", mu: "μ", pi: "π", sigma: "σ", phi: "φ", omega: "ω",
  };
  return value
    .replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, "$1/$2")
    .replace(/\\sqrt\{([^{}]+)\}/g, "√$1")
    .replace(/\\(?:text|mathrm|mathbf|mathit)\{([^{}]+)\}/g, "$1")
    .replace(/\\(alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|phi|omega)\b/g, (_match, name: string) => symbols[name])
    .replaceAll("\\times", "×")
    .replaceAll("\\cdot", "·")
    .replaceAll("\\leq", "≤")
    .replaceAll("\\geq", "≥")
    .replaceAll("\\neq", "≠")
    .replace(/\\([%_#$&{}])/g, "$1")
    .replace(/[{}]/g, "");
}

function InlineMarkup({ text }: { text: string }) {
  const parts = text.split(INLINE_FORMATTING);
  return <>{parts.map((part, index) => {
    if (index % 2 === 0) return part;
    if (part.startsWith("**")) return <strong key={`${part}:${index}`}>{part.slice(2, -2)}</strong>;
    const math = part.startsWith("$") ? part.slice(1, -1) : part.slice(2, -2);
    return <span className="claude-inline-math" key={`${part}:${index}`}>{readableMath(math)}</span>;
  })}</>;
}

function IdentifierText({ text }: { text: string }) {
  const parts = text.split(PERSISTENT_IDENTIFIER);
  return <>{parts.map((part, index) => {
    if (index % 2 === 0) return <InlineMarkup key={index} text={part} />;
    const href = part.startsWith("http") ? part : `https://${part}`;
    return <a className="claude-bibliography-identifier" href={href} key={`${part}:${index}`} target="_blank" rel="noreferrer">{part}</a>;
  })}</>;
}

const CITATION_TOKEN = /\[\[cite:(\d+):(https:\/\/[^\]]+)\]\]/g;

function citationToken(number: number | undefined, url: string | undefined) {
  return number && url?.startsWith("https://") ? `[[cite:${number}:${url}]]` : "";
}

function withReferenceNumbers(text: string, references: ReviewResult["references"], referenceNumbers: Map<string, number>) {
  const numericCitation = (alias: string) => {
    const number = Number(alias);
    const reference = references[number - 1];
    return citationToken(number, reference?.url);
  };
  const sourceCitation = (paperId: string) => {
    const reference = references.find((item) => item.paper_id === paperId);
    return citationToken(referenceNumbers.get(paperId), reference?.url);
  };

  return text
    .replace(/\[\[(?:paper\s*|p|r)?(\d+)\](?!\])/gi, (_match, alias: string) => numericCitation(alias))
    .replace(/(?<!\[)\[(?:paper\s*|p|r)?(\d+)\]+/gi, (_match, alias: string) => numericCitation(alias))
    .replace(/\[\[([A-Za-z0-9_.:-]+)\]\]/g, (_match, paperId: string) => sourceCitation(paperId));
}

function buildReportAnswer(result: ReviewResult): Message {
  if (result.intent !== "litreview" && result.assistant_response) {
    return {
      message_id: `research-report:${result.job_id}`,
      client_message_id: `research_report:${result.job_id}`,
      role: "assistant",
      message_type: "research_report",
      text: result.assistant_response,
      citations: [],
    };
  }
  const vietnamese = result.response_language
    ? result.response_language === "Vietnamese"
    : /[àáạảãâầấậẩẫèéẹẻẽêềếệểễòóọỏõôồốộổỗùúụủũưừứựửữìíịỉĩỳýỵỷỹđơ]/i.test(result.topic) || /\b(tôi|bạn|cho|các|bài|báo|về|nghiên cứu|tổng hợp|giải thích)\b/i.test(result.topic);
  const copy = vietnamese
    ? { unknownAuthor: "Không rõ tác giả", noEvidence: "Chưa có luận điểm đủ bằng chứng." }
    : { unknownAuthor: "Unknown authors", noEvidence: "No evidence-backed claim was extracted for this paper." };
  const referenceNumbers = new Map(result.references.map((reference, index) => [reference.paper_id, index + 1]));
  const fallbackSections = (result.themes ?? []).flatMap((theme) => {
    const claim = result.claims.find((item) => item.claim_id === theme.summary_claim_id);
    const citations = (claim?.supporting_paper_ids ?? theme.supporting_paper_ids ?? [])
      .map((paperId) => citationToken(referenceNumbers.get(paperId), result.references.find((reference) => reference.paper_id === paperId)?.url))
      .filter(Boolean)
      .join(" ");
    return claim ? [`## ${theme.title}`, `${claim.text}${citations ? ` ${citations}` : ""}`] : [];
  });
  const gapSections = (result.potential_gaps ?? []).flatMap((gap, index) => {
    const citations = (gap.coverage ?? [])
      .filter((coverage) => coverage.mentioned)
      .map((coverage) => citationToken(referenceNumbers.get(coverage.paper_id), result.references.find((reference) => reference.paper_id === coverage.paper_id)?.url))
      .filter(Boolean)
      .join(" ");
    const title = vietnamese ? `Khoảng trống ${index + 1}: ${gap.aspect}` : `Gap ${index + 1}: ${gap.aspect}`;
    const details = [
      gap.reviewer_rationale,
      gap.suggested_method ? (vietnamese ? `Đề xuất kiểm chứng: ${gap.suggested_method}` : `Suggested method: ${gap.suggested_method}`) : "",
      gap.falsification_condition ? (vietnamese ? `Điều kiện bác bỏ: ${gap.falsification_condition}` : `Falsification condition: ${gap.falsification_condition}`) : "",
    ].filter(Boolean);
    return [`## ${title}`, `${gap.scope_statement}${citations ? ` ${citations}` : ""}`, ...details];
  });
  const literatureReview = result.literature_review;
  const articleLabels = vietnamese
    ? { introduction: "Giới thiệu", conclusion: "Kết luận", references: "Tài liệu tham khảo" }
    : { introduction: "Introduction", conclusion: "Conclusion", references: "References" };
  const articleLines = literatureReview
    ? [
      `## ${articleLabels.introduction}`,
      withReferenceNumbers(literatureReview.introduction, result.references, referenceNumbers),
      ...literatureReview.sections.flatMap((section) => [
        `## ${section.title}`,
        ...section.paragraphs.map((paragraph) => withReferenceNumbers(paragraph, result.references, referenceNumbers)),
      ]),
      `## ${articleLabels.conclusion}`,
      withReferenceNumbers(literatureReview.conclusion, result.references, referenceNumbers),
    ]
    : result.intent === "research_gap"
      ? (gapSections.length
        ? [
          `## ${vietnamese ? "Bản đồ khoảng trống nghiên cứu" : "Research gap map"}`,
          ...(result.narrative ? [result.narrative] : []),
          ...gapSections,
        ]
        : [`## ${vietnamese ? "Bản đồ khoảng trống nghiên cứu" : "Research gap map"}`, vietnamese ? "Không có khoảng trống nào vượt qua các bước kiểm chứng; hãy mở rộng hoặc tinh chỉnh chủ đề." : "No candidate passed the verification gates; broaden or refine the topic."])
      : [
        ...(fallbackSections.length
          ? fallbackSections
          : [`## ${vietnamese ? "Tổng hợp" : "Synthesis"}`, copy.noEvidence]),
      ];
  const bibliography = result.references.map((reference, index) => {
    const authors = reference.authors?.slice(0, 3).join(", ") || copy.unknownAuthor;
    const year = reference.year ? ` (${reference.year})` : "";
    const identifier = persistentIdentifier(reference);
    return `- ${citationToken(index + 1, reference.url)} ${authors}${year}. ${reference.title}${identifier ? `. ${identifier.label}` : ""}`;
  });
  return {
    message_id: `research-report:${result.job_id}`,
    client_message_id: `research_report:${result.job_id}`,
    role: "assistant",
    message_type: "research_report",
    text: [
      ...articleLines,
      "", `## ${literatureReview ? articleLabels.references : (vietnamese ? "Tài liệu tham khảo" : "References")}`,
      ...bibliography,
    ].join("\n"),
    citations: [],
  };
}

function escapeLatexText(value: string) {
  return value
    .replaceAll("\\", "\\textbackslash{}")
    .replaceAll("&", "\\&")
    .replaceAll("%", "\\%")
    .replaceAll("$", "\\$")
    .replaceAll("#", "\\#")
    .replaceAll("_", "\\_")
    .replaceAll("{", "\\{")
    .replaceAll("}", "\\}");
}

function latexLineWithCitations(value: string) {
  const parts = value.split(CITATION_TOKEN);
  return parts.map((part, index) => {
    if (index % 3 !== 0) return "";
    const number = parts[index + 1];
    const url = parts[index + 2];
    return `${escapeLatexText(part)}${number && url ? `\\cite{ref${number}}` : ""}`;
  }).join("");
}

function safeLatexUrl(value: string) {
  return value
    .replaceAll("\\", "%5C")
    .replaceAll("{", "%7B")
    .replaceAll("}", "%7D")
    .replaceAll(/\s/g, "%20");
}

function latexBibliography(references: ReviewResult["references"], heading: string) {
  const unknownAuthors = heading === "References" ? "Unknown authors" : "Không rõ tác giả";
  if (!references.length) {
    const emptyMessage = heading === "References" ? "No references available." : "Không có tài liệu tham khảo.";
    return `\\section*{${escapeLatexText(heading)}}\n${escapeLatexText(emptyMessage)}`;
  }
  const entries = references.map((reference, index) => {
    const authors = reference.authors?.join(", ") || unknownAuthors;
    const year = reference.year ? String(reference.year) : "n.d.";
    const identifier = persistentIdentifier(reference);
    const sourceUrl = identifier?.href || reference.url;
    return `\\bibitem{ref${index + 1}} ${escapeLatexText(authors)} (${escapeLatexText(year)}). ${escapeLatexText(reference.title)}. \\newblock \\url{${safeLatexUrl(sourceUrl)}}`;
  });
  return [
    `\\renewcommand{\\refname}{${escapeLatexText(heading)}}`,
    `\\begin{thebibliography}{${Math.max(9, references.length)}}`,
    ...entries,
    "\\end{thebibliography}",
  ].join("\n");
}

function upgradeLegacyBibliography(latex: string, result: ReviewResult) {
  if (latex.includes("\\begin{thebibliography}")) return latex;
  const legacyBibliography = /\\section\{[^{}]*\}\s*\\begin\{itemize\}[\s\S]*?\\end\{itemize\}(?=\s*\\end\{document\})/;
  const match = latex.match(legacyBibliography);
  if (!match) return latex;
  const heading = match[0].match(/^\\section\{([^{}]*)\}/)?.[1] || "References";
  return latex.replace(legacyBibliography, latexBibliography(result.references, heading));
}

function reportToLatex(result: ReviewResult) {
  const lines = buildReportAnswer(result).text.split("\n");
  const bibliographyHeadingIndex = Math.max(0, lines.length - result.references.length - 1);
  const bibliographyHeading = lines[bibliographyHeadingIndex]?.replace(/^##\s+/, "") || "References";
  const reportLines = lines.slice(0, bibliographyHeadingIndex);
  const body: string[] = [];
  let inList = false;
  const closeList = () => { if (inList) { body.push("\\end{itemize}"); inList = false; } };

  for (const rawLine of reportLines) {
    const line = rawLine.trim();
    if (!line) { closeList(); continue; }
    if (line.startsWith("## ")) { closeList(); body.push(`\\section{${latexLineWithCitations(line.slice(3))}}`); continue; }
    if (line.startsWith("### ")) { closeList(); body.push(`\\subsection{${latexLineWithCitations(line.slice(4))}}`); continue; }
    if (line.startsWith("- ")) {
      if (!inList) { body.push("\\begin{itemize}"); inList = true; }
      body.push(`  \\item ${latexLineWithCitations(line.slice(2))}`);
      continue;
    }
    closeList();
    body.push(latexLineWithCitations(line));
  }
  closeList();
  return [
    "\\documentclass[11pt]{article}",
    "\\usepackage[utf8]{inputenc}",
    "\\usepackage[T1]{fontenc}",
    "\\usepackage{hyperref}",
    "\\usepackage[margin=1in]{geometry}",
    `\\title{${escapeLatexText(result.topic)}}`,
    "\\date{}",
    "\\begin{document}",
    "\\maketitle",
    "",
    ...body,
    "",
    latexBibliography(result.references, bibliographyHeading),
    "",
    "\\end{document}",
  ].join("\n");
}

function latexToReportText(latex: string, references: ReviewResult["references"] = []) {
  const referenceHeading = latex.match(/\\renewcommand\{\\refname\}\{([^}]*)\}/)?.[1] || "References";
  const parsed = latex
    .replace(/^%.*$/gm, "")
    .replace(/^\\documentclass(?:\[[^\]]*\])?\{[^}]*\}\s*$/gm, "")
    .replace(/^\\usepackage(?:\[[^\]]*\])?\{[^}]*\}\s*$/gm, "")
    .replace(/^\\(?:title|date)\{.*?\}\s*$/gm, "")
    .replace(/\\renewcommand\{\\refname\}\{[^}]*\}/g, "")
    .replace(/\\(?:begin|end)\{document\}|\\maketitle/g, "")
    .replace(/\\begin\{thebibliography\}\{[^}]*\}/g, `\n\n## ${referenceHeading}\n`)
    .replace(/\\end\{thebibliography\}/g, "")
    .replace(/\\bibitem\{ref(\d+)\}/g, (_match, value: string) => {
      const reference = references[Number(value) - 1];
      return reference?.url?.startsWith("https://") ? `- [[cite:${value}:${reference.url}]] ` : `- [${value}] `;
    })
    .replace(/\\cite[a-zA-Z]*(?:\[[^\]]*\])?\{([^}]*)\}/g, (_match, keys: string) => keys.split(",").map((key) => {
      const number = key.trim().match(/^ref(\d+)$/)?.[1];
      const reference = number ? references[Number(number) - 1] : undefined;
      return number && reference?.url?.startsWith("https://") ? `[[cite:${number}:${reference.url}]]` : number ? `[${number}]` : "";
    }).filter(Boolean).join(" "))
    .replace(/\\newblock\s*/g, "")
    .replace(/\\url\{([^}]*)\}/g, "$1")
    .replace(/\\section\*?\{([^}]*)\}/g, "\n\n## $1\n")
    .replace(/\\subsection\*?\{([^}]*)\}/g, "\n### $1\n")
    .replace(/\\begin\{itemize\}|\\end\{itemize\}/g, "")
    .replace(/\\item(?:\[.*?\])?/g, "- ")
    .replace(/\\(?:textbf|emph|textit)\{([^}]*)\}/g, "$1")
    .replace(/\\href\{([^}]*)\}\{\[?(\d+)\]?\}/g, (_match, url: string, number: string) => `[[cite:${number}:${url}]]`)
    .replace(/\\([&#%$_{}])/g, "$1")
    .replace(/\\textbackslash\{\}/g, "\\")
    .replace(/\\[a-zA-Z]+(?:\[[^\]]*\])?/g, "")
    .replace(/[{}]/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return parsed.replace(/\[(\d+)\]/g, (match, value: string) => {
    const reference = references[Number(value) - 1];
    return reference?.url?.startsWith("https://") ? `[[cite:${value}:${reference.url}]]` : match;
  });
}

function downloadReportFile(content: BlobPart, filename: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function reportFilename(value: string) {
  return value.replaceAll(/[^a-z0-9]+/gi, "-").replaceAll(/^-|-$/g, "").toLowerCase() || "report";
}

function escapeReportHtml(value: string) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function escapeReportAttribute(value: string) {
  return escapeReportHtml(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function visualArtifactText(value: string) {
  return value.replace(/\s*\[+\s*(?:P?\d+\s*(?:,\s*P?\d+\s*)*)\]+/gi, "").replace(/\s{2,}/g, " ").trim();
}

function buildErrorAnswer(result: JobStatus): Message {
  const reason = result.error?.trim() || "Không tìm thấy tài liệu học thuật phù hợp với truy vấn này.";
  return {
    message_id: `research-error:${result.job_id}`,
    client_message_id: `research_error:${result.job_id}`,
    role: "assistant",
    message_type: "research_error",
    text: `Mình không thể tổng hợp cho yêu cầu này vì ${reason}`,
    citations: [],
  };
}

type GeneratedVisualArtifact = {
  title: string;
  overview: string;
  branches: { title: string; points: string[] }[];
  slides: { title: string; subtitle: string; points: string[]; speaker_notes: string; visual_prompt: string; visual_alt: string; image_data_url: string }[];
};

type ReportVisualArtifact = { report: ReviewResult; artifact: GeneratedVisualArtifact };

const MINDMAP_TONES = ["#d8535b", "#d8841b", "#23a8b8", "#47983e", "#7a4df0", "#dd63b7"];
const MINDMAP_WIDTH = 1600;
const MINDMAP_POINT_GAP = 92;

type MindMapLayout = {
  branch: GeneratedVisualArtifact["branches"][number];
  index: number;
  side: "left" | "right";
  branchX: number;
  branchY: number;
  leafX: number;
  tone: string;
};

function mindMapLayout(artifact: GeneratedVisualArtifact) {
  const leftCount = Math.floor(artifact.branches.length / 2);
  const sides = [
    { side: "left" as const, branches: artifact.branches.slice(0, leftCount), offset: 0 },
    { side: "right" as const, branches: artifact.branches.slice(leftCount), offset: leftCount },
  ];
  const slotHeight = (points: string[]) => Math.max(172, (points.length - 1) * MINDMAP_POINT_GAP + 142);
  const diagramHeight = Math.max(700, Math.max(...sides.map(({ branches }) => branches.reduce((total, branch) => total + slotHeight(branch.points), 0))) + 100);
  const centerY = diagramHeight / 2;
  const layouts: MindMapLayout[] = sides.flatMap(({ side, branches, offset }) => {
    const span = branches.reduce((total, branch) => total + slotHeight(branch.points), 0);
    let cursor = (diagramHeight - span) / 2;
    return branches.map((branch, sideIndex) => {
      const branchY = cursor + slotHeight(branch.points) / 2;
      cursor += slotHeight(branch.points);
      const index = offset + sideIndex;
      // Keep a visible breathing gap between the root (630–970) and the
      // branch cards (375–625 / 975–1225); the previous 520/1080 centers
      // overlapped the root by 15px and made the hierarchy look fused.
      return { branch, index, side, branchX: side === "left" ? 485 : 1115, branchY, leafX: side === "left" ? 145 : 1455, tone: MINDMAP_TONES[index % MINDMAP_TONES.length] };
    });
  });
  return { centerY, diagramHeight, layouts };
}

function wrapMindMapExportText(value: string, limit: number) {
  const words = value.trim().split(/\s+/);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (`${line} ${word}`.trim().length > limit && line) { lines.push(line); line = word; }
    else line = `${line} ${word}`.trim();
  }
  if (line) lines.push(line);
  return lines.slice(0, 5);
}

function mindMapSvgText(value: string, x: number, y: number, width: number, size: number, color: string, weight = 400) {
  const lines = wrapMindMapExportText(visualArtifactText(value), Math.max(12, Math.floor(width / (size * .55))));
  const lineHeight = Math.round(size * 1.35);
  const start = y - ((lines.length - 1) * lineHeight) / 2;
  return `<text x="${x}" y="${start}" text-anchor="middle" fill="${color}" font-family="Arial, sans-serif" font-size="${size}" font-weight="${weight}">${lines.map((line, index) => `<tspan x="${x}" dy="${index ? lineHeight : 0}">${escapeReportHtml(line)}</tspan>`).join("")}</text>`;
}

function mindMapPointCountLabel(count: number) {
  return `${count} key ${count === 1 ? "point" : "points"}`;
}

function mindMapSvgMarkup(artifact: GeneratedVisualArtifact) {
  const { centerY, diagramHeight, layouts } = mindMapLayout(artifact);
  const paths = layouts.flatMap((layout) => {
    const branchControl = layout.side === "left" ? 660 : 940;
    const leafStartControl = layout.side === "left" ? 410 : 1190;
    const leafEndControl = layout.side === "left" ? 230 : 1370;
    return [
      `<path d="M800 ${centerY} C${branchControl} ${centerY} ${branchControl} ${layout.branchY} ${layout.branchX} ${layout.branchY}" stroke="${layout.tone}" />`,
      ...layout.branch.points.map((_, pointIndex) => {
        const pointY = layout.branchY + (pointIndex - (layout.branch.points.length - 1) / 2) * MINDMAP_POINT_GAP;
        return `<path d="M${layout.branchX} ${layout.branchY} C${leafStartControl} ${layout.branchY} ${leafEndControl} ${pointY} ${layout.leafX} ${pointY}" stroke="${layout.tone}" />`;
      }),
    ];
  }).join("");
  const nodes = layouts.flatMap((layout) => {
    const branch = `<rect x="${layout.branchX - 125}" y="${layout.branchY - 42}" width="250" height="84" rx="14" fill="#fffaf5" stroke="${layout.tone}" stroke-width="2" />${mindMapSvgText(layout.branch.title, layout.branchX, layout.branchY - 9, 216, 17, "#172238", 600)}${mindMapSvgText(mindMapPointCountLabel(layout.branch.points.length), layout.branchX, layout.branchY + 22, 216, 9, "#756d63", 600)}`;
    const leaves = layout.branch.points.map((point, pointIndex) => {
      const pointY = layout.branchY + (pointIndex - (layout.branch.points.length - 1) / 2) * MINDMAP_POINT_GAP;
      return `<rect x="${layout.leafX - 135}" y="${pointY - 36}" width="270" height="72" rx="10" fill="#ffffff" stroke="${layout.tone}" />${mindMapSvgText(point, layout.leafX, pointY, 238, 13, "#4d4842")}`;
    });
    return [branch, ...leaves];
  }).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${MINDMAP_WIDTH}" height="${diagramHeight}" viewBox="0 0 ${MINDMAP_WIDTH} ${diagramHeight}"><rect width="100%" height="100%" fill="#fffdf8"/><g fill="none" stroke-linecap="round" stroke-width="2.6">${paths}</g><rect x="630" y="${centerY - 67}" width="340" height="134" rx="16" fill="#172238"/>${mindMapSvgText(artifact.title, 800, centerY, 290, 24, "#ffffff", 600)}${nodes}</svg>`;
}

function MindMapDiagram({ artifact }: { artifact: GeneratedVisualArtifact }) {
  const { centerY, diagramHeight, layouts } = mindMapLayout(artifact);

  return <div className="mindmap-radial-scroll"><div className="mindmap-radial" style={{ height: `${diagramHeight}px` }}>
    <svg className="mindmap-radial-edges" viewBox={`0 0 ${MINDMAP_WIDTH} ${diagramHeight}`} aria-hidden="true">
      {layouts.flatMap((layout) => {
        const branchControl = layout.side === "left" ? 660 : 940;
        const leafStartControl = layout.side === "left" ? 410 : 1190;
        const leafEndControl = layout.side === "left" ? 230 : 1370;
        const points = layout.branch.points.map((point, pointIndex) => {
          const pointY = layout.branchY + (pointIndex - (layout.branch.points.length - 1) / 2) * MINDMAP_POINT_GAP;
          return <path key={`${point}-${pointIndex}`} d={`M${layout.branchX} ${layout.branchY} C${leafStartControl} ${layout.branchY} ${leafEndControl} ${pointY} ${layout.leafX} ${pointY}`} stroke={layout.tone} />;
        });
        return [<path key={`branch-${layout.index}`} d={`M800 ${centerY} C${branchControl} ${centerY} ${branchControl} ${layout.branchY} ${layout.branchX} ${layout.branchY}`} stroke={layout.tone} />, ...points];
      })}
    </svg>
    <article className="mindmap-radial-root"><strong>{visualArtifactText(artifact.title)}</strong></article>
    {layouts.map((layout) => <section key={`${layout.branch.title}-${layout.index}`} className="mindmap-radial-branch" data-side={layout.side} style={{ "--mindmap-tone": layout.tone, left: `${layout.branchX}px`, top: `${layout.branchY}px` } as CSSProperties}><h3>{visualArtifactText(layout.branch.title)}</h3><span>{mindMapPointCountLabel(layout.branch.points.length)}</span></section>)}
    {layouts.flatMap((layout) => layout.branch.points.map((point, pointIndex) => {
      const pointY = layout.branchY + (pointIndex - (layout.branch.points.length - 1) / 2) * MINDMAP_POINT_GAP;
      return <p key={`${layout.branch.title}-${pointIndex}`} className="mindmap-radial-leaf" data-side={layout.side} style={{ "--mindmap-tone": layout.tone, left: `${layout.leafX}px`, top: `${pointY}px` } as CSSProperties}>{visualArtifactText(point)}</p>;
    }))}
  </div></div>;
}

function InlineCitationPopover({ number, reference, result }: {
  number: string;
  reference: ReviewResult["references"][number];
  result: ReviewResult;
}) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<"above" | "below">("above");
  const [availableSpace, setAvailableSpace] = useState(430);
  const rootRef = useRef<HTMLSpanElement>(null);
  const vietnamese = result.response_language === "Vietnamese";
  const excerpts = result.claims
    .filter((claim) => claim.validation_status !== "rejected" && claim.validation_status !== "invalid")
    .flatMap((claim) => claim.evidence.filter((item) => item.paper_id === reference.paper_id))
    .filter((item, index, items) => items.findIndex((candidate) => candidate.quote === item.quote) === index)
    .slice(0, 4);

  const togglePopover = () => {
    if (open) {
      setOpen(false);
      return;
    }
    const root = rootRef.current;
    if (root) {
      const anchor = root.getBoundingClientRect();
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
      const scrollFrame = root.closest(".claude-messages")?.getBoundingClientRect();
      const headerBottom = document.querySelector(".claude-chat-header")?.getBoundingClientRect().bottom ?? 0;
      const topBoundary = Math.max(scrollFrame?.top ?? 0, headerBottom) + 18;
      const bottomBoundary = Math.min(scrollFrame?.bottom ?? viewportHeight, viewportHeight) - 18;
      const spaceAbove = Math.max(0, anchor.top - topBoundary - 9);
      const spaceBelow = Math.max(0, bottomBoundary - anchor.bottom - 9);
      const nextPlacement = spaceBelow > spaceAbove ? "below" : "above";
      setPlacement(nextPlacement);
      setAvailableSpace(Math.max(160, Math.floor(nextPlacement === "below" ? spaceBelow : spaceAbove)));
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return <span className="claude-citation-popover" ref={rootRef}>
    <button
      type="button"
      className="claude-inline-citation"
      aria-expanded={open}
      aria-haspopup="dialog"
      aria-label={vietnamese ? `Xem nguyên văn từ nguồn ${number}` : `View original excerpt from reference ${number}`}
      onClick={togglePopover}
    >[{number}]</button>
    {open && <span
      className="claude-citation-card"
      data-placement={placement}
      style={{ "--citation-space": `${availableSpace}px` } as CSSProperties}
      role="dialog"
      aria-label={vietnamese ? `Nguyên văn từ nguồn ${number}` : `Original excerpt from reference ${number}`}
    >
      <span className="claude-citation-card-heading">{vietnamese ? "Nguồn" : "Source"} [{number}]</span>
      <strong>{reference.title}</strong>
      {excerpts.length ? <span className="claude-citation-claims">
        {excerpts.map((evidence, index) => <span key={`${evidence.paper_id}:${evidence.quote}:${index}`} className="claude-citation-excerpt">
          {evidence.context_before ? <span>{evidence.context_before} </span> : null}
          <span className="claude-citation-main-sentence">{evidence.quote}</span>
          {evidence.context_after ? <span> {evidence.context_after}</span> : null}
        </span>)}
      </span> : <span className="claude-citation-empty">{vietnamese ? "Chưa có câu trích nguyên văn cho nguồn này." : "No original excerpt is available for this source."}</span>}
      <a href={reference.url} target="_blank" rel="noreferrer">{vietnamese ? "Mở bài báo" : "Open paper"} ↗</a>
    </span>}
  </span>;
}

function InlineMessageText({ text, result, citationMode = "link" }: {
  text: string;
  result?: ReviewResult;
  citationMode?: "popover" | "link";
}) {
  const parts = text.split(CITATION_TOKEN);
  return <>{parts.map((part, index) => {
    if (index % 3 !== 0) return null;
    const number = parts[index + 1];
    const url = parts[index + 2];
    const reference = number && result?.references[Number(number) - 1];
    const citation = number && url
      ? citationMode === "popover" && result && reference
        ? <InlineCitationPopover number={number} reference={reference} result={result} />
        : <a className="claude-inline-citation" href={url} target="_blank" rel="noreferrer" aria-label={`Open reference ${number}`}>[{number}]</a>
      : null;
    return <span key={index}><IdentifierText text={part} />{citation}</span>;
  })}</>;
}

function MessageContent({ text, result }: { text: string; result?: ReviewResult }) {
  const [visibleText, annotationText] = text.split(ANNOTATION_CONTEXT_MARKER, 2);
  const annotations = annotationText
    ? annotationText.split(/\n\n(?=Annotation \d+:\n)/).map((item) => item.replace(/^Annotation \d+:\n/, "").trim()).filter(Boolean)
    : [];
  const lines = visibleText.replace(/\s*\[source:\d+\]/g, "").split("\n");
  const lastHeadingIndex = result ? lines.reduce((last, line, index) => line.trim().startsWith("## ") ? index : last, -1) : -1;
  const blocks: Array<{ type: "h3" | "h4" | "p" | "ul"; content: string | string[]; citationMode: "popover" | "link" }> = [];
  let bullets: string[] = [];
  let citationMode: "popover" | "link" = result ? "popover" : "link";
  const flushBullets = () => { if (bullets.length) { blocks.push({ type: "ul", content: bullets, citationMode }); bullets = []; } };
  for (const [lineIndex, rawLine] of lines.entries()) {
    if (lineIndex === lastHeadingIndex) citationMode = "link";
    const line = rawLine.trim();
    if (!line) { flushBullets(); continue; }
    if (line.startsWith("### ")) { flushBullets(); blocks.push({ type: "h4", content: line.slice(4), citationMode }); continue; }
    if (line.startsWith("## ")) { flushBullets(); blocks.push({ type: "h3", content: line.slice(3), citationMode }); continue; }
    if (line.startsWith("* ")) { bullets.push(line.slice(2)); continue; }
    if (line.startsWith("• ") || line.startsWith("- ")) { bullets.push(line.slice(2)); continue; }
    flushBullets();
    blocks.push({ type: "p", content: line, citationMode });
  }
  flushBullets();
  return <div className="claude-message-content">{annotations.length > 0 && <details className="claude-message-annotations"><summary>▣ {annotations.length} annotation{annotations.length === 1 ? "" : "s"}</summary><div>{annotations.map((annotation, annotationIndex) => <p key={annotationIndex}><strong>Annotation {annotationIndex + 1}</strong>{annotation}</p>)}</div></details>}{blocks.map((block, index) => {
    if (block.type === "h3") return <h3 key={index}><InlineMessageText text={block.content as string} result={result} citationMode={block.citationMode} /></h3>;
    if (block.type === "h4") return <h4 key={index}><InlineMessageText text={block.content as string} result={result} citationMode={block.citationMode} /></h4>;
    if (block.type === "ul") return <ul key={index}>{(block.content as string[]).map((item, itemIndex) => <li key={itemIndex}><InlineMessageText text={item} result={result} citationMode={block.citationMode} /></li>)}</ul>;
    return <p key={index}><InlineMessageText text={block.content as string} result={result} citationMode={block.citationMode} /></p>;
  })}</div>;
}

function WorkspaceData() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const { user } = useUser();
  const { lang, t } = useLanguage();
  const search = useSearchParams();
  const initialProjectId = search.get("project");
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [sessionsByProject, setSessionsByProject] = useState<Record<string, Session[]>>({});
  const [messages, setMessages] = useState<Message[]>([]);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [focusedReviewJobId, setFocusedReviewJobId] = useState<string | null>(null);
  const [flowStatus, setFlowStatus] = useState<Record<string, JobStatus>>({});
  const [flowResults, setFlowResults] = useState<Record<string, ReviewResult>>({});
  const [reportLoadError, setReportLoadError] = useState<Record<string, string>>({});
  const [prompt, setPrompt] = useState("");
  const [textSelection, setTextSelection] = useState<{ text: string; top: number; left: number } | null>(null);
  const [selectedAnnotations, setSelectedAnnotations] = useState<string[]>([]);
  const [expandedAnnotationIndex, setExpandedAnnotationIndex] = useState<number | null>(null);
  const [annotationPickerOpen, setAnnotationPickerOpen] = useState(false);
  const composerInputRef = useRef<HTMLTextAreaElement>(null);
  const [attachedDocument, setAttachedDocument] = useState<File | null>(null);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const documentInputRef = useRef<HTMLInputElement>(null);
  const [executionMode, setExecutionMode] = useState<"review" | "autonomous">("review");
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [queryDraft, setQueryDraft] = useState<string[]>([]);
  const [selectedPaperIds, setSelectedPaperIds] = useState<string[]>([]);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [hiddenHitlStages, setHiddenHitlStages] = useState<Record<string, string>>({});
  const [flowExpanded, setFlowExpanded] = useState(true);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [latexEditorReport, setLatexEditorReport] = useState<ReviewResult | null>(null);
  const [latexDraft, setLatexDraft] = useState("");
  const [savedLatexByReport, setSavedLatexByReport] = useState<Record<string, string>>({});
  const [mindMapArtifact, setMindMapArtifact] = useState<ReportVisualArtifact | null>(null);
  const [slideDeckArtifact, setSlideDeckArtifact] = useState<ReportVisualArtifact | null>(null);
  const [visualGeneration, setVisualGeneration] = useState<"mindmap" | "slides" | null>(null);
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);
  const [sandboxCapabilities, setSandboxCapabilities] = useState<SandboxCapabilities | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const updateSelectionToolbar = () => {
      const selection = window.getSelection();
      const selectedText = selection?.toString().trim() ?? "";
      const anchor = selection?.anchorNode;
      const contentRoot = anchor instanceof Element
        ? anchor.closest(".claude-research-answer .claude-message-content")
        : anchor?.parentElement?.closest(".claude-research-answer .claude-message-content");
      if (!selectedText || !contentRoot || !selection?.rangeCount) {
        setTextSelection(null);
        return;
      }
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      if (!rect.width && !rect.height) {
        setTextSelection(null);
        return;
      }
      setTextSelection({
        text: selectedText,
        top: Math.max(12, rect.top - 44),
        left: Math.min(Math.max(12, rect.left + rect.width / 2), window.innerWidth - 140),
      });
    };
    document.addEventListener("selectionchange", updateSelectionToolbar);
    document.addEventListener("mouseup", updateSelectionToolbar);
    return () => {
      document.removeEventListener("selectionchange", updateSelectionToolbar);
      document.removeEventListener("mouseup", updateSelectionToolbar);
    };
  }, []);

  function addSelectionToChat() {
    if (!textSelection) return;
    setSelectedAnnotations((current) => current.includes(textSelection.text) ? current : [...current, textSelection.text]);
    setAnnotationPickerOpen(false);
    setTextSelection(null);
    window.requestAnimationFrame(() => composerInputRef.current?.focus());
  }

  useEffect(() => {
    const savedEntries = Object.keys(flowResults).flatMap((jobId) => {
      const latex = window.localStorage.getItem(`litreview-report-latex:${jobId}`);
      return latex ? [[jobId, latex] as const] : [];
    });
    if (savedEntries.length) setSavedLatexByReport((current) => ({ ...Object.fromEntries(savedEntries), ...current }));
  }, [flowResults]);

  const api = useCallback(
    (path: string, init?: RequestInit) =>
      authenticatedJson<Record<string, unknown>>(getToken, path, init, {
        signInMessage: "Vui lòng đăng nhập để tiếp tục.",
        fallbackError: (status) => `Không thể hoàn tất yêu cầu (${status}).`,
      }),
    [getToken],
  );

  useEffect(() => {
    if (!project?.project_id) {
      setSandboxCapabilities(null);
      return;
    }
    let active = true;
    void api(`/projects/${project.project_id}/sandbox/capabilities`)
      .then((body) => {
        if (active) setSandboxCapabilities(body as unknown as SandboxCapabilities);
      })
      .catch(() => {
        if (active) setSandboxCapabilities(null);
      });
    return () => { active = false; };
  }, [api, project?.project_id]);

  const executionModeKey = useCallback((conversationId: string) => `litreview.executionMode.${conversationId}`, []);

  useEffect(() => {
    setAttachedDocument(null);
    if (documentInputRef.current) documentInputRef.current.value = "";
  }, [project?.project_id]);

  const modeForSession = useCallback((conversationId: string | undefined) => {
    if (!conversationId) return "review" as const;
    return window.localStorage.getItem(executionModeKey(conversationId)) === "autonomous" ? "autonomous" : "review";
  }, [executionModeKey]);

  const setSavedExecutionMode = useCallback((mode: "review" | "autonomous") => {
    setExecutionMode(mode);
    if (session?.conversation_id) window.localStorage.setItem(executionModeKey(session.conversation_id), mode);
  }, [executionModeKey, session?.conversation_id]);

  function selectDocument(file: File | null) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError(t("research_ui.document_too_large"));
      return;
    }
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (extension !== "pdf" && extension !== "docx") {
      setError(t("research_ui.document_type_invalid"));
      return;
    }
    setError("");
    setAttachedDocument(file);
    setUploadDialogOpen(false);
  }

  const loadProject = useCallback(async (next: Project) => {
    const [conversationBody, reviewBody] = await Promise.all([
      api(`/projects/${next.project_id}/conversations`),
      api(`/projects/${next.project_id}/reviews`),
    ]);
    const loadedSessions = (conversationBody.items ?? []) as Session[];
    setSessionsByProject((current) => ({ ...current, [next.project_id]: loadedSessions }));
    setProject(next);
    const loadedReviews = (reviewBody.items ?? []) as Review[];
    const sessionReviews = loadedSessions[0] ? loadedReviews.filter((review) => review.conversation_id === loadedSessions[0].conversation_id) : [];
    setReviews(sessionReviews);
    setFocusedReviewJobId(null);
    setFlowStatus({});
    const onlyConversation = loadedSessions[0] ?? null;
    setSession(onlyConversation);
    setExecutionMode(modeForSession(onlyConversation?.conversation_id));
    if (onlyConversation) {
      const history = await api(`/conversations/${onlyConversation.conversation_id}/messages`);
      setMessages(restoreResearchPrompts((Array.isArray(history.items) ? history.items : []).map(asWorkspaceMessage).filter((item): item is Message => item !== null), sessionReviews));
    } else setMessages([]);
    window.localStorage.setItem("litreview.activeProjectId", next.project_id);
    window.history.replaceState({}, "", `/workspace?project=${next.project_id}`);
  }, [api, modeForSession]);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    void (async () => {
      try {
        const body = await api("/projects");
        const items = (body.items ?? []) as Project[];
        setProjects(items);
        const conversationPairs = await Promise.all(items.map(async (item) => [item.project_id, (await api("/projects/" + item.project_id + "/conversations")).items ?? []] as const));
        setSessionsByProject(Object.fromEntries(conversationPairs) as Record<string, Session[]>);
        const remembered = window.localStorage.getItem("litreview.activeProjectId");
        const next = items.find((item) => item.project_id === initialProjectId) ?? items.find((item) => item.project_id === remembered) ?? items[0];
        if (next) await loadProject(next);
      } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    })();
  }, [api, initialProjectId, isLoaded, isSignedIn, loadProject]);

  const activeReviews = useMemo(() => reviews.filter((review) => ACTIVE.has(review.status)), [reviews]);
  const displayedReviews = useMemo(() => {
    if (focusedReviewJobId) {
      const focused = reviews.find((review) => review.job_id === focusedReviewJobId);
      if (focused) return [focused];
    }
    return activeReviews.length ? activeReviews : reviews.slice(0, 1);
  }, [activeReviews, focusedReviewJobId, reviews]);
  const currentReview = displayedReviews[0] ?? null;
  // Keep an active job visible during the short gap between creating it and
  // receiving its first status response. This also protects the workflow UI
  // if React batches the state reset and the new review in the same render.
  const currentFlow = currentReview
    ? flowStatus[currentReview.job_id] ?? (ACTIVE.has(currentReview.status) ? queuedFlowStatus(currentReview, executionMode) : null)
    : null;

  useEffect(() => {
    const container = messagesRef.current;
    if (!container) return;
    // The message list uses flex `order` for workflow anchoring, so scrolling
    // to a trailing sentinel can accidentally target the top of the flex
    // layout. Scroll the actual viewport to its content bottom instead.
    const frame = window.requestAnimationFrame(() => {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [busy, currentFlow?.current_node, currentFlow?.job_id, currentFlow?.node_trace.length, messages]);

  const currentHitlStage = currentFlow?.hitl_stage ?? (
    currentFlow?.current_node === "waiting_for_subqueries" ? "subqueries" :
      currentFlow?.current_node === "waiting_for_papers" ? "papers" :
        ["hitl_review", "waiting_for_review", "human_review"].includes(currentFlow?.current_node ?? "") ? "review" : null
  );
  const queryWordCount = (query: string) => query.trim() ? query.trim().split(/\s+/).length : 0;
  const populatedSubQueries = queryDraft.filter((query) => query.trim());
  const canApproveSubQueries = populatedSubQueries.length > 0 && populatedSubQueries.every((query) => {
    const wordCount = queryWordCount(query);
    return wordCount >= 8 && wordCount <= 14;
  });

  useEffect(() => {
    if (!currentFlow) return;
    if (currentHitlStage === "subqueries") setQueryDraft(currentFlow.sub_queries.length ? currentFlow.sub_queries : [""]);
    if (currentHitlStage === "papers") setSelectedPaperIds(currentFlow.papers.map((paper) => paper.paper_id));
  }, [currentFlow?.hitl_stage, currentFlow?.current_node, currentFlow?.job_id, currentHitlStage]);

  async function resumeWorkflow(payload: Record<string, unknown>) {
    if (!currentFlow) return;
    setDecisionBusy(true); setError("");
    try {
      await api(`/reviews/${currentFlow.job_id}/resume`, { method: "POST", body: JSON.stringify({ ...payload, execution_mode: currentFlow.execution_mode ?? "review" }) });
      setHiddenHitlStages((value) => ({ ...value, [currentFlow.job_id]: String(payload.stage ?? "") }));
      setFlowStatus((value) => ({ ...value, [currentFlow.job_id]: { ...currentFlow, status: "resuming", current_node: "resuming", hitl_stage: null } }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setDecisionBusy(false); }
  }

  useEffect(() => {
    if (!displayedReviews.length) return;
    let cancelled = false;
    async function refreshFlowStatus() {
      const updates = await Promise.all(displayedReviews.map(async (review) => {
        try { return await api(`/reviews/${review.job_id}/status`) as unknown as JobStatus; }
        catch { return null; }
      }));
      if (cancelled) return;
      const ready = updates.filter((item): item is JobStatus => item !== null);
      setFlowStatus((current) => ({ ...current, ...Object.fromEntries(ready.map((item) => [item.job_id, item])) }));
      setReviews((current) => current.map((review) => {
        const status = ready.find((item) => item.job_id === review.job_id);
        return status ? { ...review, status: status.status } : review;
      }));
      await Promise.all(ready.filter((item) => ["hitl_waiting", "approved", "changes_requested"].includes(item.status)).map(async (item) => {
        try {
          const result = await api(`/reviews/${item.job_id}`) as unknown as ReviewResult;
          if (!cancelled) setFlowResults((current) => ({ ...current, [item.job_id]: result }));
        } catch { /* The status remains available even if the report is still being persisted. */ }
      }));
    }
    void refreshFlowStatus();
    // A job can become terminal a moment before its report row is persisted.
    // Keep polling until the terminal result has actually arrived so the user
    // never needs to refresh the page manually.
    const waitingForResult = displayedReviews.some((review) => {
      return ["hitl_waiting", "approved", "changes_requested"].includes(review.status) && !flowResults[review.job_id];
    });
    const timer = activeReviews.length || waitingForResult ? window.setInterval(() => void refreshFlowStatus(), 3000) : undefined;
    return () => { cancelled = true; if (timer) window.clearInterval(timer); };
  }, [activeReviews.length, api, displayedReviews, flowResults]);
  const loadedResult = currentFlow ? flowResults[currentFlow.job_id] : null;
  // A report loaded while the agent is waiting for sub-query/paper selection
  // is only the candidate snapshot. Do not present its candidate count as the
  // final selected corpus (e.g. 10 candidates when the user selected 9).
  const reportIsReady = Boolean(currentFlow && (
    ["approved", "changes_requested"].includes(currentFlow.status) || currentHitlStage === "review"
  ));
  const currentResult = reportIsReady ? loadedResult : null;
  const reportResult = currentResult;
  const reportContentSignature = useMemo(() => reportResult ? JSON.stringify(reportResult) : "", [reportResult]);
  const shouldPublishReport = Boolean(currentFlow && ["approved", "changes_requested"].includes(currentFlow.status));

  useEffect(() => {
    if (!currentFlow) return;
    // Keep live progress compact so a long paper list does not push the
    // active request to the top of the viewport. Expand automatically only
    // when the user must inspect or act on a review decision.
    setFlowExpanded(Boolean(currentHitlStage) || currentFlow.status === "error");
  }, [currentFlow?.job_id, currentFlow?.status, currentHitlStage]);

  useEffect(() => {
    if (!currentFlow || !["hitl_waiting", "approved", "changes_requested"].includes(currentFlow.status)) return;
    let cancelled = false;
    const loadReviewResult = async () => {
      try {
        const result = await api(`/reviews/${currentFlow.job_id}`) as unknown as ReviewResult;
        if (!cancelled) {
          setFlowResults((current) => ({ ...current, [currentFlow.job_id]: result }));
          setReportLoadError((current) => { const next = { ...current }; delete next[currentFlow.job_id]; return next; });
        }
      } catch (cause) {
        if (!cancelled) setReportLoadError((current) => ({ ...current, [currentFlow.job_id]: cause instanceof Error ? cause.message : "Không thể tải báo cáo." }));
      }
    };
    void loadReviewResult();
    const timer = window.setInterval(() => void loadReviewResult(), currentFlow.status === "hitl_waiting" ? 1500 : 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [api, currentFlow?.job_id, currentFlow?.status]);

  useEffect(() => {
    // A review-stage result is a draft for the approval form, not the final
    // chat reply. Publish only after the worker persists the approved result.
    if (!reportResult || !shouldPublishReport) return;
    const answer = buildReportAnswer(reportResult);
    setMessages((current) => {
      // A conversation can contain several research jobs. Match only the
      // report belonging to this job; matching the first research_report
      // caused a later report to replace an earlier question's output.
      const existingIndex = current.findIndex((message) => (
        message.message_id === answer.message_id ||
        message.client_message_id === answer.client_message_id
      ));
      if (existingIndex < 0) {
        const promptIndex = current.findIndex((message) => (
          message.role === "user" && message.client_message_id === `review:${reportResult.job_id}`
        ));
        if (promptIndex >= 0) return [...current.slice(0, promptIndex + 1), answer, ...current.slice(promptIndex + 1)];
        return [...current, answer];
      }
      return current.map((message, index) => index === existingIndex ? answer : message);
    });
  }, [reportContentSignature, shouldPublishReport]);

  useEffect(() => {
    if (!currentFlow || currentFlow.status !== "error") return;
    const answer = buildErrorAnswer(currentFlow);
    setMessages((current) => {
      const existingIndex = current.findIndex((message) => (
        message.message_id === answer.message_id ||
        message.client_message_id === answer.client_message_id
      ));
      if (existingIndex >= 0) return current;
      const promptIndex = current.findIndex((message) => (
        message.role === "user" && message.client_message_id === `review:${currentFlow.job_id}`
      ));
      if (promptIndex >= 0) return [...current.slice(0, promptIndex + 1), answer, ...current.slice(promptIndex + 1)];
      return [...current, answer];
    });
  }, [currentFlow?.error, currentFlow?.job_id, currentFlow?.status]);

  // The HITL stage is authoritative while polling status transitions.
  const isPaperApproval = Boolean(currentFlow) && currentFlow?.status === "hitl_waiting" && currentHitlStage === "papers" && hiddenHitlStages[currentFlow?.job_id ?? ""] !== "papers";
  const isSubqueryApproval = Boolean(currentFlow) && currentFlow?.status === "hitl_waiting" && currentHitlStage === "subqueries" && hiddenHitlStages[currentFlow?.job_id ?? ""] !== "subqueries";
  const needsUserDecision = isPaperApproval || isSubqueryApproval;
  const flowTopic = displayedReviews[0]?.topic?.trim().toLowerCase() ?? "";
  const flowJobId = displayedReviews[0]?.job_id;
  const flowPromptIndexByJob = currentFlow && flowJobId
    ? messages.findIndex((message) => message.role === "user" && message.client_message_id === `review:${flowJobId}`)
    : -1;
  // History created before client ids were persisted can still be displayed.
  // In that case, use the most recent matching prompt rather than the first.
  const flowPromptIndex = flowPromptIndexByJob >= 0 ? flowPromptIndexByJob : messages.reduce((match, message, index) => (
    currentFlow && flowTopic && message.role === "user" && message.text.trim().toLowerCase() === flowTopic ? index : match
  ), -1);
  // Flex `order` accepts integers only. Reserve even values for messages and
  // insert the active workflow at the odd value directly after its prompt.
  const flowAnchorIndex = flowPromptIndex >= 0 ? flowPromptIndex * 2 + 1 : messages.length * 2 + 1;
  const visibleNodeTrace = currentFlow?.node_trace.filter((step) => !HIDDEN_FLOW_NODES.has(step.node)) ?? [];
  const currentFlowNodeVisible = Boolean(currentFlow && !HIDDEN_FLOW_NODES.has(currentFlow.current_node));
  const lastVisibleNode = visibleNodeTrace[visibleNodeTrace.length - 1]?.node ?? "queued";
  const visibleProgressNode = currentFlowNodeVisible ? currentFlow!.current_node : lastVisibleNode;

  async function openProject(target: Project) {
    setBusy(true); setError("");
    setProject(target);
    setSession(null);
    setMessages([]);
    setReviews([]);
    setFocusedReviewJobId(null);
    setFlowStatus({});
    setFlowResults({});
    setQueryDraft([]);
    setSelectedPaperIds([]);
    setHiddenHitlStages({});
    setPrompt("");
    setSelectedAnnotations([]);
    setExpandedAnnotationIndex(null);
    setAnnotationPickerOpen(false);
    window.localStorage.setItem("litreview.activeProjectId", target.project_id);
    window.history.replaceState({}, "", `/workspace?project=${target.project_id}`);
    try {
      const body = await api(`/projects/${target.project_id}/conversations`);
      const loadedSessions = (body.items ?? []) as Session[];
      setSessionsByProject((current) => ({ ...current, [target.project_id]: loadedSessions }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function createSession(target: Project = project as Project) {
    if (!target) return;
    setBusy(true); setError("");
    setProject(target);
    setExecutionMode("review");
    setSession(null);
    setMessages([]);
    setReviews([]);
    setFocusedReviewJobId(null);
    setFlowStatus({});
    setFlowResults({});
    setQueryDraft([]);
    setSelectedPaperIds([]);
    setHiddenHitlStages({});
    setPrompt("");
    setSelectedAnnotations([]);
    setExpandedAnnotationIndex(null);
    setAnnotationPickerOpen(false);
    window.localStorage.setItem("litreview.activeProjectId", target.project_id);
    window.history.replaceState({}, "", `/workspace?project=${target.project_id}`);
    try {
      const body = await api("/projects/" + target.project_id + "/conversations", { method: "POST", body: JSON.stringify({ force_new: true }) });
      const created = body.conversation as Session;
      setSessionsByProject((current) => ({ ...current, [target.project_id]: [created, ...(current[target.project_id] ?? [])] }));
      setSession(created);
      setExecutionMode(modeForSession(created.conversation_id));
      setMessages([]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }


  async function renameSession(target: Session) {
    const title = window.prompt("Tên chat", target.title || "");
    if (!title?.trim()) return;
    try {
      const body = await api("/conversations/" + target.conversation_id, { method: "PATCH", body: JSON.stringify({ title: title.trim() }) });
      const updated = body.conversation as Session;
      setSession((current) => current?.conversation_id === updated.conversation_id ? updated : current);
      setSessionsByProject((current) => Object.fromEntries(Object.entries(current).map(([id, rows]) => [id, rows.map((row) => row.conversation_id === updated.conversation_id ? updated : row)])));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }

  async function setFirstQuestionTitle(target: Session, question: string) {
    if (target.title && target.title !== "New conversation") return;
    try {
      const body = await api("/conversations/" + target.conversation_id, { method: "PATCH", body: JSON.stringify({ title: question.slice(0, 200) }) });
      const updated = body.conversation as Session;
      setSession(updated);
      setSessionsByProject((current) => Object.fromEntries(Object.entries(current).map(([id, rows]) => [id, rows.map((row) => row.conversation_id === updated.conversation_id ? updated : row)])));
    } catch { }
  }

  async function selectSession(next: Session) {
    setSession(next);
    setExecutionMode(modeForSession(next.conversation_id));
    setError("");
    try {
      const [history, reviewBody] = await Promise.all([
        api("/conversations/" + next.conversation_id + "/messages"),
        project ? api(`/projects/${project.project_id}/reviews`) : Promise.resolve({ items: [] }),
      ]);
      const sessionReviews = ((reviewBody.items ?? []) as Review[]).filter((review) => review.conversation_id === next.conversation_id);
      setReviews(sessionReviews);
      setFocusedReviewJobId(null);
      setFlowStatus({});
      setFlowResults({});
      setReportLoadError({});
      setHiddenHitlStages({});
      setMessages(restoreResearchPrompts((Array.isArray(history.items) ? history.items : []).map(asWorkspaceMessage).filter((item): item is Message => item !== null), sessionReviews));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }

  async function deleteSession(target: Session) {
    if (!window.confirm("Xóa session này và toàn bộ lịch sử trò chuyện?")) return;
    setBusy(true); setError("");
    try {
      const projectId = project?.project_id;
      const reviewBody = projectId ? await api(`/projects/${projectId}/reviews`) : { items: [] };
      const sessionReviews = projectId
        ? ((reviewBody.items ?? []) as Review[]).filter((review) => review.conversation_id === target.conversation_id)
        : [];
      if (sessionReviews.some((review) => DELETE_BLOCKING.has(review.status))) throw new Error("Session đang có flow chạy. Hãy chờ flow hoàn tất rồi xóa session.");
      if (projectId) await Promise.all(sessionReviews.map((review) => api("/projects/" + projectId + "/reviews/" + review.job_id, { method: "DELETE" })));
      await api("/conversations/" + target.conversation_id, { method: "DELETE" });
      let remaining: Session[] = [];
      if (projectId) {
        setSessionsByProject((current) => {
          const next = (current[projectId] ?? []).filter((item) => item.conversation_id !== target.conversation_id);
          remaining = next;
          return { ...current, [projectId]: next };
        });
      }
      const deletedCurrentSession = session?.conversation_id === target.conversation_id;
      if (deletedCurrentSession) {
        setReviews((current) => current.filter((review) => !sessionReviews.some((item) => item.job_id === review.job_id)));
        setFlowStatus({});
        setFlowResults({});
        setPrompt("");
        const nextSession = remaining[0] ?? null;
        setSession(nextSession);
        setMessages([]);
        if (nextSession) {
          await selectSession(nextSession);
        }
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function deleteProject(target: Project) {
    if (!window.confirm("Xóa project và toàn bộ chat, báo cáo trong đó?")) return;
    setBusy(true); setError("");
    try {
      await api("/projects/" + target.project_id, { method: "DELETE" });
      const remainingProjects = projects.filter((item) => item.project_id !== target.project_id);
      setProjects(remainingProjects);
      setSessionsByProject((current) => { const next = { ...current }; delete next[target.project_id]; return next; });
      if (project?.project_id === target.project_id) {
        const nextProject = remainingProjects[0] ?? null;
        if (nextProject) await loadProject(nextProject);
        else { setProject(null); setSession(null); setMessages([]); setReviews([]); }
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!projectName.trim()) return;
    setBusy(true); setError("");
    try {
      const body = await api("/projects", { method: "POST", body: JSON.stringify({ name: projectName.trim(), description: "" }) });
      const created = { ...(body.project as Project), project_role: "owner" as const };
      setProjects((current) => [created, ...current]);
      setProjectName(""); setCreatingProject(false);
      await loadProject(created);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function runResearch(text: string, displayText = text, annotations: string[] = []) {
    if (!project) return;
    setPrompt(""); setSelectedAnnotations([]); setExpandedAnnotationIndex(null); setAnnotationPickerOpen(false); setBusy(true); setError("");
    try {
      const isFirstTurn = messages.length === 0;
      const optimisticText = annotations.length
        ? `${displayText}${ANNOTATION_CONTEXT_MARKER}${annotations.map((annotation, index) => `Annotation ${index + 1}:\n${annotation}`).join("\n\n")}`
        : displayText;
      const optimistic: Message = { message_id: crypto.randomUUID(), role: "user", message_type: "user_message", text: optimisticText, citations: [], annotations };
      setMessages((current) => [...current, optimistic]);
      // The composer always creates a research job. Its first node is the
      // LLM intent guardrail, which decides whether the prompt is a literature
      // review request before search or synthesis capabilities are invoked.
      setFlowStatus({});
      setFlowResults({});
      setReportLoadError({});
      setHiddenHitlStages({});
      let activeSession = session;
      if (!activeSession) {
        const createdBody = await api(`/projects/${project.project_id}/conversations`, { method: "POST", body: JSON.stringify({}) });
        activeSession = createdBody.conversation as Session;
        setSession(activeSession);
        setSessionsByProject((current) => ({ ...current, [project.project_id]: [activeSession!, ...(current[project.project_id] ?? [])] }));
      }
      // Refresh the server-owned conversation boundary before routing. A report
      // may have completed since this workspace last polled, and follow-up
      // questions must stay inside that chat's pinned report rather than start
      // a second research job.
      const currentConversation = await api(`/conversations/${activeSession.conversation_id}`);
      activeSession = currentConversation.conversation as Session;
      setSession(activeSession);
      setSessionsByProject((current) => Object.fromEntries(Object.entries(current).map(([projectId, sessions]) => [
        projectId,
        sessions.map((item) => item.conversation_id === activeSession!.conversation_id ? activeSession! : item),
      ])));
      if (isFirstTurn) {
        await setFirstQuestionTitle(activeSession, displayText);
      }
      const intent = await api(`/conversations/${activeSession.conversation_id}/classify-intent`, { method: "POST", body: JSON.stringify({ text }) });
      if (intent.intent === "grounded_rag") {
        const body = await api(`/conversations/${activeSession.conversation_id}/messages`, {
          method: "POST",
          body: JSON.stringify({
            client_message_id: optimistic.message_id,
            text,
            expected_report_version_id: activeSession.active_report_version_id ?? null,
          }),
        });
        const answer = asWorkspaceMessage(body.assistant_message);
        if (answer) setMessages((current) => [...current, answer]);
        return;
      }
      if (intent.intent === "clarify") {
        const fallback = lang === "vi"
          ? "Mình chưa xác định được bạn muốn tổng quan tài liệu hay phân tích khoảng trống nghiên cứu. Hãy nêu rõ câu hỏi nghiên cứu hoặc mục tiêu phân tích."
          : "I could not determine whether you want a literature review or a research-gap analysis. Please state your research question or analysis goal.";
        const explanation = typeof intent.reason === "string" && intent.reason.trim() ? intent.reason.trim() : fallback;
        setMessages((current) => [...current, {
          message_id: `clarify:${crypto.randomUUID()}`,
          client_message_id: null,
          role: "assistant",
          message_type: "clarification",
          text: `${fallback}\n\n${explanation}`,
          citations: [],
        }]);
        return;
      }
      if (intent.intent === "unsafe") {
        const refusal = lang === "vi"
          ? "Mình không thể hỗ trợ yêu cầu có thể gây hại. Mình có thể hỗ trợ một câu hỏi nghiên cứu trung lập về phòng ngừa, tác động hoặc giảm thiểu tác hại."
          : "I can’t help with a request that could cause harm. I can help with neutral research on prevention, impact, or harm reduction.";
        setMessages((current) => [...current, {
          message_id: `unsafe:${crypto.randomUUID()}`,
          client_message_id: null,
          role: "assistant",
          message_type: "refusal",
          text: refusal,
          citations: [],
        }]);
        return;
      }
      const isGapWorkflow = intent.intent === "research_gap";
      const body = await api(`/projects/${project.project_id}/${isGapWorkflow ? "research-gaps" : "reviews"}`, { method: "POST", body: JSON.stringify({ topic: text, max_results: 20, conversation_id: activeSession.conversation_id, execution_mode: executionMode, response_language: lang === "vi" ? "Vietnamese" : "English" }) });
      const review: Review = { project_id: project.project_id, job_id: String(body.job_id), topic: text, status: String(body.status ?? "queued"), created_at: new Date().toISOString(), conversation_id: activeSession.conversation_id, workflow_type: isGapWorkflow ? "research_gap" : "litreview" };
      setReviews((current) => [review, ...current]);
      setFocusedReviewJobId(review.job_id);
      // Render the queued state immediately. Without this local status, the
      // chat stays visually blank until the first status poll returns even
      // though the research job was already accepted by the server.
      setFlowStatus((current) => ({ ...current, [review.job_id]: queuedFlowStatus(review, executionMode) }));
      // The workflow panel below is the live status for this request. Do not
      // add a second, client-only assistant message here: the final report
      // is inserted after this prompt, so that placeholder used to make the
      // visible question/answer sequence appear out of order until reload.
      setMessages((current) => current.map((message) => (
        message.message_id === optimistic.message_id
          ? { ...message, client_message_id: `review:${review.job_id}` }
          : message
      )));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  async function cancelCurrentReview() {
    if (!project || !currentFlow) return;
    setDecisionBusy(true); setError("");
    try {
      await api(`/projects/${project.project_id}/reviews/${currentFlow.job_id}/cancel`, { method: "POST" });
      setFlowStatus((current) => ({ ...current, [currentFlow.job_id]: { ...currentFlow, status: "cancelled", current_node: "cancelled", hitl_stage: null } }));
      setReviews((current) => current.map((review) => review.job_id === currentFlow.job_id ? { ...review, status: "cancelled" } : review));
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setDecisionBusy(false); }
  }

  async function copyMessage(message: Message) {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopiedMessageId(message.message_id);
      window.setTimeout(() => setCopiedMessageId((current) => current === message.message_id ? null : current), 1800);
    } catch {
      setError(t("research_ui.copy_failed"));
    }
  }

  function openLatexEditor(report: ReviewResult) {
    const storageKey = `litreview-report-latex:${report.job_id}`;
    const savedLatex = savedLatexByReport[report.job_id] ?? window.localStorage.getItem(storageKey) ?? "";
    setLatexDraft(savedLatex ? upgradeLegacyBibliography(savedLatex, report) : reportToLatex(report));
    setLatexEditorReport(report);
  }

  function saveLatexReport() {
    if (!latexEditorReport) return;
    const nextLatex = latexDraft.trim();
    setSavedLatexByReport((current) => ({ ...current, [latexEditorReport.job_id]: nextLatex }));
    window.localStorage.setItem(`litreview-report-latex:${latexEditorReport.job_id}`, nextLatex);
    setLatexEditorReport(null);
  }

  function exportLatexReport(report: ReviewResult) {
    const savedLatex = savedLatexByReport[report.job_id] ?? window.localStorage.getItem(`litreview-report-latex:${report.job_id}`) ?? "";
    const latex = savedLatex ? upgradeLegacyBibliography(savedLatex, report) : reportToLatex(report);
    downloadReportFile(latex, `${reportFilename(report.topic)}.tex`, "application/x-tex;charset=utf-8");
  }

  function exportPdfReport(report: ReviewResult) {
    const savedLatex = savedLatexByReport[report.job_id] ?? window.localStorage.getItem(`litreview-report-latex:${report.job_id}`) ?? "";
    const latex = savedLatex ? upgradeLegacyBibliography(savedLatex, report) : reportToLatex(report);
    const printWindow = window.open("", "_blank", "width=900,height=760");
    if (!printWindow) { setError("Trình duyệt đã chặn cửa sổ in. Hãy cho phép pop-up và thử lại."); return; }
    const reportText = latexToReportText(latex, report.references).replace(CITATION_TOKEN, (_match, number: string) => `[${number}]`).replace(/^#{2,3}\s+/gm, "").replace(/^- /gm, "• ");
    printWindow.document.write(`<!doctype html><html lang="vi"><head><title>${escapeReportHtml(report.topic)}</title><style>body{max-width:720px;margin:56px auto;color:#172238;font:16px/1.7 Georgia,serif}h1{font:700 29px/1.2 Georgia,serif;margin:0 0 30px;border-bottom:2px solid #d04f35;padding-bottom:16px}article{white-space:pre-wrap}@page{margin:18mm}</style></head><body><h1>${escapeReportHtml(report.topic)}</h1><article>${escapeReportHtml(reportText)}</article><script>window.onload=()=>window.print();<\/script></body></html>`);
    printWindow.document.close();
  }

  function exportMindMapPng(artifact: GeneratedVisualArtifact) {
    const svg = mindMapSvgMarkup(artifact);
    const svgUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const image = new Image();
    image.onload = () => {
      const { diagramHeight } = mindMapLayout(artifact);
      const scale = 2;
      const canvas = document.createElement("canvas");
      canvas.width = MINDMAP_WIDTH * scale;
      canvas.height = diagramHeight * scale;
      const context = canvas.getContext("2d");
      if (!context) { setError("Trình duyệt không hỗ trợ xuất ảnh PNG."); URL.revokeObjectURL(svgUrl); return; }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        URL.revokeObjectURL(svgUrl);
        if (!blob) { setError("Không thể tạo ảnh PNG. Hãy thử lại."); return; }
        downloadReportFile(blob, `${reportFilename(artifact.title)}-mindmap.png`, "image/png");
      }, "image/png");
    };
    image.onerror = () => { URL.revokeObjectURL(svgUrl); setError("Không thể tạo ảnh PNG. Hãy thử lại."); };
    image.src = svgUrl;
  }

  function exportMindMapPdf(artifact: GeneratedVisualArtifact) {
    const printWindow = window.open("", "_blank", "width=1200,height=820");
    if (!printWindow) { setError("Trình duyệt đã chặn cửa sổ in. Hãy cho phép pop-up và thử lại."); return; }
    printWindow.document.write(`<!doctype html><html lang="vi"><head><title>${escapeReportHtml(artifact.title)}</title><style>@page{size:landscape;margin:10mm}body{margin:0;background:#fffdf8}svg{display:block;width:100%;height:auto}</style></head><body>${mindMapSvgMarkup(artifact)}<script>window.onload=()=>window.print();<\/script></body></html>`);
    printWindow.document.close();
  }

  function exportSlidesPdf(artifact: GeneratedVisualArtifact) {
    const printWindow = window.open("", "_blank", "width=1200,height=820");
    if (!printWindow) { setError("Trình duyệt đã chặn cửa sổ in. Hãy cho phép pop-up và thử lại."); return; }
    const slides = artifact.slides.map((slide, index) => `<section class="slide">${slide.image_data_url ? `<img src="${escapeReportAttribute(slide.image_data_url)}" alt="${escapeReportAttribute(slide.visual_alt || "AI illustration")}"/>` : ""}<div class="veil"></div><div class="copy"><span>${escapeReportHtml(visualArtifactText(slide.subtitle || "Báo cáo tổng hợp"))}</span><h1>${escapeReportHtml(visualArtifactText(slide.title))}</h1><ul>${slide.points.map((point) => `<li>${escapeReportHtml(visualArtifactText(point))}</li>`).join("")}</ul></div>${slide.image_data_url ? "<em>Minh hoạ AI · không phải bằng chứng</em>" : ""}<small>${String(index + 1).padStart(2, "0")} / ${String(artifact.slides.length).padStart(2, "0")}</small></section>`).join("");
    printWindow.document.write(`<!doctype html><html lang="vi"><head><title>${escapeReportHtml(artifact.title)}</title><style>@page{size:16in 9in;margin:0}*{box-sizing:border-box}html,body{width:16in;margin:0;color:#fff;font-family:"IBM Plex Sans",ui-sans-serif,sans-serif}.slide{position:relative;display:flex;width:16in;height:9in;align-items:center;overflow:hidden;padding:1.1in;background:#172238;break-after:page;page-break-after:always;print-color-adjust:exact;-webkit-print-color-adjust:exact}.slide:last-child{break-after:auto;page-break-after:auto}.slide img{position:absolute;inset:0 0 0 auto;width:57%;height:100%;object-fit:cover}.veil{position:absolute;inset:0;background:linear-gradient(90deg,#172238 0%,rgba(23,34,56,.96) 42%,rgba(23,34,56,.42) 74%,rgba(23,34,56,.16) 100%)}.copy{position:relative;z-index:1;width:56%}.copy span{color:#ed9475;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.copy h1{margin:20px 0 30px;font:600 48px/1.08 Georgia,serif}.copy ul{margin:0;padding-left:24px;font-size:20px;line-height:1.5}.copy li+li{margin-top:13px}.slide em{position:absolute;z-index:1;right:28px;top:24px;padding:6px 8px;background:rgba(23,34,56,.7);font-size:10px;font-style:normal;text-transform:uppercase}.slide small{position:absolute;z-index:1;right:28px;bottom:25px;color:rgba(255,255,255,.65);font-size:11px}</style></head><body>${slides}<script>window.onload=()=>window.print();<\/script></body></html>`);
    printWindow.document.close();
  }

  function savedLatexFor(report: ReviewResult) {
    return savedLatexByReport[report.job_id]
      ?? window.localStorage.getItem(`litreview-report-latex:${report.job_id}`)
      ?? reportToLatex(report);
  }

  async function generateVisualArtifact(report: ReviewResult, artifactType: "mindmap" | "slides") {
    if (visualGeneration) return;
    setVisualGeneration(artifactType);
    setError("");
    try {
      const response = await api(`/reviews/${report.job_id}/visual-artifact`, {
        method: "POST",
        body: JSON.stringify({ artifact_type: artifactType, latex: savedLatexFor(report) }),
      });
      const artifact = response.artifact as GeneratedVisualArtifact | undefined;
      if (!artifact || !artifact.title || !Array.isArray(artifact.branches) || !Array.isArray(artifact.slides)) {
        throw new Error("Nội dung tạo ra không đúng định dạng. Hãy thử lại.");
      }
      const result = { report, artifact };
      if (artifactType === "mindmap") {
        setMindMapArtifact(result);
      } else {
        setActiveSlideIndex(0);
        setSlideDeckArtifact(result);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setVisualGeneration(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = prompt.trim();
    if ((!text && !attachedDocument) || !project || busy) return;
    const annotationContext = selectedAnnotations.length
      ? `\n\nCác đoạn tham chiếu được chọn:\n${selectedAnnotations.map((annotation, index) => `Annotation ${index + 1}:\n${annotation}`).join("\n\n")}`
      : "";
    const textWithAnnotation = `${text}${annotationContext}`;
    if (!attachedDocument) {
      void runResearch(textWithAnnotation, text, selectedAnnotations);
      return;
    }
    setBusy(true); setError("");
    try {
      const form = new FormData();
      form.append("document", attachedDocument);
      form.append("focus", textWithAnnotation);
      const seed = await api(`/projects/${project.project_id}/document-search-seed`, { method: "POST", body: form });
      const topic = String(seed.topic ?? "").trim();
      if (!topic) throw new Error("Could not create a search topic from this document.");
      const filename = String(seed.filename ?? attachedDocument.name);
      setAttachedDocument(null);
      if (documentInputRef.current) documentInputRef.current.value = "";
      const displayText = `${t("research_ui.document_context", "Find papers related to this document")}: ${filename}\n${topic}`;
      await runResearch(topic, displayText);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  }

  if (!isLoaded) return <main className="claude-loading">{t("research_ui.loading_workspace")}</main>;
  if (!isSignedIn) return <main className="claude-loading"><p>{t("research_ui.sign_in")}</p><Link href="/auth">{t("common.sign_in")}</Link></main>;
  const showSandboxCandidates = Boolean(
    project && currentFlow?.status === "approved" && currentResult?.potential_gaps?.length &&
    sandboxCapabilities?.enabled && sandboxCapabilities.available && sandboxCapabilities.graph_context_enabled &&
    sandboxCapabilities.modes.hypothesis
  );
  const hasRightRail = showSandboxCandidates;

  return <main className="claude-shell">
    <aside className="claude-sidebar">
      <div className="claude-brand"><span className="claude-mark" aria-hidden="true"><span>L</span></span><span>LitReview</span></div>
      <Link className="claude-dashboard-link claude-dashboard-top" href="/dashboard">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
        <span>Dashboard</span>
      </Link>
      <button className="claude-new-project" onClick={() => setCreatingProject(true)}><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square"><path d="M8 3v10M3 8h10" /></svg>Dự án mới</button>
      <div className="claude-side-label">Projects</div>
      <nav className="claude-project-list" aria-label="Projects">
        {projects.map((item) => {
          const projectSessions = sessionsByProject[item.project_id] ?? [];
          return <section className="claude-project-tree" key={item.project_id}>
            <div className="claude-project-row">
              <button className={item.project_id === project?.project_id ? "active" : ""} onClick={() => void openProject(item)}>
                <svg className="folder" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.5h6l2 2h9v7.2a2.3 2.3 0 0 1-2.3 2.3H5.8a2.3 2.3 0 0 1-2.3-2.3z" /><path d="M3.5 7.5V6.2a2.2 2.2 0 0 1 2.2-2.2h4l2 2h6.5" /></svg>
                <span>{item.name}</span>
              </button>
              <button className="claude-project-new-session" type="button" onClick={() => void createSession(item)} disabled={busy} aria-label="Tạo chat mới"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button>
              <button className="claude-project-delete" type="button" onClick={() => void deleteProject(item)} disabled={busy} aria-label="Xóa project"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8h14M9 8V5h6v3m-8 0 1 11h8l1-11M10 11v5m4-5v5" /></svg></button>
            </div>
            <div className="claude-project-chats">
              {projectSessions.map((chat, index) => <div className="claude-session-row" key={chat.conversation_id}>
                <button className={chat.conversation_id === session?.conversation_id ? "claude-session-select active" : "claude-session-select"} type="button" onClick={() => void selectSession(chat)} title={chat.title || `Chat ${projectSessions.length - index}`}><svg className="chat-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5h16v11H9l-5 3z" /></svg><strong>{chat.title || `Chat ${projectSessions.length - index}`}</strong></button><button className="claude-session-rename" type="button" onClick={(event) => { event.stopPropagation(); void renameSession(chat); }} aria-label="Đổi tên chat"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6 4 4M5 19l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L9 18z" /></svg></button>
                <button className="claude-session-delete" type="button" onClick={() => void deleteSession(chat)} disabled={busy} aria-label="Xóa chat"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8h14M9 8V5h6v3m-8 0 1 11h8l1-11M10 11v5m4-5v5" /></svg></button>
              </div>)}
              {!projectSessions.length && <span className="claude-no-chats">Chưa có chat</span>}
            </div>
          </section>;
        })}
      </nav>
      <div className="claude-sidebar-bottom"><span>{user?.fullName ?? "Researcher"}</span></div>
    </aside>

    <section className={`claude-chat${hasRightRail ? " claude-chat-with-sandbox" : ""}`}>
      <header className="claude-chat-header"><div><span>{project ? t("research_ui.research_agent") : "LitReview"}</span><h2>{project?.name ?? t("research_ui.header_empty")}</h2></div><div className="claude-header-actions"><LanguageToggle />{project && <Link href={`/projects/${project.project_id}/document-review`}>Rà soát bản thảo</Link>}{project && sandboxCapabilities?.enabled && sandboxCapabilities.available && <Link className="claude-sandbox-link" href={`/projects/${project.project_id}/sandbox`}>Mở Sandbox{sandboxCapabilities.demo_mode && <small>Demo</small>}</Link>}{project && <Link href={`/projects/${project.project_id}/synthesis`}>{t("research_ui.synthesis")}</Link>}<UserButton /></div></header>
      {error && <button className="claude-error" onClick={() => setError("")}>{error}</button>}
      <div ref={messagesRef} className="claude-messages">
        {messages.length === 0 && <div className="claude-welcome"><div className="claude-welcome-icon">✦</div><h2>{t("research_ui.welcome_title")}</h2><p>{t("research_ui.welcome_body")}</p></div>}
        {messages.map((message, index) => {
          const currentReport = message.message_type === "research_report"
            ? Object.values(flowResults).find((report) => (
              message.message_id === `research-report:${report.job_id}` ||
              message.client_message_id === `research_report:${report.job_id}`
            ))
            : undefined;
          const savedLatex = currentReport ? savedLatexByReport[currentReport.job_id] : undefined;
          const displayText = currentReport ? (savedLatex ? latexToReportText(savedLatex, currentReport.references) : buildReportAnswer(currentReport).text) : message.text;
          const canOpenAnswerInSandbox = Boolean(project && session && message.role === "assistant" && message.message_type === "grounded_answer" && sandboxCapabilities?.enabled && sandboxCapabilities.available && sandboxCapabilities.graph_context_enabled && sandboxCapabilities.modes.hypothesis);
          const sandboxAnswerHref = canOpenAnswerInSandbox ? `/projects/${project!.project_id}/sandbox?mode=hypothesis&entrypoint=graphrag_answer&source_resource_id=${encodeURIComponent(message.message_id)}&source_parent_id=${encodeURIComponent(session!.conversation_id)}&title=${encodeURIComponent("Giả thuyết từ câu trả lời GraphRAG")}` : "";
          return <article style={{ order: index * 2 }} key={message.message_id} className={`claude-message ${message.role} ${message.message_type === "research_report" ? "claude-research-answer" : ""}`}><div className="claude-avatar">{message.role === "assistant" ? "✦" : (user?.firstName?.[0] ?? "B")}</div><div className="claude-message-body"><div className="claude-message-content"><MessageContent text={displayText} result={currentReport ?? undefined} />{currentReport && <div className="claude-report-derivatives"><span>{visualGeneration ? "Đang đọc LaTeX đã lưu…" : "Tạo từ LaTeX đã lưu"}</span><div><button type="button" disabled={Boolean(visualGeneration)} onClick={() => void generateVisualArtifact(currentReport, "mindmap")}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="19" cy="5" r="2" /><circle cx="19" cy="19" r="2" /><path d="M7 12h5m2-5-3 4m3 6-3-4" /></svg>{visualGeneration === "mindmap" ? "Đang tạo mind map…" : "Tạo mind map"}</button><button type="button" disabled={Boolean(visualGeneration)} onClick={() => void generateVisualArtifact(currentReport, "slides")}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="14" rx="1" /><path d="M8 21h8M12 18v3M7 8h10M7 12h6" /></svg>{visualGeneration === "slides" ? "Đang tạo slide…" : "Tạo slide"}</button></div></div>}{message.citations.map((citation, citationIndex) => <a key={`${message.message_id}-${citationIndex}`} href={citation.source_url} target="_blank" rel="noreferrer">{citation.paper_id ?? t("common.source")}: {citation.quote}</a>)}</div><div className="claude-report-actions">{canOpenAnswerInSandbox && <Link className="claude-report-action claude-sandbox-action" href={sandboxAnswerHref}>Mở trong Sandbox</Link>}{currentReport && <button className="claude-report-action" type="button" onClick={() => openLatexEditor(currentReport)}>Edit LaTeX</button>}<div className="claude-report-secondary-actions">{currentReport && <details className="claude-report-export"><summary>Xuất</summary><div><button type="button" onClick={() => exportLatexReport(currentReport)}>Tệp .tex</button><button type="button" onClick={() => exportPdfReport(currentReport)}>PDF</button></div></details>}<button className="claude-copy-message" type="button" onClick={() => void copyMessage({ ...message, text: displayText })} aria-label={t("research_ui.copy")}>{copiedMessageId === message.message_id ? t("research_ui.copied") : t("research_ui.copy")}</button></div></div></div></article>;
        })}
          {currentFlow && !["approved", "changes_requested", "cancelled", "error"].includes(currentFlow.status) && <section style={{ order: flowAnchorIndex }} className="claude-flow-detail"><div className="claude-flow-banner"><div><i /> <span>{needsUserDecision ? t("research_ui.flow_needs_decision") : t("research_ui.flow_searching")}</span>{currentFlowNodeVisible && <strong>{flowLabel(currentFlow.current_node, t)}</strong>}</div><div className="claude-flow-bar"><b style={{ width: `${Math.max(5, Math.min(96, Math.round(((Math.max(0, FLOW_STEPS.indexOf(visibleProgressNode)) + 1) / FLOW_STEPS.length) * 100)))}%` }} /></div><button className="claude-cancel-flow" type="button" onClick={() => void cancelCurrentReview()} disabled={decisionBusy}>{t("research_ui.cancel_task")}</button></div>
          {isSubqueryApproval && <div className="claude-review-panel"><h3>Duyệt kế hoạch tìm kiếm</h3><p>Mỗi sub-query cần 8–14 từ và giữ đúng trọng tâm yêu cầu của bạn. Bạn có thể sửa, thêm hoặc xoá trước khi tìm kiếm.</p>{queryDraft.map((query, index) => { const wordCount = queryWordCount(query); const isValid = !query.trim() || (wordCount >= 8 && wordCount <= 14); return <div className="claude-query-edit" key={index}><div><input value={query} aria-invalid={!isValid} aria-describedby={`subquery-length-${index}`} onChange={(event) => setQueryDraft((rows) => rows.map((item, row) => row === index ? event.target.value : item))} /><small id={`subquery-length-${index}`} className={isValid ? "" : "invalid"}>{wordCount}/8–14 từ</small></div><button type="button" onClick={() => setQueryDraft((rows) => rows.filter((_, row) => row !== index))} aria-label="Xoá sub-query">×</button></div>; })}<div className="claude-review-actions"><button type="button" onClick={() => setQueryDraft((rows) => [...rows, ""])}>+ Thêm sub-query</button><button type="button" disabled={decisionBusy || !canApproveSubQueries} onClick={() => void resumeWorkflow({ stage: "subqueries", sub_queries: populatedSubQueries })}>Xác nhận và tìm kiếm</button></div></div>}
          {isPaperApproval && <div className="claude-review-panel"><h3>Chọn bài báo để tổng hợp</h3><p>Bạn có thể tự chọn từng bài, ho-c dùng toàn bộ danh sách đã được agent xếp hạng.</p><div className="claude-paper-select-list">{currentFlow.papers.map((paper) => { const source = paper.source?.trim().toLowerCase(); const sourceLabel = source && source !== "openalex" ? `${source.toUpperCase()} - ` : ""; return <label key={paper.paper_id}><input type="checkbox" checked={selectedPaperIds.includes(paper.paper_id)} onChange={() => setSelectedPaperIds((rows) => rows.includes(paper.paper_id) ? rows.filter((id) => id !== paper.paper_id) : [...rows, paper.paper_id])} /><span><strong>{paper.title}</strong><small>{sourceLabel}{paper.authors.slice(0, 2).join(", ") || "Không rõ tác giả"}{paper.year ? ` - ${paper.year}` : ""} - xếp hạng {paper.relevance_score?.toFixed(2) ?? "—"}</small></span><a href={paper.url} target="_blank" rel="noreferrer">Nguồn</a></label>; })}</div><div className="claude-review-actions"><button type="button" disabled={decisionBusy} onClick={() => void resumeWorkflow({ stage: "papers", mode: "ranked" })}>Dùng kết quả xếp hạng</button><button type="button" disabled={decisionBusy || !selectedPaperIds.length} onClick={() => void resumeWorkflow({ stage: "papers", mode: "manual", selected_paper_ids: selectedPaperIds })}>Tổng hợp {selectedPaperIds.length} bài đã chọn</button></div></div>}
          <details className="claude-trace-details" open={flowExpanded} onToggle={(event) => setFlowExpanded(event.currentTarget.open)}><summary>Tiến trình agent ({visibleNodeTrace.length} bước)</summary><div className="claude-flow-columns"><div><h3>Các bước đang thực hiện</h3><ol className="claude-task-list">{visibleNodeTrace.map((step, index) => <li key={step.trace_id ?? `${step.node}-${index}`} className={step.node === currentFlow.current_node ? "active" : ""}><span>{step.node === currentFlow.current_node ? "●" : "✓"}</span><div><strong>{flowLabel(step.node, t)}</strong></div></li>)}</ol></div><div><h3>Bài báo đã tìm thấy ({currentFlow.papers.length})</h3>{currentFlow.papers.length ? <div className="claude-paper-list">{currentFlow.papers.map((paper) => { const source = paper.source?.trim().toLowerCase(); const sourceLabel = source && source !== "openalex" ? source.toUpperCase() : ""; const citationLabel = paper.cited_by_count > 0 ? `${paper.cited_by_count} lượt trích dẫn` : ""; const meta = [sourceLabel, paper.authors.slice(0, 2).join(", ") || "Không rõ tác giả", paper.year ? String(paper.year) : "", citationLabel].filter(Boolean).join(" - "); return <a key={paper.paper_id} href={paper.url || undefined} target={paper.url ? "_blank" : undefined} rel="noreferrer"><strong>{paper.title}</strong><span>{meta}</span></a>; })}</div> : <p className="claude-flow-empty">Kết quả bài báo sẽ xuất hiện tại đây ngay khi bước tìm kiếm hoàn tất.</p>}</div></div></details></section>}
        {currentFlow && !currentResult && ["approved", "changes_requested"].includes(currentFlow.status) && <section className="claude-review-panel claude-report-loading"><strong>Đang tải báo cáo tổng hợp…</strong><span>{reportLoadError[currentFlow.job_id] ?? "Flow đã hoàn tất; hệ thống đang đồng bộ nội dung report."}</span></section>}
        {busy && (!currentFlow || !["error", "cancelled"].includes(currentFlow.status)) && <div className="claude-typing" style={{ order: currentFlow ? flowAnchorIndex + 1 : 0 }}><span /><span /><span /> Agent đang xử lý…</div>}
      </div>
      {hasRightRail && <aside className="claude-chat-rail">
        {showSandboxCandidates && <section className="claude-sandbox-candidates"><div><strong>Phát triển các khoảng trống đã duyệt</strong><span>Mở candidate trong chế độ Giả thuyết để tạo bản thảo có thể kiểm định và thiết kế thực nghiệm.</span></div><div>{(currentResult?.potential_gaps ?? []).map((gap, index) => <Link key={gap.gap_id} href={`/projects/${project?.project_id ?? ""}/sandbox?mode=hypothesis&entrypoint=validated_candidate&source_resource_id=${encodeURIComponent(gap.gap_id)}&title=${encodeURIComponent(`Phát triển candidate ${index + 1}: ${gap.aspect}`)}`}>Tạo giả thuyết {index + 1}</Link>)}</div></section>}
      </aside>}
      {project && <form className="claude-composer" onSubmit={submit}>
        <div className="claude-composer-options">
          <div className="claude-mode" role="group" aria-label={lang === "vi" ? "Chọn chế độ chạy agent" : "Choose agent run mode"}>
            <span>{lang === "vi" ? "CHẾ ĐỘ CHẠY" : "RUN MODE"}</span>
            <select value={executionMode} onChange={(event) => setSavedExecutionMode(event.target.value as "review" | "autonomous")} aria-label={lang === "vi" ? "Chọn chế độ chạy agent" : "Choose agent run mode"}>
              <option value="review">{t("research_ui.mode_review")}</option>
              <option value="autonomous">{t("research_ui.mode_autonomous")}</option>
            </select>
            <small>{executionMode === "review" ? t("research_ui.mode_review_help") : t("research_ui.mode_autonomous_help")}</small>
          </div>
        </div>
        {selectedAnnotations.length > 0 && <div className="claude-composer-annotation-picker"><div className="claude-composer-annotation-row" role="list" aria-label={`${selectedAnnotations.length} annotations`}>{selectedAnnotations.map((annotation, index) => <span className="claude-composer-annotation-chip" key={`${index}-${annotation.slice(0, 24)}`} role="listitem"><button type="button" aria-expanded={annotationPickerOpen && expandedAnnotationIndex === index} onClick={() => { setExpandedAnnotationIndex(index); setAnnotationPickerOpen(true); }}>▣ Annotation {index + 1}</button><button type="button" onClick={() => { setSelectedAnnotations((current) => current.filter((_, itemIndex) => itemIndex !== index)); setExpandedAnnotationIndex(null); }} aria-label={`Xoá Annotation ${index + 1}`}>×</button></span>)}</div>{annotationPickerOpen && expandedAnnotationIndex !== null && selectedAnnotations[expandedAnnotationIndex] && <div className="claude-composer-annotation-popover" role="dialog" aria-label={`Nội dung Annotation ${expandedAnnotationIndex + 1}`}><strong>Annotation {expandedAnnotationIndex + 1}</strong><p>{selectedAnnotations[expandedAnnotationIndex]}</p></div>}</div>}
        <textarea ref={composerInputRef} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} disabled={!project || busy} placeholder={t("research_ui.input_placeholder")} />
        {attachedDocument && <div className="claude-attached-document" aria-live="polite"><span>{attachedDocument.name}</span><button type="button" onClick={() => { setAttachedDocument(null); if (documentInputRef.current) documentInputRef.current.value = ""; }} disabled={busy} aria-label={t("research_ui.remove_document")}>×</button></div>}
        <div className="claude-composer-footer"><span>Enter · Shift + Enter</span><button className="claude-attach-placeholder" type="button" disabled={!project || busy} onClick={() => setUploadDialogOpen(true)} title={t("research_ui.attach_document")} aria-label={t("research_ui.attach_document")}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8.5 12.5 6.7-6.7a3 3 0 1 1 4.2 4.2l-8.5 8.5a5 5 0 0 1-7.1-7.1l8-8" /></svg></button><button type="submit" disabled={!project || busy || (!prompt.trim() && !attachedDocument)} aria-label={t("research_ui.confirm_search")}>↑</button></div>
      </form>}
      {textSelection && <div className="claude-selection-toolbar" role="toolbar" aria-label="Thao tác với đoạn văn bản đã chọn" style={{ top: textSelection.top, left: textSelection.left }} onMouseDown={(event) => event.preventDefault()}><button type="button" onClick={addSelectionToChat}>Thêm vào chat</button></div>}
    </section>

    {uploadDialogOpen && <div className="claude-modal-backdrop" role="presentation" onMouseDown={() => setUploadDialogOpen(false)}><section className="claude-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-document-title" onMouseDown={(event) => event.stopPropagation()}><button className="claude-upload-close" type="button" onClick={() => setUploadDialogOpen(false)} aria-label={t("common.cancel")}>×</button><div className="claude-upload-zone" role="button" tabIndex={0} onClick={() => documentInputRef.current?.click()} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); documentInputRef.current?.click(); } }} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); selectDocument(event.dataTransfer.files?.[0] ?? null); }}><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M10.5 24h10.1a5.4 5.4 0 0 0 .7-10.8A6.7 6.7 0 0 0 8.5 15.1 4.5 4.5 0 0 0 10.5 24Z" /><path d="m16 20.5 0-9m0 0-3.2 3.2M16 11.5l3.2 3.2" /></svg><h2 id="upload-document-title">{lang === "vi" ? "Tải tài liệu lên" : "Upload a document"}</h2><p>{lang === "vi" ? "Kéo thả tệp vào đây hoặc chọn tệp từ máy tính" : "Drop a file here or choose one from your computer"}<br />{lang === "vi" ? "Hỗ trợ PDF, DOCX · tối đa 10 MB" : "PDF and DOCX supported · up to 10 MB"}</p><button className="claude-upload-browse" type="button" onClick={(event) => { event.stopPropagation(); documentInputRef.current?.click(); }}>{lang === "vi" ? "Chọn tệp" : "Browse files"}</button><input ref={documentInputRef} className="claude-upload-input" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => { selectDocument(event.currentTarget.files?.[0] ?? null); event.currentTarget.value = ""; }} /></div><p className="claude-upload-retention">{lang === "vi" ? "Tệp chỉ được dùng để tạo truy vấn tìm paper và được xoá ngay sau khi đọc." : "The file is used only to create a paper-search query and is deleted immediately after extraction."}</p></section></div>}

    {creatingProject && <div className="claude-modal-backdrop"><form className="claude-modal" onSubmit={createProject}><button type="button" className="claude-modal-close" onClick={() => setCreatingProject(false)}>×</button><span>DỰ ÁN MỚI</span><h2>Tạo không gian nghiên cứu</h2><p>Mỗi dự án có một cuộc chat chung, các flow nghiên cứu và báo cáo tổng hợp.</p><label>Tên dự án<input autoFocus value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Ví dụ: AI trong giáo dục đại học" /></label><button disabled={busy || !projectName.trim()} type="submit">Tạo dự án</button></form></div>}
    {latexEditorReport && <div className="latex-editor-layer" role="dialog" aria-modal="true" aria-label="Chỉnh sửa bài báo cáo bằng LaTeX"><section className="latex-editor" onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveLatexReport(); } }}><header className="latex-editor-header"><div><span>TRÌNH SOẠN THẢO BÁO CÁO</span><h2>{latexEditorReport.topic}</h2></div><div className="latex-editor-header-actions"><button className="latex-cancel-btn" type="button" onClick={() => setLatexEditorReport(null)}>Hủy</button><button className="latex-save-btn" type="button" onClick={saveLatexReport}>Lưu thay đổi</button></div></header><div className="latex-editor-note">Chỉnh sửa nội dung và tài liệu tham khảo dạng bibliography/bibitem. Nhấn Ctrl/Cmd + S để lưu.</div><div className="latex-editor-workspace"><label className="latex-code-pane"><span>LATEX</span><textarea value={latexDraft} onChange={(event) => setLatexDraft(event.target.value)} spellCheck={false} aria-label="Mã LaTeX bài báo cáo" /></label><section className="latex-preview-pane" aria-live="polite"><span>XEM TRƯỚC</span><article><MessageContent text={latexToReportText(latexDraft, latexEditorReport.references) || "Bắt đầu nhập nội dung LaTeX để xem trước."} /></article></section></div></section></div>}
    {mindMapArtifact && <div className="report-visual-layer" role="dialog" aria-modal="true" aria-label="Mind map báo cáo"><section className="report-mindmap"><header><div><h2>Mind map báo cáo</h2><p>{mindMapArtifact.report.topic}</p></div><div className="report-visual-actions"><button className="report-visual-export" type="button" onClick={() => exportMindMapPng(mindMapArtifact.artifact)}>PNG</button><button className="report-visual-export" type="button" onClick={() => exportMindMapPdf(mindMapArtifact.artifact)}>Xuất PDF</button><button className="report-visual-close" type="button" onClick={() => setMindMapArtifact(null)} aria-label="Đóng mind map">×</button></div></header><MindMapDiagram artifact={mindMapArtifact.artifact} /></section></div>}
    {slideDeckArtifact && (() => { const slides = slideDeckArtifact.artifact.slides; const activeSlide = slides[activeSlideIndex] ?? slides[0]; return activeSlide ? <div className="report-visual-layer" role="dialog" aria-modal="true" aria-label="Slide thuyết trình"><section className="report-slides"><header><div><h2>Slide thuyết trình</h2><p>{visualArtifactText(slideDeckArtifact.artifact.title)}</p></div><div className="report-visual-actions"><button className="report-visual-export" type="button" onClick={() => exportSlidesPdf(slideDeckArtifact.artifact)}>Xuất PDF</button><button className="report-visual-close" type="button" onClick={() => setSlideDeckArtifact(null)} aria-label="Đóng slide">×</button></div></header><div className={`slide-canvas${activeSlide.image_data_url ? " has-image" : ""}`}>{activeSlide.image_data_url && <img className="slide-illustration" src={activeSlide.image_data_url} alt={activeSlide.visual_alt || `Minh hoạ AI cho ${visualArtifactText(activeSlide.title)}`} />}<span>{visualArtifactText(activeSlide.subtitle || "Báo cáo tổng hợp")}</span><h3>{visualArtifactText(activeSlide.title)}</h3><ul>{activeSlide.points.map((point, index) => <li key={index}>{visualArtifactText(point)}</li>)}</ul>{activeSlide.image_data_url && <em className="slide-image-label">Minh hoạ AI · không phải bằng chứng</em>}<small>{String(activeSlideIndex + 1).padStart(2, "0")} / {String(slides.length).padStart(2, "0")}</small></div>{activeSlide.speaker_notes && <details className="slide-notes"><summary>Ghi chú thuyết trình</summary><p>{visualArtifactText(activeSlide.speaker_notes)}</p></details>}<footer><button type="button" onClick={() => setActiveSlideIndex((index) => Math.max(0, index - 1))} disabled={activeSlideIndex === 0}>← Trước</button><div>{slides.map((slide, index) => <button key={slide.title} type="button" className={index === activeSlideIndex ? "active" : ""} onClick={() => setActiveSlideIndex(index)}>{index + 1}</button>)}</div><button type="button" onClick={() => setActiveSlideIndex((index) => Math.min(slides.length - 1, index + 1))} disabled={activeSlideIndex === slides.length - 1}>Sau →</button></footer></section></div> : null; })()}
  </main>;
}

function WorkspaceUnavailable() { return <main className="claude-loading">Cần cấu hình Clerk để dùng workspace này.</main>; }
export default function Workspace() { return configured ? <WorkspaceData /> : <WorkspaceUnavailable />; }
