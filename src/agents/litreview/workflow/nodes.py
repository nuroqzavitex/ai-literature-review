"""LitReview Agent Nodes Execution Implementation.

OWNER: Leader & Team
TECHNICAL CONTRACT SPEC: Mục 5.1

14 Nodes:
1. intent_guardrail_node   8. synthesize_claims_node
2. plan_search_node        9. validate_grounding_node
3. search_academic_sources_node   10. revise_claims_node
4. assess_sources_node     11. human_review_node
5. refine_query_node       12. finalize_node
6. screen_papers_node      13. out_of_scope_node
7. extract_evidence_node   14. fail_node
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
from pydantic import ValidationError

from src.agents.litreview.domain.models import (
    AgentDecision,
    AgentState,
    Claim,
    ClaimCandidate,
    EvidenceQuote,
    EvidenceRow,
    LiteratureReview,
    Paper,
    PotentialGap,
    Reference,
    RevisionRecord,
    RevisionSource,
    Theme,
)
from src.agents.litreview.prompts.extraction import BatchExtractionResult, get_extraction_prompt
from src.agents.litreview.prompts.intent import IntentClassification, get_intent_guardrail_prompt
from src.agents.litreview.prompts.literature_review import (
    LiteratureReviewDraft,
    get_literature_review_markdown_prompt,
    get_literature_review_prompt,
)
from src.agents.litreview.prompts.query_planning import SubQueryPlan, get_query_planning_prompt
from src.agents.litreview.prompts.relevance import PaperRelevanceBatch, get_paper_relevance_prompt
from src.agents.litreview.prompts.research_gap import ResearchGapAssessmentResult, get_research_gap_prompt
from src.agents.litreview.prompts.revision import RevisionResult, get_revision_prompt
from src.agents.litreview.prompts.synthesis import (
    GapCoverage,
    SynthesisResult,
    SynthesizedGap,
    get_gap_recovery_prompt,
    get_synthesis_prompt,
)
from src.agents.litreview.prompts.validation import EntailmentResult, get_entailment_prompt
from src.agents.litreview.tools.openalex import search_academic_sources
from src.config import get_settings
from src.logging_utils import event, id_summary, paper_summary
from src.services.academic_search import AcademicSearchService, rank_papers
from src.services.language import response_language
from src.services.llm import get_llm, get_llm_fallbacks
from src.services.paper_ingestion import ingest_papers
from src.services.vector_store import QdrantVectorStore, VectorStoreError
from src.validation.grounding import check_absolute_wording, validate_summary

logger = logging.getLogger(__name__)
_SUB_QUERY_MIN_TERMS = 8
_SUB_QUERY_MAX_TERMS = 14


def _compact_sub_query(value: str) -> str:
    """Preserve descriptive phrases while removing provider wildcard syntax."""
    cleaned = " ".join(re.sub(r"[*?]+", " ", value).split()).strip(" -,:;")
    cleaned = re.sub(
        r"^(?:what|how|why|which|where|when)\s+(?:(?:does|do|is|are|can|could|would|should)\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return " ".join(cleaned.split()[:_SUB_QUERY_MAX_TERMS])


def _fallback_sub_query(value: str) -> str:
    """Keep a degraded-mode query bounded while retaining the user's topic."""
    words = _compact_sub_query(value).split()
    for qualifier in ("academic", "research", "methods", "evidence", "evaluation"):
        if len(words) >= _SUB_QUERY_MIN_TERMS:
            break
        words.append(qualifier)
    return " ".join(words[:_SUB_QUERY_MAX_TERMS])


def _has_valid_sub_query_length(value: str) -> bool:
    return _SUB_QUERY_MIN_TERMS <= len(value.split()) <= _SUB_QUERY_MAX_TERMS


_PUBLICATION_YEAR_RANGE_PATTERN = re.compile(
    r"(?:from|từ|giai đoạn|between)?\s*(?:year|năm)?\s*"
    r"(?P<start>(?:19|20)\d{2})\s*(?:-|–|—|to|đến|tới|and)\s*"
    r"(?:year|năm)?\s*(?P<end>(?:19|20)\d{2})",
    re.IGNORECASE,
)
_PUBLICATION_YEAR_FROM_PATTERN = re.compile(
    r"(?:from|since|từ|kể\s+từ)\s*(?:year|năm)?\s*(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)
_PUBLICATION_YEAR_BEFORE_PATTERN = re.compile(
    r"(?:before|trước)\s*(?:year|năm)?\s*(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)


def _explicit_publication_year_range(value: str) -> tuple[int | None, int | None] | None:
    """Parse common explicit publication windows without relying on an LLM."""
    if match := _PUBLICATION_YEAR_RANGE_PATTERN.search(value):
        return int(match["start"]), int(match["end"])
    if match := _PUBLICATION_YEAR_FROM_PATTERN.search(value):
        return int(match["year"]), None
    if match := _PUBLICATION_YEAR_BEFORE_PATTERN.search(value):
        return None, int(match["year"]) - 1
    return None


def _matches_publication_year(paper: Paper, publication_year_range: tuple[int | None, int | None] | None) -> bool:
    """Apply an explicit user-requested publication window as a hard filter."""
    if publication_year_range is None:
        return True
    year = paper.get("year")
    if not isinstance(year, int):
        return False
    start, end = publication_year_range
    return (start is None or year >= start) and (end is None or year <= end)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


_PAPER_CITATION_PATTERN = re.compile(r"\[\[([A-Za-z0-9_.:-]+)\]\]")
_SHORT_CITATION_PATTERN = re.compile(r"(?<!\[)\[(?:paper\s*|p|r)?(\d+)\](?!\])", re.IGNORECASE)
_SINGLE_CITATION_WITH_EXTRA_CLOSE_PATTERN = re.compile(r"(?<!\[)\[(?:paper\s*|p|r)?(\d+)\]\]+", re.IGNORECASE)
_BRACKETED_ALIAS_PATTERN = re.compile(r"\[\[(?:paper\s*|p|r)?(\d+)\]\]", re.IGNORECASE)
_MALFORMED_BRACKETED_ALIAS_PATTERN = re.compile(r"\[\[(?:paper\s*|p|r)?(\d+)\](?!\])", re.IGNORECASE)
_CITATION_ALIAS_PATTERN = re.compile(r"^(?:paper\s*|p|r)?(\d+)$", re.IGNORECASE)
_GROUPED_CITATION_ALIAS_PATTERN = re.compile(
    r"\[\[\s*((?:(?:paper\s*|p|r)?\d+\s*[,;]\s*)+(?:paper\s*|p|r)?\d+)\s*\]\]",
    re.IGNORECASE,
)
_SINGLE_GROUPED_CITATION_ALIAS_PATTERN = re.compile(
    r"(?<!\[)\[\s*((?:(?:paper\s*|p|r)?\d+\s*[,;]\s*)+(?:paper\s*|p|r)?\d+)\s*\](?!\])",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_PATTERN = re.compile(r"(?m)^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_MARKDOWN_FENCE_PATTERN = re.compile(
    r"\A\s*```(?:markdown|md)?\s*(?P<body>[\s\S]*?)\s*```\s*\Z",
    re.IGNORECASE,
)
# Ranking already requires a shared subject term.  This second floor prevents a
# weak incidental overlap from becoming a citation in a generated report.
# The final corpus gate is semantic cosine similarity, produced by Qdrant from
# the configured embedding model. Lexical relevance remains a first-pass guard
# against term drift; it is never presented as an embedding score.
_MIN_EMBEDDING_RELEVANCE_SCORE = 0.6
_CLAIM_VALIDATION_RETRY_CONCURRENCY = 3
_CLAIM_VALIDATION_429_BACKOFF_SECONDS = 1.0
_MIN_GAP_CORPUS_SIZE = 4


def _normalized_passage_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _attach_evidence_context(evidence: dict, source_text: str) -> dict:
    """Keep the verbatim quote and attach one neighboring sentence on each side."""
    resolved = dict(evidence)
    quote = str(evidence.get("quote") or "").strip()
    source = str(source_text or "").strip()
    if not quote or not source:
        return resolved

    tokens = quote.split()
    if not tokens:
        return resolved
    quote_pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(quote_pattern, source, flags=re.IGNORECASE)
    if not match:
        return resolved

    sentence_spans: list[tuple[int, int]] = []
    sentence_start = 0
    for boundary in re.finditer(r"[.!?][\"'’”]*\s+", source):
        sentence_end = boundary.end()
        while sentence_end > sentence_start and source[sentence_end - 1].isspace():
            sentence_end -= 1
        if source[sentence_start:sentence_end].strip():
            sentence_spans.append((sentence_start, sentence_end))
        sentence_start = boundary.end()
    if source[sentence_start:].strip():
        sentence_spans.append((sentence_start, len(source)))

    overlapping = [
        index for index, (start, end) in enumerate(sentence_spans) if start < match.end() and end > match.start()
    ]
    if not overlapping:
        return resolved

    first_index, last_index = overlapping[0], overlapping[-1]
    before_start = sentence_spans[first_index - 1][0] if first_index > 0 else sentence_spans[first_index][0]
    context_before = source[before_start : match.start()].strip()
    if context_before:
        resolved["context_before"] = context_before
    after_end = (
        sentence_spans[last_index + 1][1] if last_index + 1 < len(sentence_spans) else sentence_spans[last_index][1]
    )
    context_after = source[match.end() : after_end].strip()
    if context_after:
        resolved["context_after"] = context_after
    return resolved


def _is_usable_fulltext_passage(item: dict) -> bool:
    """Exclude obvious reference-list and metadata chunks from evidence."""
    if item.get("source_level") != "full_text":
        return False
    text = str(item.get("quote") or "").strip()
    section_type = str(item.get("section_type") or "").strip().lower()
    if not text or section_type == "references":
        return False
    lowered = text.casefold()
    if re.match(r"^(references|bibliography|works cited)\b", lowered):
        return False
    metadata_labels = sum(marker in lowered for marker in ("paper id:", "authors:", "year:", "url:"))
    if metadata_labels >= 3:
        return False
    doi_count = lowered.count("https://doi.org/") + lowered.count("doi:")
    return doi_count < 3 and len(re.findall(r"\[\d+\]", text)) < 6


def _resolve_retrieved_evidence(evidence_list: list[dict], retrieved: list[dict]) -> list[dict]:
    """Attach Qdrant provenance and context without replacing the extracted quote."""
    usable = [item for item in retrieved if _is_usable_fulltext_passage(item)]
    resolved: list[dict] = []
    for evidence in evidence_list:
        quote = _normalized_passage_text(str(evidence.get("quote") or ""))
        match = next(
            (
                item
                for item in usable
                if item.get("paper_id") == evidence.get("paper_id")
                and quote
                and quote in _normalized_passage_text(str(item.get("quote") or ""))
            ),
            None,
        )
        if not match:
            resolved.append(evidence)
            continue
        provenance = {key: value for key, value in match.items() if key != "quote"}
        resolved.append(
            _attach_evidence_context(
                {**evidence, **provenance, "quote": evidence.get("quote", "")},
                str(match.get("quote") or ""),
            )
        )
    return resolved


async def _fulltext_first_contexts(
    papers: list[Paper], topic: str, state: AgentState, chunks_per_paper: int = 4
) -> dict[str, dict[str, str]]:
    """Retrieve topical full-text passages per paper, with an abstract fallback."""
    contexts = {paper["paper_id"]: {"text": paper["abstract"], "source_level": "abstract"} for paper in papers}
    if not papers or not get_settings().qdrant_enabled:
        return contexts

    try:
        store = QdrantVectorStore(backend=state.get("embedding_backend", "primary"))

        async def retrieve(paper: Paper) -> tuple[str, list[dict]]:
            passages = await store.retrieve_claim_evidence(
                topic,
                state.get("job_id") or state.get("thread_id") or "adhoc",
                paper_ids=[paper["paper_id"]],
                limit=chunks_per_paper,
            )
            return paper["paper_id"], passages

        retrieved = await asyncio.gather(*(retrieve(paper) for paper in papers))
    except VectorStoreError as exc:
        logger.warning(
            "full-text retrieval fallback job=%s error=%s",
            state.get("job_id") or state.get("thread_id") or "adhoc",
            exc,
        )
        return contexts

    for paper_id, passages in retrieved:
        full_text = [item["quote"] for item in passages if _is_usable_fulltext_passage(item)]
        if full_text:
            contexts[paper_id] = {"text": "\n\n".join(full_text), "source_level": "full_text"}
    return contexts


_FAILOVER_ERROR_MARKERS = (
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "invalid authentication",
    "authentication_error",
    "unauthenticated",
    "unauthorized",
    "forbidden",
    "permission_denied",
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "status code 401",
    "status code 403",
    "status code 429",
    "error code: 401",
    "error code: 403",
    "status code 500",
    "status code 502",
    "status code 503",
    "service unavailable",
    "connection error",
    "connect timeout",
    "read timeout",
)

_SCHEMA_CAPABILITY_ERROR_MARKERS = (
    "response_format type is unavailable",
    "response_format is unavailable",
    "response_format is not supported",
    "response_format unsupported",
    "json_schema is not supported",
    "structured output is not supported",
    "structured outputs are not supported",
)

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(?P<body>[\s\S]*?)\s*```$", re.IGNORECASE)


class PromptedJSONValidationError(ValueError):
    """Raised when a prompt-JSON response cannot satisfy the Pydantic schema."""


def _is_provider_failover_error(error: Exception) -> bool:
    """Return True for an LLM provider availability/configuration failure."""

    message = str(error).lower()
    return any(marker in message for marker in _FAILOVER_ERROR_MARKERS)


def _is_provider_concurrency_error(error: BaseException) -> bool:
    """Detect an HTTP 429 concurrency limit through wrapped exception causes."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).lower()
        if "too many concurrent requests" in message or ("429" in message and "too many requests" in message):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_schema_capability_error(error: Exception) -> bool:
    """Return True when a provider rejects native ``response_format`` support."""

    message = str(error).lower()
    return (
        any(marker in message for marker in _SCHEMA_CAPABILITY_ERROR_MARKERS)
        # Gemini reports some response-schema validation failures as the generic
        # INVALID_ARGUMENT instead of naming response_format. This branch runs
        # only before prompted-JSON mode is enabled, so retrying without native
        # schema is the safe recovery path.
        or ("googleinvalidrequesterror" in message and "invalid_argument" in message)
    )


def _is_structured_output_error(error: Exception) -> bool:
    """Return True when a provider response cannot satisfy the output schema.

    These failures are model-response failures, not evidence that a claim is
    unsupported.  They are therefore retried once and then routed to the next
    configured provider instead of being converted into a grounding verdict.
    """

    return isinstance(error, (PromptedJSONValidationError, ValidationError, OutputParserException))


def _parse_prompted_json(content: object, schema):
    """Accept one JSON object (optionally in one JSON fence) and validate it strictly."""

    if not isinstance(content, str):
        raise PromptedJSONValidationError("Model response content must be a text JSON object")

    text = content.strip()
    fenced = _JSON_FENCE_PATTERN.fullmatch(text)
    if fenced:
        text = fenced.group("body").strip()
    elif text.startswith("```") or text.endswith("```"):
        raise PromptedJSONValidationError("Model response contains an incomplete or non-JSON Markdown fence")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PromptedJSONValidationError(f"Model returned invalid JSON: {exc.msg}") from exc

    try:
        return schema.model_validate(payload, strict=True, extra="forbid")
    except ValidationError as exc:
        raise PromptedJSONValidationError(f"JSON does not match the required schema: {exc}") from exc


class _StructuredLLMInvoker:
    """Invoke a structured prompt and rotate through configured LLM fallbacks.

    A successful fallback remains preferred for the rest of this node execution.
    This is especially important for extraction, where several batches can be
    processed during one job. Providers are supplied only by
    get_llm_fallbacks; no key or endpoint is manufactured at runtime.
    """

    def __init__(
        self,
        prompt,
        schema,
        operation: str,
        job_id: str | None = None,
        run_id: str | None = None,
        node_name: str | None = None,
        execution_mode: str = "unknown",
        structured_output_retries: int = 1,
    ):
        self._prompt = prompt
        self._schema = schema
        self._operation = operation
        self._job_id = job_id or "adhoc"
        self._run_id = run_id or self._job_id
        self._node_name = node_name or operation
        self._execution_mode = execution_mode
        self._structured_output_retries = structured_output_retries
        self._clients: list | None = None
        self._preferred_index = 0
        self._prompted_json_indices: set[int] = set()

    def _get_clients(self) -> list:
        if self._clients is None:
            self._clients = [get_llm(), *get_llm_fallbacks()]
        return self._clients

    def _prompted_json_messages(self, inputs: dict, *, repair: bool = False) -> list:
        schema_json = json.dumps(self._schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "Return exactly one valid JSON object and no Markdown, code fence, or surrounding text. "
            "The response must validate against this JSON Schema exactly: "
            f"{schema_json}"
        )
        if repair:
            instruction = (
                "Your previous output was invalid. Return only a corrected JSON object that matches "
                "this schema exactly; do not include an explanation, Markdown, or a code fence. "
                f"JSON Schema: {schema_json}"
            )
        return [SystemMessage(content=instruction), *self._prompt.format_messages(**inputs)]

    async def ainvoke(self, inputs: dict, *, trace_context: dict | None = None):
        clients = self._get_clients()
        last_error: Exception | None = None
        start_index = self._preferred_index
        call_id = f"llm_{uuid4().hex}"
        call_started = perf_counter()
        trace_context = trace_context or {}

        for offset in range(len(clients)):
            index = (start_index + offset) % len(clients)
            candidate = clients[index]
            endpoint = getattr(candidate, "endpoint", None)
            provider = getattr(endpoint, "provider", "unknown")
            model = getattr(endpoint, "model", "unknown")
            llm_state = {"job_id": self._job_id, "run_id": self._run_id, "execution_mode": self._execution_mode}
            provider_started = perf_counter()
            event(
                logger,
                "llm.attempt",
                state=llm_state,
                operation=self._operation,
                node=self._node_name,
                provider=provider,
                model=model,
                call_id=call_id,
                fallback_index=index,
                retry_index=0,
                native_schema_supported=getattr(candidate, "native_schema_supported", True),
                **trace_context,
            )
            native_schema_supported = getattr(candidate, "native_schema_supported", True)
            prompted_json = not native_schema_supported or index in self._prompted_json_indices
            retries_used = 0
            repair_json = False

            while True:
                try:
                    if prompted_json:
                        messages = self._prompted_json_messages(inputs, repair=repair_json)
                        raw_client = getattr(candidate, "client", candidate)
                        response = await raw_client.ainvoke(messages)
                        raw_content = getattr(response, "content", response)
                        result = _parse_prompted_json(raw_content, self._schema)
                    else:
                        structured_llm = candidate.with_structured_output(self._schema)
                        chain = self._prompt | structured_llm
                        result = await chain.ainvoke(inputs)
                    self._preferred_index = index
                    event(
                        logger,
                        "llm.success",
                        state=llm_state,
                        operation=self._operation,
                        node=self._node_name,
                        provider=provider,
                        model=model,
                        call_id=call_id,
                        fallback_index=index,
                        retry_index=retries_used,
                        duration_ms=round((perf_counter() - call_started) * 1000),
                        provider_duration_ms=round((perf_counter() - provider_started) * 1000),
                        **trace_context,
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    if not prompted_json and _is_schema_capability_error(exc):
                        prompted_json = True
                        self._prompted_json_indices.add(index)
                        logger.warning(
                            "LLM %s does not support native response_format; switching to prompted JSON validation.",
                            self._operation,
                        )
                        event(
                            logger,
                            "llm.retry",
                            state=llm_state,
                            level=logging.WARNING,
                            operation=self._operation,
                            node=self._node_name,
                            provider=provider,
                            model=model,
                            call_id=call_id,
                            retry_index=retries_used,
                            failure_code="NATIVE_SCHEMA_UNSUPPORTED",
                            fallback_reason="provider does not support native structured output",
                            **trace_context,
                        )
                        continue

                    structured_error = _is_structured_output_error(exc)
                    provider_error = _is_provider_failover_error(exc)

                    if structured_error and retries_used < self._structured_output_retries:
                        retries_used += 1
                        # Native parsing can hide the raw invalid payload. Retrying
                        # with a JSON-only repair prompt gives Ollama-compatible
                        # models one clear chance to correct their format.
                        prompted_json = True
                        repair_json = True
                        self._prompted_json_indices.add(index)
                        logger.warning(
                            "LLM %s returned invalid structured output; retrying provider once with a JSON repair prompt.",
                            self._operation,
                        )
                        event(
                            logger,
                            "llm.retry",
                            state=llm_state,
                            level=logging.WARNING,
                            operation=self._operation,
                            node=self._node_name,
                            provider=provider,
                            model=model,
                            call_id=call_id,
                            retry_index=retries_used,
                            failure_code="STRUCTURED_OUTPUT_REPAIR",
                            fallback_reason="retrying once with explicit JSON-only repair prompt",
                            **trace_context,
                        )
                        continue
                    if not structured_error and not provider_error:
                        raise
                    break

            self._preferred_index = (index + 1) % len(clients)
            event(
                logger,
                "llm.failed",
                state=llm_state,
                level=logging.WARNING,
                operation=self._operation,
                node=self._node_name,
                provider=provider,
                model=model,
                call_id=call_id,
                fallback_index=index,
                retry_index=retries_used,
                duration_ms=round((perf_counter() - call_started) * 1000),
                provider_duration_ms=round((perf_counter() - provider_started) * 1000),
                error_type=type(last_error).__name__ if last_error else "unknown",
                error=str(last_error) if last_error else "unknown",
                failure_code=(
                    "STRUCTURED_OUTPUT_INVALID" if _is_structured_output_error(last_error) else "PROVIDER_FAILURE"
                ),
                failed_stage="llm.invoke",
                fallback_reason=(
                    "next configured provider" if offset < len(clients) - 1 else "no configured provider remains"
                ),
                **trace_context,
            )
            if offset < len(clients) - 1:
                failure_kind = "structured-output" if _is_structured_output_error(last_error) else "provider"
                logger.warning(
                    "LLM %s failed with a %s error; rotating to the next configured fallback.",
                    self._operation,
                    failure_kind,
                )
            else:
                logger.error("LLM %s failed on the final configured provider.", self._operation)

        assert last_error is not None
        raise last_error


# ─── Node 1: plan_search_node ──────────────────────────────────────────────────


def _guardrail_rejection_response(topic: str, intent: str) -> str:
    if intent == "unsafe":
        if response_language(topic) == "Vietnamese":
            return (
                "Mình không thể hỗ trợ nội dung cổ vũ phân biệt đối xử hoặc hướng dẫn "
                "hành động nguy hiểm. Mình có thể hỗ trợ tổng quan tài liệu trung lập, có "
                "trích dẫn về tác động, phòng ngừa hoặc giảm thiểu tác hại của chủ đề này."
            )
        return (
            "I can’t help with discriminatory or dangerous content. I can help with a "
            "neutral, cited literature review on the impacts, prevention, or harm reduction "
            "related to this topic."
        )
    if response_language(topic) == "Vietnamese":
        return (
            "Mình chỉ hỗ trợ các yêu cầu liên quan đến tổng quan tài liệu học thuật "
            "(LitReview), như tìm, đánh giá, so sánh và tổng hợp nghiên cứu có nguồn trích dẫn. "
            "Bạn có thể cho mình một chủ đề hoặc câu hỏi nghiên cứu để mình hỗ trợ nhé."
        )
    return (
        "I can only help with academic literature-review requests, such as finding, "
        "evaluating, comparing, and synthesizing cited research. Please share a research "
        "topic or question and I will help."
    )


async def intent_guardrail_node(state: AgentState) -> dict:
    """Route untrusted user input before any research, retrieval, or synthesis runs."""

    topic = (state.get("original_topic") or "").strip()
    if not topic:
        raise ValueError("Missing original_topic in LangGraph initial state")

    try:
        classifier = _StructuredLLMInvoker(
            get_intent_guardrail_prompt(),
            IntentClassification,
            "intent guardrail",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="intent_guardrail",
            execution_mode=state.get("execution_mode", "review"),
        )
        classification = await classifier.ainvoke({"topic": topic}, trace_context={"batch_id": "intent_guardrail"})
        intent = classification.intent
        reason = classification.reason.strip()
    except Exception as exc:
        # This is an LLM-only guardrail: do not substitute keyword matching or
        # heuristic classification. Fail closed so unsafe content cannot bypass
        # the safety boundary when every configured LLM is unavailable.
        logger.warning("LLM intent guardrail failed; denying request safely: %s", exc)
        intent = "unsafe"
        reason = "Safety classifier unavailable; request was not processed."

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="intent_guardrail",
            action="continue" if intent == "litreview" else "finish",
            reason=reason,
            created_at=_now_iso(),
        )
    )
    return {
        "intent": intent,
        "intent_reason": reason,
        "decisions": decisions,
        "status": "running" if intent == "litreview" else "approved",
        "current_node": "intent_guardrail",
    }


async def out_of_scope_node(state: AgentState) -> dict:
    """Return a bounded reply without invoking research capabilities."""

    topic = (state.get("original_topic") or "").strip()
    response = _guardrail_rejection_response(topic, state.get("intent", "out_of_scope"))
    return {
        "assistant_response": response,
        "scope_disclaimer": response,
        "status": "approved",
        "current_node": "out_of_scope",
    }


# ─── Node 2: plan_search_node ──────────────────────────────────────────────────


async def plan_search_node(state: AgentState) -> dict:
    topic = (state.get("original_topic") or "").strip()
    if not topic:
        raise ValueError("Missing original_topic in LangGraph initial state")
    query = topic
    history = list(state.get("conversation_history", []))
    history_text = (
        "\n".join(
            f"{turn.get('role', 'user')}: {str(turn.get('text', '')).strip()}"
            for turn in history[-20:]
            if str(turn.get("text", "")).strip()
        )
        or "(No previous conversation turns.)"
    )
    try:
        planner = _StructuredLLMInvoker(
            get_query_planning_prompt(),
            SubQueryPlan,
            "query planning",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="plan_search",
            execution_mode=state.get("execution_mode", "review"),
        )
        planned = await planner.ainvoke(
            {"topic": topic, "conversation_history": history_text}, trace_context={"batch_id": "query_planning"}
        )
        query = planned.normalized_question.strip()
        sub_queries = list(
            dict.fromkeys(
                compact for raw_query in planned.sub_queries if (compact := _compact_sub_query(raw_query.strip()))
            )
        )
        required_terms = list(dict.fromkeys(term.strip() for term in planned.required_terms if term.strip()))
        excluded_terms = list(dict.fromkeys(term.strip() for term in planned.excluded_terms if term.strip()))
        planned_year_range = (
            tuple(planned.publication_year_range) if planned.publication_year_range is not None else None
        )
        publication_year_range = _explicit_publication_year_range(topic) or planned_year_range
    except Exception as exc:
        logger.warning("LLM query planning failed; using contextual fallback: %s", exc)
        context_hint = next(
            (str(turn.get("text", "")).strip() for turn in reversed(history[:-1]) if str(turn.get("text", "")).strip()),
            "",
        )
        base = (
            f"{topic} {context_hint}".strip() if context_hint and context_hint.lower() not in topic.lower() else topic
        )
        sub_queries = list(
            dict.fromkeys(
                _fallback_sub_query(candidate)
                for candidate in (
                    f"{base} methods and evaluation",
                    f"{base} empirical evidence and outcomes",
                    f"{base} limitations challenges and implementation",
                )
                if _fallback_sub_query(candidate)
            )
        )
        required_terms = []
        excluded_terms = []
        publication_year_range = _explicit_publication_year_range(topic)
    if not sub_queries:
        raise ValueError("LLM returned no usable sub-queries")
    event(
        logger,
        "plan_search.completed",
        state=state,
        normalized_question=query,
        sub_queries=sub_queries,
        required_terms=required_terms,
        excluded_terms=excluded_terms,
        publication_year_range=publication_year_range,
    )

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="plan_search",
            action="continue",
            reason=f"LLM-normalized research question: '{query}'",
            created_at=_now_iso(),
        )
    )

    return {
        "original_topic": topic,
        "search_query": query,
        "normalized_question": query,
        "search_attempt": 0,
        "max_search_attempts": 2,
        "grounding_revision_attempt": 0,
        "review_revision_attempt": 0,
        "max_claim_revision_attempts": 1,
        "revision_source": None,
        "revision_log": [],
        # Keep the history truthful: these variants are proposals until the
        # user confirms them at the interrupt below. ``sub_queries`` is the
        # editable plan shown in the UI; ``query_history`` records searches
        # that have actually been accepted/run.
        "query_history": [query],
        "sub_queries": sub_queries,
        "required_terms": required_terms,
        "excluded_terms": excluded_terms,
        "publication_year_range": publication_year_range,
        "execution_mode": state.get("execution_mode", "review"),
        "hitl_stage": None if state.get("execution_mode", "review") == "autonomous" else "subqueries",
        "decisions": decisions,
        "status": "running",
        "current_node": "plan_search",
    }


# ─── Node 2: search_academic_sources_node ──────────────────────────────────────


async def search_academic_sources_node(state: AgentState) -> dict:
    queries = [str(query).strip() for query in state.get("sub_queries", []) if str(query).strip()]
    query = (state.get("search_query") or state.get("original_topic") or "").strip()
    if not queries and not query:
        raise ValueError("Missing search_query and original_topic before OpenAlex search")
    requested_limit = state.get("max_results") or 20
    event(
        logger,
        "search.started",
        state=state,
        queries=queries or [query],
        requested_limit=requested_limit,
        search_attempt=state.get("search_attempt", 0) + 1,
    )
    # Retrieve a wider candidate pool before the deterministic relevance ranker
    # selects the requested number of papers. Fetching only requested_limit
    # caused relevant works at OpenAlex positions 11-20 to be discarded before
    # they could be scored against the research topic.
    retrieval_limit = max(requested_limit, get_settings().max_ranked_papers)
    attempt = state.get("search_attempt", 0) + 1

    queries = queries or [query]
    try:
        # Sub-queries are independent network calls, so run them concurrently.
        batches = await asyncio.gather(
            *[search_academic_sources.ainvoke({"query": sub_query, "limit": retrieval_limit}) for sub_query in queries]
        )
        new_papers = [paper for batch in batches for paper in batch]
        event(
            logger,
            "search.completed",
            state=state,
            retrieval_limit=retrieval_limit,
            retrieved_count=len(new_papers),
            retrieved_paper_ids=id_summary([paper.get("paper_id") for paper in new_papers]),
            search_attempt=attempt,
        )
        error_msg = None
    except Exception as exc:
        logger.exception(
            "node=search_academic_sources job=%s failed", state.get("job_id") or state.get("thread_id") or "adhoc"
        )
        event(
            logger,
            "search.failed",
            state=state,
            level=logging.ERROR,
            search_attempt=attempt,
            failure_code="ACADEMIC_SEARCH_FAILED",
            failed_stage="search.provider",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        new_papers = []
        error_msg = str(exc)

    existing_papers = list(state.get("papers", []))
    # Searches are performed independently for each approved sub-query.  Use
    # the same cross-provider canonicalization as the search service so a
    # preprint and its published version cannot count as two sources.
    merged_papers = AcademicSearchService._deduplicate(existing_papers + new_papers)
    publication_year_range = state.get("publication_year_range")
    if publication_year_range is not None:
        before_filter_count = len(merged_papers)
        merged_papers = [paper for paper in merged_papers if _matches_publication_year(paper, publication_year_range)]
        event(
            logger,
            "search.publication_year_filtered",
            state=state,
            publication_year_range=publication_year_range,
            before_filter_count=before_filter_count,
            after_filter_count=len(merged_papers),
        )
    event(
        logger,
        "search.corpus_merged",
        state=state,
        existing_count=len(existing_papers),
        new_count=len(new_papers),
        deduplicated_count=len(merged_papers),
        paper_ids=id_summary([paper.get("paper_id") for paper in merged_papers]),
        search_attempt=attempt,
    )

    result = {
        "papers": merged_papers,
        "search_attempt": attempt,
        "query_history": queries,
        "current_node": "search_academic_sources",
    }
    if error_msg:
        result["error"] = error_msg

    return result


async def review_subqueries_node(state: AgentState) -> dict:
    """Pause before search so the user owns the research plan."""
    proposed = list(state.get("sub_queries", []))
    if state.get("execution_mode", "review") == "autonomous":
        if any(not _has_valid_sub_query_length(query) for query in proposed):
            raise ValueError("Mỗi sub-query phải có từ 8 đến 14 từ.")
        return {
            "sub_queries": proposed,
            "search_query": proposed[0] if proposed else state.get("original_topic", ""),
            "query_history": proposed,
            "hitl_stage": None,
            "current_node": "search_academic_sources",
        }
    resume_payload = interrupt(
        {
            "stage": "subqueries",
            "sub_queries": proposed,
            "instruction": "Review, add, edit, or remove search queries before research starts.",
        }
    )
    resumed_autonomous = isinstance(resume_payload, dict) and resume_payload.get("execution_mode") == "autonomous"
    queries = resume_payload.get("sub_queries", proposed) if isinstance(resume_payload, dict) else proposed
    clean = list(dict.fromkeys(" ".join(str(query).split()) for query in queries if str(query).strip()))
    if not clean:
        raise ValueError("Cần ít nhất một sub-query để bắt đầu tìm kiếm.")
    if any(not _has_valid_sub_query_length(query) for query in clean):
        raise ValueError("Mỗi sub-query phải có từ 8 đến 14 từ.")
    return {
        "sub_queries": clean,
        "search_query": clean[0],
        "query_history": clean,
        "execution_mode": "autonomous" if resumed_autonomous else state.get("execution_mode", "review"),
        "hitl_stage": None,
        "current_node": "search_academic_sources",
    }


async def review_papers_node(state: AgentState) -> dict:
    """Pause after ranking; the user can select manually or accept ranking."""

    async def index_selected(papers_to_index: list[Paper], job_id: str) -> tuple[list[Paper], list[str]]:
        """Ingest selected papers and persist their content availability."""
        if not papers_to_index or not get_settings().qdrant_enabled:
            return papers_to_index, []
        indexed_papers = papers_to_index
        try:
            documents, ingestion_warnings = await ingest_papers(
                papers_to_index, job_id, root=get_settings().paper_storage_dir
            )
            ingestion_by_paper_id = {document["paper"]["paper_id"]: document["ingestion"] for document in documents}
            indexed_papers = [
                {**paper, "ingestion": ingestion_by_paper_id[paper["paper_id"]]} for paper in papers_to_index
            ]
            indexed_papers_by_id = {paper["paper_id"]: paper for paper in indexed_papers}
            indexed_documents = [
                {**document, "paper": indexed_papers_by_id[document["paper"]["paper_id"]]} for document in documents
            ]
            indexed = await QdrantVectorStore(backend=state.get("embedding_backend", "primary")).index_selected_papers(
                indexed_papers, job_id, replace_existing=True, documents=indexed_documents
            )
            logger.info("node=review_papers job=%s indexed_selected_papers=%s", job_id, indexed)
            fulltext_count = sum(bool(document.get("downloaded")) for document in documents)
            return indexed_papers, [*ingestion_warnings, f"FULLTEXT_COVERAGE:{fulltext_count}/{len(documents)}"]
        except VectorStoreError as exc:
            # Qdrant is a derived index; keep the research run usable if it is
            # temporarily unavailable because extraction still has abstracts.
            logger.warning("Selected-paper embedding failed for job=%s: %s", job_id, exc)
            return indexed_papers, [f"QDRANT_SELECTED_INDEX_FALLBACK: {exc}"]

    papers = list(state.get("papers", []))
    job_id = state.get("job_id") or state.get("thread_id") or "adhoc"
    if state.get("execution_mode", "review") == "autonomous":
        papers, warnings = await index_selected(papers, job_id)
        return {
            "papers": papers,
            "selected_paper_ids": [paper["paper_id"] for paper in papers],
            "source_warnings": [*state.get("source_warnings", []), *warnings],
            "hitl_stage": None,
            "current_node": "extract_evidence",
        }
    resume_payload = interrupt(
        {
            "stage": "papers",
            "papers": papers,
            "instruction": "Choose papers manually or accept the agent ranking before synthesis.",
        }
    )
    resumed_autonomous = isinstance(resume_payload, dict) and resume_payload.get("execution_mode") == "autonomous"
    if resumed_autonomous:
        papers, warnings = await index_selected(papers, job_id)
        return {
            "papers": papers,
            "selected_paper_ids": [paper["paper_id"] for paper in papers],
            "source_warnings": [*state.get("source_warnings", []), *warnings],
            "hitl_stage": None,
            "execution_mode": "autonomous",
            "current_node": "extract_evidence",
        }
    mode = resume_payload.get("mode", "ranked") if isinstance(resume_payload, dict) else "ranked"
    selected_ids = resume_payload.get("selected_paper_ids", []) if isinstance(resume_payload, dict) else []
    if mode == "manual":
        selected = set(str(paper_id) for paper_id in selected_ids)
        papers = [paper for paper in papers if paper.get("paper_id") in selected]
    if not papers:
        raise ValueError("Bạn cần chọn ít nhất một bài báo để tổng hợp.")
    papers, warnings = await index_selected(papers, job_id)
    return {
        "papers": papers,
        "selected_paper_ids": [paper["paper_id"] for paper in papers],
        "source_warnings": [*state.get("source_warnings", []), *warnings],
        "hitl_stage": None,
        "current_node": "extract_evidence",
    }


# ─── Node 3: assess_sources_node ──────────────────────────────────────────────


async def assess_sources_node(state: AgentState) -> dict:
    papers = state.get("papers", [])
    attempt = state.get("search_attempt", 1)
    decisions = list(state.get("decisions", []))
    logger.info(
        "node=assess_sources job=%s papers=%s attempt=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(papers),
        attempt,
    )

    if state.get("error"):
        action = "fail"
        reason = "OpenAlex search failed."
        error = state.get("error")
    elif len(papers) == 0 and attempt >= 2:
        action = "fail"
        reason = "Zero valid papers found from OpenAlex after 2 search attempts."
        error = "Không tìm thấy bài báo nào từ OpenAlex. Hệ thống dừng để tránh bịa nguồn."
    elif len(papers) < 10 and attempt < 2:
        action = "refine_query"
        reason = f"Only {len(papers)} papers found (target >= 10). Refining search query."
        error = None
    else:
        action = "continue"
        reason = f"Source assessment passed with {len(papers)} papers."
        error = None

    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="assess_sources",
            action=action,
            reason=reason,
            created_at=_now_iso(),
        )
    )

    result = {
        "decisions": decisions,
        "current_node": "assess_sources",
    }
    if error:
        result["error"] = error
    logger.info(
        "node=assess_sources job=%s action=%s error=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        action,
        bool(error),
    )
    return result


# ─── Node 4: refine_query_node ─────────────────────────────────────────────────


async def refine_query_node(state: AgentState) -> dict:
    current_query = state.get("search_query", "")
    history = list(state.get("query_history", []))
    logger.info(
        "node=refine_query job=%s query=%r",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        current_query,
    )

    # Refine query by appending survey / review keyword
    refined_query = f"{current_query} survey review overview"
    history.append(refined_query)

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="refine_query",
            action="refine_query",
            reason=f"Refined search query from '{current_query}' to '{refined_query}'",
            created_at=_now_iso(),
        )
    )

    return {
        "search_query": refined_query,
        "query_history": history,
        "decisions": decisions,
        "current_node": "refine_query",
    }


# ─── Node 5: screen_papers_node ────────────────────────────────────────────────


async def screen_papers_node(state: AgentState) -> dict:
    # Claims must be traceable to an abstract. Excluding unusable records here
    # prevents downstream extraction from manufacturing unsupported evidence.
    papers = [paper for paper in state.get("papers", []) if str(paper.get("abstract") or "").strip()]
    topic = state.get("original_topic") or ""
    normalized_question = (state.get("normalized_question") or state.get("search_query") or topic).strip()
    limit = state.get("max_results") or 20
    source_warnings = list(state.get("source_warnings", []))
    embedding_backend = state.get("embedding_backend", "primary")
    store: QdrantVectorStore | None = None
    event(
        logger,
        "screen.started",
        state=state,
        input_count=len(papers),
        input_paper_ids=id_summary([paper.get("paper_id") for paper in papers]),
        topic=topic,
        normalized_question=normalized_question,
        ranking_queries=state.get("sub_queries", []) or state.get("query_history", []),
        requested_limit=limit,
        technical_candidate_limit=get_settings().qdrant_embedding_candidate_limit,
        embedding_threshold=_MIN_EMBEDDING_RELEVANCE_SCORE,
        embedding_backend=embedding_backend,
    )

    if papers and topic:
        # Score each approved sub-query independently. A relevant paper can
        # satisfy one branch of a research plan without needing to contain all
        # terms from every other branch. Qdrant remains in use later for RAG
        # over papers that pass this lexical relevance gate.
        ranking_queries = [str(query).strip() for query in state.get("sub_queries", []) if str(query).strip()]
        ranking_queries = ranking_queries or [
            str(query).strip() for query in state.get("query_history", []) if str(query).strip()
        ]
        lexical_candidates = rank_papers(
            papers,
            ranking_queries or [topic],
            min(len(papers), get_settings().qdrant_embedding_candidate_limit),
            required_terms=[str(term).strip() for term in state.get("required_terms", []) if str(term).strip()],
            excluded_terms=[str(term).strip() for term in state.get("excluded_terms", []) if str(term).strip()],
        )
        event(
            logger,
            "screen.lexical_ranked",
            state=state,
            lexical_count=len(lexical_candidates),
            lexical_papers=[paper_summary(paper) for paper in lexical_candidates],
        )
        if not lexical_candidates:
            ranked = []
        elif not get_settings().qdrant_enabled:
            event(
                logger,
                "screen.embedding_failed",
                state=state,
                level=logging.ERROR,
                failure_code="EMBEDDING_NOT_CONFIGURED",
                failed_stage="screen.embedding_rank",
                embedding_backend=embedding_backend,
            )
            return {
                "papers": [],
                "source_warnings": [
                    *source_warnings,
                    "EMBEDDING_SCREENING_UNAVAILABLE: Qdrant embedding screening is required.",
                ],
                "error": "Không thể chấm điểm tương đồng ngữ nghĩa vì embedding screening chưa được cấu hình.",
                "current_node": "screen_papers",
            }
        else:
            try:
                store = QdrantVectorStore(backend=embedding_backend)
                embedding_started = perf_counter()
                ranked = await store.index_and_rank(
                    lexical_candidates,
                    normalized_question,
                    state.get("job_id") or state.get("thread_id") or "adhoc",
                    limit,
                )
                event(
                    logger,
                    "screen.embedding_ranked",
                    state=state,
                    embedding_backend=embedding_backend,
                    embedding_collection=getattr(store, "collection", None),
                    ranked_papers=[paper_summary(paper) for paper in ranked],
                    duration_ms=round((perf_counter() - embedding_started) * 1000),
                )
            except VectorStoreError as exc:
                if embedding_backend == "fallback" or not get_settings().qdrant_fallback_enabled:
                    event(
                        logger,
                        "screen.embedding_failed",
                        state=state,
                        level=logging.ERROR,
                        failure_code="EMBEDDING_RANK_FAILED",
                        failed_stage="screen.embedding_rank",
                        embedding_backend=embedding_backend,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    return {
                        "papers": [],
                        "source_warnings": [*source_warnings, f"EMBEDDING_SCREENING_UNAVAILABLE: {exc}"],
                        "error": "Không thể chấm điểm tương đồng ngữ nghĩa. Hệ thống dừng để không dùng bài báo chưa qua ngưỡng embedding.",
                        "current_node": "screen_papers",
                    }
                try:
                    store = QdrantVectorStore(backend="fallback")
                    ranked = await store.index_and_rank(
                        lexical_candidates,
                        normalized_question,
                        state.get("job_id") or state.get("thread_id") or "adhoc",
                        limit,
                    )
                    embedding_backend = "fallback"
                    event(
                        logger,
                        "screen.embedding_fallback",
                        state=state,
                        level=logging.WARNING,
                        embedding_backend=embedding_backend,
                        embedding_collection=getattr(store, "collection", None),
                        error=str(exc),
                        fallback_reason="primary embedding rank failed",
                        duration_ms=round((perf_counter() - embedding_started) * 1000),
                    )
                    source_warnings.append(
                        f"EMBEDDING_FALLBACK_USED: primary backend failed ({exc}); using local FastEmbed."
                    )
                    logger.warning(
                        "node=screen_papers job=%s switched from primary embedding to local FastEmbed: %s",
                        state.get("job_id") or state.get("thread_id") or "adhoc",
                        exc,
                    )
                except VectorStoreError as fallback_exc:
                    event(
                        logger,
                        "screen.embedding_failed",
                        state=state,
                        level=logging.ERROR,
                        failure_code="EMBEDDING_PRIMARY_AND_FALLBACK_FAILED",
                        failed_stage="screen.embedding_rank",
                        embedding_backend="fallback",
                        error_type=type(fallback_exc).__name__,
                        error=str(fallback_exc),
                        fallback_reason=f"primary failed: {type(exc).__name__}",
                    )
                    return {
                        "papers": [],
                        "source_warnings": [
                            *source_warnings,
                            f"EMBEDDING_SCREENING_UNAVAILABLE: primary={exc}; fallback={fallback_exc}",
                        ],
                        "error": "Không thể chấm điểm tương đồng ngữ nghĩa bằng cả Gemini lẫn local embedding.",
                        "current_node": "screen_papers",
                    }
        embedding_passed: list[Paper] = [
            {
                "paper_id": p["paper_id"],
                "title": p["title"],
                "authors": p["authors"],
                "year": p["year"],
                "doi": p["doi"],
                "url": p["url"],
                "abstract": p["abstract"],
                "cited_by_count": p.get("cited_by_count", 0),
                "is_open_access": p.get("is_open_access", True),
                "pdf_url": p.get("pdf_url"),
                "source": p.get("source") or "openalex",
                "relevance_score": p["relevance_score"],
                "rank": p["rank"],
            }
            for p in ranked
            if p["relevance_score"] >= _MIN_EMBEDDING_RELEVANCE_SCORE
        ]
        event(
            logger,
            "screen.embedding_gate",
            state=state,
            embedding_threshold=_MIN_EMBEDDING_RELEVANCE_SCORE,
            embedding_backend=embedding_backend,
            passed_count=len(embedding_passed),
            rejected_count=max(0, len(ranked) - len(embedding_passed)),
            passed_papers=[paper_summary(paper) for paper in embedding_passed],
            rejected_papers=[
                paper_summary(paper)
                for paper in ranked
                if paper.get("relevance_score", 0) < _MIN_EMBEDDING_RELEVANCE_SCORE
            ],
        )
        if embedding_passed:
            papers_text = "\n\n".join(
                f"ID: {paper['paper_id']}\nTitle: {paper['title']}\n"
                f"Embedding score: {paper['relevance_score']:.4f}\n"
                f"Abstract: {paper['abstract']}"
                for paper in embedding_passed
            )
            try:
                relevance_judge = _StructuredLLMInvoker(
                    get_paper_relevance_prompt(),
                    PaperRelevanceBatch,
                    "paper relevance judging",
                    job_id=state.get("job_id") or state.get("thread_id"),
                    run_id=state.get("run_id"),
                    node_name="screen_papers",
                    execution_mode=state.get("execution_mode", "review"),
                )
                relevance_result = await relevance_judge.ainvoke(
                    {
                        "topic": topic,
                        "normalized_question": normalized_question,
                        "required_terms": ", ".join(state.get("required_terms", [])) or "(none)",
                        "excluded_terms": ", ".join(state.get("excluded_terms", [])) or "(none)",
                        "papers_text": papers_text,
                    },
                    trace_context={
                        "batch_id": "relevance_screen",
                        "paper_ids": id_summary([paper["paper_id"] for paper in embedding_passed]),
                    },
                )
            except Exception as exc:
                logger.warning("LLM paper relevance judge failed closed: %s", exc)
                event(
                    logger,
                    "screen.relevance_failed",
                    state=state,
                    level=logging.ERROR,
                    failure_code="RELEVANCE_JUDGE_UNAVAILABLE",
                    failed_stage="screen.relevance_judge",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return {
                    "papers": [],
                    "source_warnings": [*source_warnings, f"RELEVANCE_JUDGE_UNAVAILABLE: {exc}"],
                    "error": "Không thể xác minh mức độ liên quan của các bài báo. Hệ thống dừng để tránh tổng hợp tài liệu lạc đề.",
                    "current_node": "screen_papers",
                }

            allowed_ids = {paper["paper_id"] for paper in embedding_passed}
            decisions = {}
            duplicate_ids: set[str] = set()
            for decision in relevance_result.decisions:
                if decision.paper_id not in allowed_ids:
                    continue
                if decision.paper_id in decisions:
                    duplicate_ids.add(decision.paper_id)
                    continue
                decisions[decision.paper_id] = decision
            judged_papers: list[Paper] = []
            for paper in embedding_passed:
                decision = decisions.get(paper["paper_id"])
                # Missing decisions fail closed: an unchecked paper must never
                # enter extraction or either execution mode.
                if (
                    decision is None
                    or paper["paper_id"] in duplicate_ids
                    or decision.label not in {"direct", "supporting"}
                ):
                    continue
                judged_papers.append(
                    {
                        **paper,
                        "relevance_label": decision.label,
                        "relevance_reason": decision.reason.strip(),
                    }
                )

            direct_count = sum(p.get("relevance_label") == "direct" for p in judged_papers)
            supporting_count = sum(p.get("relevance_label") == "supporting" for p in judged_papers)
            event(
                logger,
                "screen.relevance_judged",
                state=state,
                decision_count=len(relevance_result.decisions),
                decisions=[
                    {
                        "paper_id": decision.paper_id,
                        "label": decision.label,
                        "reason": decision.reason,
                        "accepted": decision.paper_id in {paper["paper_id"] for paper in judged_papers},
                    }
                    for decision in relevance_result.decisions
                ],
                accepted_papers=[paper_summary(paper) for paper in judged_papers],
            )
            coverage_ok = direct_count >= 2 or (direct_count >= 1 and supporting_count >= 2)
            event(
                logger,
                "screen.coverage_decision",
                state=state,
                direct_count=direct_count,
                supporting_count=supporting_count,
                coverage_ok=coverage_ok,
                accepted_count=len(judged_papers),
                required_coverage="2 direct OR 1 direct + 2 supporting",
                failure_code=None if coverage_ok else "INSUFFICIENT_DIRECT_COVERAGE",
            )
            if not coverage_ok:
                source_warnings.append(
                    "INSUFFICIENT_DIRECT_COVERAGE: Corpus needs at least 2 direct papers, "
                    "or 1 direct and 2 supporting papers."
                )
                return {
                    "papers": [],
                    "source_warnings": source_warnings,
                    "error": (
                        "Không có bài báo nào phù hợp để tổng hợp cho truy vấn này. "
                        "Hệ thống sẽ không bịa thêm nguồn hoặc cố suy diễn từ tài liệu lạc đề."
                    ),
                    "current_node": "screen_papers",
                }
            screened_papers = judged_papers[:limit]
        else:
            screened_papers = []
    else:
        screened_papers = papers[:limit]

    if papers and topic and not screened_papers:
        source_warnings.extend(
            [
                "NO_RELEVANT_PAPERS",
                "Retrieved records did not meet the relevance threshold for this topic.",
            ]
        )
        return {
            "papers": [],
            "source_warnings": source_warnings,
            "error": (
                "Không có bài báo nào phù hợp để tổng hợp cho truy vấn này. "
                "Hệ thống đã dừng thay vì dùng tài liệu không đủ liên quan."
            ),
            "current_node": "screen_papers",
        }

    event(
        logger,
        "screen.completed",
        state=state,
        screened_count=len(screened_papers),
        screened_ids=id_summary([paper.get("paper_id") for paper in screened_papers]),
        warning_count=len(source_warnings),
        embedding_backend=embedding_backend,
    )
    return {
        "papers": screened_papers,
        "source_warnings": source_warnings,
        "embedding_backend": embedding_backend,
        "embedding_collection": store.collection if store is not None else state.get("embedding_collection"),
        "hitl_stage": None if state.get("execution_mode", "review") == "autonomous" else "papers",
        "current_node": "screen_papers",
    }


# ─── Node 6: extract_evidence_node ─────────────────────────────────────────────


async def extract_evidence_node(state: AgentState) -> dict:
    papers = state.get("papers", [])
    topic = (state.get("original_topic") or "").strip()
    if not topic:
        raise ValueError("Missing original_topic before evidence extraction")
    candidates: list[ClaimCandidate] = []
    paper_relevance = {paper["paper_id"]: paper.get("relevance_label") for paper in papers}
    logger.info(
        "node=extract_evidence job=%s papers=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(papers),
    )

    if not papers:
        return {"claim_candidates": candidates, "current_node": "extract_evidence"}

    source_contexts = await _fulltext_first_contexts(papers, topic, state)

    prompt = get_extraction_prompt()
    llm_invoker = _StructuredLLMInvoker(
        prompt,
        BatchExtractionResult,
        "evidence extraction",
        job_id=state.get("job_id") or state.get("thread_id"),
        run_id=state.get("run_id"),
        node_name="extract_evidence",
        execution_mode=state.get("execution_mode", "review"),
    )

    batch_size = 5
    batches = [papers[i : i + batch_size] for i in range(0, len(papers), batch_size)]
    logger.info(
        "node=extract_evidence job=%s batches=%s batch_size=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(batches),
        batch_size,
    )

    async def process_batch(batch_index, batch):
        papers_text = "\n\n".join(
            [
                f"ID: {p['paper_id']}\nTitle: {p['title']}\n"
                f"Source level: {source_contexts[p['paper_id']]['source_level']}\n"
                f"Source passages:\n{source_contexts[p['paper_id']]['text']}"
                for p in batch
            ]
        )
        try:
            result = await llm_invoker.ainvoke(
                {
                    "topic": topic,
                    "response_language": state.get("response_language") or response_language(topic),
                    "papers_text": papers_text,
                },
                trace_context={
                    "batch_id": f"evidence_extraction_{batch_index + 1}",
                    "paper_ids": id_summary([paper["paper_id"] for paper in batch]),
                },
            )
            logger.info(
                "node=extract_evidence job=%s batch_papers=%s extracted=%s",
                state.get("job_id") or state.get("thread_id") or "adhoc",
                len(batch),
                len(getattr(result, "extracted_papers", [])),
            )
            return result
        except Exception as e:
            logging.error(f"Error extracting batch: {e}")
            return None

    results = await asyncio.gather(*[process_batch(index, batch) for index, batch in enumerate(batches)])

    for res in results:
        if not res:
            logger.error(
                "node=extract_evidence job=%s invalid LLM output",
                state.get("job_id") or state.get("thread_id") or "adhoc",
            )
            state["error"] = "INVALID_LLM_OUTPUT"
            return state
        for paper_extract in res.extracted_papers:
            paper_id = paper_extract.paper_id
            source_label = paper_relevance.get(paper_id)
            for c in paper_extract.claims:
                # A supported fact can still be unrelated to the user's actual
                # question. Only direct and necessary supporting claims pass.
                if (
                    not c.text.strip()
                    or c.relevance not in {"direct", "supporting"}
                    or source_label not in {None, "direct", "supporting"}
                    # A paper screened as supporting context cannot generate a
                    # purported direct answer later in the pipeline.
                    or (source_label == "supporting" and c.relevance == "direct")
                ):
                    continue
                quotes = [
                    _attach_evidence_context(
                        EvidenceQuote(
                            paper_id=paper_id,
                            quote=q.quote.strip(),
                            section=source_contexts.get(paper_id, {}).get("source_level", "abstract"),
                            source_level=source_contexts.get(paper_id, {}).get("source_level", "abstract"),
                        ),
                        source_contexts.get(paper_id, {}).get("text", ""),
                    )
                    for q in c.evidence_quotes
                    if q.quote.strip()
                ]
                candidates.append(
                    ClaimCandidate(
                        claim_type=c.claim_type,
                        text=c.text.strip(),
                        supporting_paper_ids=[paper_id],
                        evidence=quotes,
                    )
                )

    logger.info(
        "node=extract_evidence job=%s candidates=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(candidates),
    )
    return {
        "claim_candidates": candidates,
        "current_node": "extract_evidence",
    }


# ─── Node 7: synthesize_claims_node ───────────────────────────────────────────


async def synthesize_claims_node(state: AgentState) -> dict:
    papers = state.get("papers", [])
    topic = (state.get("original_topic") or "").strip()
    if not topic:
        raise ValueError("Missing original_topic before claim synthesis")
    logger.info(
        "node=synthesize_claims job=%s papers=%s claims=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(papers),
        len(state.get("claims", [])),
    )

    # Only synthesize valid claims
    all_claims = state.get("claims", [])
    valid_claims = [c for c in all_claims if c.get("validation_status") == "valid"]

    evidence_rows: list[EvidenceRow] = []
    references: list[Reference] = []

    # Map paper_id -> claim_type -> claim_id while retaining every selected
    # record in References for transparent corpus and gap coverage.
    paper_claim_map = {p["paper_id"]: {} for p in papers}
    for c in valid_claims:
        for p_id in c["supporting_paper_ids"]:
            if p_id in paper_claim_map:
                paper_claim_map[p_id][c["claim_type"]] = c["claim_id"]

    for p in papers:
        first_author = p["authors"][0] if p.get("authors") else "Unknown"
        year_str = f" ({p['year']})" if p.get("year") else ""
        label = f"{first_author}{year_str}"

        c_map = paper_claim_map[p["paper_id"]]
        evidence_rows.append(
            EvidenceRow(
                paper_id=p["paper_id"],
                citation_label=label,
                title=p["title"],
                year=p["year"],
                url=p["url"],
                method_claim_id=c_map.get("method"),
                dataset_claim_id=c_map.get("dataset"),
                contribution_claim_id=c_map.get("contribution"),
                limitation_claim_id=c_map.get("limitation"),
            )
        )

        references.append(
            Reference(
                paper_id=p["paper_id"],
                title=p["title"],
                authors=p.get("authors", []),
                year=p.get("year"),
                doi=p.get("doi"),
                url=p["url"],
                source=p.get("source", "openalex"),
                metadata_valid=True,
            )
        )

    # LLM Synthesis for Themes and Gaps
    themes = []
    potential_gaps = []
    claim_candidates = []
    if valid_claims and papers:
        source_contexts = await _fulltext_first_contexts(papers, topic, state)
        prompt = get_synthesis_prompt()
        llm_invoker = _StructuredLLMInvoker(
            prompt,
            SynthesisResult,
            "claim synthesis",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="synthesize_claims",
            execution_mode=state.get("execution_mode", "review"),
        )

        claims_text_lines = []
        for c in valid_claims:
            ev_text = "; ".join([f"[{e['paper_id']}] {e['quote']}" for e in c.get("evidence", [])])
            claims_text_lines.append(
                f"ID: {c['claim_id']} | Type: {c['claim_type']} | Text: {c['text']} | Evidence: {ev_text}"
            )
        claims_text = "\n".join(claims_text_lines)

        papers_text = "\n\n".join(
            [
                f"ID: {p['paper_id']} | Title: {p['title']}\n"
                f"Source level: {source_contexts[p['paper_id']]['source_level']}\n"
                f"Source passages:\n{source_contexts[p['paper_id']]['text']}"
                for p in papers
            ]
        )

        try:
            result = await llm_invoker.ainvoke(
                {
                    "topic": topic,
                    "response_language": state.get("response_language") or response_language(topic),
                    "claims_text": claims_text,
                    "papers_text": papers_text,
                },
                trace_context={
                    "batch_id": "claim_synthesis",
                    "paper_ids": id_summary([paper["paper_id"] for paper in papers]),
                },
            )

            paper_id_set = {p["paper_id"] for p in papers}

            # Map back to TypedDict formats, enforce max 5 themes
            for t in result.themes[:5]:
                valid_supporting_ids = [pid for pid in t.supporting_paper_ids if pid in paper_id_set]
                if len(valid_supporting_ids) < 2:
                    continue  # A theme must be supported by at least two sources.

                theme_id = f"theme_{uuid4().hex[:8]}"
                summary_claim_id = f"claim_{uuid4().hex[:8]}"
                claim_candidates.append(
                    {
                        "claim_id": summary_claim_id,
                        "claim_type": "theme",
                        "text": t.summary,
                        "supporting_paper_ids": valid_supporting_ids,
                        "evidence": [
                            _attach_evidence_context(
                                {
                                    "paper_id": ev.paper_id,
                                    "quote": ev.quote,
                                    "section": source_contexts.get(ev.paper_id, {}).get("source_level", "abstract"),
                                    "source_level": source_contexts.get(ev.paper_id, {}).get(
                                        "source_level", "abstract"
                                    ),
                                },
                                source_contexts.get(ev.paper_id, {}).get("text", ""),
                            )
                            for ev in getattr(t, "evidence", [])
                        ],
                    }
                )

                themes.append(
                    Theme(
                        theme_id=theme_id,
                        title=t.title,
                        summary_claim_id=summary_claim_id,
                        supporting_paper_ids=valid_supporting_ids,
                    )
                )

            candidate_gaps = list(result.potential_gaps)
            if len(papers) >= _MIN_GAP_CORPUS_SIZE and not candidate_gaps:
                try:
                    recovery = await _StructuredLLMInvoker(
                        get_gap_recovery_prompt(),
                        SynthesisResult,
                        "research gap recovery",
                        job_id=state.get("job_id") or state.get("thread_id"),
                        run_id=state.get("run_id"),
                        node_name="synthesize_claims",
                        execution_mode=state.get("execution_mode", "review"),
                    ).ainvoke(
                        {
                            "topic": topic,
                            "response_language": state.get("response_language") or response_language(topic),
                            "claims_text": claims_text,
                            "papers_text": papers_text,
                        },
                        trace_context={
                            "batch_id": "research_gap_recovery",
                            "paper_ids": id_summary([paper["paper_id"] for paper in papers]),
                        },
                    )
                    candidate_gaps = list(recovery.potential_gaps)
                except Exception as exc:
                    logger.warning(
                        "node=synthesize_claims gap recovery failed job=%s error=%s",
                        state.get("job_id") or "adhoc",
                        exc,
                    )
            if len(papers) >= _MIN_GAP_CORPUS_SIZE and not candidate_gaps:
                limitation_ids = {
                    paper_id
                    for claim in valid_claims
                    if claim.get("claim_type") == "limitation"
                    for paper_id in claim.get("supporting_paper_ids", [])
                    if paper_id in paper_id_set
                }
                if len(limitation_ids) <= max(1, len(papers) // 3):
                    candidate_gaps = [
                        SynthesizedGap(
                            aspect="explicit evaluation limitations and external validation",
                            scope_statement="Limited coverage in the reviewed corpus.",
                            coverage=[
                                GapCoverage(paper_id=paper["paper_id"], mentioned=False, evidence_quote="")
                                for paper in papers
                            ],
                        )
                    ]
                    logger.info(
                        "node=synthesize_claims heuristic gap detector used job=%s",
                        state.get("job_id") or "adhoc",
                    )

            for g in candidate_gaps:
                gap_id = f"gap_{uuid4().hex[:8]}"

                # ── Contract §4.8 validation ──
                # 1. Minimum corpus size for a scoped candidate gap.
                if len(papers) < _MIN_GAP_CORPUS_SIZE:
                    continue

                # 2. Coverage must contain every paper (no missing, no duplicates)
                coverage_paper_ids = [cov.paper_id for cov in g.coverage]
                if set(coverage_paper_ids) != paper_id_set:
                    continue  # Missing or extra paper IDs
                if len(coverage_paper_ids) != len(set(coverage_paper_ids)):
                    continue  # Duplicate coverage rows

                # 3. mentioned=true entries must have a non-empty evidence_quote
                quote_invalid = False
                for cov in g.coverage:
                    if cov.mentioned and not (cov.evidence_quote and cov.evidence_quote.strip()):
                        quote_invalid = True
                        break
                if quote_invalid:
                    continue

                # 4. Not too many papers mention it (scales with corpus size)
                mentioned_count = sum(1 for cov in g.coverage if cov.mentioned)
                if mentioned_count > max(2, len(papers) // 3):
                    continue

                # 5. Reject absolute wording in scope_statement
                if check_absolute_wording(g.scope_statement):
                    continue

                # 6. Enforce scoped wording template
                if mentioned_count > 0:
                    scope_statement = (
                        f"Trong {len(papers)} bài thu thập từ các nguồn học thuật "
                        f'cho truy vấn "{topic}", chỉ có {mentioned_count} bài đề cập đến {g.aspect}.'
                    )
                else:
                    scope_statement = (
                        f"Trong {len(papers)} bài thu thập từ các nguồn học thuật "
                        f'cho truy vấn "{topic}", chưa thấy {g.aspect} được đề cập.'
                    )

                gap_claim_id = f"claim_{uuid4().hex[:8]}"

                # Gather evidence from the gap coverage where mentioned is True
                gap_evidence = [
                    _attach_evidence_context(
                        {
                            "paper_id": cov.paper_id,
                            "quote": cov.evidence_quote,
                            "section": source_contexts.get(cov.paper_id, {}).get("source_level", "abstract"),
                            "source_level": source_contexts.get(cov.paper_id, {}).get("source_level", "abstract"),
                        },
                        source_contexts.get(cov.paper_id, {}).get("text", ""),
                    )
                    for cov in g.coverage
                    if cov.mentioned and cov.evidence_quote
                ]

                claim_candidates.append(
                    {
                        "claim_id": gap_claim_id,
                        "claim_type": "potential_gap",
                        "text": scope_statement,
                        "supporting_paper_ids": [cov.paper_id for cov in g.coverage if cov.mentioned],
                        "evidence": gap_evidence,
                    }
                )

                coverage = []
                for cov in g.coverage:
                    coverage.append(
                        {
                            "paper_id": cov.paper_id,
                            "mentioned": cov.mentioned,
                            "evidence_quote": cov.evidence_quote if cov.evidence_quote else None,
                        }
                    )

                potential_gaps.append(
                    PotentialGap(
                        gap_id=gap_id,
                        claim_id=gap_claim_id,
                        aspect=g.aspect,
                        papers_checked=len(papers),
                        coverage=coverage,
                        scope_statement=scope_statement,
                    )
                )
        except Exception as e:
            logging.error(f"Error in LLM synthesis: {e}")
            state["error"] = "INVALID_LLM_OUTPUT"
            return state

    # Keep the report useful when the model returns themes whose source IDs do
    # not survive validation. The validated claims are still evidence-backed,
    # so group them into transparent fallback themes instead of rendering an
    # empty synthesis section.
    if valid_claims and papers and not themes:
        fallback_labels = {
            "method": "Phương pháp và cách tiếp cận",
            "dataset": "Dữ liệu và benchmark",
            "contribution": "Đóng góp chính",
            "limitation": "Hạn chế và thách thức",
            "potential_gap": "Khoảng trống nghiên cứu",
        }
        for claim_type, grouped in itertools.groupby(
            sorted(valid_claims, key=lambda claim: claim.get("claim_type", "finding")),
            key=lambda claim: claim.get("claim_type", "finding"),
        ):
            grouped_claims = list(grouped)
            supporting_ids = list(
                dict.fromkeys(
                    paper_id
                    for claim in grouped_claims
                    for paper_id in claim.get("supporting_paper_ids", [])
                    if paper_id in {paper["paper_id"] for paper in papers}
                )
            )
            if len(supporting_ids) < 2:
                continue
            summary_claim_id = f"claim_{uuid4().hex[:8]}"
            claim_candidates.append(
                {
                    "claim_id": summary_claim_id,
                    "claim_type": "theme",
                    "text": " ".join(claim["text"] for claim in grouped_claims[:4]),
                    "supporting_paper_ids": supporting_ids,
                    "evidence": [
                        evidence for claim in grouped_claims[:4] for evidence in claim.get("evidence", [])[:1]
                    ],
                }
            )
            themes.append(
                Theme(
                    theme_id=f"theme_{uuid4().hex[:8]}",
                    title=fallback_labels.get(claim_type, "Các phát hiện liên quan"),
                    summary_claim_id=summary_claim_id,
                    supporting_paper_ids=supporting_ids,
                )
            )

    if state.get("execution_mode", "review") == "autonomous":
        review_status = (
            "Agent đã hoàn tất luồng tự động; các bài báo và khẳng định đã đi qua cùng "
            "các cổng relevance, coverage và grounding của chế độ người dùng duyệt."
        )
    else:
        review_status = "Các khẳng định đang chờ Reviewer xác nhận ở bước duyệt cuối."
    scope_disclaimer = (
        f"Báo cáo này được tự động tổng hợp từ {len(papers)} bài báo thu thập từ OpenAlex cho chủ đề '{topic}'. "
        f"{review_status}"
    )

    logger.info(
        "node=synthesize_claims job=%s themes=%s gaps=%s evidence_rows=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(themes),
        len(potential_gaps),
        len(evidence_rows),
    )
    return {
        "claim_candidates": claim_candidates,
        "evidence_rows": evidence_rows,
        "themes": themes,
        "potential_gaps": potential_gaps,
        "references": references,
        "scope_disclaimer": scope_disclaimer,
        "current_node": "synthesize_claims",
        "synthesis_completed": True,
    }


async def analyze_research_gaps_node(state: AgentState) -> dict:
    """Enrich grounded gap hypotheses before the literature review is composed."""
    raw_gaps = list(state.get("potential_gaps", []))
    gaps: list[PotentialGap] = []
    seen_aspects: set[str] = set()
    for gap in raw_gaps:
        key = re.sub(r"\W+", " ", gap.get("aspect", "").lower()).strip()
        if key and key not in seen_aspects:
            seen_aspects.add(key)
            gaps.append(gap)
    topic = (state.get("original_topic") or "").strip()
    if not gaps or not topic:
        return {
            "potential_gaps": gaps,
            "gap_analysis_completed": True,
            "current_node": "analyze_research_gaps",
        }

    gaps_text = "\n\n".join(
        "\n".join(
            [
                f"gap_id: {gap['gap_id']}",
                f"aspect: {gap['aspect']}",
                f"scope_statement: {gap['scope_statement']}",
                "coverage: "
                + "; ".join(
                    f"{coverage['paper_id']}|mentioned={coverage['mentioned']}|quote={coverage.get('evidence_quote') or ''}"
                    for coverage in gap["coverage"]
                ),
            ]
        )
        for gap in gaps
    )

    try:
        result = await _StructuredLLMInvoker(
            get_research_gap_prompt(),
            ResearchGapAssessmentResult,
            "research gap assessment",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="analyze_research_gaps",
            execution_mode=state.get("execution_mode", "review"),
        ).ainvoke(
            {
                "topic": topic,
                "response_language": state.get("response_language") or response_language(topic),
                "gaps_text": gaps_text,
            },
            trace_context={"batch_id": "research_gap_assessment", "gap_count": len(gaps)},
        )
        assessments = {assessment.gap_id: assessment for assessment in result.assessments}
        if set(assessments) != {gap["gap_id"] for gap in gaps}:
            raise ValueError("Research-gap assessment did not return every grounded gap exactly once")

        enriched_gaps: list[PotentialGap] = []
        for gap in gaps:
            assessment = assessments[gap["gap_id"]]
            enriched_gaps.append(
                PotentialGap(
                    **gap,
                    gap_type=assessment.gap_type,
                    confidence=assessment.confidence,
                    counter_search_query=assessment.counter_search_query.strip(),
                    reviewer_rationale=assessment.reviewer_rationale.strip(),
                    verification_status="needs_counter_search",
                    evidence_score=max(0, min(100, assessment.evidence_score)),
                    novelty_score=max(0, min(100, assessment.novelty_score)),
                    feasibility_score=max(0, min(100, assessment.feasibility_score)),
                    quality_score=round(
                        (assessment.evidence_score + assessment.novelty_score + assessment.feasibility_score) / 3
                    ),
                    suggested_method=assessment.suggested_method.strip(),
                    falsification_condition=assessment.falsification_condition.strip(),
                    source_type=assessment.source_type,
                )
            )
    except Exception as exc:
        # A classifier outage must not discard a hypothesis that passed the
        # stricter coverage and quote validation earlier in the graph.
        logger.warning("node=analyze_research_gaps fallback job=%s error=%s", state.get("job_id") or "adhoc", exc)
        enriched_gaps = [
            PotentialGap(
                **gap,
                gap_type="topical",
                confidence="low",
                counter_search_query=f'"{topic}" "{gap["aspect"]}"',
                reviewer_rationale="Corpus-level hypothesis; counter-search and reviewer confirmation are required.",
                verification_status="needs_counter_search",
                evidence_score=35,
                novelty_score=50,
                feasibility_score=50,
                quality_score=45,
                suggested_method="Run a targeted benchmark or cross-domain replication study.",
                falsification_condition="A newer directly relevant study covers the scoped aspect with comparable evidence.",
                source_type="corpus_inferred",
            )
            for gap in gaps
        ]

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="analyze_research_gaps",
            action="wait_for_human",
            reason=f"Prepared {len(enriched_gaps)} grounded gap hypotheses for counter-search and gap review.",
            created_at=_now_iso(),
        )
    )
    return {
        "potential_gaps": enriched_gaps,
        "gap_analysis_completed": True,
        "decisions": decisions,
        "current_node": "analyze_research_gaps",
    }


def _review_citation_errors(review: LiteratureReviewDraft, paper_ids: set[str]) -> list[str]:
    """Return actionable citation-contract errors for a composed review."""
    errors: list[str] = []
    section_prose = [paragraph for section in review.sections for paragraph in section.paragraphs]
    all_prose = [review.abstract, review.introduction, *section_prose, review.conclusion, review.limitations]
    # Limitations is meta-commentary — citations preferred but not required
    # The abstract answers the question and every findings section must retain
    # an inline citation. Introductions and conclusions may synthesize evidence
    # already cited in the surrounding sections.
    if not _PAPER_CITATION_PATTERN.findall(review.abstract):
        errors.append("abstract has no traceable citation")
    for section in review.sections:
        if not any(_PAPER_CITATION_PATTERN.findall(paragraph) for paragraph in section.paragraphs):
            errors.append(f"section {section.title!r} has no traceable citation")

    # All cited paper IDs must be traceable to this corpus
    for text in all_prose:
        for citation in _PAPER_CITATION_PATTERN.findall(text):
            if citation not in paper_ids:
                errors.append(f"citation [[{citation}]] is outside the selected corpus")

    for section in review.sections:
        if not section.supporting_paper_ids:
            errors.append(f"section {section.title!r} has no supporting_paper_ids")
        elif not set(section.supporting_paper_ids).issubset(paper_ids):
            errors.append(f"section {section.title!r} contains an unknown supporting paper")
    return list(dict.fromkeys(errors))


def _review_citations_are_valid(review: LiteratureReviewDraft, paper_ids: set[str]) -> bool:
    """Require traceable sources without rejecting uncited narrative transitions."""
    errors = _review_citation_errors(review, paper_ids)
    for error in errors:
        logger.warning("review_citations: %s", error)
    return not errors


def _canonical_citation_id(value: str, citation_aliases: dict[str, str]) -> str:
    normalized = value.strip()
    alias = _CITATION_ALIAS_PATTERN.fullmatch(normalized)
    if alias:
        return citation_aliases.get(alias.group(1), normalized)
    return citation_aliases.get(normalized, normalized)


def _canonicalize_citation_text(text: str, citation_aliases: dict[str, str]) -> str:
    def grouped(match: re.Match[str]) -> str:
        aliases = re.split(r"\s*[,;]\s*", match.group(1))
        return " ".join(f"[[{_canonical_citation_id(alias, citation_aliases)}]]" for alias in aliases)

    text = _GROUPED_CITATION_ALIAS_PATTERN.sub(grouped, text)
    text = _SINGLE_GROUPED_CITATION_ALIAS_PATTERN.sub(grouped, text)
    text = _MALFORMED_BRACKETED_ALIAS_PATTERN.sub(
        lambda match: f"[[{_canonical_citation_id(match.group(1), citation_aliases)}]]",
        text,
    )
    text = _SINGLE_CITATION_WITH_EXTRA_CLOSE_PATTERN.sub(
        lambda match: f"[[{_canonical_citation_id(match.group(1), citation_aliases)}]]",
        text,
    )
    text = _SHORT_CITATION_PATTERN.sub(
        lambda match: f"[[{_canonical_citation_id(match.group(1), citation_aliases)}]]",
        text,
    )
    text = _BRACKETED_ALIAS_PATTERN.sub(
        lambda match: f"[[{_canonical_citation_id(match.group(1), citation_aliases)}]]",
        text,
    )
    return _PAPER_CITATION_PATTERN.sub(
        lambda match: f"[[{_canonical_citation_id(match.group(1), citation_aliases)}]]",
        text,
    )


def _canonicalize_review_citations(
    review: LiteratureReviewDraft,
    citation_aliases: dict[str, str],
) -> LiteratureReviewDraft:
    """Replace short, model-facing citation aliases with stored paper IDs."""
    return LiteratureReviewDraft(
        title=review.title,
        abstract=_canonicalize_citation_text(review.abstract, citation_aliases),
        introduction=_canonicalize_citation_text(review.introduction, citation_aliases),
        sections=[
            {
                "title": section.title,
                "paragraphs": [
                    _canonicalize_citation_text(paragraph, citation_aliases) for paragraph in section.paragraphs
                ],
                "supporting_paper_ids": [
                    _canonical_citation_id(paper_id, citation_aliases) for paper_id in section.supporting_paper_ids
                ],
            }
            for section in review.sections
        ],
        conclusion=_canonicalize_citation_text(review.conclusion, citation_aliases),
        limitations=_canonicalize_citation_text(review.limitations, citation_aliases),
    )


def _repair_review_citations(review: LiteratureReviewDraft, paper_ids: set[str]) -> tuple[LiteratureReviewDraft, int]:
    """Remove untraceable citations without inventing replacement sources."""
    if not paper_ids:
        return review, 0
    repair_count = 0

    def repair_text(text: str) -> str:
        nonlocal repair_count
        known: list[str] = []

        def keep_known(match: re.Match[str]) -> str:
            nonlocal repair_count
            citation = match.group(1)
            if citation in paper_ids:
                known.append(citation)
                return match.group(0)
            repair_count += 1
            return ""

        repaired = _PAPER_CITATION_PATTERN.sub(keep_known, text).strip()
        return repaired

    repaired_sections = []
    for section in review.sections:
        valid_ids = [paper_id for paper_id in section.supporting_paper_ids if paper_id in paper_ids]
        repaired_sections.append(
            {
                "title": section.title,
                "paragraphs": [repair_text(paragraph) for paragraph in section.paragraphs],
                "supporting_paper_ids": list(dict.fromkeys(valid_ids)),
            }
        )
    return LiteratureReviewDraft(
        title=review.title,
        abstract=repair_text(review.abstract),
        introduction=repair_text(review.introduction),
        sections=repaired_sections,
        conclusion=repair_text(review.conclusion),
        limitations=repair_text(review.limitations),
    ), repair_count


def _repair_review_structure(review: LiteratureReviewDraft, paper_ids: set[str]) -> tuple[LiteratureReviewDraft, int]:
    """Drop uncited sections and derive section sources from inline citations."""
    repair_count = 0
    repaired_sections: list[dict] = []
    cited_across_sections: list[str] = []
    for section in review.sections:
        cited_ids = list(
            dict.fromkeys(
                citation
                for paragraph in section.paragraphs
                for citation in _PAPER_CITATION_PATTERN.findall(paragraph)
                if citation in paper_ids
            )
        )
        if not cited_ids:
            repair_count += 1
            continue
        if section.supporting_paper_ids != cited_ids:
            repair_count += 1
        cited_across_sections.extend(cited_ids)
        repaired_sections.append(
            {
                "title": section.title,
                "paragraphs": section.paragraphs,
                "supporting_paper_ids": cited_ids,
            }
        )

    # Keep the original draft intact when every section is uncited so the
    # validator can reject it and trigger the model retry/fallback.
    if not repaired_sections:
        return review, repair_count

    abstract = review.abstract
    if not _PAPER_CITATION_PATTERN.findall(abstract):
        citations = " ".join(f"[[{paper_id}]]" for paper_id in dict.fromkeys(cited_across_sections))
        abstract = f"{abstract.rstrip()} {citations}"
        repair_count += 1

    return LiteratureReviewDraft(
        title=review.title,
        abstract=abstract,
        introduction=review.introduction,
        sections=repaired_sections,
        conclusion=review.conclusion,
        limitations=review.limitations,
    ), repair_count


def _markdown_heading_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    cleaned = re.sub(r"^[\dIVXLC]+[.)\s-]+", "", ascii_text, flags=re.IGNORECASE)
    return re.sub(r"[^a-z]+", " ", cleaned.casefold()).strip()


def _markdown_paragraphs(value: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", value.strip()) if block.strip()]


def _parse_markdown_literature_review(
    markdown: str,
    *,
    topic: str,
    citation_aliases: dict[str, str],
    paper_ids: set[str],
) -> tuple[LiteratureReview, int]:
    """Turn a heading-based Markdown report into the reader-facing review shape."""
    fenced = _MARKDOWN_FENCE_PATTERN.fullmatch(markdown)
    text = (fenced.group("body") if fenced else markdown).strip()
    headings = list(_MARKDOWN_HEADING_PATTERN.finditer(text))
    if not headings:
        raise ValueError("Markdown literature review contains no headings")

    title = topic
    special: dict[str, list[str]] = {
        "abstract": [],
        "introduction": [],
        "conclusion": [],
        "limitations": [],
    }
    body_sections: list[tuple[str, str]] = []
    aliases = {
        "abstract": ("abstract", "tom tat"),
        "introduction": ("introduction", "gioi thieu"),
        "conclusion": ("conclusion", "ket luan"),
        "limitations": ("limitations", "limitation", "han che"),
        "references": ("references", "bibliography", "tai lieu tham khao"),
    }

    for index, heading in enumerate(headings):
        level = len(heading.group(1))
        heading_title = heading.group(2).strip().strip("*_`# ")
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        content = text[heading.end() : block_end].strip()
        if level == 1 and title == topic:
            title = heading_title or topic
            continue
        if not content:
            continue
        key = _markdown_heading_key(heading_title)
        role = next(
            (
                name
                for name, candidates in aliases.items()
                if any(key == candidate or key.startswith(f"{candidate} ") for candidate in candidates)
            ),
            None,
        )
        if role == "references":
            continue
        if role:
            special[role].append(content)
        else:
            body_sections.append((heading_title, content))

    missing = [name for name, blocks in special.items() if not blocks]
    if missing or not body_sections:
        details = ", ".join([*missing, *([] if body_sections else ["thematic sections"])])
        raise ValueError(f"Markdown literature review is missing required sections: {details}")

    if len(body_sections) > 4:
        merged_title = body_sections[3][0]
        merged_content = "\n\n".join(content for _, content in body_sections[3:])
        body_sections = [*body_sections[:3], (merged_title, merged_content)]

    repair_count = 0

    def clean_citations(value: str) -> str:
        nonlocal repair_count
        canonical = _canonicalize_citation_text(value, citation_aliases)

        def keep_known(match: re.Match[str]) -> str:
            nonlocal repair_count
            if match.group(1) in paper_ids:
                return match.group(0)
            repair_count += 1
            return ""

        return _PAPER_CITATION_PATTERN.sub(keep_known, canonical).strip()

    sections: list[dict] = []
    for heading_title, content in body_sections:
        paragraphs = [clean_citations(paragraph) for paragraph in _markdown_paragraphs(content)]
        cited_ids = list(
            dict.fromkeys(
                citation
                for paragraph in paragraphs
                for citation in _PAPER_CITATION_PATTERN.findall(paragraph)
                if citation in paper_ids
            )
        )
        sections.append(
            {
                "title": heading_title,
                "paragraphs": paragraphs,
                "supporting_paper_ids": cited_ids,
            }
        )

    def special_text(name: str) -> str:
        return clean_citations("\n\n".join(special[name]))

    return LiteratureReview(
        title=title,
        abstract=special_text("abstract"),
        introduction=special_text("introduction"),
        sections=sections,
        conclusion=special_text("conclusion"),
        limitations=special_text("limitations"),
    ), repair_count


def _llm_response_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content or "").strip()


async def _compose_markdown_literature_review(
    invoke_args: dict,
    *,
    citation_aliases: dict[str, str],
    paper_ids: set[str],
    job_id: str | None,
    run_id: str | None,
    execution_mode: str,
) -> tuple[LiteratureReview, int]:
    """Compose and parse plain Markdown while rotating configured providers."""
    prompt = get_literature_review_markdown_prompt()
    clients = [get_llm(), *get_llm_fallbacks()]
    last_error: Exception | None = None
    call_id = f"llm_{uuid4().hex}"
    call_started = perf_counter()
    llm_state = {
        "job_id": job_id or "adhoc",
        "run_id": run_id or job_id or "adhoc",
        "execution_mode": execution_mode,
    }

    for index, candidate in enumerate(clients):
        endpoint = getattr(candidate, "endpoint", None)
        provider = getattr(endpoint, "provider", "unknown")
        model = getattr(endpoint, "model", "unknown")
        provider_started = perf_counter()
        event(
            logger,
            "llm.attempt",
            state=llm_state,
            operation="literature review markdown fallback",
            node="compose_literature_review",
            provider=provider,
            model=model,
            call_id=call_id,
            fallback_index=index,
            retry_index=0,
            batch_id="literature_review_markdown_fallback",
            paper_ids=id_summary(paper_ids),
        )
        try:
            response = await candidate.ainvoke(prompt.format_messages(**invoke_args))
            markdown = _llm_response_text(response)
            if not markdown:
                raise ValueError("Model returned empty Markdown")
            review, repairs = _parse_markdown_literature_review(
                markdown,
                topic=invoke_args["topic"],
                citation_aliases=citation_aliases,
                paper_ids=paper_ids,
            )
            event(
                logger,
                "llm.success",
                state=llm_state,
                operation="literature review markdown fallback",
                node="compose_literature_review",
                provider=provider,
                model=model,
                call_id=call_id,
                fallback_index=index,
                retry_index=0,
                duration_ms=round((perf_counter() - call_started) * 1000),
                provider_duration_ms=round((perf_counter() - provider_started) * 1000),
                batch_id="literature_review_markdown_fallback",
                paper_ids=id_summary(paper_ids),
            )
            return review, repairs
        except Exception as exc:
            last_error = exc
            event(
                logger,
                "llm.failed",
                state=llm_state,
                level=logging.WARNING,
                operation="literature review markdown fallback",
                node="compose_literature_review",
                provider=provider,
                model=model,
                call_id=call_id,
                fallback_index=index,
                retry_index=0,
                duration_ms=round((perf_counter() - call_started) * 1000),
                provider_duration_ms=round((perf_counter() - provider_started) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
                failure_code="MARKDOWN_FALLBACK_FAILED",
                failed_stage="llm.invoke",
                fallback_reason=(
                    "next configured provider" if index < len(clients) - 1 else "no configured provider remains"
                ),
                batch_id="literature_review_markdown_fallback",
                paper_ids=id_summary(paper_ids),
            )

    assert last_error is not None
    raise last_error


def _ensure_corpus_citation_coverage(
    review: LiteratureReviewDraft | LiteratureReview,
    paper_ids: set[str],
    response_language: str,
) -> tuple[LiteratureReviewDraft | LiteratureReview, int]:
    """Keep selected-but-unused records visible without inventing claims."""
    if isinstance(review, dict):
        abstract = review.get("abstract", "")
        introduction = review.get("introduction", "")
        conclusion = review.get("conclusion", "")
        limitations = review.get("limitations", "")
        paragraphs = [
            paragraph for section in review.get("sections", []) for paragraph in section.get("paragraphs", [])
        ]
    else:
        abstract, introduction, conclusion, limitations = (
            review.abstract,
            review.introduction,
            review.conclusion,
            review.limitations,
        )
        paragraphs = [paragraph for section in review.sections for paragraph in section.paragraphs]
    cited_ids = {
        match.group(1)
        for block in [abstract, introduction, conclusion, limitations, *paragraphs]
        for match in _PAPER_CITATION_PATTERN.finditer(block)
    }
    missing_ids = sorted(paper_ids - cited_ids)
    if not missing_ids:
        return review, 0
    citations = " ".join(f"[[{paper_id}]]" for paper_id in missing_ids)
    if response_language == "Vietnamese":
        note = f"Các bài đã chọn nhưng chưa đóng góp luận điểm đã kiểm chứng được giữ lại để đối chiếu phạm vi và research gap; không dùng để suy ra kết luận: {citations}"
    else:
        note = f"Selected records that did not contribute a grounded narrative claim are retained for corpus and gap coverage, but are not used to infer conclusions: {citations}"
    limitations = f"{limitations.rstrip()} {note}"
    if isinstance(review, dict):
        updated = dict(review)
        updated["limitations"] = limitations
        return updated, len(missing_ids)
    return review.model_copy(update={"limitations": limitations}), len(missing_ids)


def _fallback_literature_review(
    topic: str,
    themes: list[Theme],
    claims: list[Claim],
    paper_ids: set[str],
    scope_disclaimer: str,
    output_language: str = "English",
    related_papers: list[dict] | None = None,
) -> LiteratureReview:
    """Produce a language-matched, evidence-quoting report if article generation fails."""
    vietnamese = output_language == "Vietnamese"
    titles = (
        {
            "contribution": "Lợi ích được báo cáo",
            "method": "Phương pháp và triển khai",
            "dataset": "Dữ liệu và đánh giá",
            "limitation": "Hạn chế và biện pháp bảo đảm",
            "theme": "Các phát hiện đã kiểm chứng",
        }
        if vietnamese
        else {
            "contribution": "Reported Benefits",
            "method": "Methods and Implementation",
            "dataset": "Data and Evaluation",
            "limitation": "Limitations and Safeguards",
            "theme": "Validated Findings",
        }
    )

    def evidence_sentence(claim: Claim) -> tuple[str, list[str]] | None:
        evidence = [
            item for item in claim.get("evidence", []) if item.get("paper_id") in paper_ids and item.get("quote")
        ]
        if not evidence:
            return None
        selected = evidence[0]
        paper_id = selected["paper_id"]
        prefix = "Bằng chứng được chọn cho biết:" if vietnamese else "The selected evidence reports:"
        return f"{prefix} “{selected['quote']}” [[{paper_id}]]", [paper_id]

    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        grouped.setdefault(claim.get("claim_type", "finding"), []).append(claim)

    sections: list[dict] = []
    for claim_type, grouped_claims in grouped.items():
        sentences: list[str] = []
        supporting_ids: list[str] = []
        for claim in grouped_claims[:4]:
            rendered = evidence_sentence(claim)
            if not rendered:
                continue
            sentence, evidence_ids = rendered
            sentences.append(sentence)
            supporting_ids.extend(evidence_ids)
        if sentences:
            sections.append(
                {
                    "title": titles.get(
                        claim_type, "Các phát hiện đã kiểm chứng" if vietnamese else "Validated Findings"
                    ),
                    "paragraphs": [" ".join(sentences)],
                    "supporting_paper_ids": list(dict.fromkeys(supporting_ids)),
                }
            )

    related_context = []
    related_ids = []
    for paper in related_papers or []:
        paper_id = paper.get("paper_id")
        abstract = " ".join(str(paper.get("abstract") or "").split())
        if paper_id not in paper_ids or not abstract:
            continue
        excerpt = re.split(r"(?<=[.!?])\s+", abstract, maxsplit=1)[0]
        related_context.append(f"{excerpt} [[{paper_id}]]")
        related_ids.append(paper_id)
        if len(related_context) == 2:
            break
    if related_context:
        sections.append(
            {
                "title": "Bối cảnh liên quan từ các bài báo đã tìm được"
                if vietnamese
                else "Related Context from Reviewed Papers",
                "paragraphs": [" ".join(related_context)],
                "supporting_paper_ids": related_ids,
            }
        )

    fallback_citation = f"[[{next(iter(paper_ids))}]]" if paper_ids else ""

    if not claims:
        if vietnamese:
            return LiteratureReview(
                title=f"Báo cáo bằng chứng hạn chế: {topic}",
                abstract=(
                    f"Báo cáo này chỉ trình bày bối cảnh liên quan từ {len(paper_ids)} bài báo đã tìm được; "
                    f"chưa có claim nào vượt qua kiểm định bằng chứng. {fallback_citation}"
                ),
                introduction=(
                    "Các bài báo dưới đây có liên quan đến câu hỏi nghiên cứu, nhưng các passage hiện có chưa đủ "
                    f"để xác thực một kết luận tổng hợp. {fallback_citation}"
                ),
                sections=sections,
                conclusion=(
                    "Corpus hiện tại cung cấp bối cảnh để tiếp tục tìm kiếm, không đủ để đưa ra kết luận về câu hỏi nghiên cứu. "
                    f"{fallback_citation}"
                ),
                limitations=(
                    "Cần thêm full text hoặc bằng chứng trực tiếp trước khi chuyển các ý bối cảnh thành finding đã kiểm định. "
                    f"{fallback_citation}"
                ),
            )
        return LiteratureReview(
            title=f"Evidence-Limited Literature Review: {topic}",
            abstract=(
                f"This report presents related context from {len(paper_ids)} retrieved papers; no claim passed evidence validation. "
                f"{fallback_citation}"
            ),
            introduction=(
                "The reviewed papers are relevant to the research question, but the available passages do not support "
                f"a validated synthesis finding. {fallback_citation}"
            ),
            sections=sections,
            conclusion=(
                "The current corpus provides context for further searching, not a conclusion about the research question. "
                f"{fallback_citation}"
            ),
            limitations=(
                "More full text or direct evidence is needed before contextual observations can become validated findings. "
                f"{fallback_citation}"
            ),
        )

    if vietnamese:
        intro_text = (
            f"Bản tổng hợp này dựa trên bằng chứng có thể truy vết từ {len(paper_ids)} bài báo đã chọn. "
            "Đây là bản dự phòng thận trọng vì bước tạo bài viết đầy đủ không đáp ứng yêu cầu đầu ra. "
            f"Do đó, các phần bên dưới chỉ trích dẫn bằng chứng đã qua kiểm chứng. {fallback_citation}"
        )
        conclusion_text = (
            "Trong phạm vi tập tài liệu đã xem xét, các bằng chứng được trích dẫn cho thấy một kết luận có điều kiện về chủ đề này, "
            "nhưng bản dự phòng không mở rộng vượt quá các nguồn đã chọn. "
            f"Nên tạo lại bài viết hoàn chỉnh khi dịch vụ tổng hợp sẵn sàng. {fallback_citation}"
        )
        limitations = (
            "Bản dự phòng này chỉ giới hạn trong tập tài liệu đã chọn và các bằng chứng đã kiểm chứng; "
            f"không khẳng định kết luận vượt quá các nguồn đó. {fallback_citation}"
        )
        title = f"Tổng quan tài liệu: {topic}"
    else:
        intro_text = (
            f"This review synthesizes traceable evidence from {len(paper_ids)} selected papers. "
            "It is presented as a conservative fallback because the full article-generation step did not meet its output contract. "
            f"The findings below therefore quote only the evidence that passed grounding checks. {fallback_citation}"
        )
        conclusion_text = (
            "Across the reviewed corpus, the cited evidence supports a qualified account of the topic, "
            "but this fallback summary does not extend beyond the selected papers. "
            f"A complete article should be regenerated when the composition service is available. {fallback_citation}"
        )
        limitations = (
            "This fallback is limited to the selected corpus and its validated evidence; "
            f"it does not establish conclusions beyond those sources. {fallback_citation}"
        )
        title = f"Literature review: {topic}"

    logger.info(
        "_fallback_literature_review: topic=%r sections=%d",
        topic,
        len(sections),
    )
    return LiteratureReview(
        title=title,
        abstract=(
            f"Bản tổng quan này tổng hợp các bằng chứng đã kiểm chứng cho {topic}. {fallback_citation}"
            if vietnamese
            else f"This review synthesizes the validated evidence available for {topic}. {fallback_citation}"
        ),
        introduction=intro_text,
        sections=sections
        or [
            {
                "title": "Validated findings",
                "paragraphs": [fallback_citation],
                "supporting_paper_ids": list(paper_ids)[:1],
            }
        ],
        conclusion=conclusion_text,
        limitations=limitations,
    )


async def compose_literature_review_node(state: AgentState) -> dict:
    """Turn grounded themes into the final reader-facing literature review."""
    topic = (state.get("original_topic") or "").strip()
    claims = [claim for claim in state.get("claims", []) if claim.get("validation_status") == "valid"]
    themes = list(state.get("themes", []))
    papers = list(state.get("papers", []))
    paper_ids = {paper["paper_id"] for paper in papers}
    scope_disclaimer = state.get("scope_disclaimer", "")
    article_language = "Vietnamese" if response_language(topic) == "Vietnamese" else "English"

    if not topic or not paper_ids:
        return {"literature_review": None, "current_node": "compose_literature_review"}

    claims_by_id = {claim["claim_id"]: claim for claim in claims}
    citation_aliases = {str(index): paper["paper_id"] for index, paper in enumerate(papers, start=1)}
    paper_to_alias = {paper_id: alias for alias, paper_id in citation_aliases.items()}

    def cite(paper_id: str) -> str:
        return f"[[{paper_to_alias[paper_id]}]]"

    def format_evidence(items: list[dict]) -> tuple[str, str]:
        usable = [item for item in items if item.get("paper_id") in paper_to_alias]
        evidence = "\n".join(f"- {cite(item['paper_id'])} {item['quote']}" for item in usable)
        note = (
            "\nQuantitative evidence is available: preserve its exact metric, value, unit, and comparison in the article."
            if any(re.search(r"\d", str(item.get("quote", ""))) for item in usable)
            else ""
        )
        return evidence, note

    theme_blocks = []
    for theme in themes:
        claim = claims_by_id.get(theme["summary_claim_id"])
        if not claim:
            continue
        evidence, quantitative_note = format_evidence(claim.get("evidence", []))
        theme_blocks.append(
            f"Theme: {theme['title']}\nSupporting paper IDs: {', '.join(theme['supporting_paper_ids'])}\n"
            f"Validated synthesis: {claim['text']}\nEvidence:\n{evidence}{quantitative_note}"
        )

    # A theme can be rejected by the stricter multi-paper grounding rule while
    # its underlying, single-paper claims remain valid.  Those claims are still
    # usable evidence for the article and must not silently collapse the whole
    # review into the one-line fallback.
    if not theme_blocks:
        for claim in claims:
            supporting_ids = [paper_id for paper_id in claim.get("supporting_paper_ids", []) if paper_id in paper_ids]
            evidence, quantitative_note = format_evidence(claim.get("evidence", []))
            if supporting_ids and evidence:
                theme_blocks.append(
                    f"Evidence bundle: {claim['claim_type']}\n"
                    f"Supporting paper IDs: {', '.join(supporting_ids)}\n"
                    f"Validated synthesis: {claim['text']}\nEvidence:\n{evidence}{quantitative_note}"
                )
    themes_text = "\n\n".join(theme_blocks)
    logger.info(
        "node=compose_literature_review job=%s theme_blocks=%d themes_text_len=%d claims=%d",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(theme_blocks),
        len(themes_text),
        len(claims),
    )
    papers_text = "\n\n".join(
        f"Citation {cite(paper['paper_id'])} | Paper ID: {paper['paper_id']} | Title: {paper['title']}\n"
        f"Abstract (context only; not a validated claim): {' '.join(str(paper.get('abstract') or '').split())[:1400]}"
        for paper in papers
    )

    review: LiteratureReview
    citation_repair_count = 0

    def to_literature_review(result: LiteratureReviewDraft) -> LiteratureReview:
        return LiteratureReview(
            title=result.title,
            abstract=result.abstract,
            introduction=result.introduction,
            sections=[
                {
                    "title": section.title,
                    "paragraphs": section.paragraphs,
                    "supporting_paper_ids": section.supporting_paper_ids,
                }
                for section in result.sections
            ],
            conclusion=result.conclusion,
            limitations=result.limitations,
        )

    if themes_text:
        invoker = _StructuredLLMInvoker(
            get_literature_review_prompt(),
            LiteratureReviewDraft,
            "literature review composition",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="compose_literature_review",
            execution_mode=state.get("execution_mode", "review"),
        )
        invoke_args = {
            "topic": topic,
            "response_language": article_language,
            "citation_feedback": "No previous draft. Follow the citation contract exactly.",
            "themes_text": themes_text,
            "papers_text": papers_text,
        }
        max_compose_attempts = 2
        last_exc: Exception | None = None
        last_claim_based_draft: LiteratureReviewDraft | None = None
        last_citation_errors: list[str] = []
        for attempt in range(1, max_compose_attempts + 1):
            markdown_error: Exception | None = None
            try:
                result = await invoker.ainvoke(
                    invoke_args,
                    trace_context={
                        "batch_id": f"literature_review_attempt_{attempt}",
                        "paper_ids": id_summary(paper_ids),
                    },
                )
                result = _canonicalize_review_citations(result, citation_aliases)
                result, citation_repairs = _repair_review_citations(result, paper_ids)
                result, structure_repairs = _repair_review_structure(result, paper_ids)
                result, coverage_notes = _ensure_corpus_citation_coverage(result, paper_ids, article_language)
                citation_repair_count += citation_repairs + structure_repairs + coverage_notes
                citation_errors = _review_citation_errors(result, paper_ids)
                if citation_errors:
                    # The draft was composed exclusively from the validated
                    # claim bundles above. Preserve it as a useful fail-open
                    # report if citation structure alone keeps failing.
                    last_claim_based_draft = result
                    last_citation_errors = citation_errors
                    raise ValueError("Literature review citation contract failed: " + "; ".join(citation_errors))
                review = to_literature_review(result)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if last_citation_errors:
                    invoke_args["citation_feedback"] = (
                        "The previous draft failed citation validation. Regenerate the complete draft. "
                        "Fix these citation errors: "
                        + "; ".join(last_citation_errors[:5])
                        + ". Use only the numeric aliases supplied with the evidence, in exact [[N]] format."
                    )
                if attempt < max_compose_attempts:
                    logger.warning(
                        "node=compose_literature_review attempt=%d/%d job=%s error=%s — retrying",
                        attempt,
                        max_compose_attempts,
                        state.get("job_id") or "adhoc",
                        exc,
                    )
                    continue
        if last_exc is not None:
            if last_claim_based_draft is not None:
                logger.warning(
                    "node=compose_literature_review citation_validation_bypassed job=%s errors=%s",
                    state.get("job_id") or "adhoc",
                    last_citation_errors,
                )
                review = to_literature_review(last_claim_based_draft)
                warnings = [
                    *state.get("source_warnings", []),
                    "LITERATURE_REVIEW_CITATION_VALIDATION_BYPASSED:" + "; ".join(last_citation_errors),
                ]
                if citation_repair_count:
                    warnings.append(f"LITERATURE_REVIEW_CITATION_REPAIRED:{citation_repair_count}")
                return {
                    "literature_review": review,
                    "current_node": "compose_literature_review",
                    "response_language": article_language,
                    "source_warnings": warnings,
                }
            try:
                review, markdown_repairs = await _compose_markdown_literature_review(
                    invoke_args,
                    citation_aliases=citation_aliases,
                    paper_ids=paper_ids,
                    job_id=state.get("job_id") or state.get("thread_id"),
                    run_id=state.get("run_id"),
                    execution_mode=state.get("execution_mode", "review"),
                )
                warnings = [
                    *state.get("source_warnings", []),
                    f"LITERATURE_REVIEW_MARKDOWN_FALLBACK:{type(last_exc).__name__}:{last_exc}",
                ]
                if markdown_repairs:
                    warnings.append(f"LITERATURE_REVIEW_CITATION_REPAIRED:{markdown_repairs}")
                return {
                    "literature_review": review,
                    "current_node": "compose_literature_review",
                    "response_language": article_language,
                    "source_warnings": warnings,
                }
            except Exception as markdown_exc:
                markdown_error = markdown_exc
                logger.warning(
                    "node=compose_literature_review markdown_fallback_failed job=%s error=%s",
                    state.get("job_id") or "adhoc",
                    markdown_exc,
                )
            assert markdown_error is not None
            logger.warning(
                "node=compose_literature_review fallback job=%s error=%s",
                state.get("job_id") or "adhoc",
                last_exc,
            )
            review = _fallback_literature_review(
                topic, themes, claims, paper_ids, scope_disclaimer, article_language, related_papers=papers
            )
            review, coverage_notes = _ensure_corpus_citation_coverage(review, paper_ids, article_language)
            return {
                "literature_review": review,
                "current_node": "compose_literature_review",
                "response_language": article_language,
                "source_warnings": [
                    *state.get("source_warnings", []),
                    f"LITERATURE_REVIEW_FALLBACK:{type(last_exc).__name__}:{last_exc}",
                    f"LITERATURE_REVIEW_MARKDOWN_FALLBACK_FAILED:{type(markdown_error).__name__}:{markdown_error}",
                    *([f"LITERATURE_REVIEW_CITATION_REPAIRED:{coverage_notes}"] if coverage_notes else []),
                ],
            }
    else:
        logger.warning(
            "node=compose_literature_review job=%s themes_text is empty — using fallback",
            state.get("job_id") or "adhoc",
        )
        review = _fallback_literature_review(
            topic, themes, claims, paper_ids, scope_disclaimer, article_language, related_papers=papers
        )

    review, coverage_notes = _ensure_corpus_citation_coverage(review, paper_ids, article_language)
    citation_repair_count += coverage_notes

    output = {
        "literature_review": review,
        "current_node": "compose_literature_review",
        "response_language": article_language,
    }
    warnings = list(state.get("source_warnings", []))
    if not claims:
        warnings.append("LITERATURE_REVIEW_EVIDENCE_LIMITED:NO_VALIDATED_CLAIMS")
    if citation_repair_count:
        warnings.append(f"LITERATURE_REVIEW_CITATION_REPAIRED:{citation_repair_count}")
    if warnings:
        output["source_warnings"] = warnings
    return output


# ─── Node 8: validate_grounding_node ───────────────────────────────────────────


async def validate_grounding_node(state: AgentState) -> dict:
    candidates = state.get("claim_candidates", [])
    papers_list = state.get("papers", [])
    papers_dict = {p["paper_id"]: p for p in papers_list}
    logger.info(
        "node=validate_grounding job=%s candidates=%s papers=%s",
        state.get("job_id") or state.get("thread_id") or "adhoc",
        len(candidates),
        len(papers_list),
    )

    valid_claims_dict: dict[str, Claim] = (
        {c["claim_id"]: c for c in state.get("claims", [])} if state.get("synthesis_completed") else {}
    )
    rejected_claims: list[Claim] = list(state.get("rejected_claims", [])) if state.get("synthesis_completed") else []
    validation_warnings: list[str] = (
        list(state.get("validation_warnings", [])) if state.get("synthesis_completed") else []
    )

    if len(papers_list) < 10:
        validation_warnings.append(
            f"INSUFFICIENT_PAPERS: Chỉ có {len(papers_list)} bài báo, kết quả tổng hợp có thể thiếu tính đại diện."
        )

    prompt = get_entailment_prompt()
    llm_invoker = _StructuredLLMInvoker(
        prompt,
        EntailmentResult,
        "grounding entailment",
        job_id=state.get("job_id") or state.get("thread_id"),
        run_id=state.get("run_id"),
        node_name="validate_grounding",
        execution_mode=state.get("execution_mode", "review"),
    )
    grounding_warnings: list[str] = []
    evidence_verdicts: dict[str, str] = {}

    async def validate_single_candidate(cand, claim_id):
        resolved_evidence = list(cand.get("evidence", []))
        if cand.get("claim_type") == "potential_gap":
            gap = next((g for g in state.get("potential_gaps", []) if g["claim_id"] == claim_id), None)
            if not gap:
                return False, ["Gap object not found for this claim ID"], resolved_evidence, "low"

            if len(papers_list) < 10:
                return False, ["papers_checked must be >= 10 for potential_gap"], resolved_evidence, "low"

            coverage = gap.get("coverage", [])
            if len(coverage) != len(papers_list):
                return False, ["Coverage length does not match total papers checked"], resolved_evidence, "low"

            cov_pids = [c["paper_id"] for c in coverage]
            if len(cov_pids) != len(set(cov_pids)):
                return False, ["Coverage contains duplicate paper IDs"], resolved_evidence, "low"

            if set(cov_pids) != set(papers_dict.keys()):
                return False, ["Coverage paper IDs do not match exact checked papers"], resolved_evidence, "low"

            mentioned_count = 0
            all_issues = []
            for c in coverage:
                if c["mentioned"]:
                    mentioned_count += 1
                    if not c.get("evidence_quote") or not c["evidence_quote"].strip():
                        return (
                            False,
                            [f"Paper {c['paper_id']} has mentioned=true but empty evidence_quote"],
                            resolved_evidence,
                            "low",
                        )

                    # Validate quote matches the abstract
                    ev_paper = papers_dict[c["paper_id"]]
                    res = validate_summary(
                        paper_id=ev_paper["paper_id"],
                        abstract=ev_paper["abstract"],
                        evidence_quote=c["evidence_quote"],
                        contribution="",
                        limitations="",
                        doi=ev_paper.get("doi"),
                        url=ev_paper["url"],
                    )
                    if not res.passed:
                        # Extract quote-related errors
                        all_issues.extend(res.issues)

            if all_issues:
                return False, all_issues, resolved_evidence, "low"

            if mentioned_count > 2:
                return False, ["Too many papers mention this aspect for it to be a gap"], resolved_evidence, "low"

            return True, [], resolved_evidence, "low"

        # Validate ALL supporting papers exist (for non-gap claims)
        paper_ids = cand.get("supporting_paper_ids", [])
        if not paper_ids:
            return False, ["Không có supporting_paper_ids"], resolved_evidence, "low"

        missing_ids = [pid for pid in paper_ids if pid not in papers_dict]
        if missing_ids:
            return False, [f"Paper IDs không tồn tại trong danh sách nguồn: {missing_ids}"], resolved_evidence, "low"

        evidence_list = resolved_evidence
        if not evidence_list:
            return False, ["Evidence list cannot be empty"], resolved_evidence, "low"

        # Attach canonical Qdrant provenance only when the indexed passage
        # actually contains the quote selected during extraction. A merely
        # similar top-ranked chunk must not replace the claim's evidence.
        if get_settings().qdrant_enabled:
            try:
                retrieved = await QdrantVectorStore(
                    backend=state.get("embedding_backend", "primary")
                ).retrieve_claim_evidence(
                    cand["text"],
                    state.get("job_id") or state.get("thread_id") or "adhoc",
                    paper_ids=paper_ids,
                )
                resolved_evidence = _resolve_retrieved_evidence(evidence_list, retrieved)
                evidence_list = resolved_evidence
            except VectorStoreError as exc:
                warning = f"QDRANT_CLAIM_EVIDENCE_FALLBACK:{claim_id}:{exc}"
                grounding_warnings.append(warning)
                logger.warning("node=validate_grounding job=%s %s", state.get("job_id") or "adhoc", warning)

        if cand.get("claim_type") == "theme":
            if len(set(paper_ids)) < 2:
                return False, ["Theme requires at least 2 distinct supporting papers"], resolved_evidence, "low"
            evidence_ids = {e.get("paper_id") for e in evidence_list}
            if not set(paper_ids).issubset(evidence_ids):
                return False, ["Theme is missing evidence quotes for some supporting papers"], resolved_evidence, "low"

        # Run 3-layer grounding validation for all quotes
        cand_text = cand["text"]
        claim_type = cand["claim_type"]
        is_contrib = claim_type in ("contribution", "theme")
        is_lim = claim_type in ("limitation", "potential_gap")

        all_issues = []
        for ev in evidence_list:
            ev_paper_id = ev.get("paper_id")
            if ev_paper_id not in papers_dict:
                return False, [f"Evidence paper_id {ev_paper_id} not found in source papers"], resolved_evidence, "low"

            ev_paper = papers_dict[ev_paper_id]
            evidence_source = ev.get("quote", "") if ev.get("source_level") == "full_text" else ev_paper["abstract"]
            res = validate_summary(
                paper_id=ev_paper["paper_id"],
                abstract=evidence_source,
                evidence_quote=ev.get("quote", ""),
                contribution=cand_text if is_contrib else "",
                limitations=cand_text if is_lim else "",
                doi=ev_paper.get("doi"),
                url=ev_paper["url"],
            )
            if not res.passed:
                all_issues.extend(res.issues)

        if all_issues:
            return False, all_issues, resolved_evidence, "low"

        # Semantic Entailment Guardrail (use all quotes for entailment check)
        all_quotes = "\n".join(e.get("quote", "") for e in evidence_list)
        try:
            entailment = await llm_invoker.ainvoke(
                {"claim_text": cand_text, "evidence_quote": all_quotes},
                trace_context={"batch_id": "grounding_entailment", "claim_id": claim_id},
            )
            if not entailment.entails:
                return False, [f"Semantic Entailment Failed: {entailment.reason}"], resolved_evidence, "low"
        except Exception as e:
            logging.error(f"Error in LLM Entailment check: {e}")
            raise RuntimeError("Grounding entailment could not be validated by any configured LLM provider") from e

        full_text_paper_ids = {ev["paper_id"] for ev in resolved_evidence if ev.get("source_level") == "full_text"}
        confidence = "high" if set(paper_ids).issubset(full_text_paper_ids) else "low"
        source_levels = {ev.get("source_level", "abstract") for ev in resolved_evidence}
        if confidence == "high":
            # Only an exact passage retrieved from every supporting paper can
            # automatically reach the strongest verdict.
            evidence_verdicts[claim_id] = "supported"
        elif "snippet" in source_levels:
            # A third-party source snippet can support a claim, but retain the
            # conservative model verdict and route non-support to reviewers.
            evidence_verdicts[claim_id] = entailment.verdict or "partial"
        else:
            # Abstract-only evidence is intentionally capped, matching the
            # PaperPulse three-tier contract.
            evidence_verdicts[claim_id] = "uncertain"
        return True, [], resolved_evidence, confidence

    validation_inputs = []
    for cand in candidates:
        claim_id = cand.get("claim_id") or f"claim_{uuid4().hex[:8]}"
        valid_claims_dict.pop(claim_id, None)
        validation_inputs.append((cand, claim_id))

    initial_concurrency = get_settings().litreview_claim_validation_concurrency
    semaphore = asyncio.Semaphore(initial_concurrency)

    async def validate_with_limit(cand: ClaimCandidate, claim_id: str):
        async with semaphore:
            return await validate_single_candidate(cand, claim_id)

    validation_results = list(
        await asyncio.gather(
            *(validate_with_limit(cand, claim_id) for cand, claim_id in validation_inputs),
            return_exceptions=True,
        )
    )

    retry_indices: list[int] = []
    for index, result in enumerate(validation_results):
        if not isinstance(result, BaseException):
            continue
        if _is_provider_concurrency_error(result):
            retry_indices.append(index)
            continue
        raise result

    if retry_indices:
        retry_concurrency = min(_CLAIM_VALIDATION_RETRY_CONCURRENCY, initial_concurrency)
        warning = f"GROUNDING_ENTAILMENT_429_RETRY:claims={len(retry_indices)}:concurrency={retry_concurrency}"
        validation_warnings.append(warning)
        logger.warning(
            "node=validate_grounding job=%s retrying_429_claims=%s concurrency=%s",
            state.get("job_id") or state.get("thread_id") or "adhoc",
            len(retry_indices),
            retry_concurrency,
        )
        await asyncio.sleep(_CLAIM_VALIDATION_429_BACKOFF_SECONDS)
        retry_semaphore = asyncio.Semaphore(retry_concurrency)

        async def retry_with_limit(index: int):
            cand, claim_id = validation_inputs[index]
            async with retry_semaphore:
                return await validate_single_candidate(cand, claim_id)

        retry_results = await asyncio.gather(
            *(retry_with_limit(index) for index in retry_indices),
            return_exceptions=True,
        )
        for index, result in zip(retry_indices, retry_results, strict=True):
            if isinstance(result, BaseException):
                raise result
            validation_results[index] = result

    for (cand, claim_id), (passed, issues, resolved_evidence, confidence) in zip(
        validation_inputs, validation_results, strict=True
    ):
        if passed:
            verdict = evidence_verdicts.get(claim_id, "uncertain")
            valid_claims_dict[claim_id] = Claim(
                claim_id=claim_id,
                claim_type=cand["claim_type"],
                text=cand["text"],
                supporting_paper_ids=cand.get("supporting_paper_ids", []),
                evidence=resolved_evidence,
                validation_status="valid",
                validation_errors=[],
                evidence_confidence=confidence,
                evidence_verdict=verdict,
                requires_human_review=verdict != "supported",
            )
        else:
            rejected_claims.append(
                Claim(
                    claim_id=claim_id,
                    claim_type=cand["claim_type"],
                    text=cand["text"],
                    supporting_paper_ids=cand.get("supporting_paper_ids", []),
                    evidence=resolved_evidence,
                    validation_status="rejected",
                    validation_errors=issues,
                    evidence_verdict="unsupported",
                    evidence_confidence="low",
                    requires_human_review=True,
                )
            )
            validation_warnings.extend(issues)

    valid_claims = list(valid_claims_dict.values())

    valid_claim_ids = {c["claim_id"] for c in valid_claims}
    themes = [t for t in state.get("themes", []) if t["summary_claim_id"] in valid_claim_ids]
    potential_gaps = [g for g in state.get("potential_gaps", []) if g["claim_id"] in valid_claim_ids]

    decisions = list(state.get("decisions", []))
    grounding_revision_attempt = state.get("grounding_revision_attempt", 0)

    # revision_source is set explicitly here so revise_claims_node never needs
    # to infer it from unsupported_ids or any other heuristic.
    revision_limit = state.get("max_claim_revision_attempts", 1)
    if rejected_claims and papers_list and grounding_revision_attempt < revision_limit:
        action = "revise_claims"
        reason = (
            f"{len(rejected_claims)} claims rejected. Routing to revise_claims_node "
            f"(grounding attempt {grounding_revision_attempt + 1})."
        )
        next_revision_source = "grounding"
    elif len(valid_claims) == 0:
        action = "fail"
        reason = "Zero valid claims after grounding validation."
        next_revision_source: RevisionSource | None = None
    else:
        action = "wait_for_human"
        reason = f"Grounding validation passed with {len(valid_claims)} valid claims."
        next_revision_source = None

    claim_ids_by_paper_and_type = {
        (paper_id, claim["claim_type"]): claim["claim_id"]
        for claim in valid_claims
        for paper_id in claim["supporting_paper_ids"]
    }
    evidence_rows = [
        EvidenceRow(
            **{
                **row,
                "method_claim_id": claim_ids_by_paper_and_type.get((row["paper_id"], "method")),
                "dataset_claim_id": claim_ids_by_paper_and_type.get((row["paper_id"], "dataset")),
                "contribution_claim_id": claim_ids_by_paper_and_type.get((row["paper_id"], "contribution")),
                "limitation_claim_id": claim_ids_by_paper_and_type.get((row["paper_id"], "limitation")),
            }
        )
        for row in state.get("evidence_rows", [])
    ]

    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="validate_grounding",
            action=action,
            reason=reason,
            created_at=_now_iso(),
        )
    )

    return {
        "claims": valid_claims,
        "themes": themes,
        "potential_gaps": potential_gaps,
        "rejected_claims": rejected_claims,
        "evidence_rows": evidence_rows,
        "validation_warnings": validation_warnings,
        "source_warnings": [*state.get("source_warnings", []), *grounding_warnings],
        # Any human-requested revision invalidates an earlier narrative. The
        # compose node rebuilds it only from the newly validated claims.
        "literature_review": None,
        "decisions": decisions,
        "revision_source": next_revision_source,
        "current_node": "validate_grounding",
    }


# ─── Node 9: revise_claims_node ────────────────────────────────────────────────


async def revise_claims_node(state: AgentState) -> dict:
    """Revise claims based on an explicit revision_source set upstream.

    Source is ALWAYS read from state["revision_source"] — never inferred.
    - "grounding": revise state["rejected_claims"] using their validation_errors.
    - "reviewer":  revise claims marked unsupported in state["review_decisions"].

    LLM missing a claim in its output is treated as an error (retry-able),
    NOT as a silent discard.  Only action=="discard" in the LLM response
    removes a claim.
    """
    revision_source: RevisionSource | None = state.get("revision_source")
    if revision_source is None:
        # Should never happen — defensive guard
        return {"error": "revise_claims_node reached with revision_source=None"}

    grounding_revision_attempt = state.get("grounding_revision_attempt", 0)
    review_revision_attempt = state.get("review_revision_attempt", 0)
    revision_log: list[RevisionRecord] = list(state.get("revision_log", []))

    # ── Determine which claims to revise and what feedback to use ──────────────
    if revision_source == "grounding":
        claims_to_revise: list[Claim] = list(state.get("rejected_claims", []))
        # Claims that already passed validation remain as candidates unchanged
        unchanged_claims: list[Claim] = list(state.get("claims", []))
        review_round = grounding_revision_attempt + 1
    else:  # reviewer
        review_decisions = state.get("review_decisions", [])
        unsupported_ids = {
            d["claim_id"]: d.get("note", "") for d in review_decisions if d.get("verdict") == "unsupported"
        }
        claims_to_revise = [c for c in state.get("claims", []) if c["claim_id"] in unsupported_ids]
        unchanged_claims = [c for c in state.get("claims", []) if c["claim_id"] not in unsupported_ids]
        review_round = review_revision_attempt + 1

    # Unchanged (valid / supported) claims pass through directly as candidates
    revised_candidates: list[ClaimCandidate] = [
        ClaimCandidate(
            claim_id=c["claim_id"],
            claim_type=c["claim_type"],
            text=c["text"],
            supporting_paper_ids=c["supporting_paper_ids"],
            evidence=c["evidence"],
        )
        for c in unchanged_claims
    ]

    if claims_to_revise:
        prompt = get_revision_prompt()
        llm_invoker = _StructuredLLMInvoker(
            prompt,
            RevisionResult,
            "claim revision",
            job_id=state.get("job_id") or state.get("thread_id"),
            run_id=state.get("run_id"),
            node_name="revise_claims",
            execution_mode=state.get("execution_mode", "review"),
        )

        feedback_text = ""
        for c in claims_to_revise:
            if revision_source == "grounding":
                feedback = "\n".join(f"- {e}" for e in c.get("validation_errors", []))
                feedback_source_label = "grounding validation"
            else:
                feedback = unsupported_ids.get(c["claim_id"], "")
                feedback_source_label = "human reviewer"

            evidence_text = "\n".join(f"- {q['quote']}" for q in c.get("evidence", []))
            feedback_text += (
                f"Claim ID: {c['claim_id']}\n"
                f"Feedback source: {feedback_source_label}\n"
                f"Current Text: {c['text']}\n"
                f"Evidence:\n{evidence_text}\n"
                f"Feedback:\n{feedback}\n\n"
            )

        try:
            result = await llm_invoker.ainvoke(
                {"feedback_text": feedback_text},
                trace_context={"batch_id": "claim_revision", "claim_ids": [c["claim_id"] for c in claims_to_revise]},
            )
        except Exception as e:
            logging.error(f"LLM revision call failed: {e}")
            return {"error": f"REVISION_LLM_ERROR: {e}"}

        # Validate LLM returned entries for ALL claims — missing = error, not discard
        returned_ids = {r.claim_id for r in result.revised_claims}
        missing_ids = [c["claim_id"] for c in claims_to_revise if c["claim_id"] not in returned_ids]
        if missing_ids:
            err = f"LLM revision response missing entries for claim IDs: {missing_ids}"
            logging.error(err)
            return {"error": f"REVISION_LLM_INCOMPLETE: {err}"}

        for c in claims_to_revise:
            revised = next(r for r in result.revised_claims if r.claim_id == c["claim_id"])

            # Build lineage record — always, for all actions
            rev_index = (
                grounding_revision_attempt + 1 if revision_source == "grounding" else review_revision_attempt + 1
            )
            revision_log.append(
                RevisionRecord(
                    revision_id=f"{c['claim_id']}-R{rev_index}",
                    claim_id=c["claim_id"],
                    source=revision_source,
                    action=revised.action,
                    reason=revised.action_taken,
                    review_round=review_round,
                    revised_text=revised.revised_text,
                    previous_text=c["text"],
                )
            )

            if revised.action == "discard":
                # LLM explicitly chose discard — do NOT add to candidates
                logger.info(f"Claim {c['claim_id']} discarded (source={revision_source}): {revised.action_taken}")
                continue

            # revise or narrow → update text, keep claim_id stable
            revised_candidates.append(
                ClaimCandidate(
                    claim_id=c["claim_id"],
                    claim_type=c["claim_type"],
                    text=revised.revised_text,
                    supporting_paper_ids=c["supporting_paper_ids"],
                    evidence=c["evidence"],
                )
            )

    # Increment the correct counter
    new_grounding_revision_attempt = grounding_revision_attempt
    new_review_revision_attempt = review_revision_attempt
    if revision_source == "grounding":
        new_grounding_revision_attempt += 1
    else:
        new_review_revision_attempt += 1

    decisions = list(state.get("decisions", []))
    discarded_count = sum(1 for r in revision_log if r["source"] == revision_source and r["action"] == "discard")
    revised_count = len(claims_to_revise) - discarded_count
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="revise_claims",
            action="revise_claims",
            reason=(
                f"Revision (source={revision_source}, round={review_round}): "
                f"revised/narrowed={revised_count}, discarded={discarded_count}."
            ),
            created_at=_now_iso(),
        )
    )

    return {
        "grounding_revision_attempt": new_grounding_revision_attempt,
        "review_revision_attempt": new_review_revision_attempt,
        "revision_source": None,  # reset after use
        "revision_log": revision_log,
        "claim_candidates": revised_candidates,
        "decisions": decisions,
        "current_node": "revise_claims",
    }


# ─── Node 10: human_review_node ────────────────────────────────────────────────


async def human_review_node(state: AgentState) -> dict:
    job_id = state.get("job_id") or f"job_{uuid4().hex[:8]}"
    payload = {
        "job_id": job_id,
        "claims": state.get("claims", []),
        "references": state.get("references", []),
        "research_gaps": state.get("potential_gaps", []),
        "scope_disclaimer": state.get("scope_disclaimer", ""),
        "instruction": (
            "Review each claim and reference. Research gaps are corpus-scoped hypotheses: "
            "review their evidence, run the supplied counter-search queries, then select "
            "'approve' or 'request_changes'."
        ),
    }

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="human_review",
            action="wait_for_human",
            reason="Graph paused for Human-in-the-loop (Reviewer) decision.",
            created_at=_now_iso(),
        )
    )

    if state.get("execution_mode", "review") in {"review", "autonomous"}:
        decisions[-1]["action"] = "continue"
        decisions[-1]["reason"] = "Final review is approved automatically; human review gate was skipped."
        return {
            "status": "running",
            "hitl_payload": None,
            "hitl_decision": "approve",
            "review_decisions": [],
            "reference_checks": [],
            "review_feedback": "",
            "revision_source": None,
            "decisions": decisions,
            "current_node": "finalize",
        }

    # In interactive LangGraph execution, trigger interrupt
    try:
        resume_payload = interrupt(payload)
    except GraphInterrupt:
        # Re-raise to actually pause the graph execution
        raise
    except Exception as e:
        if state.get("hitl_decision"):
            resume_payload = state.get("hitl_decision")
        else:
            raise ValueError(f"Graph interrupt failed and no hitl_decision found: {e}")

    hitl_decision_val = resume_payload
    review_decisions = []
    reference_checks = []
    review_feedback = ""

    if isinstance(resume_payload, dict):
        hitl_decision_val = resume_payload.get("hitl_decision")
        if not hitl_decision_val:
            raise ValueError("resume_payload missing hitl_decision")
        review_decisions = resume_payload.get("review_decisions", [])
        reference_checks = resume_payload.get("reference_checks", [])
        review_feedback = resume_payload.get("review_feedback", "")

    # revision_source is set explicitly here when the reviewer requests changes.
    # The graph router (after_human_review) will route to revise_claims_node only
    # when hitl_decision == "request_changes", so revision_source="reviewer" is
    # safe to set unconditionally — it is ignored when hitl_decision == "approve".
    next_revision_source: RevisionSource | None = "reviewer" if hitl_decision_val == "request_changes" else None

    return {
        "status": "hitl_waiting",
        "hitl_payload": payload,
        "hitl_decision": hitl_decision_val,
        "review_decisions": review_decisions,
        "reference_checks": reference_checks,
        "review_feedback": review_feedback,
        "revision_source": next_revision_source,
        "decisions": decisions,
        "current_node": "human_review",
    }


# ─── Node 11: finalize_node ────────────────────────────────────────────────────


async def finalize_node(state: AgentState) -> dict:
    # Paper selection is the user approval gate for this research flow.  The
    # legacy reviewer decision remains supported for existing jobs.
    hitl_decision = state.get("hitl_decision") or "approve"
    final_status = "approved" if hitl_decision == "approve" else "changes_requested"

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="finalize",
            action="finish",
            reason=f"Workflow completed with final status '{final_status}'.",
            created_at=_now_iso(),
        )
    )

    return {
        "status": final_status,
        "decisions": decisions,
        "current_node": "finalize",
    }


# ─── Node 12: fail_node ────────────────────────────────────────────────────────


async def fail_node(state: AgentState) -> dict:
    error_msg = state.get("error") or "Execution failed during LitReview Agent workflow."

    decisions = list(state.get("decisions", []))
    decisions.append(
        AgentDecision(
            decision_id=f"dec_{uuid4().hex[:8]}",
            node="fail",
            action="fail",
            reason=f"Workflow failed: {error_msg}",
            created_at=_now_iso(),
        )
    )

    return {
        "status": "error",
        "error": error_msg,
        "decisions": decisions,
        "current_node": "fail",
    }
