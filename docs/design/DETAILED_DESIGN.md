# Detailed Design

> Source mapping và runtime contract của implementation hiện tại, cập nhật 2026-09-01.

## 1. Composition root

`src/main.py` tạo FastAPI app, middleware và đăng ký bốn nhóm router dưới `/api/v1`: literature reviews, document reviews, Research Copilot/project APIs và sandbox. Internal sandbox router giữ prefix `/internal/v1/sandbox`.

Lifespan khởi tạo worker embedded khi `WORKER_MODE=embedded`. Với `WORKER_MODE=external`, API chỉ tạo durable job; `python -m src.worker_main` chạy worker riêng.

## 2. Source map

| Capability | Source of truth |
|---|---|
| Settings | `src/config.py` |
| API registration | `src/main.py` |
| Literature review routes | `src/api/routers/literature_reviews.py` |
| Project/Copilot routes | `src/api/routers/research_copilot.py` |
| Document review routes | `src/api/routers/document_reviews.py` |
| Sandbox routes | `src/api/routers/sandbox.py`, `sandbox_internal.py` |
| Main graph | `src/agents/graph.py` |
| Research-gap graph | `src/agents/research_gap_graph.py` |
| Graph runner/checkpoint | `src/services/jobs.py` |
| Durable worker | `src/services/worker_runtime.py`, `src/worker_main.py` |
| Database | `src/services/repositories/database.py` |
| Literature repository | `src/services/repositories/literature_reviews.py` |
| Product repository | `src/services/repositories/research_copilot.py` |
| Redis acceleration | `src/services/redis_jobs.py` |
| Academic search | `src/services/academic_search.py` |
| Paper ingestion/Qdrant | `src/services/paper_ingestion.py`, `vector_store.py` |

## 3. Job execution contract

1. API validates actor/project and inserts a `queued` PostgreSQL row.
2. Redis event may notify a worker; failure to publish does not lose the job.
3. Worker claims a row using PostgreSQL ownership/lease fields.
4. Worker starts heartbeat and executes the requested workflow.
5. `LitReviewJobService` compiles LangGraph with `AsyncPostgresSaver` using the repository database URL.
6. Node updates, interrupt state, result or error are persisted.
7. Execution fence prevents stale worker completion after ownership changes.

## 4. Literature-review graph

`src/agents/graph.py` registers 18 nodes. The high-level phases are:

```text
intent guard → search planning → subquery review
→ multi-source search/refinement → paper screening/review
→ evidence extraction → claim synthesis/grounding/revision
→ research-gap analysis → report composition → human review → finalize
```

Các điều kiện route phải được đọc từ `after_*`; không suy diễn từ tên node. Sơ đồ chuẩn: [AGENT_STATE_GRAPH.md](../architecture/AGENT_STATE_GRAPH.md).

## 5. Research-gap graph

`ResearchGapGraph` chạy extract, ba detector song song, origin labeling, verification, counter-evidence, quality scoring, deduplication và synthesis. Nó là workflow riêng nhưng có thể dùng corpus/report của project. Sơ đồ chuẩn: [RESEARCH_GAP_FLOW.md](../architecture/RESEARCH_GAP_FLOW.md).

## 6. Academic search và grounding

Main tool gọi `AcademicSearchService.search_all_sources()` để tìm OpenAlex,
Semantic Scholar và arXiv, sau đó normalize/deduplicate. `search()` chỉ là
helper OpenAlex-only cho lookup hẹp. Paper model giữ `source`; arXiv ID dùng
prefix `arxiv:`. Abstract tối thiểu và retry/rate limit lấy từ settings.

Full text được tải khi có URL phù hợp, parse thành text/chunk và index trong Qdrant. Qdrant query được scope theo job/corpus. Nếu vector retrieval lỗi, workflow phải dùng fallback được định nghĩa thay vì xem Qdrant là dữ liệu gốc.

## 7. Persistence

- `DATABASE_URL` bắt buộc PostgreSQL; repository database layer reject URL loại khác.
- LangGraph checkpoint dùng PostgreSQL, không dùng `AsyncSqliteSaver`.
- `PRODUCT_DATABASE_URL` cho phép tách product store; nếu trống thì dùng `DATABASE_URL`.
- Alembic/Supabase migrations định nghĩa schema; không tạo DDL ngầm bằng repository khi chạy request.
- Redis status cache có TTL và luôn có PostgreSQL fallback.

## 8. API groups

| Nhóm | Ví dụ endpoint |
|---|---|
| Health/status | `GET /health`, `GET /status` |
| Review jobs | `POST /reviews`, `GET /reviews/{job_id}`, resume/review/evaluation |
| Projects | CRUD project, members, capabilities và research plans |
| Project research | create/list/cancel/delete review, create research-gap job |
| Collaboration | invitations, assignments, report versions và feedback |
| Copilot | conversations, messages, memories và action proposals |
| Gap verification | comparison matrix, gaps, countersearch và review |
| Document review | create/read/update/reanalyze/verify/apply/explain/rewrite |
| Sandbox | project-scoped session/capability API và internal adoption API |

OpenAPI tại `/docs` khi backend chạy là danh sách endpoint chi tiết đáng tin cậy hơn bản chép tay.

## 9. Security boundaries

- Production auth lấy identity từ Clerk token; client-supplied role/user ID không phải nguồn tin cậy.
- Project APIs phải gọi membership/capability checks trước read hoặc mutation.
- Internal sandbox API không được expose như public browser API.
- Secret chỉ đến từ environment/backend; log không in raw token, key, prompt riêng tư hoặc reviewer feedback.

## 10. Failure and recovery

| Failure | Expected behavior |
|---|---|
| Redis unavailable | Worker scan PostgreSQL; status đọc PostgreSQL |
| Qdrant unavailable | Degrade/fail theo retrieval policy; không mất business record |
| Worker chết | Lease hết hạn, worker khác reclaim, fence chặn stale completion |
| API restart | Queued/running state vẫn ở PostgreSQL |
| Provider timeout/rate limit | Bounded retry/fallback; persist warning/error |
| Invalid reviewer action | Reject trước mutation |

## 11. Build and CI baseline

- Project và CI: Python 3.12; backend `Dockerfile` còn 3.11 và cần đồng bộ.
- Frontend: Next.js 16.2.12, React 19.2.7, TypeScript 5.8.3.
- CI chạy Ruff, pytest coverage, frontend lint/build và sandbox PostgreSQL/runtime suites.

## 12. Verification checklist

- [x] Documentation does not call SQLite or ChromaDB current runtime infrastructure.
- [x] API/worker both use the same PostgreSQL database in Docker/native design.
- [x] Redis/Qdrant are described as non-authoritative.
- [x] Main and research-gap graph docs match source nodes and routes.
- [x] Frontend/API versions and ports match package/configuration files.
