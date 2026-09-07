# Research Agent — MVP V2: Conversational Evidence Workspace và Gap Verification

> Historical roadmap baseline. Project/Copilot, memory, action, gap và
> collaboration capability đã có trong repository ở nhiều mức độ; trạng thái
> hiện tại phải kiểm từ code, migration và test thay vì dòng roadmap cũ.

> Trạng thái: **Roadmap kế tiếp; MVP V1 đã được nghiệm thu.**
> Kế thừa: [README_MVP_V1.md](README_MVP_V1.md) và
> [contracts/contract_v1.md](../../contracts/contract_v1.md).
> Contract triển khai riêng cho V2:
> [contracts/contract_v2.md](../../contracts/contract_v2.md).
> Khi roadmap và mô tả schema/API chi tiết khác nhau, contract MVP2 là source
> of truth cho implementation.
>
> Mục tiêu của V2: xây một **Research Copilot có tool calling và Project
> Memory**, đồng hành lâu dài trên evidence thật, gọi lại research engine V1 khi
> thiếu tài liệu và chỉ đưa research gap đi tiếp sau coverage, counterevidence
> và Reviewer verdict.

## 1. Vị trí của V2

MVP V1 là research engine ổn định:

```text
topic/scope
→ OpenAlex search
→ screening
→ evidence extraction
→ grounding/revision
→ themes/potential gaps
→ HITL
```

MVP V2 không thay research engine bằng một chatbot tự do. V2 thêm lớp tương tác
có trạng thái ở phía trên V1:

```text
Research Copilot
├─ đọc project context và evidence hiện có
├─ nhớ scope, quyết định và việc còn dang dở theo project
├─ trả lời có citation
├─ giải thích claim/theme/gap/warning
├─ đề xuất hành động có cấu trúc
├─ gọi tool V1 sau khi được xác nhận
└─ kiểm chứng candidate gap
```

V2 thành công khi người dùng có thể thảo luận, bổ sung phạm vi, tìm thêm evidence
và kiểm tra gap mà mọi thay đổi vẫn có provenance, version và human control.

## 2. Giả thuyết giá trị

> Một Copilot dựa trên project evidence, có tool calling và action confirmation
> có giúp Researcher hiểu, mở rộng và kiểm chứng review nhanh hơn mà không làm
> giảm Reference Validity hoặc Claim-support Accuracy của V1 hay không?

Chat nhiều không phải metric thành công. V2 phải chứng minh:

- câu trả lời học thuật có nguồn;
- thiếu evidence thì nói thiếu thay vì dùng trí nhớ model để lấp chỗ trống;
- search/refinement do chat khởi tạo vẫn đi qua pipeline V1;
- gap có thể bị narrow, contradicted, reject hoặc kết luận insufficient;
- Reviewer feedback trở thành artifact và hành động rõ ràng cho Researcher.
- Copilot nhớ đúng quyết định đã xác nhận nhưng không biến hypothesis hoặc chat
  summary thành evidence.

## 3. Điều kiện bắt đầu

- MVP V1 đã chạy ổn định tới `hitl_waiting`, approve và request-changes/resume.
- Structured report V1 là source of truth; không còn legacy Markdown schema.
- Search history, decision trace, evidence quote và revision lineage đọc được.
- Baseline/reference artifacts của đợt nghiệm thu V1 được giữ làm regression set.
- Frontend được tách theo feature block và dùng typed API client.
- Có trusted identity/project scope tối thiểu; actor/role không được lấy từ body
  rồi tin cậy trực tiếp.

Không cần production SSO hoặc enterprise RBAC ở V2, nhưng backend phải biết actor
nào sở hữu project, ai được review và không cho Researcher tự review output của
chính mình.

## 4. Phạm vi theo release gate

### V2.1 — Grounded Research Chat và Project Memory

- Conversation gắn với một project và một report version.
- Hỏi đáp trên paper, evidence, claim, theme, gap, warning và reviewer decision.
- Citation bắt buộc cho factual answer về nội dung nghiên cứu.
- So sánh paper dựa trên structured evidence.
- Trả `insufficient_evidence` khi corpus hiện tại không đủ.
- Session Memory cho hội thoại hiện tại và Project Memory cho scope, quyết định,
  reviewer feedback, open questions và công việc còn dang dở.
- Memory chỉ được lưu theo policy; người dùng có thể xem, supersede và xóa.

### V2.2 — Tool Calling và Search Refinement

- Đề xuất thêm/bớt keyword, year, context và inclusion/exclusion criteria.
- Tìm thêm paper, thêm paper theo DOI/OpenAlex ID và rerun validation.
- Gọi các capability ổn định của V1; không gọi node nội bộ tùy ý.
- Mọi mutation hoặc thao tác tốn chi phí đáng kể cần user confirmation.
- Mỗi lần search tạo `SearchRun`; mọi thay đổi có thể làm khác report/evidence
  state đều tạo `ReportVersion`, kể cả khi corpus không đổi.

### V2.3 — Evidence Matrix và Gap Verification

- Summary từng paper dựa trên evidence.
- Comparison matrix theo research facets.
- Candidate gap từ coverage có cấu trúc.
- Một vòng counterevidence search mặc định cho mỗi gap.
- Gap-specific Reviewer decision.
- Suggested research question chỉ từ gap đã được approve/narrow.

### V2.4 — Selective Full Text, capability gate tùy chọn

- Chỉ ingest paper được chọn và có quyền truy cập hợp lệ.
- Parse section/page, lưu evidence span và parser provenance.
- Copilot ưu tiên full text đã validate, fallback về abstract khi cần.
- Không yêu cầu vector database cho corpus nhỏ.

Đây là selective full text phục vụ kiểm chứng và không chặn MVP2 Core
(V2.1–V2.3). Multi-source/full-text RAG ở quy mô nhiều project, Qdrant, reranker
và map-reduce thuộc V4.

## 5. Kiến trúc V2

Không ghép conversation, V1 ReviewGraph và gap logic thành một LangGraph lớn.

```text
Next.js Workspace
├─ Structured Evidence UI
└─ Research Copilot Panel
          │
          ▼
Conversation API
  → Conversation Orchestrator
      ├─ Intent Router
      ├─ Project Context Resolver
      ├─ Memory Policy / Memory Retriever
      ├─ Evidence Retriever
      ├─ Citation Validator
      ├─ Action/Approval Service
      └─ Tool Registry
           ├─ V1 Literature Tools
           ├─ V2 Gap Tools
           └─ Selective Full-text Tools

V1 LiteratureReviewGraph     V2 GapVerificationGraph
          │                             │
          └──── structured artifacts ──┘
```

Conversation chỉ là lớp điều phối. Paper, claim, gap, review và report version
trong database mới là source of truth; chat history không được dùng thay cho
structured project state.

## 6. Context và evidence policy

Thứ tự nguồn Copilot được phép dùng:

```text
1. Full text đã ingest và validate trong project
2. Abstract đã lưu từ academic provider
3. Metadata source đã xác minh
4. Thông tin người dùng cung cấp: hypothesis/search hint
5. Kiến thức chung của model: chỉ dùng đề xuất query, không dùng làm evidence
```

Mỗi factual answer phải trả một trong hai dạng:

```text
grounded_answer + citations + content_scope + limitations
```

hoặc:

```text
insufficient_evidence + reason + optional_action_proposal
```

Thông tin Researcher nhập không tự động trở thành claim. DOI/OpenAlex ID do
người dùng cung cấp phải được source adapter xác minh trước khi paper được thêm.

Mỗi lượt chat nhận `CapabilitySnapshot` do backend tạo, gồm data stage, active
artifact/report version, pending Reviewer feedback và allowed tool set. Khi chưa
có corpus, Copilot chỉ clarify/propose search; khi chỉ có abstract phải nói rõ
phạm vi abstract; khi có full text chỉ được dùng section đã ingest; khi feedback
đang chờ chỉ được giải thích và tạo proposal, không tự mutation. Snapshot phải
lưu `snapshot_schema_version`, `tool_registry_version` và `policy_version`.

### 6.1 Research Memory policy

Bộ nhớ được chia thành bốn lớp:

```text
Session Memory          → ngữ cảnh hội thoại ngắn hạn
Project Memory          → scope, quyết định, open questions, reviewer feedback
Evidence Memory         → structured artifacts bất biến, không do chat tự viết
User Preference Memory  → ngôn ngữ/cách trình bày, chỉ khi opt-in
```

V2 Core chỉ bắt buộc Session Memory và Project Memory. User Preference xuyên
project thuộc V4 sau khi có privacy/retention controls production.

```python
class MemoryItem(TypedDict):
    memory_id: str
    scope: Literal["session", "project"]
    project_id: str
    conversation_id: str | None
    memory_type: Literal[
        "research_scope", "hypothesis", "decision", "reviewer_feedback",
        "open_question", "task", "conversation_summary",
    ]
    content: dict  # phải validate theo typed payload trong contract V2
    source_message_id: str | None
    source_feedback_id: str | None
    evidence_ids: list[str]
    dependency_artifact_ids: list[str]
    dependency_hash: str | None
    report_version_id: str | None
    status: Literal[
        "proposed", "active", "stale", "superseded", "expired", "deleted"
    ]
    created_by: str
    confirmed_by: str | None
    supersedes_memory_id: str | None
    created_at: str
    expires_at: str | None
```

Quy tắc ghi nhớ:

- evidence-backed fact phải có `evidence_ids` và report version;
- scope/preference/decision do người dùng hoặc Reviewer xác nhận;
- hypothesis luôn giữ nhãn `hypothesis`, không được retrieve như fact;
- summary giúp tiết kiệm context nhưng không làm evidence;
- thay đổi tạo memory mới và `superseded` memory cũ, không sửa âm thầm;
- raw full text, API key, secret và dữ liệu nhạy cảm không vào chat memory;
- người dùng có thể xem và xóa memory trong project scope.

Luồng ghi nhớ:

```text
message
→ detect memory candidate
→ MemoryProposal
→ user/reviewer confirmation nếu cần
→ persist versioned MemoryItem
→ retrieve theo project + active report version ở lượt chat sau
```

### 6.2 Trusted identity và project scope tối thiểu

```python
class ProjectMembership(TypedDict):
    project_id: str
    user_id: str
    role: Literal["owner", "researcher", "reviewer"]
    status: Literal["active", "revoked"]
    created_at: str
```

Backend lấy `actor_id` từ trusted auth context, sau đó kiểm tra membership và
capability. Mọi V2 project-scoped request chứa `role`, `user_id`, `actor_id` hoặc
`reviewer_id` phải bị reject; endpoint V1 cũ chỉ giữ tạm trong compatibility
window. V2 dùng opaque HttpOnly server-side session và không cần enterprise SSO,
nhưng phải có `GET /me`, project isolation và audit tối thiểu.

## 7. Tool-calling contract

### Read-only tools — có thể tự gọi

```text
get_project_context
get_current_report
find_relevant_evidence
get_paper
get_claim
compare_papers
get_validation_warnings
get_search_history
get_gap_coverage
get_pending_reviewer_feedback
get_reviewer_decision
retrieve_fulltext_sections   # chỉ khi V2.4 bật
```

### Mutating hoặc costly tools — bắt buộc confirmation

```text
refine_research_scope
search_more_papers
add_paper_by_identifier
exclude_paper
rerun_grounding
create_countersearch
revise_claim
narrow_claim
discard_claim
request_fulltext_ingestion   # chỉ khi V2.4 bật
```

`create_report_version`, ghi Reviewer decision, authorization và audit là
internal service. Chúng không được expose thành generic LLM tool; Reviewer
decision chỉ đi qua Reviewer API có permission và checklist validation.

Tool input/output dùng schema versioned. Tool execution cần:

- `project_id`, authenticated `actor_id` và permission;
- idempotency key cho mutation;
- bounded result/cost/time;
- typed success/failure;
- audit tool, parameters đã redact, runtime route và artifact IDs;
- không cho LLM tự dựng tool name hoặc gọi arbitrary backend function.

Action proposal phải hiển thị query/scope diff, lý do, giới hạn và tác động dự
kiến trước khi Researcher xác nhận.

## 8. Conversation và action contracts

```python
class Conversation(TypedDict):
    conversation_id: str
    project_id: str
    active_report_version_id: str | None
    created_by: str
    status: Literal["active", "archived"]
    created_at: str


class ChatCitation(TypedDict):
    citation_id: str
    project_id: str
    report_version_id: str
    paper_id: str
    evidence_id: str
    content_scope: Literal["abstract", "full_text"]
    section_id: str | None
    page_start: int | None
    quote: str
    source_url: str


class ChatMessage(TypedDict):
    message_id: str
    conversation_id: str
    project_id: str
    report_version_id: str | None
    role: Literal["researcher", "reviewer", "assistant", "system"]
    text: str
    answer_status: Literal[
        "not_applicable", "grounded", "insufficient_evidence", "action_proposed"
    ]
    citation_ids: list[str]
    memory_ids_used: list[str]
    context_artifact_ids: list[str]
    action_proposal_ids: list[str]
    created_at: str


class ActionProposal(TypedDict):
    action_id: str
    project_id: str
    conversation_id: str | None
    base_report_version_id: str | None
    action_type: Literal[
        "refine_scope", "search_more", "add_paper", "exclude_paper",
        "rerun_grounding", "countersearch", "revise_claim", "narrow_claim",
        "discard_claim", "request_fulltext_ingestion"
    ]
    parameters: ActionParameters  # validated mapping theo action_type ở contract V2
    reason: str
    source_feedback_id: str | None
    acceptance_criteria: list[str]
    estimated_impact: EstimatedImpact
    status: Literal[
        "proposed", "approved", "rejected", "stale", "queued", "running",
        "completed", "failed", "cancelled",
    ]
    proposed_by: str
    approved_by: str | None
    approved_at: str | None
    executed_job_id: str | None
    result_report_version_id: str | None
    result_artifact_ids: list[str]
    failure_code: str | None
    created_at: str
```

Conversation summary chỉ giúp tiết kiệm context. Nó không được thay thế message
audit hoặc structured artifacts. Nếu active report version khác
`base_report_version_id`, action chưa chạy phải thành `stale` và được xác nhận
lại; không áp dụng proposal cũ lên state mới.

## 9. Search và report versioning

```python
class SearchRun(TypedDict):
    search_run_id: str
    project_id: str
    purpose: Literal["initial", "refinement", "counterevidence"]
    query: str
    provider: Literal["openalex"]
    retrieved_count: int
    screened_count: int
    included_count: int
    parent_action_id: str | None
    parent_gap_id: str | None
    created_at: str


class ReportVersion(TypedDict):
    report_version_id: str
    project_id: str
    parent_version_id: str | None
    corpus_hash: str
    evidence_state_hash: str
    review_state_hash: str
    search_run_ids: list[str]
    change_summary: str
    created_by: str
    created_at: str
```

UI phải phân biệt `retrieved`, `screened` và `included`. Corpus/report cũ không
được ghi đè âm thầm sau một yêu cầu chat. Search, rerun grounding, gap review,
scope change hoặc reviewer revision đều tạo version mới nếu output thay đổi.

## 10. Selective full-text contract

Có PDF URL không đồng nghĩa Copilot đã đọc được full text. Pipeline bắt buộc:

```text
check availability/license
→ request/confirm ingestion
→ fetch eligible content
→ parse structured sections
→ validate parse quality
→ persist content + provenance
→ retrieve relevant spans
→ validate quote/locator
```

```python
class IngestionJob(TypedDict):
    ingestion_id: str
    project_id: str
    paper_id: str
    source_record_id: str
    source_url: str
    license: str | None
    requested_by: str
    approved_by: str | None
    status: Literal[
        "requested", "approved", "fetching", "parsing", "parsed", "failed",
        "restricted", "deleted",
    ]
    content_hash: str | None
    parser_version: str | None
    retention_until: str | None
    error_code: str | None
    created_at: str


class PaperSection(TypedDict):
    section_id: str
    ingestion_id: str
    paper_id: str
    title: str | None
    section_type: str
    section_order: int
    page_start: int | None
    page_end: int | None
    text_hash: str


class EvidenceSpan(TypedDict):
    evidence_id: str
    paper_id: str
    ingestion_id: str | None
    content_scope: Literal["abstract", "full_text"]
    section_id: str | None
    section_type: str | None
    page_start: int | None
    page_end: int | None
    quote: str
    source_url: str
    content_hash: str
    parser_version: str | None
```

Nếu parse lỗi, restricted hoặc quote/locator không hợp lệ, Copilot phải fallback
về abstract và hiển thị limitation. Không vượt paywall, không tự suy ra quyền
lưu trữ và không tạo page number giả.

## 11. Research facets và gap contract

Baseline V2.3 chỉ triển khai 4–5 facet có giá trị cao trước:

```text
context_or_population
method
dataset_or_sample
evaluation_metric
limitation_or_future_work
```

Có thể mở rộng `study_design`, `comparator`, `main_finding` sau khi baseline đủ
chất lượng. Mỗi observation có trạng thái:

```python
FacetStatus = Literal[
    "present", "not_reported", "unknown", "not_applicable", "extraction_failed"
]
```

`not_reported` chỉ nghĩa là không thấy trong content scope đã kiểm tra; không có
nghĩa là vắng mặt trong toàn paper hoặc toàn lĩnh vực.

```python
class FacetObservation(TypedDict):
    observation_id: str
    paper_id: str
    report_version_id: str
    facet: str
    value: str | None
    status: FacetStatus
    evidence_ids: list[str]
    content_scope: Literal["abstract", "full_text"]
    extractor_version: str


GapStatus = Literal[
    "candidate", "countersearching", "contradicted", "partially_supported",
    "supported_in_searched_corpus", "insufficient_coverage",
    "reviewer_approved", "reviewer_narrowed", "reviewer_rejected",
]


class GapCandidate(TypedDict):
    gap_id: str
    project_id: str
    report_version_id: str
    gap_type: Literal[
        "population", "context", "methodological", "dataset", "evaluation",
        "contradiction", "replication", "temporal",
    ]
    scoped_statement: str
    status: GapStatus
    corpus_size: int
    present_count: int
    not_reported_count: int
    unknown_count: int
    source_scope: Literal["openalex"]
    content_scope: Literal["abstract", "full_text", "mixed"]
    supporting_observation_ids: list[str]
    counterevidence_paper_ids: list[str]


class GapDecision(TypedDict):
    gap_id: str
    report_version_id: str
    reviewer_id: str
    verdict: Literal["approve", "narrow", "reject", "request_more_evidence"]
    revised_statement: str | None
    note: str
    reviewed_at: str
```

Candidate gap chỉ được tạo khi:

1. Mỗi paper có FacetObservation hoặc explicit unknown/failed state.
2. Không coi unknown/extraction_failed là absent.
3. Statement ghi source, query, corpus size và content scope.
4. Evidence quote/locator hợp lệ.
5. Không dùng wording tuyệt đối như “chưa ai” hoặc “không tồn tại nghiên cứu”.
6. Candidate qua countersearch trước khi được đề nghị approve.

Gap lifecycle:

```text
candidate
→ countersearching
→ contradicted / partially_supported / supported_in_searched_corpus / insufficient
→ reviewer_approved / reviewer_narrowed / reviewer_rejected
```

Wording hợp lệ:

> Trong 10 paper thuộc corpus OpenAlex cho truy vấn X, một paper có nội dung đã
> kiểm tra đề cập trực tiếp Y; countersearch Z chưa tìm thêm evidence trong phạm
> vi đã kiểm tra.

## 12. Reviewer và notification flow

Reviewer xem evidence, coverage, countersearch, warnings và revision history.
Sau review, hệ thống gửi thông báo có cấu trúc cho Researcher/Copilot:

```text
Reviewer decision
→ Copilot giải thích verdict và việc cần làm
→ đề xuất action tương ứng
→ Researcher xác nhận
→ tool chạy
→ artifact/report version mới
```

Reviewer feedback không được chatbot tự diễn giải thành thay đổi rồi chạy ngay.
Quyết định gốc, actor, thời gian và note phải được giữ nguyên trong audit.
Schema `ReviewerFeedback`, mapping verdict → action, stale handling và test loop
được khóa trong [contract V2, mục 14](../../contracts/contract_v2.md).

Knowledge graph là capability tùy chọn sau V2.3. Chỉ xây khi có use case rõ cho
paper–method–dataset–metric–claim relations và metric chứng minh graph cải thiện
navigation hoặc discovery; không đưa vào Definition of Done mặc định.

## 13. Frontend feature blocks

```text
ProjectHeader
ConversationPanel
ProjectMemoryPanel
MemoryProposalCard
GroundedAnswerCard
CitationDrawer
ActionProposalCard
SearchStrategyPanel
PaperLibrary
PaperSummaryCard
FacetComparisonMatrix
CandidateGapList
GapCoverageDrawer
CountersearchTrace
GapReviewPanel
ReportVersionHistory
ResearchQuestionPanel
```

Chat là lớp điều khiển/giải thích. Evidence table, matrix, code-like trace và
review form vẫn là UI có cấu trúc; không biến toàn bộ sản phẩm thành một ô chat.

## 14. API dự kiến

```http
GET  /api/v1/me
POST /api/v1/auth/session
DELETE /api/v1/auth/session
POST /api/v1/projects
GET  /api/v1/projects/{project_id}
GET  /api/v1/projects/{project_id}/members
GET  /api/v1/projects/{project_id}/capabilities
POST /api/v1/projects/{project_id}/reviews

POST /api/v1/projects/{project_id}/conversations
GET  /api/v1/conversations/{conversation_id}/messages
POST /api/v1/conversations/{conversation_id}/messages
POST /api/v1/action-proposals/{action_id}/approve
POST /api/v1/action-proposals/{action_id}/reject
POST /api/v1/action-proposals/{action_id}/cancel
GET  /api/v1/projects/{project_id}/report-versions

GET    /api/v1/projects/{project_id}/memories
POST   /api/v1/projects/{project_id}/memories/{memory_id}/confirm
POST   /api/v1/projects/{project_id}/memories/{memory_id}/supersede
DELETE /api/v1/projects/{project_id}/memories/{memory_id}
GET    /api/v1/projects/{project_id}/review-feedback

GET  /api/v1/reviews/{job_id}/comparison-matrix
GET  /api/v1/reviews/{job_id}/gaps
POST /api/v1/gaps/{gap_id}/countersearch
POST /api/v1/gaps/{gap_id}/review
GET  /api/v1/gaps/{gap_id}/research-question

POST /api/v1/papers/{paper_id}/ingestions
GET  /api/v1/ingestions/{ingestion_id}
GET  /api/v1/papers/{paper_id}/sections
```

Streaming có thể dùng SSE cho message/job progress; WebSocket không phải điều
kiện MVP. Mutation cần idempotency key và backend authorization.

## 15. Metrics và release gates

V2 giữ toàn bộ metric V1 và bổ sung:

```text
Factual Answer Citation Coverage
Citation/Evidence Accuracy
Unsupported Factual Answer Rate
Intent/Action Proposal Accuracy
Unconfirmed Mutation Rate
Memory Write Precision / Stale Memory Rate
Search Refinement Yield
Facet Coverage / Unknown Rate
Gap Precision
Counterevidence Hit Rate
Gap Reviewer Acceptance
Active Review Time
Selective Full-text Parse/Locator Accuracy (chỉ V2.4)
```

Ngưỡng nghiệm thu ban đầu:

- Reference Validity = 100%;
- Claim-support Accuracy không hồi quy so với baseline V1;
- factual answer citation coverage = 100%;
- citation trỏ sai paper/evidence = 0 trên gold conversation set;
- unconfirmed mutation = 0;
- evidence-backed memory thiếu evidence/version = 0;
- hypothesis được retrieve như fact = 0;
- stale action áp dụng lên report version mới = 0;
- mọi approved gap có 100% corpus coverage record;
- 0 approved gap dùng wording tuyệt đối;
- Gap precision >= 70% trên gold set ban đầu;
- 100% research question truy về gap đã approved/narrowed;
- khi V2.4 bật: full-text quote/locator mismatch = 0 trên content đã chấp nhận.

## 16. Test bắt buộc

Conversation/tooling:

- câu trả lời factual không citation bị reject hoặc chuyển insufficient;
- citation ngoài active project/report version bị reject;
- model knowledge không được persist thành evidence;
- read-only tool không làm thay đổi state;
- mutation chưa confirm không chạy;
- confirm lặp lại không tạo duplicate SearchRun/job;
- tool timeout/provider failure trả typed status và không làm hỏng conversation;
- Researcher/Reviewer không gọi tool ngoài project permission.
- message/citation luôn gắn report version bất biến;
- stale action không chạy cho đến khi được xác nhận lại.

Memory:

- hypothesis không được dùng như evidence;
- memory proposal chưa confirm không trở thành active decision/scope;
- supersede giữ lineage, không sửa memory cũ;
- memory ngoài project không retrieve được;
- delete/retention loại memory khỏi retrieval;
- conversation summary sai không được ghi đè structured artifact.

Search/versioning:

- refinement tạo SearchRun và ReportVersion mới;
- retrieved/screened/included được phân biệt;
- paper mới phải qua dedup, extraction và grounding;
- report cũ vẫn mở/audit được;
- action/corpus/report lineage đầy đủ.

Gap; bổ sung full-text suite khi V2.4 bật:

- unknown không bị tính thành absent;
- countersearch bounded và lưu trace;
- contradicted gap không thể approve nếu chưa narrow/review lại;
- restricted/parse-failed content fallback abstract;
- quote/section/page mismatch bị reject;
- research question không sinh từ gap chưa duyệt.

Toàn bộ V1 graph/API/grounding/regression tests phải tiếp tục pass.

## 17. Definition of Done

### MVP2 Core — V2.1 đến V2.3

- [ ] Copilot trả lời trên project evidence và có citation bắt buộc.
- [ ] Backend CapabilitySnapshot khóa cách trả lời/tool theo data stage mỗi turn.
- [ ] Session/Project Memory có typed payload, TTL, confirmation, lineage và quyền xóa.
- [ ] Hypothesis/summary không được dùng như evidence-backed fact.
- [ ] Thiếu evidence trả insufficient + proposal, không bịa câu trả lời.
- [ ] Tool registry phân biệt read-only và mutation/costly action.
- [ ] Mutation chỉ chạy sau confirmation, authorized và idempotent.
- [ ] Search/refinement gọi lại V1 engine và tạo report version mới.
- [ ] Message/citation/action gắn immutable report version; stale action bị chặn.
- [ ] Conversation không trở thành source of truth thay structured artifacts.
- [ ] Facet matrix phân biệt present/not_reported/unknown/failed.
- [ ] Candidate gap có coverage, countersearch và Reviewer verdict riêng.
- [ ] Reviewer feedback được thông báo, giải thích và chuyển thành proposal.
- [ ] Reviewer decision không là LLM tool; feedback mutation cần Researcher confirm.
- [ ] Frontend tách thành feature blocks; chat không thay evidence/review UI.
- [ ] Metric Copilot/memory/gap được đo trên gold set; V1 không hồi quy.

### V2.4 Optional gate — Selective Full Text

- [ ] Ingestion có source/license/approval/status/retention audit.
- [ ] Parse section/page và EvidenceSpan có provenance.
- [ ] Restricted/failed content fallback abstract và hiển thị limitation.
- [ ] Quote/locator mismatch = 0 trên eligible full-text gold set.

MVP2 Core được nghiệm thu mà không phụ thuộc V2.4. Chỉ tuyên bố hỗ trợ full text
khi toàn bộ gate V2.4 đã đạt.

## 18. Ngoài phạm vi

- chatbot trả lời tự do không dựa trên project evidence;
- agent tự chạy mutation hoặc search loop vô hạn;
- kết luận gap đúng cho toàn bộ lĩnh vực;
- nhiều academic provider mặc định;
- full-text RAG quy mô lớn, Qdrant/reranker/map-reduce;
- data upload và code sandbox;
- enterprise SSO, billing hoặc real-time collaborative editing;
- cross-project personal memory trước khi có privacy controls production;
- knowledge graph bắt buộc chỉ để tăng số lượng công nghệ.

Nếu V2 chỉ thêm một ô chat gọi LLM mà chưa có project context, citations, tool
policy, confirmation, versioning và gap verification, nó vẫn là chatbot thông
thường và **chưa đạt MVP V2**.
