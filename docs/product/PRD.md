# Product Requirements Document

**Sản phẩm:** LitReview Agent
**Trạng thái tài liệu:** Living PRD, cập nhật 2026-09-01

## 1. Mục tiêu

Giúp researcher tạo và kiểm chứng literature review/research-gap artifact có provenance trong một project workspace bền vững, có reviewer collaboration và các công cụ phân tích được kiểm soát.

KPI 50% time reduction và 80% claim-support accuracy vẫn là mục tiêu cần đo; không được ghi là đã đạt khi chưa có acceptance artifact.

## 2. Actors và authorization

| Actor | Hành động chính |
|---|---|
| Owner/Researcher | CRUD project, lập plan, chạy/cancel/delete review, chạy gap, mời reviewer, dùng Copilot/document review/sandbox |
| Reviewer | Xem assignment được giao, đọc report/evidence và submit decision |

Production dùng Clerk bearer token. Backend suy ra actor từ trusted auth context và kiểm tra membership/assignment; không tin `role` hoặc `user_id` do client tự khai.

## 3. Functional requirements

### FR-01 — Project workspace

- Tạo, liệt kê, đọc và xóa project theo quyền.
- Quản lý member, capability, research plan, report version và audit-relevant state.
- Dữ liệu project A không được đọc hoặc mutate từ actor chỉ thuộc project B.

### FR-02 — Literature review

- Tạo durable review job trong project và trả `202` cùng job ID.
- Worker tìm song song OpenAlex, Semantic Scholar và arXiv, normalize/deduplicate corpus.
- Yêu cầu HITL ở subquery, paper selection và final review theo execution mode.
- Trích evidence, synthesize/validate/revise claim, phân tích gap và compose report.
- Lưu progress, checkpoint, result và failure trong PostgreSQL.

### FR-03 — Grounding và retrieval

- Metadata/DOI/URL không được do LLM tự tạo.
- Claim factual phải trỏ tới paper/evidence phù hợp.
- Full text chỉ tải khi khả dụng/hợp policy; Qdrant index phải được scope theo corpus/job.
- Qdrant lỗi không được làm mất job/report đã lưu.

### FR-04 — Research-gap verification

- Tạo research-gap job từ project/corpus đã xác định.
- Chạy detector, origin labeling, verifier, counter-evidence, scoring và deduplicate.
- Cho phép countersearch và reviewer verdict.
- UI phải phân biệt candidate gap với gap đã được reviewer xác nhận.

### FR-05 — Reviewer collaboration

- Owner/researcher mời reviewer vào một review cụ thể.
- Invitation có expiry/revoke/resend và copyable link fallback khi email không cấu hình.
- Reviewer chỉ truy cập assignment được cấp; decision lưu actor và loại self/external review.

### FR-06 — Copilot và governed actions

- Conversation/message gắn project và có citation/provenance khi trả lời factual.
- Memory có lifecycle confirm/supersede/delete.
- Mutation hoặc tác vụ tốn chi phí dùng action proposal/capability policy phù hợp.

### FR-07 — Document review

- Tạo/read/update document review; chạy critic/citation checks.
- Hỗ trợ explain, rewrite và apply suggestion theo endpoint hiện có.
- File/input là untrusted content; giới hạn size/page/timeout lấy từ settings.

### FR-08 — Research sandbox

- Chỉ mở session khi project/capability cho phép.
- Runtime/artifact/adoption đi qua public project API và internal control boundary riêng.
- Kết quả phân tích phải truy vết plan, code/artifact và execution metadata.

## 4. Runtime requirements

- PostgreSQL là source of truth cho application data và LangGraph checkpoint.
- Redis chỉ làm dispatch/status cache và phải có PostgreSQL fallback.
- Worker dùng lease, heartbeat và execution fence để chịu restart/reclaim.
- Local hỗ trợ embedded worker; Docker/production hỗ trợ external worker.
- API base path là `/api/v1`; OpenAPI runtime tại `/docs`.

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | Clerk verification, project isolation, backend-only secrets, internal sandbox boundary |
| Reliability | Durable queue semantics trên PostgreSQL, bounded retry, recovery sau restart |
| Observability | Structured events có request/job/run/worker identifiers khi áp dụng |
| Performance | Giới hạn concurrency/rate theo provider; không đặt con số p95 nếu chưa benchmark |
| Accessibility | Keyboard/focus/semantic HTML, responsive layout và VI/EN nhất quán |
| Compatibility | Schema change dùng migration và cập nhật frontend/API tests |

## 6. Acceptance criteria

- Tạo project → tạo review → worker chạy → HITL/resume → report version thành công.
- Multi-source result giữ đúng `source`, DOI/URL và deduplicate.
- Redis ngắt không làm mất queued job; worker vẫn scan PostgreSQL.
- Reviewer không được giao không thể đọc/submit review khác.
- Candidate gap hiển thị confidence/evidence/counter-evidence và trạng thái review.
- CI pass backend lint/test, frontend lint/build và sandbox suites được cấu hình.
- KPI học thuật chỉ được công bố từ dataset/reviewer artifact có thể kiểm tra.

## 7. Out of scope của tài liệu

Proposal trong `docs/roadmap/concepts/` và roadmap lịch sử không được coi là functionality đã triển khai. Tính năng chỉ được ghi “implemented” khi có route/service/schema/test hoặc UI tương ứng trong repository.

## 8. Implementation gap đã xác nhận

Subquery và paper-selection interrupt đang hoạt động trong `review` mode.
`human_review_node` lại tự đặt `approve` cho cả `review` và `autonomous`, vì vậy
FR-02 về final review chưa đạt dù reviewer route/schema tồn tại. Không dùng PRD
này để tuyên bố final reviewer gate đã triển khai hoàn chỉnh.
