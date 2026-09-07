# Phân tích dự án và roadmap MVP V1–V4

> Historical analysis snapshot ngày 2026-08-02. Các mô tả SQLite,
> `BackgroundTasks`, OpenAlex-only và thứ tự triển khai V1–V4 đã bị code hiện tại
> vượt qua; xem `docs/architecture/ARCHITECTURE.md` cho trạng thái đang chạy.

> Cập nhật theo code/API/frontend và quyết định sản phẩm ngày 2026-08-02.
> MVP V1 đã được chủ dự án nghiệm thu vận hành. Các metric định lượng vẫn phải
> giữ artifact/gold set để làm baseline và regression cho V2–V4.

## 1. Kết luận chốt

Dự án đã đóng phạm vi chức năng MVP V1 như một **grounded literature-review
engine**:

```text
OpenAlex search
→ deterministic screening
→ LLM evidence extraction
→ claim grounding
→ bounded revision
→ theme/potential-gap synthesis
→ grounding lần hai
→ LangGraph HITL
→ Reviewer decision/evaluation
```

Các lỗi P0 cũ về terminal review, revision counters, revision action, structured
output và final status đã được sửa. Chủ dự án xác nhận MVP V1 đã chạy tốt và đã
nghiệm thu; từ đây không mở rộng thêm chức năng vào V1, chỉ giữ bug fix,
security fix và regression.

“MVP V1 đã nghiệm thu” không đồng nghĩa “production platform đã hoàn tất”:

- trusted project identity tối thiểu được đưa vào nền tảng MVP V2;
- production AuthN/AuthZ, durable workers, Postgres, backup và observability
  thuộc V4.1;
- potential gap V1 vẫn là observation trên corpus/abstract, chưa phải kết luận
  gap của toàn lĩnh vực;
- metric và artifact V1 phải được giữ làm regression gate cho mọi version sau.

Roadmap cũ **không tối ưu cho đề bài** vì đặt multi-source metadata ở V2 và
full-text/RAG ở V3, trong khi data-analysis — một nửa chức năng của đề bài — bị
đẩy tới V4. Roadmap đã được sửa thành:

| Phiên bản | Mục tiêu sản phẩm |
|---|---|
| MVP V1 | Grounded abstract-based literature review + HITL |
| MVP V2 | Research Copilot + tool calling + evidence/gap verification + selective full text |
| MVP V3 | Copilot-assisted data analysis + safe code sandbox |
| MVP V4 | Production Copilot/platform + gated multi-source/full-text RAG |

## 2. Đề bài thực sự có hai workflow

[README_project.md](../product/README_project.md) yêu cầu:

### A. Literature Review và Research Gap

```text
search
→ screen
→ summarize
→ synthesize themes
→ comparison table
→ identify candidate gaps
→ human review
```

### B. Initial Research Data Analysis

```text
upload data
→ profile
→ recommend method
→ generate code
→ execute safely
→ validate result
→ interpret
→ human review
```

Hai workflow dùng chung project, identity, audit, model gateway, storage và
evaluation nhưng phải có graph/state/validation riêng. Không ghép thành một
prompt hoặc một LangGraph khổng lồ.

Từ V2, cả hai workflow dùng chung một lớp tương tác thứ ba:

```text
Research Copilot
→ đọc structured project context
→ trả lời có evidence
→ tạo ActionProposal
→ gọi tool của workflow phù hợp sau confirmation
```

Copilot không phải workflow khoa học thứ ba và không phải source of truth. Nó là
interface/orchestrator phía trên LiteratureReviewGraph, GapVerificationGraph và
AnalysisGraph.

## 3. Trạng thái code V1 đã xác nhận

### 3.1 Search và screening

Đã có:

- OpenAlex-only adapter;
- chỉ giữ record có ID, title, authors, URL và abstract đủ dài;
- deduplicate;
- lấy candidate pool rộng hơn rồi xếp hạng;
- chọn 10–20 paper theo request;
- relevance/rank từ rule có thể kiểm tra;
- query history và decision trace.

Một trace “source assessment 18 papers” trong khi report có 10 paper không phải
lỗi dữ liệu: 18 là candidate hợp lệ trước screening, 10 là corpus cuối. Tuy vậy
label cần phân biệt `retrieved`, `screened` và `included` để người dùng không
hiểu sai.

### 3.2 Evidence và grounding

LLM trích bốn loại claim cấp paper:

```text
method
dataset
contribution
limitation
```

Validator kiểm tra:

- paper ID thuộc corpus;
- quote không rỗng và là substring của abstract;
- metadata/URL/DOI do source cung cấp;
- wording tuyệt đối;
- semantic entailment;
- theme/gap claims cũng phải qua grounding.

Claim bị lỗi có thể `revise`, `narrow` hoặc `discard`; lineage lưu previous/new
text, source và round. Grounding revision và Reviewer revision dùng counter
riêng.

### 3.3 LLM routing

Code hiện hỗ trợ route cấu hình qua Google, OpenCode, Ollama, OpenAI và
OpenRouter. Gateway:

- dùng native structured output nếu endpoint hỗ trợ;
- chuyển sang prompt JSON + strict Pydantic nếu model không hỗ trợ schema;
- retry invalid structured output có giới hạn;
- rotate provider cho quota/network/provider failure;
- không coi lỗi provider là bằng chứng claim unsupported.

Endpoint `/api/v1/status` chỉ báo **configured**, không giả vờ rằng quota và
connectivity đã được runtime verify.

### 3.4 Structured report và frontend

Report hiện dùng structured schema:

```text
papers
claims
evidence_rows
themes
potential_gaps
references
scope_disclaimer
decision_trace
revision_log
source_warnings
validation_warnings
review audit
```

Legacy Markdown report đã bị loại khỏi API. Frontend hiển thị:

- overview và live status;
- Evidence Matrix gồm method/dataset/contribution/limitation;
- claim + evidence quote + source URL;
- theme và potential gap;
- references;
- Reviewer queue/decision;
- revision lineage, warnings, routing configuration và MVP metrics.

Các số papers, claims, themes, gaps và references đều lấy từ job result; không
phải số demo hard-code.

### 3.5 HITL và state machine

API chỉ nhận review khi job ở `hitl_waiting`; trạng thái khác trả 409. Approve
yêu cầu review toàn bộ claims/references. Request changes yêu cầu ít nhất một
claim `unsupported`. Resume dùng cùng `job_id/thread_id` và graph checkpoint.

Status/report được đồng bộ khi finalize; có recovery scanner cho job bị kẹt ở
`resuming`.

### 3.6 KPI framework

Repository/API đã có công thức:

- Claim-support Accuracy;
- claim review coverage;
- Reference Validity;
- reference review coverage;
- median time reduction;
- evaluation records.

Đây mới là **instrumentation**. Chưa có dữ liệu đủ thì `mvp_passed` không được
diễn giải thành KPI đã đạt.

## 4. Các P0 cũ đã đóng

| P0 cũ | Trạng thái hiện tại | Bằng chứng hành vi |
|---|---|---|
| Review sau terminal vẫn 202 | Đã sửa | chỉ `hitl_waiting` được nhận; còn lại 409 |
| Dùng chung revision counter | Đã sửa | `grounding_revision_attempt` và `review_revision_attempt` |
| Revision chỉ rewrite | Đã sửa | `revise/narrow/discard` + revision lineage |
| Approved nhưng trace/report lệch | Đã sửa | finalize cập nhật status và persisted result |
| Recovery/metrics sai scope | Đã sửa | periodic scanner và metrics chỉ tính approved/reviewed data |
| Model không hỗ trợ schema làm gãy job | Đã sửa ở gateway | prompted JSON + Pydantic + bounded fallback |

Các mục này không nên tiếp tục xuất hiện dưới tiêu đề “lỗi đang chặn nghiệm
thu” trong tài liệu hiện hành.

## 5. Nền tảng chuyển tiếp từ V1 sang V2

### G1 — Trusted identity và project scope tối thiểu thuộc V2 foundation

V1 đã đáp ứng luồng HITL demo, nhưng V2 tạo project, conversation, action và về
sau có selective full text. Vì vậy actor không thể tiếp tục được tin cậy chỉ từ
`role`, `user_id` hoặc `reviewer_id` do client gửi.

Đầu V2 cần:

- backend dùng opaque HttpOnly server-side session; local/test bootstrap token
  bị disable ngoài môi trường cho phép;
- project-scoped API V2 reject `role`, `user_id`, `actor_id`, `reviewer_id` trong
  body/query; legacy endpoint V1 chỉ giữ tạm trong compatibility window;
- owner/member/reviewer scope tối thiểu theo project;
- Researcher không tự review output của chính mình;
- action/tool call lưu actor, permission và audit.

Enterprise SSO, invitations, Admin policy và RBAC production được mở rộng ở
V4.1; không chờ tới V4 mới có project isolation cơ bản.

### G2 — Đóng gói artifact nghiệm thu V1 thành regression baseline

Chủ dự án đã nghiệm thu V1. Việc còn lại là chuẩn hóa bằng chứng nghiệm thu để
V2 không làm hồi quy chất lượng:

- topic/corpus cố định đã dùng nghiệm thu;
- tối thiểu 30 reviewed claims;
- review toàn bộ references trong report mẫu;
- baseline manual active time;
- thời gian Researcher nhập scope + Reviewer kiểm tra/sửa;
- phân loại lỗi retrieval/extraction/grounding/synthesis/gap.

Baseline phải lưu metric và lỗi theo version; nếu chưa có số đo chính xác thì
ghi `not_measured`, không suy diễn từ việc test xanh. Các gate tiếp tục giữ:

```text
Reference Validity = 100%
Claim-support Accuracy >= 80%
Median active-human-time reduction >= 50%
```

### G3 — Deployment evidence là hardening, production gate ở V4.1

V1 đã được nghiệm thu vận hành trong phạm vi hiện tại. URL/staging,
health/readiness, restart test, env/secrets setup vẫn nên có trong quá trình mở
V2; SLA, rollback, backup và incident handling là Definition of Done V4.1.

### G4 — Runtime hiện đủ MVP, durable execution thuộc V4.1

FastAPI BackgroundTasks + SQLite/checkpoint SQLite phù hợp phạm vi V1/V2 nhỏ.
Conversation/action phải thiết kế idempotent ngay từ V2; durable queue,
transactional worker claim, Postgres và reconciliation thuộc V4.1.

### G5 — Frontend phải modular trước khi thêm Copilot

UI có các khu vực chức năng nhưng phần lớn type, fetch, state và rendering vẫn
nằm trong `frontend/app/page.tsx`. Trước khi thêm V2 nên tách:

```text
features/reviews
features/evidence
features/gaps
features/reviewer
features/metrics
features/conversations
features/actions
features/ingestion
lib/api
components/layout
```

Mỗi feature dùng typed API client và block component độc lập.

### G6 — Compiled graph/checkpoint E2E đã đóng, phải giữ regression

CI hiện đã có compiled graph/checkpoint E2E. Các test sau phải tiếp tục được giữ:

```text
create job
→ compiled graph
→ HITL interrupt/checkpoint
→ approve
→ final persisted approved result
```

và:

```text
request changes
→ revise
→ validate
→ resume/finalize
```

Test này phải có timeout rõ để không treo CI.

Kết quả kiểm tra tại thời điểm cập nhật tài liệu:

```text
ruff check src tests                                      → pass
pytest tests                                               → 113 passed
frontend TypeScript check                                 → pass
checkpoint pause/resume approve/request-changes           → pass
```

Checkpoint test dùng cùng `uvloop` runtime mà `uvicorn[standard]` chọn trên
Linux; điều này tránh được tình trạng `aiosqlite` worker thread treo trên
Python 3.12 selector loop. Gate kỹ thuật này đã đóng và trở thành regression
gate cho V2–V4.

## 6. Đánh giá chất lượng potential gap hiện tại

V1 đang làm đúng một việc giới hạn:

> Tìm khía cạnh ít/không được nhắc trong abstract của corpus đã chọn.

Nó chưa làm được “research gap của lĩnh vực”. Ví dụ gap “Standardized
Benchmarking for Computational Efficiency” chỉ có quote nói về so sánh
computational efficiency; từ `standardized` chưa được evidence hỗ trợ mạnh.

Những giới hạn hiện tại:

- corpus thường chỉ 10 abstract;
- không đọc full text;
- không phân biệt rõ unknown/not-reported/extraction-failed;
- không có counterquery nhằm bác bỏ gap;
- Reviewer review gap như claim chung, chưa có gap-specific verdict;
- absence trong abstract không chứng minh absence trong paper/lĩnh vực.

Vì vậy output V1 phải gọi là **Potential Gap / Scope-bound Observation**. Đây là
lý do MVP V2 ưu tiên gap verification thay vì thêm provider ngay.

## 7. Vì sao roadmap cũ không ổn

Roadmap cũ:

```text
V1 OpenAlex abstracts
→ V2 multi-source metadata
→ V3 full-text + RAG
→ V4 data-analysis sandbox
```

Ba vấn đề:

1. Không theo thứ tự giá trị của đề bài: nhánh data analysis bị trì hoãn cuối.
2. Thêm nguồn/RAG trước khi gap logic có facet, unknown state và countersearch.
3. Mỗi version được định nghĩa theo công nghệ, không theo giả thuyết cần kiểm
   chứng và outcome của người dùng.

Roadmap trung gian chỉ thêm evidence/gap UI ở V2 cũng chưa đủ: người dùng cần
thảo luận, bổ sung scope và yêu cầu tìm thêm ngay trong quá trình nghiên cứu.
Vì vậy V2 được định nghĩa lại thành Research Copilot có governed tool calling;
evidence workspace và gap verification là structured workspace phía sau chat.

Thêm dữ liệu không tự động làm claim/gap chính xác. Vector database cũng không
sửa được state machine, semantics hay reviewer workflow.

## 8. Roadmap mới

### MVP V1 — Grounded Literature Review

Mục tiêu:

> Từ topic, tạo evidence map từ 10–20 OpenAlex abstracts, kiểm tra grounding và
> dừng cho Reviewer.

Trạng thái: **đã được chủ dự án nghiệm thu**. Từ đây V1 là research engine ổn
định; chỉ nhận bug/security fix và phải tiếp tục pass regression khi V2–V4 gọi
lại các capability search, extraction, grounding và review.

Chi tiết: [README_MVP_V1.md](README_MVP_V1.md).

### MVP V2 — Conversational Evidence Workspace và Gap Verification

Mục tiêu:

> Research Copilot thảo luận trên project evidence, gọi tool có kiểm soát, gọi
> lại V1 khi thiếu tài liệu và kiểm chứng candidate gap trước khi đề xuất research
> question.

Thành phần chính:

- trusted identity/project scope tối thiểu;
- Conversation Orchestrator, Context Resolver và Citation Validator;
- backend CapabilitySnapshot khóa data stage và allowed tool set mỗi turn;
- grounded chat trên report/evidence hiện có;
- Session/Project/Evidence Memory có typed payload, TTL, stale và lineage;
- read-only tools và mutating tools có confirmation;
- search refinement gọi lại V1 engine;
- SearchRun và ReportVersion lineage;
- summary từng paper;
- research-facet comparison matrix;
- present/not_reported/unknown/extraction_failed;
- gap taxonomy/lifecycle;
- bounded countersearch;
- gap-specific review;
- suggested research question chỉ từ approved gap;
- selective full-text ingestion có license/parse/locator validation;
- Reviewer notification → Copilot explanation → Researcher-confirmed action;
- Reviewer decision không phải LLM tool; feedback có revise/narrow/discard lineage;
- frontend feature blocks.

Release theo V2.1 Grounded Chat → V2.2 Tool Calling → V2.3 Gap Verification →
V2.4 Selective Full Text. Knowledge graph là optional feature gate, không phải
Definition of Done mặc định.

Chi tiết: [README_MVP_V2.md](README_MVP_V2.md).

### MVP V3 — Conversational Data Analysis và Safe Sandbox

Mục tiêu:

> Mở rộng cùng Research Copilot bằng analysis tools: upload/profile dữ liệu,
> thảo luận và duyệt plan, chạy code an toàn, validate và tái lập kết quả.

Thành phần chính:

- CSV/XLSX/Parquet upload trực tiếp qua Dataset API rồi profile bằng action;
- Copilot clarification trên research question/profile;
- method/assumption plan;
- action confirmation + plan approval;
- code policy + isolated sandbox;
- structured outputs/statistical validation;
- AnalysisCitation riêng cho numeric/result provenance;
- plan/result decision chỉ qua review API, không phải Copilot tool;
- result review/reproducibility bundle.

Không tạo chatbot hoặc conversation store thứ hai. AnalysisGraph tách khỏi
ReviewGraph/GapGraph nhưng được điều phối qua cùng Conversation Orchestrator và
tool policy V2.

Chi tiết: [README_MVP_V3.md](README_MVP_V3.md).

### MVP V4 — Production Research Copilot và Advanced Retrieval

Mục tiêu:

> Production hóa Copilot, tool ecosystem và hai workflow cho nhiều project/user;
> chỉ scale multi-source/full-text RAG khi metric chứng minh cần thiết.

Thành phần chính:

- V4.1: AuthN/AuthZ production, project dashboard và reviewer assignment;
- V4.1: Postgres, durable tool workers, object storage;
- V4.1: conversation/action/tool audit, quota và cancellation;
- monitoring, backup/restore/deletion/incident handling;
- versioned evaluation, RAGAS bổ sung và controlled time study;
- V4.2: gated multi-source metadata;
- V4.3: selective full text V2 được scale thành durable ingestion;
- V4.4: evaluated Qdrant/retrieval/reranker;
- V4.4: provenance-preserving map-reduce;
- Qdrant/queue/storage là implementation, không expose thành LLM tool;
- cost/latency/model-route audit.

Chi tiết: [README_MVP_V4.md](README_MVP_V4.md).

## 9. Kiến trúc mục tiêu

```text
RESEARCH PROJECT
│
├─ Research Copilot (V2)
│    ├─ Conversation Orchestrator
│    ├─ Context/Citation/Action services
│    └─ Governed Tool Registry
│
├─ LiteratureReviewGraph (V1 research engine)
│    └─ GapVerificationGraph (V2)
│
├─ AnalysisGraph (V3)
│    └─ Sandbox Runtime
│
└─ Shared Platform (V4)
     ├─ Identity/RBAC
     ├─ Project/Audit
     ├─ Durable Jobs
     ├─ Model Gateway
     ├─ Academic/Ingestion Gateway
     ├─ Conversation/Tool Audit
     ├─ Evaluation/Usage
     └─ Storage/Monitoring
```

Nguyên tắc chung:

- structured artifacts là source of truth;
- conversation chỉ là interface/orchestration, không là source of truth;
- claim/result phải trace về evidence/output thật;
- mọi loop bounded;
- read-only tool và mutating/execution tool có policy khác nhau;
- mutation/execution cần confirmation và backend authorization;
- mọi mutation authorized + idempotent;
- mọi model/provider/schema/prompt version được audit;
- Reviewer chịu trách nhiệm quyết định cuối.

## 10. KPI theo từng version

### V1 Literature

```text
Reference Validity
Claim-support Accuracy
Claim/Reference Review Coverage
Active-human-time Reduction
Reviewer Acceptance
```

### V2 Copilot/Gap/Selective Full Text

```text
Factual Answer Citation Coverage
Citation/Evidence Accuracy
Unsupported Factual Answer Rate
Action Proposal Accuracy
Unconfirmed Mutation Rate
Search Refinement Yield
Facet Coverage / Unknown Rate
Gap Precision
Counterevidence Hit Rate
Gap Reviewer Acceptance
Gap Active Review Time
Full-text Parse / Evidence Locator Accuracy
```

### V3 Analysis

```text
Schema/Profile Accuracy
Method Appropriateness
Numeric Correctness
Reproducibility
Unsafe-code Rejection / Escape Rate
Interpretation Accuracy
Unconfirmed Execution Rate
Numeric Answer Provenance Coverage
Active-human-time Reduction
```

### V4 Platform/Retrieval

```text
Authorization/Isolation Failures
Job Durability / Recovery
Retrieval Recall@K
Evidence Locator Accuracy
Full-text Parse Success
Coverage Gain / Dedup Precision
Cost / Latency / Availability
Tool Permission / Idempotency / Cancellation
Cross-version Quality Regression
```

RAGAS không thay thế claim/reference/gap/numeric checks của Reviewer hoặc gold
set. Mục tiêu giảm 50% phải đo **active human time**, không so agent runtime với
manual effort.

## 11. Việc cần làm ngay

MVP V1 đã được nghiệm thu. Thứ tự thực tế để bắt đầu V2:

1. Đóng gói artifact/metric nghiệm thu V1 thành regression baseline.
2. Tách frontend theo feature blocks và typed API client.
3. Thêm trusted identity/project scope tối thiểu.
4. Chốt Conversation, ChatCitation, ActionProposal, SearchRun và ReportVersion
   contracts trong technical contract.
5. Làm V2.1 Grounded Chat read-only trên report V1.
6. Làm V2.2 tool calling/confirmation và gọi lại V1 search pipeline.
7. Dùng lỗi thật từ baseline để chốt 4–5 facets, rồi làm V2.3 gap verification.
8. Chỉ sau khi quote/citation chat ổn định mới làm V2.4 selective full text.

Không bắt đầu bằng Qdrant, knowledge graph hoặc thêm provider chỉ để tăng số
lượng công nghệ. Copilot phải pass citation/confirmation/versioning gates trước.

## 12. Định vị sản phẩm

Hiện tại:

> Grounded abstract-based literature review engine đã nghiệm thu, có HITL và
> potential gap giới hạn trong corpus.

Sau V2:

> Research Copilot đồng hành trong project: thảo luận có citation, gọi tool có
> xác nhận, tìm thêm evidence qua V1, đọc selective full text hợp lệ và kiểm
> chứng candidate gap với human decision.

Sau V3:

> Cùng Research Copilot điều phối literature/gap workflow và initial
> data-analysis workflow an toàn, không tạo chatbot silo mới.

Sau V4:

> Production Research Copilot có governed tools, provenance, evaluation và
> advanced retrieval được bật theo bằng chứng, không theo hype công nghệ.
