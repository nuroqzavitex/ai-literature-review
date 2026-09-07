# PaperPulse Agent Adoption Plan

> Historical proposal. Một số hạng mục, gồm `retrieve_claim_evidence()` và
> full-text-first grounding, đã được triển khai sau khi file này được viết;
> checkbox/phase bên dưới không phản ánh trạng thái runtime ngày 2026-09-01.
> Dùng `docs/architecture/` và code/test hiện tại để xác định functionality.

## Purpose

This roadmap adopts the strongest research-agent ideas found in PaperPulse while preserving LitReview's existing production strengths:

- background workers, PostgreSQL checkpoints, and execution fencing;
- multi-source academic search;
- human approval of search queries, papers, and final reports;
- evidence-backed claims and reviewer gates.

The target architecture is:

```text
Full-text evidence
  -> Corpus intelligence
    -> Verified research gaps
      -> Traceable knowledge graph
        -> Real-time progress
```

## Guiding Principles

1. Do not replace the worker/checkpoint lifecycle with request-bound agent execution.
2. A claim cannot be marked `supported` from an abstract alone.
3. Every user-visible conclusion must link to source evidence.
4. Corpus structure should be derived from data before the LLM names or explains it.
5. Research gaps are hypotheses requiring both corpus coverage and counter-search.
6. Each phase must have measurable acceptance criteria before the next phase is enabled.

## Phase 0 — Baseline and Evidence Contract

**Duration:** 2–3 days  
**Priority:** Foundation

### Goals

- Establish measurable quality and cost baselines.
- Define one evidence payload used by extraction, validation, review UI, graphing, and export.

### Work

1. Add benchmark metrics:
   - claim-support rate;
   - full-text evidence coverage;
   - citation precision and recall;
   - research-gap false-positive rate;
   - median/P95 latency and token cost at 10, 30, and 50 papers;
   - reviewer approval rates for claims, themes, and gaps.
2. Build an evaluation set with:
   - 10 AI/CS topics;
   - 5 biomedical topics;
   - 5 narrow/noisy topics;
   - 5 nonsensical or out-of-scope topics;
   - 50–100 manually labelled claims.
3. Replace minimal evidence records with a stable evidence contract:

```json
{
  "paper_id": "W123",
  "source_level": "full_text | abstract | snippet",
  "document_id": "W123:chunk:7",
  "section": "Methods",
  "quote": "Exact supporting passage",
  "start_char": 1230,
  "end_char": 1412,
  "retrieval_score": 0.87,
  "validation_status": "supported | partial | unsupported | uncertain"
}
```

### Primary Files

- `src/agents/state.py`
- `src/models/schemas/literature_reviews.py`
- `src/validation/grounding.py`
- `eval/topics.json`
- `eval/results/report.md`

### Acceptance Criteria

- A real E2E benchmark writes machine-readable metrics and a Markdown report.
- The benchmark includes false-positive tests for out-of-scope and nonsensical queries.
- Existing report rendering remains compatible with legacy evidence rows.

## Phase 1 — Full-Text Grounding

**Duration:** 4–6 days  
**Priority:** P0

LitReview already downloads open-access PDFs, chunks them, and indexes them in Qdrant. This phase connects that material to claim verification.

### Target Flow

```text
Claim candidate
  -> Qdrant search over selected papers
  -> top full-text passages
  -> quote/span validation
  -> LLM entailment on passage
  -> confidence routing and reviewer decision
```

### Work

1. Add `retrieve_claim_evidence()` to `QdrantVectorStore`.
   - Input: job ID, claim text, optional paper IDs.
   - Output: top passages with paper ID, chunk index, text, and retrieval score.
2. Update `validate_grounding_node` to verify by tiers:
   - Tier 1: passage from downloaded full text/Qdrant;
   - Tier 2: Semantic Scholar snippet or ar5iv/OpenAlex open-access text;
   - Tier 3: abstract-only fallback.
3. Apply confidence rules:

| Evidence source | Maximum automatic status |
|---|---|
| Exact full-text passage | `supported` |
| Source snippet | `supported` or `partial` |
| Abstract only | `uncertain` or `partial` |
| No evidence | `unsupported` |

4. Mark abstract-only claims with `low_confidence` and require human approval.
5. Update reviewer UI to show the full passage, paper, section, and source link.

### Primary Files

- `src/services/vector_store.py`
- `src/services/paper_ingestion.py`
- `src/agents/nodes/litreview.py`
- `src/validation/grounding.py`
- `frontend/app/_components/MockWorkspace.tsx`

### Acceptance Criteria

- At least 70% of claims with an available OA PDF have full-text evidence in the benchmark.
- No abstract-only claim is automatically marked `supported`.
- Every supported claim links to an exact paper and passage.
- P95 latency grows by no more than 30% from the Phase 0 baseline.

## Phase 2 — Corpus Clustering and Theme Approval

**Duration:** 4–5 days  
**Priority:** P1

Move theme formation from a primarily LLM-defined structure to a corpus-defined structure.

### Target Flow

```text
Selected papers
  -> paper embeddings
  -> clustering
  -> centroid ranking
  -> LLM theme naming
  -> user approve / rename / merge
  -> synthesis
```

### Work

1. Add `cluster_corpus_node` after `review_papers_node`.
2. Use existing Qdrant vectors or add a dedicated SPECTER-v2 paper embedding store.
3. Find the cluster count with silhouette scoring and bound it to 3–8 clusters.
4. Exclude clusters with fewer than three papers as outliers.
5. Add a LangGraph `interrupt()` at `review_themes_node`.
6. Let users rename, merge, discard themes, and move papers between themes.
7. Make `synthesize_claims_node` consume approved themes instead of inventing the entire taxonomy.

### Proposed Files

- `src/agents/nodes/clustering.py`
- `src/services/corpus_clustering.py`
- `src/agents/graph.py`
- `src/agents/state.py`
- workspace/review frontend components.

### Acceptance Criteria

- Each visible theme has at least two or three source papers.
- Every theme includes traceable paper IDs.
- A user can alter themes without rerunning search.
- No synthesized theme is disconnected from the reviewed corpus.

## Phase 3 — Dedicated Research Gap Agent

**Duration:** 7–10 days  
**Priority:** P1

Research-gap generation should become a separate subgraph rather than expanding `synthesize_claims_node` indefinitely.

### Target Flow

```text
Approved corpus
  -> query analyzer
  -> citation snowball
  -> relevance and coherence gate
  -> topical / method / contradiction detectors
  -> counter-search
  -> quality score
  -> reviewer approval
```

### Gap Types

| Type | Meaning |
|---|---|
| Topical | An underexplored subtopic or unanswered question |
| Method | A method not yet tested in a relevant context |
| Contradiction | Conflicting result, assumption, or finding |
| Evaluation | Missing benchmark, dataset, metric, or deployment context |

### Guardrails

- Do not generate a gap below a minimum corpus size.
- Avoid absolute wording such as “nobody has studied this”.
- Require coverage of every paper in the reviewed corpus.
- Run counter-search before accepting a claimed gap.
- Lower confidence when the corpus is incoherent or evidence is abstract-only.
- Require reviewer approval before export.

### Proposed Files

- `src/agents/research_gap/graph.py`
- `src/agents/research_gap/nodes/`
- `src/agents/research_gap/schemas.py`
- `src/services/citation_snowball.py`
- `src/services/gap_quality.py`

### Reuse

- `AcademicSearchService`
- `rank_papers`
- `QdrantVectorStore`
- existing potential-gap coverage validation;
- existing worker/HITL/resume infrastructure.

### Acceptance Criteria

- Nonsensical queries return `no reliable gap found` rather than fabricated gaps.
- Every displayed gap has coverage, source evidence, and confidence metadata.
- A reviewer benchmark quantifies the false-positive rate.

## Phase 4 — Knowledge Graph

**Duration:** 3–5 days  
**Priority:** P2

Build a graph from existing structured output; this phase should not introduce more LLM calls.

### Graph Model

```text
Paper --supports--> Claim
Paper --belongs_to--> Theme
Theme --summarized_by--> Claim
Claim --contradicts--> Claim
Gap --derived_from--> Paper set
```

### Work

1. Add `build_knowledge_graph_node` after claim and gap validation.
2. Return a bounded JSON contract: `nodes`, `edges`, `stats`.
3. Render only verified claims or visibly marked low-confidence claims.
4. Add filters for theme, confidence, contradictions, and unused papers.
5. Open the linked evidence passage when a node or edge is selected.

### Acceptance Criteria

- Every edge is traceable to a source record.
- The client remains responsive at 100–300 nodes.
- A reviewer can find the evidence for a claim in a few interactions.

## Phase 5 — Real-Time Progress via SSE

**Duration:** 2–4 days  
**Priority:** P2

Keep background workers and PostgreSQL as the source of truth. Add SSE only as the faster UI transport, retaining polling as a fallback.

### Architecture

```text
Worker -> PostgreSQL / Redis progress events -> SSE endpoint -> UI
                                           └-> polling fallback
```

### Event Contract

```json
{
  "job_id": "...",
  "node": "validate_grounding",
  "phase": "Verifying full-text evidence",
  "papers_found": 42,
  "claims_verified": 19,
  "elapsed_seconds": 88,
  "status": "running"
}
```

### UI Requirements

- current phase;
- paper and claim counts;
- sources currently used;
- elapsed time;
- retry/cancel controls;
- explicit waiting-for-review status.

## Phase 6 — Hardening and Rollout

**Duration:** 3–5 days  
**Priority:** Release

### Feature Flags

- `FULL_TEXT_GROUNDING_ENABLED`
- `CORPUS_CLUSTERING_ENABLED`
- `GAP_AGENT_ENABLED`
- `KNOWLEDGE_GRAPH_ENABLED`

### Rollout Sequence

1. Internal/admin users.
2. 10% of users.
3. 50% of users after metric review.
4. General availability after reliability targets are met.

### Fallback Rules

- Missing PDF: abstract-only evidence with low confidence.
- Qdrant unavailable: no full-text `supported` status.
- Clustering failure: current theme grouping.
- Insufficient corpus: no research-gap assertion.

### Test Requirements

- unit tests for each validator;
- integration tests for every interrupt/resume stage;
- fabricated-quote regression tests;
- live API E2E tests;
- benchmark tests for latency and cost.

## Delivery Order

| Sprint | Deliverable | Product value |
|---|---|---|
| 1 | Baseline and evidence contract | Makes improvements measurable |
| 2 | Full-text grounding | Largest reliability improvement |
| 3 | Corpus clustering and theme HITL | Better review structure and traceability |
| 4–5 | Dedicated research-gap graph | Strongest product differentiation |
| 6 | Knowledge graph and SSE | Better trust and user experience |
| 7 | Benchmark, rollout, hardening | Safe production adoption |

## First Implementation Decision

Start with **Phase 1 — Full-Text Grounding**. It reuses LitReview's existing PDF ingestion and Qdrant infrastructure, substantially improves citation trust, and is the prerequisite for reliable research-gap detection and graph visualisation.
