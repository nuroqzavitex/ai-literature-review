from langgraph.graph import END, StateGraph

from src.agents.litreview.domain.models import AgentState
from src.agents.litreview.workflow.nodes import (
    analyze_research_gaps_node,
    assess_sources_node,
    compose_literature_review_node,
    extract_evidence_node,
    fail_node,
    finalize_node,
    human_review_node,
    intent_guardrail_node,
    out_of_scope_node,
    plan_search_node,
    refine_query_node,
    review_papers_node,
    review_subqueries_node,
    revise_claims_node,
    screen_papers_node,
    search_academic_sources_node,
    synthesize_claims_node,
    validate_grounding_node,
)
from src.config import get_settings


def after_assess_sources(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    papers = state.get("papers", [])
    attempt = state.get("search_attempt", 1)
    settings = get_settings()
    if len(papers) == 0 and attempt >= settings.litreview_max_search_attempts:
        return "fail"
    if len(papers) < settings.litreview_min_corpus_size and attempt < settings.litreview_max_search_attempts:
        return "refine_query"
    return "screen_papers"


def after_screen_papers(state: AgentState) -> str:
    """Do not let an empty relevance-filtered corpus reach extraction.

    ``screen_papers_node`` is the last deterministic guard before users can
    approve a corpus.  Routing its explicit no-match result to ``fail`` keeps
    the job terminal and communicates the actionable search suggestion rather
    than producing an empty, misleading review.
    """
    return "fail" if state.get("error") else "review_papers"


def after_intent_guardrail(state: AgentState) -> str:
    return "plan_search" if state.get("intent") == "litreview" else "out_of_scope"


def after_extract_evidence(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    return "validate_grounding"


def after_validate_grounding(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    claims = state.get("claims", [])
    rejected = state.get("rejected_claims", [])
    grounding_revision = state.get("grounding_revision_attempt", 0)
    revision_limit = state.get("max_claim_revision_attempts", 1)
    valid = [c for c in claims if c.get("validation_status") == "valid"]
    if rejected and state.get("papers") and grounding_revision < revision_limit:
        return "revise_claims"
    if len(valid) == 0:
        # A screened corpus can still support a transparent, evidence-limited
        # report even when no claim survives the strict entailment gate.
        return "compose_literature_review" if state.get("papers") else "fail"
    if state.get("synthesis_completed"):
        if not state.get("gap_analysis_completed"):
            return "analyze_research_gaps"
        return "compose_literature_review"
    return "synthesize_claims"


def after_synthesize_claims(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    return "validate_grounding"


def after_human_review(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    decision = state.get("hitl_decision")
    review_revision = state.get("review_revision_attempt", 0)
    if decision == "approve":
        return "finalize"
    if decision == "request_changes" and review_revision < 1:
        return "revise_claims"
    return "finalize"


def after_revise_claims(state: AgentState) -> str:
    if state.get("error"):
        return "fail"
    return "validate_grounding"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("intent_guardrail", intent_guardrail_node)
    graph.add_node("out_of_scope", out_of_scope_node)
    graph.add_node("plan_search", plan_search_node)
    graph.add_node("review_subqueries", review_subqueries_node)
    graph.add_node("search_academic_sources", search_academic_sources_node)
    graph.add_node("assess_sources", assess_sources_node)
    graph.add_node("refine_query", refine_query_node)
    graph.add_node("screen_papers", screen_papers_node)
    graph.add_node("review_papers", review_papers_node)
    graph.add_node("extract_evidence", extract_evidence_node)
    graph.add_node("synthesize_claims", synthesize_claims_node)
    graph.add_node("analyze_research_gaps", analyze_research_gaps_node)
    graph.add_node("compose_literature_review", compose_literature_review_node)
    graph.add_node("validate_grounding", validate_grounding_node)
    graph.add_node("revise_claims", revise_claims_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("fail", fail_node)

    graph.set_entry_point("intent_guardrail")

    graph.add_conditional_edges("intent_guardrail", after_intent_guardrail)
    graph.add_edge("out_of_scope", END)
    graph.add_edge("plan_search", "review_subqueries")
    graph.add_edge("review_subqueries", "search_academic_sources")
    graph.add_edge("search_academic_sources", "assess_sources")
    graph.add_conditional_edges("assess_sources", after_assess_sources)
    graph.add_edge("refine_query", "search_academic_sources")
    graph.add_conditional_edges("screen_papers", after_screen_papers)
    graph.add_edge("review_papers", "extract_evidence")
    graph.add_conditional_edges("extract_evidence", after_extract_evidence)
    graph.add_conditional_edges("validate_grounding", after_validate_grounding)
    graph.add_conditional_edges("synthesize_claims", after_synthesize_claims)
    graph.add_edge("analyze_research_gaps", "compose_literature_review")
    graph.add_edge("compose_literature_review", "human_review")
    graph.add_conditional_edges("revise_claims", after_revise_claims)
    graph.add_conditional_edges("human_review", after_human_review)
    graph.add_edge("finalize", END)
    graph.add_edge("fail", END)

    return graph


uncompiled_graph = build_graph()
