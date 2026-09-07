# MVP2 Core — Implementation Map

> Historical implementation map. Full-text ingestion, Qdrant, research-gap job
> và durable worker đã tiếp tục phát triển sau snapshot này; dùng code và
> [current architecture](../architecture/ARCHITECTURE.md) để xác định trạng thái.

Phạm vi đã triển khai là V2.1–V2.3. V2.4 selective full text vẫn là optional
gate và không được UI tuyên bố đã hỗ trợ.

## Module map

| Capability | Implementation |
|---|---|
| MVP1 literature-review schemas | `src/models/schemas/literature_reviews.py` |
| MVP2 strict Copilot schemas | `src/models/schemas/research_copilot.py` |
| MVP1 job/review persistence | `src/services/repositories/literature_reviews.py` |
| MVP2 project/Copilot persistence | `src/services/repositories/research_copilot.py` |
| Authorization, capability, chat and action orchestration | `src/services/research_copilot.py` |
| MVP1 literature-review API | `src/api/routers/literature_reviews.py` |
| MVP2 Copilot API and policy errors | `src/api/routers/research_copilot.py` |
| Browser workspace | `frontend/app/page.tsx` |
| Legacy V1 browser workspace | `frontend/app/legacy/page.tsx` |
| Contract/regression tests | `tests/test_api/test_v2_core.py` |

## Identity boundary

Production V2 endpoints verify Clerk session JWTs from the Authorization header
against Clerk JWKS and validate the authorized-party claim. Clerk is the identity
source; Supabase stores only the application profile and project-scoped roles.
Direct `researcher:actor-id` bootstrap claims remain available only in
development/test and the bootstrap endpoint returns 404 in production.

Project-scoped resources return `404` to non-members. Mutation requires an
owner/researcher membership. Review access additionally requires a review-level
assignment, except that the author may self-review. Reviewer memberships cannot
access project conversations or memories.

## Artifact and version boundary

V1 remains the only literature search/extraction/grounding engine. A completed
project job is snapshotted as an immutable `v2_report_versions` row. Messages,
citations, memories, action proposals, gaps and feedback carry a report version.
Creating a newer version marks pending old-version actions stale.

## Conversation policy

The MVP2 orchestrator currently uses deterministic structured-evidence
retrieval. It intentionally does not let an LLM compose uncited facts. A turn
returns one of:

- `grounded_answer` with validated citations;
- `insufficient_evidence` with limitations;
- `action_proposal` requiring Researcher confirmation.

This policy can later wrap an LLM, provided its output passes the same citation
validator before persistence.

## Verification

The full backend suite runs in the project Docker image:

```bash
ruff check src tests
ruff format --check src tests
pytest tests -q --cov=src --cov-fail-under=60
```

Frontend verification:

```bash
cd frontend
npm run lint
npm run build
```

MVP2 implementation completion does not equal product validation. Before the
release is declared accepted, populate a gold conversation/memory/gap set and
meet the metric thresholds in `contracts/contract_v2.md`.
