# Research Agent — MVP V3: LLM Tool Calling & Controlled Data Analysis

> Historical roadmap snapshot ngày 2026-08-05. Repository hiện đã có
> `src/research_sandbox_service/` và sandbox API; các checkbox/số test bên dưới không phản
> ánh acceptance status hiện tại.

> Trạng thái: **Roadmap — chưa triển khai.**
> Kế thừa: [README_MVP_V1.md](README_MVP_V1.md) và [README_MVP_V2.md](README_MVP_V2.md).
> Contract kỹ thuật đầy đủ: [`contracts/contract_v3.md`](../../contracts/contract_v3.md).

---

## 1. Vị trí của V3

Sau V2, sản phẩm có:

```text
Literature review pipeline với grounding và gap detection     ← V1
Research Copilot với project scope, action confirmation,
memory, conversation, citation và reviewer workflow           ← V2
```

V3 hoàn thiện hai điều còn thiếu:

| Track | Tên | Lý do cần làm |
|---|---|---|
| **3A** | LLM Tool Calling | Copilot V2 dùng keyword match, không phải LLM thật. V2 đã có action/audit/capability primitives nhưng chưa có typed executable tool registry và LLM dispatch layer |
| **3B** | Controlled Data Analysis | Nhánh B của đề bài gốc: phân tích dataset thực nghiệm, có plan approval, code sandbox và kết quả tái lập |

V3 không xây chatbot thứ hai. Conversation, ActionProposal, Memory và Audit của
V2 được tái sử dụng sau khi harden; event/status transport phải được hoàn thiện
cho tác vụ dài thay vì giả định JSON polling hiện tại là SSE.

---

## 2. Điều kiện bắt đầu

### Baseline audit code hiện tại (2026-08-05)

- [ ] Full regression suite pass 100%. Core/legacy hiện **121/136 pass**; khi
  gồm suite V2 đang có trong worktree là **154/169 pass**. Cả hai vẫn có 15 lỗi
  ở extraction/synthesis/revise vì test mock chưa cô lập `get_llm_fallbacks()`.
- [x] V2 contract suite hiện có pass **33/33** trên SQLite cô lập. Con số này
  không đồng nghĩa toàn bộ traceability matrix trong contract V2 đã có test.
- [x] ActionProposal state machine, `validate_action_parameters()` và
  `execute_action()` đã tồn tại và có test chính.
- [ ] Typed executable tool registry. Hiện `READ_ONLY_TOOLS`/`MUTATING_TOOLS`
  mới là danh sách tên; chưa có input/output schema và read-tool dispatcher.
- [ ] CapabilitySnapshot read path thuần. Hiện `GET /capabilities` gọi
  `sync_project_versions()` và có thể ghi ReportVersion/gap trong GET.
- [ ] Memory isolation/TTL/stale/supersede có implementation nhưng coverage bắt
  buộc cho expiry, delete, cross-project và dependency stale chưa đầy đủ.
- [ ] Long-running operation contract. Event endpoint hiện là JSON replay,
  chưa phải SSE; chưa có cancellation, total deadline và stuck-job gate.

Các checkbox chưa đạt là release gate cần đóng trước khi gọi Track 3A hoàn tất
hoặc bắt đầu nối sandbox của Track 3B vào Copilot.

### Bắt buộc trước khi bắt đầu 3B

- [ ] Team chốt sandbox strategy: `subprocess` giới hạn resource hay Docker container ephemeral.
- [ ] Team chốt dataset limits: size (≤ 50 MB), format (CSV / XLSX / Parquet), retention.
- [ ] Package allowlist được pin: `pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib`, `seaborn`, `pyarrow`, `openpyxl`.
- [ ] Có ít nhất 2 dataset thực tế của đề bài để làm benchmark.
- [ ] Có người chịu trách nhiệm security review sandbox.
- [ ] Không dùng `exec()` hoặc `eval()` trong FastAPI process.

---

## 3. Track 3A — LLM Tool Calling (hoàn thiện Copilot)

### Mục tiêu

Copilot gọi được tất cả tool trong `allowed_tools` qua LLM function-calling,
không chỉ 2 keyword hardcode (`search_more`, `reviewer_feedback`).

### Phạm vi

**Read-only tools** — LLM tự gọi, trả kết quả ngay trong turn:

```text
get_project_context   list_papers       get_paper
get_claim             get_evidence      compare_papers
list_report_versions  list_memories     list_reviewer_feedback
```

**Mutating tools** — LLM đề xuất, tạo ActionProposal, user phải approve thủ công:

```text
search_more     add_paper       exclude_paper    refine_scope
rerun_grounding countersearch   revise_claim     narrow_claim    discard_claim
```

### Hạ tầng được tái sử dụng

ActionProposal state machine, idempotency, stale check,
`validate_action_parameters()`, Memory, Audit, Conversation, Turn và Citation
được giữ. Tool registry/dispatcher, event/status transport và thời điểm tạo
ReportVersion phải được harden; không coi chúng là đã hoàn chỉnh chỉ vì đã có
tên tool hoặc endpoint.

### Thay đổi bắt buộc

- Trước (V2): keyword match hardcode
- Sau (V3-A): LLM function-calling loop → read-only tools execute ngay; mutating tools tạo ActionProposal
- Fallback về keyword match khi LLM unavailable — backward-compatible
- Mỗi tool có versioned input/output schema, permission, execution class và
  time/cost bound do server đăng ký; model không tự đặt tên tool.
- Read-only dispatcher chỉ đọc active immutable artifacts. Mutating/execution
  dispatcher chỉ có thể tạo ActionProposal, không gọi service nội bộ trực tiếp.
- ReportVersion được materialize khi worker hoàn tất/checkpoint, không lazy-sync
  trong `GET /capabilities`.

### Tác vụ dài và khả năng quan sát

- `GET /capabilities` là read-only, không gọi LLM/network, không tạo version/gap
  và có mục tiêu p95 dưới 500 ms trên database bình thường.
- Request khởi tạo LLM, profiling hoặc sandbox trả `202` cùng
  `operation_id`/`turn_id` trong tối đa 2 giây; worker tiếp tục chạy nền.
- Client theo dõi qua status endpoint và event replay có sequence. Nếu quảng bá
  SSE thì response phải thực sự dùng `text/event-stream`; JSON polling không
  được gọi là SSE.
- Operation lưu `stage`, progress, provider attempt đã redact, deadline,
  terminal error code và hỗ trợ cancel/recovery sau restart.
- Provider fallback có timeout từng attempt và total deadline; không giữ một
  HTTP request mở xuyên suốt nhiều provider attempt.

### Definition of Done 3A

- [ ] Chat invoke `get_paper`, `list_papers`, `get_claim` trả data đúng từ active version.
- [ ] Chat detect `add_paper`, `exclude_paper`, `revise_claim` → ActionProposal đúng parameters.
- [ ] Citation trong answer phải trỏ về `report_version_id` đang active, không tự sinh.
- [ ] LLM unavailable → fallback keyword match, không crash.
- [ ] 0 trường hợp LLM tự gọi mutating tool không qua ActionProposal.
- [ ] `GET /capabilities` không ghi database và không gọi external service.
- [ ] LLM/tool turn dài trả `202`, có status/event/cancel và terminal timeout.
- [ ] Test `test_chat_*` mở rộng, pass 100%.

---

## 4. Track 3B — Controlled Data Analysis (nhánh B đề bài)

### Mục tiêu

Researcher upload dataset → làm rõ research question → nhận analysis plan → duyệt
→ chạy Python trong sandbox → nhận kết quả structured, có thể verify và tái lập.

### Workflow

```text
Upload dataset (CSV/XLSX/Parquet ≤ 50 MB)
  → MIME/signature/schema validation
  → Dataset profiling: missing, duplicate, type, outlier
  → Copilot làm rõ research question (outcome, group, design, hypothesis)
  → Tạo AnalysisPlan (method, assumptions, limitations, expected output schema)
  → Human plan approval       ← checkpoint 1 — KHÔNG chạy code nếu chưa approve
  → Generate Python từ approved plan + package allowlist
  → Static AST/policy check (no network, no secrets, no shell)
  → Execute sandbox            ← không exec trong FastAPI process
  → Structured output validation + statistical check
  → Human result review        ← checkpoint 2 — kết quả kỹ thuật ≠ kết luận khoa học
  → ReproducibilityBundle: code_hash + input_hash + output_hash
```

### CapabilitySnapshot extension (merge với V2, không thay thế)

```python
AnalysisDataStage = Literal[
    "no_dataset", "dataset_staged", "profile_ready", "question_incomplete",
    "plan_draft", "plan_review_waiting", "plan_approved", "run_queued",
    "run_running", "run_unvalidated", "result_review_waiting",
    "result_approved", "result_rejected",
]
```

| Stage | Copilot được làm |
|---|---|
| `no_dataset` | hướng dẫn upload; không suy đoán số liệu |
| `profile_ready` | giải thích schema/quality; làm rõ research question |
| `question_incomplete` | hỏi outcome/group/covariate/design |
| `plan_draft` | giải thích assumptions/method; đề nghị review |
| `plan_approved` | tạo execution ActionProposal; cần confirm để chạy |
| `result_approved` | giải thích bằng `AnalysisCitation` đã validate |

### Analysis tools đăng ký vào ActionProposal registry V2

Không đổi state machine, confirmation, idempotency, audit rules.

```python
AnalysisActionType = Literal[
    "request_dataset_profile", "update_research_question",
    "create_or_revise_analysis_plan", "generate_code", "execute_sandbox",
    "rerun_analysis", "request_code_revision", "delete_dataset",
]
```

### Giới hạn ban đầu

- 1 dataset per run; ≤ 50 MB sau upload.
- Dữ liệu non-sensitive (không có PHI/PII).
- Methods: descriptive statistics, group comparison, correlation, kiểm định cơ bản, baseline prediction.
- CPU only; 1 lần code revision cho lỗi recoverable.
- Package/version pin sẵn trong image — không `pip install`.

### Roadmap hardening + 3 sprint

**Sprint 0 — V2 hardening cho V3-A**

```text
Typed ToolDefinition registry + dispatcher
Pure CapabilitySnapshot read model
Worker-completion materialization cho ReportVersion
Operation status/event/cancel + provider total deadline
Full regression suite xanh
```
Gate: không có GET side effect; request dài không treo connection; V1/V2 suite
pass 100% trước khi nối analysis execution.

**Sprint 1 — Dataset & Profiling (2 tuần)**

```text
POST /api/v1/projects/{id}/datasets         ← upload, validate MIME + schema
GET  /api/v1/datasets/{id}/profile          ← DatasetProfile artifact (immutable)
Profiling engine: pandas profiling, no LLM
Stage: no_dataset → dataset_staged → profile_ready
```
Gate: upload CSV → profile trong < 30s, không crash server.

**Sprint 2 — Research Question & Analysis Plan (2 tuần)**

```text
Copilot clarification (objective, outcome_columns, group, design)
POST /api/v1/datasets/{id}/analysis-plans   ← AnalysisPlan draft
POST /api/v1/analysis-plans/{id}/review     ← Human plan approval
Stage: question_incomplete → plan_draft → plan_approved
```
Gate: researcher điền xong question → system đề xuất plan → approve/reject được.

**Sprint 3 — Sandbox & Result (3-4 tuần)**

```text
Code generation từ approved plan + allowlist template
Static AST check (no network, no secrets, no shell, no pip)
Sandbox execution (subprocess giới hạn resource hoặc Docker ephemeral)
Output validation: JSON schema, statistical checks, no NaN/Inf leak
ReproducibilityBundle: code + input + output hash
Result review flow (tái dùng ReviewerFeedback V2)
```
Gate: 1 approved plan → code chạy được → result có thể reproduce.

---

## 5. Ngoài phạm vi V3

- PHI/PII hoặc dữ liệu restricted production.
- Causal inference tự động; chẩn đoán/tư vấn high-stakes.
- GPU / distributed training.
- Shell, system package manager hoặc `pip install` trong sandbox.
- Agent tự tải data từ Internet khi chạy.
- Multi-dataset cùng lúc.
- Kết luận khoa học cuối không qua Reviewer.
- Multi-source metadata, full-text ingestion, vector retrieval (V4).

---

## 6. Kết nối với V2 — không duplicate

| V2 đã có | V3 dùng như thế nào |
|---|---|
| `ActionProposal` + state machine | Thêm `AnalysisActionType` vào registry |
| `validate_action_parameters()` | Thêm param schema cho analysis actions |
| `execute_action()` | Thêm branch cho `execute_sandbox`, `generate_code` |
| `CapabilitySnapshot` | Extend với `AnalysisCapabilityExtension` |
| Memory với TTL + isolation | Thêm `memory_type` analysis: objective, plan_reference, warning |
| Conversation + turn + citation | `AnalysisCitation` bên cạnh paper citation, không thay thế |
| Audit log + event stream | Dataset/plan/run event qua cùng `event()` |

**Hai provenance tách biệt hoàn toàn:** literature citation chứng minh method/context;
`AnalysisCitation` chứng minh số liệu từ dataset. Không được trộn.

---

## 7. Definition of Done V3

### 3A — LLM Tool Calling

- [ ] LLM function-calling dispatch đúng read-only vs mutating tools.
- [ ] 0 mutating tool call không qua ActionProposal.
- [ ] Citation không tự sinh; phải trỏ về report_version thật.
- [ ] Fallback keyword match khi LLM fail; không crash.
- [ ] Typed tool registry/dispatcher enforce schema, permission và execution class.
- [ ] CapabilitySnapshot là pure read; mọi tác vụ dài chạy qua Operation worker.
- [ ] Operation có status/event/cancel/deadline/restart recovery.

### 3B — Data Analysis

- [ ] AnalysisGraph tách khỏi ReviewGraph.
- [ ] Upload: MIME, signature, schema, size validation.
- [ ] Raw dataset không đi qua LLM prompt.
- [ ] Plan chưa approve → sandbox run không được tạo.
- [ ] Code chạy trong sandbox, không trong FastAPI process.
- [ ] Sandbox: non-root, no network, no secrets, có resource limits.
- [ ] Structured output validated trước khi diễn giải.
- [ ] ReproducibilityBundle đầy đủ (code/input/output hash).
- [ ] 0 `exec()`/`eval()` trong backend.
- [ ] Security suite: escape, fork bomb, network, path traversal = 0.
- [ ] Reproducibility ≥ 95%.
- [ ] AnalysisCitation tách khỏi literature citation.
- [ ] V1/V2 regression suite tiếp tục pass.
