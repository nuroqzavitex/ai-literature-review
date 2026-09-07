# Backend Technical Design — Corpus Curation & Scientific Recombination Graph

> Trạng thái: **Proposal để triển khai; chưa được wiring vào runtime hiện tại.**
>
> Phạm vi: mở rộng backend hiện tại, không viết lại V1/V2
>
> Stack khóa: **FastAPI + LangGraph + PostgreSQL + Qdrant + OpenAlex + LLM có structured output**
>
> Tài liệu ý tưởng nguồn: [SCIENTIFIC_RECOMBINATION_GRAPH_CONCEPT.md](SCIENTIFIC_RECOMBINATION_GRAPH_CONCEPT.md)

---

## 0. Đọc phần này trước — hệ thống hoạt động như thế nào?

Phần này giải thích kiến trúc bằng ngôn ngữ sản phẩm. Các phần sau mới là
contract kỹ thuật để dev triển khai.

### 0.1 Bốn khái niệm dễ bị nhầm

| Khái niệm | Hiểu đơn giản | Trong project này |
|---|---|---|
| Knowledge Graph | Bản đồ các thực thể và quan hệ | Paper, Model, Dataset, Task, Finding, Limitation và edge giữa chúng |
| PostgreSQL | Nơi lưu dữ liệu chuẩn | Lưu entity, edge, evidence, version, review và trạng thái job |
| Qdrant | Công cụ tìm đoạn văn gần nghĩa | Tìm abstract/chunk liên quan đến câu hỏi hoặc candidate |
| GraphRAG | Cách lấy context từ graph + evidence rồi mới hỏi LLM | Trả lời câu hỏi theo quan hệ nhiều bước và vẫn có citation |

GraphRAG không phải một database mới. Nó là **quy trình retrieval** sử dụng cả
đồ thị trong PostgreSQL và semantic search trong Qdrant.

```text
PostgreSQL                         Qdrant
-----------                        ------
Ai liên kết với ai?                Đoạn nào gần nghĩa với câu hỏi?
Edge nào được xác thực?            Evidence nào nên được đọc trước?
Fact thuộc graph version nào?      Chunk nào có semantic score cao?
          │                           │
          └───────────┬───────────────┘
                      ▼
                   GraphRAG
                      ▼
             LLM trả lời có citation
```

### 0.2 Từ paper thành đồ thị

Giả sử corpus có paper `P1` với abstract nói:

> Nghiên cứu sử dụng BERT cho Question Answering và đánh giá trên SQuAD.

Extraction tạo các entity:

```text
P1                  type=PAPER
BERT                type=MODEL
SQuAD               type=DATASET
Question Answering  type=TASK
```

Sau đó tạo edge:

```text
                    ┌── USES ────────────> BERT
Paper P1 ───────────┼── EVALUATES_ON ────> SQuAD
                    └── ADDRESSES ───────> Question Answering
```

Mỗi edge không chỉ có tên quan hệ. Nó luôn đi kèm evidence:

```text
P1 --USES--> BERT
  ├─ paper_id: paper_p1
  ├─ chunk_id: chunk_p1_abstract
  ├─ quote: "...uses BERT for question answering..."
  ├─ confidence: 0.96
  └─ exact_match_valid: true
```

Trong PostgreSQL, hình trên được lưu gần giống:

```text
scientific_entities
  entity_p1     PAPER    P1
  entity_bert   MODEL    BERT
  entity_squad  DATASET  SQuAD
  entity_qa     TASK     Question Answering

scientific_edge_assertions
  entity_p1  USES          entity_bert
  entity_p1  EVALUATES_ON  entity_squad
  entity_p1  ADDRESSES     entity_qa
```

Vì vậy PostgreSQL vẫn có thể chứa một graph: node nằm trong bảng entity, edge
nằm trong bảng relationship. Neo4j chỉ là một cách lưu chuyên dụng khác, chưa
cần ở giai đoạn đầu.

### 0.3 RAG thường và GraphRAG khác nhau thế nào?

RAG thường:

```text
Câu hỏi
  → Qdrant tìm các đoạn gần nghĩa
  → đưa top chunks cho LLM
  → câu trả lời
```

RAG thường phù hợp với câu hỏi có câu trả lời nằm trực tiếp trong một vài đoạn
văn. Nhưng nó không hiểu chắc chắn chuỗi quan hệ giữa nhiều paper.

GraphRAG trong project:

```text
Câu hỏi
  → nhận diện entity/ý định
  → tìm seed entity
  → đi qua graph 1–2 hop trong PostgreSQL
  → lấy evidence của các edge
  → dùng Qdrant tìm thêm chunk liên quan
  → rerank + đóng gói context
  → LLM tổng hợp
  → citation validator
  → câu trả lời + đường graph + nguồn
```

Ví dụ người dùng hỏi:

> Những dataset nào đã được dùng để đánh giá các model giải quyết Question
> Answering và kết quả chính là gì?

GraphRAG thực hiện:

```text
Question Answering
  ← ADDRESSES ─ Paper P1 ─ EVALUATES_ON → SQuAD
                  │
                  ├─ USES → BERT
                  └─ REPORTS_FINDING → Finding F1

Question Answering
  ← ADDRESSES ─ Paper P2 ─ EVALUATES_ON → Natural Questions
                  │
                  ├─ USES → RoBERTa
                  └─ REPORTS_FINDING → Finding F2
```

Sau đó LLM chỉ được tổng hợp từ `P1`, `P2`, `F1`, `F2` và evidence quote đã
retrieve. Câu trả lời phải hiển thị citation về paper/chunk tương ứng.

### 0.4 GraphRAG được dùng ở đâu trong sản phẩm?

GraphRAG có bốn cách dùng chính:

#### A. Hỏi đáp trên project

```text
"BERT đã được đánh giá trên dataset nào?"
"Paper nào báo cáo limitation về dữ liệu nhỏ?"
"Finding nào dùng Accuracy làm metric?"
```

Đây là phần Research Copilot dùng GraphRAG thay vì chỉ vector RAG.

#### B. So sánh có cấu trúc

```text
So sánh BERT và RoBERTa
  → paper nào dùng từng model
  → dataset/task tương ứng
  → metric/finding
  → evidence cho từng ô trong bảng
```

#### C. Giải thích candidate

Khi Combination Engine sinh `BERT × MedQA × Medical QA`, GraphRAG lấy các path
hỗ trợ để giải thích:

```text
BERT đã được dùng cho QA ở các paper nào?
MedQA hỗ trợ task nào?
Có method/model tương tự đã chạy trên MedQA không?
Có limitation/counterevidence nào liên quan không?
```

#### D. Novelty và counterevidence retrieval

GraphRAG tìm trong graph hiện tại trước. Sau đó Validation Pipeline mới search
OpenAlex/external candidate pool để kiểm tra liệu công trình trực tiếp đã tồn
tại ngoài corpus hay chưa.

GraphRAG **không tự chứng minh novelty toàn cầu**, vì graph chỉ biết dữ liệu đã
được ingest.

### 0.5 GraphRAG không thay Combination Engine

Hai thành phần có nhiệm vụ khác nhau:

```text
GraphRAG
  └─ trả lời và lấy evidence từ graph

Combination Engine
  └─ duyệt cấu trúc graph để sinh missing-combination candidate

Validation Pipeline
  └─ cố gắng bác bỏ candidate bằng existing work/counterevidence
```

Ví dụ:

```text
Graph hiện có:

Paper P1 → USES BERT
Paper P1 → EVALUATES_ON SQuAD
Paper P1 → ADDRESSES QA

Paper P2 → USES RoBERTa
Paper P2 → EVALUATES_ON MedQA
Paper P2 → ADDRESSES QA

Combination Engine nhìn thấy:
  BERT đã dùng cho QA
  MedQA đã dùng cho QA
  Chưa thấy paper trong graph kết hợp BERT + MedQA + QA

Output:
  candidate = BERT × MedQA × QA
  status = generated
```

Candidate này chưa phải research gap. Validation phải tiếp tục:

```text
Novelty search
  ├─ tìm thấy paper BERT + MedQA → EXISTING_WORK_FOUND
  └─ chưa tìm thấy
       → Compatibility check
       → Counterevidence search
       → Scientific value check
       → Reviewer decision
```

### 0.6 Một lượt GraphRAG chi tiết

```text
1. User question
   "Các limitation của RAG trong education liên quan tới dữ liệu là gì?"

2. Query understanding
   intent = compare_findings
   seed types = METHOD, DOMAIN/TASK, LIMITATION
   keywords = RAG, education, data

3. Seed retrieval
   alias/exact lookup PostgreSQL: RAG
   semantic lookup Qdrant: education + data limitation

4. Graph traversal (tối đa 2 hop)
   RAG ← USES ← Paper → HAS_LIMITATION → Limitation

5. Evidence retrieval
   lấy quote của từng USES/HAS_LIMITATION edge
   lấy thêm top chunks đúng project + graph/corpus version

6. Context packing
   loại duplicate, giới hạn token, giữ paper/chunk/edge IDs

7. LLM synthesis
   chỉ dùng context pack; không bổ sung fact từ model memory

8. Grounding validation
   mọi factual sentence phải map tới evidence ID

9. Response
   answer + citations + graph paths + content_scope + limitations
```

Nếu không đủ evidence, response phải là:

```json
{
  "answer_status": "insufficient_evidence",
  "reason": "Project graph has no validated education-related limitation edges",
  "suggested_action": "Run an additional scoped search"
}
```

### 0.7 Người dùng sẽ sử dụng sản phẩm như thế nào?

```text
1. Tạo project và research question
        ↓
2. Khóa inclusion/exclusion criteria
        ↓
3. Chạy search + screening
        ↓
4. Reviewer xử lý các paper MAYBE
        ↓
5. Tạo Included Corpus
        ↓
6. Bấm Build Knowledge Graph
        ↓
7. Xem graph hoặc hỏi Copilot bằng GraphRAG
        ↓
8. Bấm Discover Opportunities
        ↓
9. Xem candidate + supporting paths + counterevidence
        ↓
10. Reviewer approve/reject/narrow candidate
```

Người dùng không cần biết SQL, Qdrant hay LangGraph. UI nên cho họ nhìn thấy:

- paper nào được include/exclude và vì sao;
- node/edge nào được tạo từ paper nào;
- câu trả lời đi qua graph path nào;
- quote nào hỗ trợ edge/câu trả lời;
- candidate đang ở `generated`, `uncertain`, `validated` hay `rejected`;
- giới hạn của corpus và novelty search.

### 0.8 GraphRAG MVP nên giới hạn thế nào?

MVP chỉ cần:

- exact/alias + Qdrant seed retrieval;
- SQL traversal tối đa 2 hop;
- filter bắt buộc theo project và graph version;
- lấy edge evidence từ PostgreSQL;
- Qdrant bổ sung evidence chunks;
- context packing có token budget;
- LLM synthesis có structured citations;
- grounding validator và `insufficient_evidence`.

Chưa cần community detection, global community summary, graph embeddings, GNN
hoặc Neo4j. Những phần đó chỉ xem xét sau khi graph đủ lớn và query 1–2 hop
trên PostgreSQL trở thành bottleneck thực tế.

---

## 1. Mục tiêu

Backend mới biến tập paper thô thành một corpus có phương pháp, sau đó xây
Scientific Knowledge Graph và phát hiện các research opportunity có thể truy
ngược về evidence gốc.

```text
Research Protocol
  → Identification/Search
  → Deduplication
  → Title/Abstract Screening
  → Full-text Eligibility (feature-gated)
  → Immutable Included Corpus
  → Scientific Extraction
  → Project Knowledge Graph
  → Candidate Recombination
  → Novelty/Compatibility/Counterevidence Validation
  → Human Review
  → Research Opportunity
```

Hệ thống không được kết luận `missing edge = research gap`. Một missing edge
chỉ là candidate trong corpus hiện tại cho tới khi validation và reviewer hoàn
tất.

### 1.1 Kết quả cần đạt

1. Mỗi project có protocol, corpus version và graph version độc lập.
2. Mỗi quyết định include/exclude có stage, lý do, actor/model và audit trace.
3. Mỗi graph edge quan trọng có ít nhất một evidence span exact-match.
4. Qdrant chỉ làm semantic ranking/retrieval; PostgreSQL là source of truth.
5. Candidate luôn gắn với đúng `corpus_version_id` và `graph_version_id`.
6. Khi graph/corpus đổi, candidate cũ không bị ghi đè mà được đánh dấu stale.
7. Reviewer là nguồn duy nhất có quyền publish graph/candidate đã xác thực.

### 1.2 Ngoài phạm vi bản đầu

- Neo4j, RDF store hoặc graph database riêng.
- GNN, graph embedding, learned link prediction.
- Agent tự do có vòng lặp search không giới hạn.
- Tự động tuyên bố PRISMA-compliant hoặc systematic review hoàn chỉnh.
- Thu thập nội dung vượt paywall hoặc không có quyền truy cập.
- Tự động đưa mọi edge do LLM sinh vào shared/global graph.
- Thay thế ReviewGraph, project/auth, report version hoặc reviewer flow hiện có.

---

## 2. Hiện trạng và quyết định kiến trúc

Backend hiện tại đã có:

- `src/agents/graph.py`: ReviewGraph với search, screen, extract, grounding và HITL.
- `src/agents/nodes/litreview.py`: `screen_papers_node` đã hỗ trợ Qdrant ranking
  và lexical fallback.
- `src/services/vector_store.py`: Qdrant là index có thể rebuild, filter theo job.
- `src/services/jobs.py`: LangGraph checkpoint trên PostgreSQL.
- `src/db/models.py` và `supabase/migrations/`: project, report version, gap,
  audit và reviewer artifacts.
- `/api/v1`: API major hiện tại, tiếp tục được giữ.

Thiết kế này giữ ReviewGraph hiện tại cho compatibility và thêm ba workflow
riêng cho flow mới. Corpus curation phải chạy **trước** scientific extraction;
không chạy ReviewGraph xong rồi mới quay lại sàng lọc:

```text
Protocol + OpenAlex adapter
          ↓
CorpusCurationGraph
          │
          │ immutable corpus_version
          ▼
GraphBuildGraph
          │
          │ immutable graph_version
          ▼
DiscoveryGraph
          │
          ▼
Candidate Review / Research Opportunity

Legacy LiteratureReviewGraph ── giữ nguyên trong compatibility window
```

`CorpusCurationGraph` tái sử dụng OpenAlex adapter, Qdrant ranking, LLM routing
và grounding utilities hiện có. Khi cần tạo report truyền thống, một adapter
đọc `corpus_version` có thể cấp đúng included papers cho các bước evidence/
synthesis hiện tại; không gọi lại `screen_papers_node` để cắt corpus lần nữa.

### 2.1 Phân biệt hai loại node

- **Workflow node:** một bước code trong LangGraph, ví dụ
  `extract_relations_node`.
- **Knowledge Graph node/entity:** một thực thể khoa học, ví dụ `BERT`,
  `SQuAD`, `Question Answering`.

Workflow node tạo hoặc cập nhật graph entity/edge trong PostgreSQL. Không phải
mỗi workflow node là một agent.

### 2.2 Source of truth

| Dữ liệu | Nơi lưu chuẩn | Ghi chú |
|---|---|---|
| Project, protocol, search run | PostgreSQL | Không lưu chuẩn trong Qdrant |
| Paper metadata | PostgreSQL | Dedup/canonical identifiers tại đây |
| Screening decision | PostgreSQL | Immutable decision history |
| Corpus/graph version | PostgreSQL | Version pointer, không overwrite |
| Entity, edge, evidence | PostgreSQL | Knowledge graph dạng relational |
| Vector title/abstract/chunk | Qdrant | Derived index, rebuild được |
| LangGraph checkpoint | PostgreSQL | Theo `thread_id/job_id` |
| Raw/full text hợp lệ | Object storage về sau | PostgreSQL chỉ giữ locator/hash |

---

## 3. Nguyên tắc bất biến

1. **No source, no graph fact.** Không evidence thì không publish edge.
2. **No protocol, no systematic claim.** Không có protocol version thì chỉ được
   gọi là exploratory review.
3. **Embedding ranks; it does not decide exclusion.** Điểm cosine thấp không
   được tự động loại paper ở MVP.
4. **LLM proposes; policy validates; human publishes.**
5. Evidence quote phải exact-match với abstract/chunk đã lưu.
6. ID, DOI, URL, source locator không lấy từ LLM output.
7. Mọi search/retry/batch/loop có giới hạn, timeout và trace.
8. Project isolation được enforce ở repository/API, không chỉ filter ở UI.
9. Artifact đã publish là immutable. Thay đổi tạo version mới.
10. Qdrant lỗi thì degraded/fallback có cảnh báo; không làm mất dữ liệu chuẩn.
11. Candidate `EXISTING_WORK_FOUND` phải bị reject, không được đổi wording để
    tiếp tục gọi là gap.
12. `UNCERTAIN` là kết quả hợp lệ; không ép mọi candidate thành opportunity.

---

## 4. Domain model và trạng thái

### 4.1 Protocol

Protocol mô tả câu hỏi và cách chọn corpus. Mỗi lần sửa tạo version mới.

```python
ProtocolStatus = Literal["draft", "locked", "superseded"]

class ProtocolVersion(TypedDict):
    protocol_version_id: str
    project_id: str
    version_number: int
    research_question: str
    search_queries: list[str]
    inclusion_criteria: list[dict]
    exclusion_criteria: list[dict]
    year_from: int | None
    year_to: int | None
    languages: list[str]
    source_names: list[str]
    review_mode: Literal["exploratory", "systematic_assisted"]
    status: ProtocolStatus
    content_hash: str
    created_by: str
    created_at: str
```

Criterion có ID ổn định và machine-readable:

```json
{
  "criterion_id": "inc_has_evaluation",
  "label": "Có experimental evaluation",
  "description": "Abstract/full text báo cáo một evaluation thực nghiệm",
  "applies_at": ["abstract", "full_text"],
  "required": true
}
```

### 4.2 Screening stage và decision

```python
ScreeningStage = Literal["title", "abstract", "full_text"]
ScreeningDecision = Literal["include", "exclude", "maybe"]
DecisionSource = Literal["rule", "llm", "reviewer"]
```

Luật chuyển stage:

```text
IDENTIFIED
  → DUPLICATE                         (không screen tiếp)
  → TITLE_INCLUDE / TITLE_MAYBE
      → ABSTRACT_INCLUDE / ABSTRACT_MAYBE
          → FULL_TEXT_INCLUDE         (nếu full text gate bật)
          → ELIGIBLE                  (abstract-only mode)

Bất kỳ stage nào → EXCLUDED với reason code
```

Reason code bản đầu:

```text
DUPLICATE
MISSING_TITLE
MISSING_ABSTRACT
OUT_OF_YEAR_RANGE
LANGUAGE_NOT_ALLOWED
WRONG_DOMAIN
WRONG_POPULATION
WRONG_INTERVENTION_OR_METHOD
NO_EMPIRICAL_EVALUATION
WRONG_PUBLICATION_TYPE
FULL_TEXT_UNAVAILABLE
FULL_TEXT_INELIGIBLE
INSUFFICIENT_INFORMATION
OTHER_REVIEWER_REASON
```

`INSUFFICIENT_INFORMATION` phải đi với `maybe`, không được dùng để tự động
exclude.

### 4.3 Corpus version

Corpus version là snapshot immutable của tập paper đã eligible.

```python
CorpusStatus = Literal["building", "ready", "superseded", "failed"]

class CorpusVersion(TypedDict):
    corpus_version_id: str
    project_id: str
    protocol_version_id: str
    parent_corpus_version_id: str | None
    version_number: int
    content_scope: Literal["abstract", "mixed", "full_text"]
    included_count: int
    corpus_hash: str
    status: CorpusStatus
    created_by: str
    created_at: str
```

`corpus_hash` là SHA-256 của canonical JSON chứa sorted paper ID + content hash
+ screening decision IDs. Cùng input phải cho cùng hash.

### 4.4 Graph entity và relation

Entity type MVP:

```text
PAPER
MODEL
DATASET
TASK
METHOD
FINDING
LIMITATION
METRIC
```

Relation type MVP:

```text
USES
EVALUATES_ON
ADDRESSES
REPORTS_FINDING
HAS_LIMITATION
MEASURED_BY
SUPPORTS_TASK
```

Không tạo một node `MODEL` chứa danh sách model. `MODEL` là type; `BERT` là
một entity riêng.

Endpoint matrix bắt buộc:

| Relation | Source type | Target type |
|---|---|---|
| `USES` | `PAPER` | `MODEL` hoặc `METHOD` |
| `EVALUATES_ON` | `PAPER` | `DATASET` |
| `ADDRESSES` | `PAPER` | `TASK` |
| `REPORTS_FINDING` | `PAPER` | `FINDING` |
| `HAS_LIMITATION` | `PAPER` | `LIMITATION` |
| `MEASURED_BY` | `FINDING` | `METRIC` |
| `SUPPORTS_TASK` | `DATASET` | `TASK` |

`MODEL → DATASET → TASK` trong UI là một projection/combination view. Fact gốc
vẫn đi qua paper, ví dụ `Paper P USES BERT`, `P EVALUATES_ON SQuAD`,
`P ADDRESSES Question Answering`. Không persist projection như fact độc lập nếu
không có provenance.

### 4.5 Edge assertion lifecycle

```python
EdgeStatus = Literal[
    "draft",
    "evidence_validated",
    "reviewer_approved",
    "rejected",
    "superseded",
]
```

```text
LLM extraction
  → draft
  → exact evidence + type/endpoint validation
  → evidence_validated
  → reviewer_approved | rejected
  → superseded nếu version mới thay thế
```

### 4.6 Candidate lifecycle

```python
CandidateStatus = Literal[
    "generated",
    "validating_novelty",
    "existing_work_found",
    "validating_compatibility",
    "validating_counterevidence",
    "validated_candidate",
    "uncertain",
    "rejected",
    "reviewer_approved",
    "reviewer_rejected",
    "stale",
]
```

`validated_candidate` không đồng nghĩa research gap toàn cầu. UI/API phải luôn
trả scope statement:

> Trong corpus version X và novelty search run Y, hệ thống chưa tìm thấy direct
> existing work đủ confidence; cần researcher xác nhận.

---

## 5. PostgreSQL schema

Migration phải additive, không xóa hoặc đổi nghĩa bảng V1/V2 hiện tại. Runtime
hiện gọi Alembic qua `run_migrations()`, vì vậy Alembic revision là migration
thực thi bắt buộc. Các file SQL trong `supabase/migrations/` phải được giữ đồng
bộ để bootstrap/deploy Supabase không lệch schema.

Tên revision/file đề xuất:

```text
alembic/versions/0004_corpus_curation.py
alembic/versions/0005_scientific_graph.py
alembic/versions/0006_discovery_candidates.py

supabase/migrations/202608100001_corpus_curation.sql
supabase/migrations/202608100002_scientific_graph.sql
supabase/migrations/202608100003_discovery_candidates.sql
```

Các model SQLAlchemy tương ứng đặt trong `src/db/models.py` hoặc tách
`src/db/models_research_graph.py` rồi import vào metadata chung. Nếu tách file,
`alembic/env.py` vẫn phải load model module trước khi lấy `Base.metadata`.

### 5.1 Durable workflow jobs

Không dùng `v2_project_review_jobs` cho curation/graph/discovery vì bảng đó đại
diện review flow hiện tại và đang có single-flow constraint theo project. Thêm
một bảng job riêng cho các workflow mới:

```sql
create table research_workflow_jobs (
    job_id text primary key,
    project_id text not null references v2_projects(project_id),
    job_type text not null check (job_type in ('corpus_curation','graph_build','discovery')),
    dedupe_key text not null,
    input_json jsonb not null,
    input_hash text not null,
    status text not null check (status in (
        'queued','running','hitl_waiting','resuming','completed','failed','cancelled'
    )),
    checkpoint_thread_id text not null unique,
    progress_json jsonb not null default '{}'::jsonb,
    result_resource_type text,
    result_resource_id text,
    requested_by text not null references v2_actors(actor_id),
    idempotency_key text,
    lease_owner text,
    lease_expires_at timestamptz,
    attempt integer not null default 0,
    max_attempts integer not null default 2,
    error_code text,
    error_detail text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz
);

create unique index uq_research_workflow_job_idempotency
    on research_workflow_jobs(project_id, idempotency_key)
    where idempotency_key is not null;

create unique index uq_research_workflow_active_dedupe
    on research_workflow_jobs(project_id, job_type, dedupe_key)
    where status in ('queued','running','hitl_waiting','resuming');

create index idx_research_workflow_claim
    on research_workflow_jobs(status, lease_expires_at, created_at);
```

`dedupe_key`:

```text
corpus_curation:{protocol_version_id}
graph_build:{corpus_version_id}:{extraction_schema_version}
discovery:{graph_version_id}:{strategy_version}
```

### 5.2 Protocol và search

#### `research_protocol_versions`

```sql
create table research_protocol_versions (
    protocol_version_id text primary key,
    project_id text not null references v2_projects(project_id),
    parent_protocol_version_id text references research_protocol_versions(protocol_version_id),
    version_number integer not null check (version_number > 0),
    research_question text not null,
    search_queries_json jsonb not null,
    inclusion_criteria_json jsonb not null,
    exclusion_criteria_json jsonb not null,
    year_from integer,
    year_to integer,
    languages_json jsonb not null,
    source_names_json jsonb not null,
    review_mode text not null check (review_mode in ('exploratory','systematic_assisted')),
    status text not null check (status in ('draft','locked','superseded')),
    content_hash text not null,
    created_by text not null references v2_actors(actor_id),
    created_at timestamptz not null default now(),
    unique(project_id, version_number),
    unique(project_id, content_hash)
);
```

#### `research_search_runs`

```sql
create table research_search_runs (
    search_run_id text primary key,
    project_id text not null references v2_projects(project_id),
    protocol_version_id text not null references research_protocol_versions(protocol_version_id),
    source_name text not null,
    query_text text not null,
    filters_json jsonb not null default '{}'::jsonb,
    status text not null check (status in ('queued','running','completed','failed')),
    result_count integer not null default 0,
    source_cursor text,
    request_hash text not null,
    error_code text,
    started_at timestamptz,
    completed_at timestamptz,
    created_by text not null references v2_actors(actor_id),
    created_at timestamptz not null default now(),
    unique(project_id, request_hash)
);
```

### 5.3 Canonical paper storage

#### `scientific_papers`

```sql
create table scientific_papers (
    paper_id text primary key,
    openalex_id text unique,
    doi_normalized text,
    title text not null,
    title_normalized text not null,
    abstract text,
    abstract_hash text,
    authors_json jsonb not null default '[]'::jsonb,
    publication_year integer,
    language text,
    publication_type text,
    source_url text not null,
    source_name text not null,
    is_open_access boolean not null default false,
    metadata_json jsonb not null default '{}'::jsonb,
    metadata_hash text not null,
    first_seen_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index uq_scientific_papers_doi
    on scientific_papers(doi_normalized)
    where doi_normalized is not null;
```

`paper_id` là server ID ổn định, không dùng title làm ID. OpenAlex ID và DOI là
identifier được verify từ source adapter.

#### `research_search_results`

```sql
create table research_search_results (
    search_run_id text not null references research_search_runs(search_run_id),
    paper_id text not null references scientific_papers(paper_id),
    source_rank integer,
    source_score double precision,
    raw_record_hash text not null,
    created_at timestamptz not null default now(),
    primary key(search_run_id, paper_id)
);
```

### 5.4 Deduplication và screening

#### `research_dedupe_groups`

```sql
create table research_dedupe_groups (
    dedupe_group_id text primary key,
    project_id text not null references v2_projects(project_id),
    canonical_paper_id text not null references scientific_papers(paper_id),
    match_method text not null check (match_method in ('openalex_id','doi','title_year','reviewer')),
    confidence double precision not null check (confidence between 0 and 1),
    created_at timestamptz not null default now()
);
```

#### `research_dedupe_members`

```sql
create table research_dedupe_members (
    dedupe_group_id text not null references research_dedupe_groups(dedupe_group_id),
    paper_id text not null references scientific_papers(paper_id),
    is_canonical boolean not null default false,
    primary key(dedupe_group_id, paper_id)
);
```

#### `research_screening_decisions`

```sql
create table research_screening_decisions (
    screening_decision_id text primary key,
    project_id text not null references v2_projects(project_id),
    protocol_version_id text not null references research_protocol_versions(protocol_version_id),
    paper_id text not null references scientific_papers(paper_id),
    stage text not null check (stage in ('title','abstract','full_text')),
    decision text not null check (decision in ('include','exclude','maybe')),
    reason_codes_json jsonb not null default '[]'::jsonb,
    criterion_results_json jsonb not null default '[]'::jsonb,
    evidence_quote text,
    content_hash text,
    decision_source text not null check (decision_source in ('rule','llm','reviewer')),
    model_provider text,
    model_name text,
    prompt_version text,
    confidence double precision check (confidence between 0 and 1),
    supersedes_decision_id text references research_screening_decisions(screening_decision_id),
    created_by text not null,
    created_at timestamptz not null default now()
);

create index idx_screening_project_protocol_stage
    on research_screening_decisions(project_id, protocol_version_id, stage, paper_id);
```

Decision hiện hành là record mới nhất trong chain chưa bị supersede. Không
`UPDATE decision='...'` lên record cũ.

### 5.5 Corpus version

#### `research_corpus_versions`

```sql
create table research_corpus_versions (
    corpus_version_id text primary key,
    project_id text not null references v2_projects(project_id),
    protocol_version_id text not null references research_protocol_versions(protocol_version_id),
    parent_corpus_version_id text references research_corpus_versions(corpus_version_id),
    version_number integer not null check (version_number > 0),
    content_scope text not null check (content_scope in ('abstract','mixed','full_text')),
    status text not null check (status in ('building','ready','superseded','failed')),
    included_count integer not null default 0,
    corpus_hash text not null,
    flow_counts_json jsonb not null default '{}'::jsonb,
    created_by text not null references v2_actors(actor_id),
    created_at timestamptz not null default now(),
    unique(project_id, version_number),
    unique(project_id, corpus_hash)
);
```

#### `research_corpus_papers`

```sql
create table research_corpus_papers (
    corpus_version_id text not null references research_corpus_versions(corpus_version_id),
    paper_id text not null references scientific_papers(paper_id),
    final_screening_decision_id text not null references research_screening_decisions(screening_decision_id),
    content_scope text not null check (content_scope in ('abstract','full_text')),
    content_hash text not null,
    primary key(corpus_version_id, paper_id)
);
```

### 5.6 Paper chunks

```sql
create table scientific_paper_chunks (
    chunk_id text primary key,
    paper_id text not null references scientific_papers(paper_id),
    content_scope text not null check (content_scope in ('abstract','full_text')),
    section_name text,
    page_start integer,
    page_end integer,
    char_start integer not null,
    char_end integer not null,
    chunk_text text not null,
    chunk_hash text not null,
    parser_name text,
    parser_version text,
    created_at timestamptz not null default now(),
    unique(paper_id, chunk_hash)
);
```

Abstract cũng được materialize thành một chunk để evidence validation dùng một
cơ chế thống nhất.

### 5.7 Knowledge Graph

#### `scientific_entities`

```sql
create table scientific_entities (
    entity_id text primary key,
    entity_type text not null check (entity_type in (
        'PAPER','MODEL','DATASET','TASK','METHOD','FINDING','LIMITATION','METRIC'
    )),
    canonical_name text not null,
    normalized_name text not null,
    properties_json jsonb not null default '{}'::jsonb,
    status text not null default 'active' check (status in ('active','merged','deprecated')),
    merged_into_entity_id text references scientific_entities(entity_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create unique index uq_scientific_entities_type_name
    on scientific_entities(entity_type, normalized_name)
    where status = 'active';
```

Mỗi paper tham gia graph phải có một `PAPER` entity và mapping FK cứng:

```sql
create table scientific_paper_entities (
    paper_id text primary key references scientific_papers(paper_id),
    entity_id text not null unique references scientific_entities(entity_id),
    created_at timestamptz not null default now()
);
```

Repository phải kiểm tra entity được map có `entity_type='PAPER'`. Không dùng
`properties_json.paper_id` làm quan hệ chuẩn.

#### `scientific_entity_aliases`

```sql
create table scientific_entity_aliases (
    entity_alias_id text primary key,
    entity_id text not null references scientific_entities(entity_id),
    alias text not null,
    normalized_alias text not null,
    source_paper_id text references scientific_papers(paper_id),
    resolution_method text not null check (resolution_method in ('exact','dictionary','embedding','llm','reviewer')),
    confidence double precision not null check (confidence between 0 and 1),
    created_at timestamptz not null default now(),
    unique(entity_id, normalized_alias)
);
```

#### `scientific_graph_versions`

```sql
create table scientific_graph_versions (
    graph_version_id text primary key,
    project_id text not null references v2_projects(project_id),
    corpus_version_id text not null references research_corpus_versions(corpus_version_id),
    parent_graph_version_id text references scientific_graph_versions(graph_version_id),
    version_number integer not null check (version_number > 0),
    graph_hash text not null,
    extraction_schema_version text not null,
    status text not null check (status in ('building','reviewing','published','superseded','failed')),
    entity_count integer not null default 0,
    edge_count integer not null default 0,
    created_by text not null,
    created_at timestamptz not null default now(),
    published_at timestamptz,
    unique(project_id, version_number),
    unique(project_id, graph_hash)
);
```

#### `scientific_edge_assertions`

```sql
create table scientific_edge_assertions (
    edge_assertion_id text primary key,
    project_id text not null references v2_projects(project_id),
    source_entity_id text not null references scientific_entities(entity_id),
    relation_type text not null check (relation_type in (
        'USES','EVALUATES_ON','ADDRESSES','REPORTS_FINDING',
        'HAS_LIMITATION','MEASURED_BY','SUPPORTS_TASK'
    )),
    target_entity_id text not null references scientific_entities(entity_id),
    assertion_hash text not null,
    confidence double precision not null check (confidence between 0 and 1),
    status text not null check (status in (
        'draft','evidence_validated','reviewer_approved','rejected','superseded'
    )),
    extraction_run_id text not null,
    supersedes_edge_assertion_id text references scientific_edge_assertions(edge_assertion_id),
    created_at timestamptz not null default now(),
    unique(project_id, assertion_hash, extraction_run_id),
    check (source_entity_id <> target_entity_id)
);

create index idx_edge_assertions_traversal
    on scientific_edge_assertions(project_id, source_entity_id, relation_type, target_entity_id);
```

#### `scientific_edge_evidence`

```sql
create table scientific_edge_evidence (
    edge_evidence_id text primary key,
    edge_assertion_id text not null references scientific_edge_assertions(edge_assertion_id),
    paper_id text not null references scientific_papers(paper_id),
    chunk_id text not null references scientific_paper_chunks(chunk_id),
    quote text not null,
    quote_char_start integer not null,
    quote_char_end integer not null,
    evidence_type text not null check (evidence_type in ('support','counterevidence','existing_work')),
    confidence double precision not null check (confidence between 0 and 1),
    exact_match_valid boolean not null default false,
    created_at timestamptz not null default now(),
    unique(edge_assertion_id, chunk_id, quote_char_start, quote_char_end)
);
```

#### `scientific_graph_version_edges`

```sql
create table scientific_graph_version_edges (
    graph_version_id text not null references scientific_graph_versions(graph_version_id),
    edge_assertion_id text not null references scientific_edge_assertions(edge_assertion_id),
    primary key(graph_version_id, edge_assertion_id)
);
```

Graph version là tập edge assertion immutable. Entity có thể dùng chung để
entity resolution nhất quán; edge và evidence luôn project-scoped.

### 5.8 Discovery và validation

#### `scientific_discovery_runs`

```sql
create table scientific_discovery_runs (
    discovery_run_id text primary key,
    project_id text not null references v2_projects(project_id),
    graph_version_id text not null references scientific_graph_versions(graph_version_id),
    strategy_version text not null,
    candidate_types_json jsonb not null,
    status text not null check (status in ('queued','running','completed','failed')),
    created_by text not null,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);
```

#### `scientific_candidates`

```sql
create table scientific_candidates (
    candidate_id text primary key,
    discovery_run_id text not null references scientific_discovery_runs(discovery_run_id),
    project_id text not null references v2_projects(project_id),
    graph_version_id text not null references scientific_graph_versions(graph_version_id),
    candidate_type text not null check (candidate_type in (
        'MODEL_DATASET_TASK','METHOD_TRANSFER','LIMITATION_DRIVEN','DATASET_TRANSFER','CONTRADICTION'
    )),
    components_json jsonb not null,
    candidate_hash text not null,
    status text not null,
    compatibility_score double precision,
    evidence_score double precision,
    novelty_score double precision,
    motivation_score double precision,
    feasibility_score double precision,
    final_score double precision,
    scoped_statement text not null,
    uncertainty text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(discovery_run_id, candidate_hash)
);
```

#### `scientific_candidate_evidence`

```sql
create table scientific_candidate_evidence (
    candidate_evidence_id text primary key,
    candidate_id text not null references scientific_candidates(candidate_id),
    paper_id text not null references scientific_papers(paper_id),
    chunk_id text references scientific_paper_chunks(chunk_id),
    evidence_type text not null check (evidence_type in ('support','counterevidence','existing_work')),
    quote text,
    source_url text not null,
    retrieval_run_id text not null,
    relevance_score double precision,
    created_at timestamptz not null default now()
);
```

#### `scientific_validation_runs`

```sql
create table scientific_validation_runs (
    validation_run_id text primary key,
    candidate_id text not null references scientific_candidates(candidate_id),
    validator_type text not null check (validator_type in (
        'novelty','compatibility','counterevidence','scientific_value','feasibility'
    )),
    input_hash text not null,
    status text not null check (status in ('running','passed','failed','uncertain','error')),
    result_json jsonb not null default '{}'::jsonb,
    model_provider text,
    model_name text,
    prompt_version text,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    unique(candidate_id, validator_type, input_hash)
);
```

#### `scientific_candidate_reviews`

```sql
create table scientific_candidate_reviews (
    candidate_review_id text primary key,
    candidate_id text not null references scientific_candidates(candidate_id),
    project_id text not null references v2_projects(project_id),
    reviewer_id text not null references v2_actors(actor_id),
    verdict text not null check (verdict in ('approve','reject','request_changes')),
    revised_statement text,
    note text not null default '',
    created_at timestamptz not null default now()
);
```

### 5.9 RLS và authorization

Các bảng mới phải `ENABLE ROW LEVEL SECURITY`, nhưng request từ browser không
được truy cập trực tiếp. Tất cả đi qua FastAPI và `ProjectMembership`.

Repository phải nhận `project_id` trong mọi query project-scoped. Không cung
cấp hàm `get_candidate(candidate_id)` không scope; dùng:

```python
get_candidate(project_id: str, candidate_id: str)
```

Permission tối thiểu:

| Hành động | owner | researcher | reviewer |
|---|---:|---:|---:|
| Tạo/lock protocol | ✓ | ✓ | đọc |
| Chạy search/screen/build graph | ✓ | ✓ | đọc |
| Override screening | ✓ | ✓ | ✓ khi được assign |
| Publish graph version | ✓ | ✓ | ✓ khi được assign |
| Review candidate | đọc | đọc | ✓ |
| Xóa/archive project | ✓ | ✗ | ✗ |

---

## 6. Qdrant design

Giữ collection hiện tại `litreview_papers` cho compatibility. Thêm collection
mới có payload rõ ràng cho corpus/graph:

```text
research_paper_chunks_v1
```

Config bổ sung:

```text
QDRANT_RESEARCH_COLLECTION=research_paper_chunks_v1
QDRANT_EMBEDDING_SCHEMA_VERSION=research-v1
QDRANT_RESEARCH_TOP_K=100
```

### 6.1 Point ID

```python
point_id = uuid5(
    NAMESPACE_URL,
    f"research-chunk:{chunk_id}:{embedding_model}:{embedding_schema_version}",
)
```

### 6.2 Payload

```json
{
  "project_id": "project_...",
  "corpus_version_id": "corpusv_...",
  "paper_id": "paper_...",
  "chunk_id": "chunk_...",
  "content_scope": "abstract",
  "section_name": "abstract",
  "eligible": true,
  "protocol_version_id": "protocolv_...",
  "chunk_hash": "sha256...",
  "embedding_schema_version": "research-v1"
}
```

### 6.3 Quy tắc sử dụng

1. Screening: Qdrant rank title + abstract nhưng không tự loại theo threshold.
2. Extraction retrieval: chỉ filter đúng `project_id + corpus_version_id`.
3. Novelty/countersearch: có thể search một external candidate pool riêng,
   nhưng kết quả phải được import/verify vào PostgreSQL trước khi dùng làm fact.
4. Delete Qdrant point không được xóa PostgreSQL record.
5. Có command rebuild collection từ `scientific_paper_chunks`.
6. Nếu Qdrant unavailable, screening dùng lexical ranking và ghi
   `QDRANT_FALLBACK`; graph traversal vẫn hoạt động từ PostgreSQL.

---

## 7. Workflow 1 — CorpusCurationGraph

### 7.1 State

Tạo `src/agents/corpus_state.py`:

```python
class CorpusCurationState(TypedDict, total=False):
    job_id: str
    project_id: str
    actor_id: str
    protocol_version_id: str
    protocol: dict
    search_run_ids: list[str]
    identified_paper_ids: list[str]
    canonical_paper_ids: list[str]
    duplicate_paper_ids: list[str]
    title_include_ids: list[str]
    title_maybe_ids: list[str]
    abstract_include_ids: list[str]
    abstract_maybe_ids: list[str]
    full_text_include_ids: list[str]
    reviewer_queue_ids: list[str]
    corpus_version_id: str | None
    flow_counts: dict[str, int]
    decisions: list[dict]
    warnings: list[str]
    current_node: str
    status: str
    error: str | None
```

State chỉ giữ ID và progress nhỏ; paper text/large payload đọc từ repository để
checkpoint không phình lớn.

### 7.2 Nodes

```text
validate_protocol
  → create_search_runs
  → search_sources
  → normalize_papers
  → deduplicate_papers
  → index_screening_candidates
  → title_screen
  → abstract_screen
  → route_borderline
      ├─ reviewer queue → human_screening (interrupt)
      └─ no borderline
  → full_text_eligibility (feature gate)
  → build_corpus_version
  → finalize_curation
```

#### `validate_protocol_node`

- Protocol phải tồn tại, cùng project, status `locked`.
- Có ít nhất một search query.
- Inclusion/exclusion criterion ID không trùng.
- `year_from <= year_to` nếu cả hai tồn tại.
- Tạo decision trace; không gọi LLM.

#### `search_sources_node`

- MVP chỉ gọi OpenAlex adapter hiện có.
- Dùng query/filter từ protocol, không để LLM tự mở rộng source.
- Mỗi request có `request_hash` và idempotency.
- Retry tối đa 2 lần/source với exponential backoff.
- Persist raw normalized metadata trước khi sang node sau.

#### `deduplicate_papers_node`

Thứ tự match:

1. Exact OpenAlex ID.
2. Exact normalized DOI.
3. Normalized title + publication year.
4. Reviewer merge cho case không chắc chắn.

Không dùng LLM làm quyết định dedupe cuối cùng ở MVP.

#### `index_screening_candidates_node`

- Upsert abstract chunks vào PostgreSQL.
- Upsert vectors vào Qdrant theo batch.
- Nếu Qdrant lỗi, warning + lexical fallback; không fail toàn job.

#### `title_screen_node`

- Rule screen metadata rõ ràng: thiếu title, ngoài year, language không hợp lệ.
- Semantic ranking để ưu tiên batch.
- LLM output structured theo criterion ID.
- Title-only không được đánh `exclude` vì thiếu thông tin thực nghiệm; trả `maybe`.

#### `abstract_screen_node`

LLM response contract:

```python
class CriterionResult(BaseModel):
    criterion_id: str
    verdict: Literal["met", "not_met", "unclear"]
    reason: str
    evidence_quote: str | None

class ScreeningOutput(BaseModel):
    paper_id: str
    decision: Literal["include", "exclude", "maybe"]
    reason_codes: list[str]
    criterion_results: list[CriterionResult]
    confidence: float
```

Validation sau LLM:

- `paper_id` phải thuộc input batch.
- Criterion ID phải thuộc locked protocol.
- Evidence quote phải exact-match abstract.
- `unclear` ở required criterion đưa vào `maybe`, không auto-exclude.
- Batch lỗi schema retry tối đa 1 lần; sau đó chuyển reviewer queue.

#### `human_screening_node`

LangGraph `interrupt` trả:

```json
{
  "type": "screening_review_required",
  "project_id": "project_...",
  "protocol_version_id": "protocolv_...",
  "papers": [
    {
      "paper_id": "paper_...",
      "stage": "abstract",
      "proposed_decision": "maybe",
      "criterion_results": [],
      "title": "...",
      "abstract": "..."
    }
  ]
}
```

Resume payload được validate và tạo reviewer decision mới, không sửa LLM
decision cũ.

#### `full_text_eligibility_node`

- Feature flag `FULL_TEXT_ELIGIBILITY_ENABLED`.
- Nếu tắt: abstract include trở thành eligible với `content_scope=abstract`.
- Nếu bật: chỉ tải nội dung open-access/licensed; ghi parser/hash/locator.
- Parse failure hoặc unavailable là decision rõ ràng; không giả lập full text.

#### `build_corpus_version_node`

- Lấy effective decision mới nhất của từng stage.
- Tạo sorted included list và corpus hash.
- Transaction tạo version + memberships + flow counts.
- Nếu cùng hash đã tồn tại, trả existing version (idempotent).

### 7.3 Routing

```text
protocol invalid                         → fail
0 result sau bounded retry              → fail
Qdrant unavailable                      → continue_with_warning
maybe/borderline tồn tại                → human_screening
full-text feature disabled              → build_corpus_version
0 eligible paper                        → fail (EMPTY_ELIGIBLE_CORPUS)
corpus version ready                     → END
```

---

## 8. Workflow 2 — GraphBuildGraph

### 8.1 State

```python
class GraphBuildState(TypedDict, total=False):
    job_id: str
    project_id: str
    actor_id: str
    corpus_version_id: str
    graph_version_id: str | None
    pending_paper_ids: list[str]
    processed_paper_ids: list[str]
    extraction_run_id: str
    extracted_entity_count: int
    extracted_edge_count: int
    rejected_edge_count: int
    unresolved_mentions: list[dict]
    warnings: list[str]
    status: str
    current_node: str
    error: str | None
```

### 8.2 Nodes

```text
load_corpus
  → prepare_chunks
  → extract_scientific_records
  → validate_extraction_evidence
  → resolve_entities
  → persist_edge_assertions
  → graph_quality_gate
  → graph_review (interrupt nếu cần)
  → publish_graph_version
```

#### Extraction output contract

LLM không xuất database ID. Nó chỉ xuất mention và evidence locator:

```python
class ExtractedEntityMention(BaseModel):
    mention_id: str
    entity_type: Literal["MODEL","DATASET","TASK","METHOD","FINDING","LIMITATION","METRIC"]
    surface_form: str
    canonical_name_suggestion: str
    properties: dict

class ExtractedRelation(BaseModel):
    relation_type: Literal[
        "USES","EVALUATES_ON","ADDRESSES","REPORTS_FINDING",
        "HAS_LIMITATION","MEASURED_BY","SUPPORTS_TASK"
    ]
    source_mention_id: str
    target_mention_id: str
    quote: str
    chunk_id: str
    confidence: float
```

Validator kiểm tra:

- mention IDs nằm trong cùng extraction response;
- relation endpoints đúng ontology;
- chunk thuộc paper và corpus version;
- quote exact-match chunk;
- relation critical nhưng thiếu quote bị reject;
- LLM-supplied unknown relation/type bị reject, không auto-map tùy tiện.

### 8.3 Entity resolution

Resolution order:

```text
exact normalized canonical name
→ exact alias
→ curated dictionary
→ embedding candidate top-k
→ LLM compare restricted candidate list
→ unresolved/new entity
```

Ngưỡng đề xuất:

- exact/dictionary: auto-resolve.
- embedding/LLM confidence `>= 0.90`: resolve nhưng ghi method/confidence.
- `0.70–0.89`: reviewer queue.
- `< 0.70`: tạo entity mới ở trạng thái active hoặc unresolved tùy type.

Không merge entity chỉ dựa trên vector similarity.

### 8.4 Graph quality gate

Graph version chỉ publish nếu:

```text
unsupported critical edge rate = 0
exact-match evidence coverage = 100% cho edge publish
unknown ontology type = 0
cross-project evidence reference = 0
duplicate active entity key = 0
graph hash reproducible = true
```

MVP có thể publish chỉ các edge `evidence_validated`; reviewer approval từng edge
là feature gate sau. Edge bị loại vẫn giữ audit nhưng không thuộc graph version.

### 8.5 GraphRAG retrieval service

GraphRAG query không cần một autonomous agent. Bản đầu triển khai bằng một
bounded orchestrator service, ví dụ `GraphRAGService.answer()`:

```python
class GraphRAGQuery(TypedDict):
    project_id: str
    graph_version_id: str
    question: str
    mode: Literal["local", "path", "hybrid"]
    max_hops: int
    top_k_entities: int
    top_k_evidence: int
    token_budget: int


class GraphRAGContextItem(TypedDict):
    context_id: str
    paper_id: str
    chunk_id: str
    edge_assertion_id: str | None
    graph_path: list[str]
    quote: str
    source_url: str
    relevance_score: float


class GraphRAGAnswer(TypedDict):
    answer_status: Literal["grounded_answer", "insufficient_evidence"]
    answer: str
    citations: list[dict]
    seed_entities: list[dict]
    graph_paths: list[dict]
    content_scope: str
    limitations: list[str]
```

Mode:

| Mode | Cách retrieve | Dùng khi |
|---|---|---|
| `local` | Seed entity → neighbors 1–2 hop | Hỏi về một model/dataset/task cụ thể |
| `path` | Tìm path giữa hai entity đã resolve | “BERT liên quan MedQA qua paper/task nào?” |
| `hybrid` | Graph traversal + Qdrant evidence search | Câu hỏi tự nhiên, so sánh hoặc tổng hợp |

Thuật toán bắt buộc:

```text
authorize project
→ resolve active/specified graph version
→ understand query bằng structured output
→ exact/alias lookup + Qdrant seed retrieval
→ validate seed entities thuộc graph version
→ traverse SQL với max_hops <= 2
→ load edge evidence từ PostgreSQL
→ semantic evidence retrieval trong đúng corpus version
→ deduplicate + rerank + context budget
→ LLM synthesis với context IDs
→ citation/grounding validation
→ response
```

SQL traversal phải parameterized và giới hạn `max_hops`, `relation_types`, số
node/edge. LLM không được sinh SQL/Cypher tùy ý rồi chạy trực tiếp.

Context pack gửi LLM:

```json
{
  "question": "BERT đã được đánh giá trên dataset nào?",
  "graph_version_id": "graphv_...",
  "content_scope": "abstract",
  "items": [
    {
      "context_id": "ctx_1",
      "path": ["BERT", "USES_REVERSE", "Paper P1", "EVALUATES_ON", "SQuAD"],
      "paper_id": "paper_p1",
      "chunk_id": "chunk_p1_abstract",
      "quote": "...",
      "source_url": "https://..."
    }
  ]
}
```

LLM response chỉ được cite `context_id` có trong input. Citation validator map
`context_id → paper/chunk/edge`, kiểm tra quote/source và loại factual sentence
không có support. Nếu không còn claim hợp lệ, trả `insufficient_evidence`.

---

## 9. Workflow 3 — DiscoveryGraph

MVP đầu tiên chỉ bật candidate type `MODEL_DATASET_TASK`.

### 9.1 Candidate generation rule

Sinh candidate khi:

```text
Có paper P1 USES Model M và ADDRESSES Task T
Có paper P2 EVALUATES_ON Dataset D và ADDRESSES Task T
Nhưng không có paper P3 đồng thời:
  USES M + EVALUATES_ON D + ADDRESSES T
```

Điều này chỉ tạo `generated`, không tạo `validated_candidate`.

Pseudo-query:

```sql
with model_task as (
    select distinct
        uses_edge.target_entity_id as model_id,
        task_edge.target_entity_id as task_id
    from published_edges uses_edge
    join published_edges task_edge
      on task_edge.source_entity_id = uses_edge.source_entity_id
    where uses_edge.relation_type = 'USES'
      and task_edge.relation_type = 'ADDRESSES'
),
dataset_task as (
    select distinct
        dataset_edge.target_entity_id as dataset_id,
        task_edge.target_entity_id as task_id
    from published_edges dataset_edge
    join published_edges task_edge
      on task_edge.source_entity_id = dataset_edge.source_entity_id
    where dataset_edge.relation_type = 'EVALUATES_ON'
      and task_edge.relation_type = 'ADDRESSES'
),
existing_combinations as (
    select distinct
        uses_edge.target_entity_id as model_id,
        dataset_edge.target_entity_id as dataset_id,
        task_edge.target_entity_id as task_id
    from published_edges uses_edge
    join published_edges dataset_edge
      on dataset_edge.source_entity_id = uses_edge.source_entity_id
    join published_edges task_edge
      on task_edge.source_entity_id = uses_edge.source_entity_id
    where uses_edge.relation_type = 'USES'
      and dataset_edge.relation_type = 'EVALUATES_ON'
      and task_edge.relation_type = 'ADDRESSES'
)
select mt.model_id, dt.dataset_id, mt.task_id
from model_task mt
join dataset_task dt on dt.task_id = mt.task_id
where not exists (
    select 1
    from existing_combinations ec
    where ec.model_id = mt.model_id
      and ec.dataset_id = dt.dataset_id
      and ec.task_id = mt.task_id
);
```

`published_edges` trong pseudo-query là view/repository query đã filter đúng
`project_id`, `graph_version_id`, edge membership và trạng thái được publish.

### 9.2 Validation order

```text
generate_candidates
  → rank_candidates
  → novelty_search
      ├─ direct existing work found → existing_work_found → END candidate
      └─ absent/uncertain
  → compatibility_check
      ├─ incompatible → rejected
      └─ pass/uncertain
  → counterevidence_search
  → scientific_value_check
  → feasibility_check
  → finalize_candidate
  → candidate_review (HITL)
```

Novelty phải chạy trước generation of hypothesis để tránh LLM “yêu” ý tưởng do
chính nó vừa tạo.

### 9.3 Scoring

Điểm chỉ dùng rank, không thay thế validator:

```text
final_score =
  0.25 * novelty_score
+ 0.20 * compatibility_score
+ 0.20 * evidence_score
+ 0.20 * motivation_score
+ 0.15 * feasibility_score
```

Hard gates:

- direct existing work confidence `>= 0.85` → `existing_work_found`.
- compatibility failed hard constraint → `rejected`.
- novelty search/countersearch chưa chạy → tối đa `uncertain`.
- critical evidence path < 2 → tối đa `uncertain`.

### 9.4 Candidate output

```json
{
  "candidate_id": "candidate_...",
  "status": "validated_candidate",
  "candidate_type": "MODEL_DATASET_TASK",
  "components": {
    "model_entity_id": "entity_...",
    "dataset_entity_id": "entity_...",
    "task_entity_id": "entity_..."
  },
  "scores": {
    "novelty": 0.82,
    "compatibility": 0.91,
    "evidence": 0.88,
    "motivation": 0.75,
    "feasibility": 0.70,
    "final": 0.82
  },
  "scoped_statement": "Trong corpus ... chưa thấy ...",
  "uncertainty": "OpenAlex + abstract scope; chưa thể khẳng định toàn literature",
  "supporting_paths": [],
  "existing_work_evidence": [],
  "counterevidence": [],
  "validation_runs": []
}
```

Research question/hypothesis/experiment chỉ sinh sau
`validated_candidate` hoặc `reviewer_approved`, tùy feature flag.

---

## 10. API contract

Giữ base path `/api/v1`. Actor lấy từ auth context, không nhận `actor_id`,
`reviewer_id` hoặc `role` từ body ở API project-scoped.

Mutation phải hỗ trợ header `Idempotency-Key`.

### 10.1 Protocol

```text
POST /api/v1/projects/{project_id}/protocols
GET  /api/v1/projects/{project_id}/protocols
GET  /api/v1/projects/{project_id}/protocols/{protocol_version_id}
POST /api/v1/projects/{project_id}/protocols/{protocol_version_id}/lock
```

Create protocol request:

```json
{
  "research_question": "Does RAG improve educational question answering?",
  "search_queries": ["retrieval augmented generation education question answering"],
  "inclusion_criteria": [],
  "exclusion_criteria": [],
  "year_from": 2022,
  "year_to": 2026,
  "languages": ["en", "vi"],
  "source_names": ["openalex"],
  "review_mode": "systematic_assisted"
}
```

### 10.2 Corpus curation

```text
POST /api/v1/projects/{project_id}/curation-runs
GET  /api/v1/projects/{project_id}/curation-runs/{job_id}/status
GET  /api/v1/projects/{project_id}/curation-runs/{job_id}/screening-queue
POST /api/v1/projects/{project_id}/curation-runs/{job_id}/screening-decisions
GET  /api/v1/projects/{project_id}/corpus-versions
GET  /api/v1/projects/{project_id}/corpus-versions/{corpus_version_id}
GET  /api/v1/projects/{project_id}/corpus-versions/{corpus_version_id}/flow
```

Start response: HTTP `202`.

```json
{
  "job_id": "curationjob_...",
  "project_id": "project_...",
  "protocol_version_id": "protocolv_...",
  "status": "queued"
}
```

Flow response:

```json
{
  "identified": 2330,
  "duplicates_removed": 181,
  "title_screened": 2149,
  "title_excluded": 1500,
  "abstract_screened": 649,
  "abstract_excluded": 392,
  "full_text_assessed": 257,
  "full_text_excluded": 177,
  "included": 80,
  "content_scope": "mixed",
  "protocol_version_id": "protocolv_...",
  "corpus_version_id": "corpusv_..."
}
```

### 10.3 Graph

```text
POST /api/v1/projects/{project_id}/graph-builds
GET  /api/v1/projects/{project_id}/graph-builds/{job_id}/status
GET  /api/v1/projects/{project_id}/graph-versions
GET  /api/v1/projects/{project_id}/graph-versions/{graph_version_id}
GET  /api/v1/projects/{project_id}/graph-versions/{graph_version_id}/entities
GET  /api/v1/projects/{project_id}/graph-versions/{graph_version_id}/edges
GET  /api/v1/projects/{project_id}/graph-versions/{graph_version_id}/neighbors/{entity_id}
GET  /api/v1/projects/{project_id}/graph/edges/{edge_assertion_id}/evidence
POST /api/v1/projects/{project_id}/graph-builds/{job_id}/review
```

Neighbor query hỗ trợ `relation_type`, `direction`, `limit`, nhưng `limit <= 200`.

### 10.4 GraphRAG query

```text
POST /api/v1/projects/{project_id}/graph-query
```

Request:

```json
{
  "question": "BERT đã được đánh giá trên những dataset nào?",
  "graph_version_id": "graphv_...",
  "mode": "hybrid",
  "max_hops": 2,
  "top_k_entities": 10,
  "top_k_evidence": 20
}
```

`graph_version_id` có thể bỏ trống để dùng active published graph, nhưng
response luôn phải trả ID thực tế đã dùng.

Response:

```json
{
  "answer_status": "grounded_answer",
  "answer": "Trong graph version ...",
  "graph_version_id": "graphv_...",
  "corpus_version_id": "corpusv_...",
  "content_scope": "abstract",
  "seed_entities": [],
  "graph_paths": [],
  "citations": [
    {
      "context_id": "ctx_1",
      "paper_id": "paper_...",
      "chunk_id": "chunk_...",
      "edge_assertion_ids": ["edge_..."],
      "quote": "...",
      "source_url": "https://..."
    }
  ],
  "limitations": ["Answer is scoped to the selected project corpus"]
}
```

Endpoint chỉ đọc dữ liệu nên không cần `Idempotency-Key`; vẫn phải enforce auth,
project scope, timeout, rate limit và token budget.

### 10.5 Discovery

```text
POST /api/v1/projects/{project_id}/discovery-runs
GET  /api/v1/projects/{project_id}/discovery-runs/{discovery_run_id}/status
GET  /api/v1/projects/{project_id}/candidates
GET  /api/v1/projects/{project_id}/candidates/{candidate_id}
POST /api/v1/projects/{project_id}/candidates/{candidate_id}/validate
POST /api/v1/projects/{project_id}/candidates/{candidate_id}/review
POST /api/v1/projects/{project_id}/candidates/{candidate_id}/research-question
POST /api/v1/projects/{project_id}/candidates/{candidate_id}/experiment
```

Filter candidates:

```text
?status=validated_candidate
&candidate_type=MODEL_DATASET_TASK
&graph_version_id=graphv_...
&limit=50
&cursor=...
```

### 10.6 Error contract

```json
{
  "error_code": "PROTOCOL_NOT_LOCKED",
  "message": "Protocol must be locked before starting curation",
  "retryable": false,
  "details": {"protocol_version_id": "protocolv_..."},
  "correlation_id": "corr_..."
}
```

Error code tối thiểu:

```text
PROJECT_NOT_FOUND
PROJECT_ACCESS_DENIED
PROTOCOL_NOT_FOUND
PROTOCOL_NOT_LOCKED
PROTOCOL_STALE
CURATION_ALREADY_RUNNING
EMPTY_SEARCH_RESULTS
EMPTY_ELIGIBLE_CORPUS
SCREENING_REVIEW_REQUIRED
CORPUS_NOT_READY
GRAPH_BUILD_ALREADY_RUNNING
GRAPH_QUALITY_GATE_FAILED
GRAPH_VERSION_STALE
GRAPH_QUERY_TOO_BROAD
GRAPH_ENTITY_NOT_RESOLVED
INSUFFICIENT_GRAPH_EVIDENCE
CANDIDATE_NOT_FOUND
CANDIDATE_STALE
VALIDATION_PREREQUISITE_MISSING
QDRANT_UNAVAILABLE
SOURCE_RATE_LIMITED
INVALID_LLM_OUTPUT
```

---

## 11. Code structure đề xuất

```text
src/
├── api/routers/
│   ├── protocols.py
│   ├── corpus_curation.py
│   ├── scientific_graph.py
│   └── discovery.py
├── models/schemas/
│   ├── protocols.py
│   ├── corpus_curation.py
│   ├── scientific_graph.py
│   └── discovery.py
├── agents/
│   ├── corpus_graph.py
│   ├── corpus_state.py
│   ├── graph_build_graph.py
│   ├── graph_build_state.py
│   ├── discovery_graph.py
│   ├── discovery_state.py
│   └── nodes/
│       ├── corpus_curation.py
│       ├── graph_build.py
│       └── discovery.py
├── extraction/
│   ├── schemas.py
│   ├── scientific_extractor.py
│   └── evidence_validator.py
├── graph/
│   ├── ontology.py
│   ├── entity_resolver.py
│   ├── repository.py
│   ├── traversal.py
│   └── versioning.py
├── retrieval/
│   ├── graph_rag.py
│   ├── graph_query_understanding.py
│   ├── context_packer.py
│   └── graph_citation_validator.py
├── screening/
│   ├── criteria.py
│   ├── deduplicator.py
│   ├── screener.py
│   └── repository.py
├── discovery/
│   ├── candidate_generator.py
│   ├── candidate_ranker.py
│   └── validators/
│       ├── novelty.py
│       ├── compatibility.py
│       ├── counterevidence.py
│       ├── scientific_value.py
│       └── feasibility.py
├── services/
│   ├── corpus_jobs.py
│   ├── graph_build_jobs.py
│   ├── discovery_jobs.py
│   └── research_vector_store.py
└── repositories/
    ├── protocols.py
    ├── corpus.py
    ├── scientific_graph.py
    └── discovery.py
```

Không sửa `src/services/vector_store.py` thành một class làm tất cả. Giữ adapter
hiện tại cho V1 và thêm `ResearchVectorStore` dùng payload/chunk contract mới.

---

## 12. Worker, idempotency và concurrency

Job API không chạy toàn pipeline trong HTTP request. Pattern:

```text
POST mutation
  → validate auth + idempotency
  → insert queued job trong PostgreSQL
  → worker claim bằng lease / SKIP LOCKED
  → LangGraph chạy với PostgreSQL checkpointer
  → API poll/SSE progress
```

Trong release đầu có thể tái sử dụng recovery scanner/job service hiện tại.
Không tạo `asyncio.create_task` như cơ chế duy nhất ở production.

Concurrency lock:

- Tối đa một curation run `running` cho mỗi project + protocol version.
- Tối đa một graph build `running` cho mỗi corpus version.
- Tối đa một discovery run cùng strategy version cho mỗi graph version.
- Dùng PostgreSQL advisory lock hoặc partial unique index.

Idempotency hash gồm:

```text
actor_id + project_id + action_type + canonical request body + base version ID
```

Cùng key/cùng payload trả lại resource cũ. Cùng key/khác payload trả `409`.

### 12.1 Operational bounds mặc định

Các giá trị phải đưa vào `Settings`, có min/max bằng Pydantic và được snapshot
vào job input để một job đang chạy không đổi hành vi khi deploy config mới:

```text
CURATION_MAX_SEARCH_QUERIES=5
CURATION_OPENALEX_PAGE_SIZE=200
CURATION_MAX_SOURCE_PAGES=25
CURATION_MAX_IDENTIFIED_PAPERS=5000
CURATION_SCREENING_BATCH_SIZE=8
CURATION_SCREENING_CONCURRENCY=4
CURATION_MAX_SCHEMA_RETRIES=1
CURATION_MAX_REVIEW_QUEUE=1000

GRAPH_EXTRACTION_BATCH_SIZE=5
GRAPH_EXTRACTION_CONCURRENCY=4
GRAPH_MAX_UNRESOLVED_MENTIONS=500

GRAPHRAG_MAX_HOPS=2
GRAPHRAG_TOP_K_ENTITIES=10
GRAPHRAG_TOP_K_EVIDENCE=20
GRAPHRAG_MAX_TRAVERSED_EDGES=200
GRAPHRAG_CONTEXT_TOKEN_BUDGET=12000
GRAPHRAG_QUERY_TIMEOUT_SECONDS=30

DISCOVERY_MAX_GENERATED_CANDIDATES=200
DISCOVERY_MAX_VALIDATED_CANDIDATES=25
DISCOVERY_SEARCH_RESULTS_PER_CANDIDATE=20
DISCOVERY_VALIDATION_CONCURRENCY=3
```

Khi chạm cap, job phải hoàn tất với warning/partial scope rõ ràng hoặc fail bằng
error code có chủ đích; không cắt dữ liệu âm thầm.

---

## 13. Versioning và invalidation

Version chain:

```text
protocol_version
    ↓
search/screening decisions
    ↓
corpus_version
    ↓
graph_version
    ↓
discovery_run
    ↓
candidate + validation runs
```

Khi protocol đổi:

- corpus cũ vẫn đọc được;
- không tự thêm/xóa paper trong corpus cũ;
- curation run mới tạo corpus version mới.

Khi corpus đổi:

- graph version cũ vẫn đọc được;
- graph build mới tạo version mới;
- candidate thuộc graph cũ chuyển `stale` nếu project active graph đổi.

Khi evidence mới chứng minh missing edge đã tồn tại:

- tạo edge assertion/version mới;
- candidate cũ chuyển `existing_work_found` hoặc `stale`;
- giữ validation/reviewer history;
- không hard-delete candidate.

---

## 14. LLM safety và prompt contract

Mỗi LLM use case có schema và `prompt_version` riêng:

```text
screening.abstract.v1
extraction.scientific_entities.v1
extraction.scientific_relations.v1
validation.compatibility.v1
validation.scientific_value.v1
generation.research_question.v1
```

Quy tắc:

1. Temperature mặc định `0` cho screening/extraction/validation.
2. Prompt input ghi rõ paper text là untrusted content.
3. Không expose arbitrary tool list cho extraction/screening.
4. Structured output phải Pydantic validate.
5. Unknown field/type bị reject.
6. Mọi quote exact-match trước khi persist/publish.
7. Log provider/model/prompt version/latency/token; không log API key.
8. Retry schema tối đa 1 lần; provider retry dùng policy hiện tại.
9. LLM không quyết định authorization, version ID hoặc final reviewer verdict.

---

## 15. Observability

Mỗi job/node log tối thiểu:

```text
correlation_id
job_id
project_id
protocol/corpus/graph version ID
node_name
attempt
input_count
output_count
duration_ms
provider/model nếu có
warning/error code
```

Progress event ví dụ:

```json
{
  "event_type": "curation.abstract_screen.completed",
  "job_id": "curationjob_...",
  "project_id": "project_...",
  "counts": {"include": 80, "exclude": 160, "maybe": 17},
  "created_at": "2026-08-10T10:00:00Z"
}
```

Metrics:

### Screening

- dedupe precision;
- screening recall trên gold set;
- include/exclude agreement giữa LLM và reviewer;
- false exclusion rate — metric quan trọng nhất;
- reviewer minutes saved;
- cost/1,000 screened papers.

### Extraction/Graph

- entity precision/recall;
- relation precision/recall;
- entity resolution accuracy;
- exact evidence coverage;
- unsupported edge rate;
- duplicate entity rate.

### Discovery

- existing-work false positive rate;
- candidate compatibility pass rate;
- counterevidence retrieval rate;
- reviewer acceptance rate;
- stale candidate invalidation correctness.

---

## 16. Test strategy

### 16.1 Unit tests

```text
tests/screening/test_criteria.py
tests/screening/test_deduplicator.py
tests/screening/test_screening_output_validation.py
tests/graph/test_ontology.py
tests/graph/test_evidence_exact_match.py
tests/graph/test_entity_resolution.py
tests/graph/test_traversal.py
tests/retrieval/test_graph_query_understanding.py
tests/retrieval/test_graph_context_packer.py
tests/retrieval/test_graph_citation_validator.py
tests/discovery/test_model_dataset_task_rule.py
tests/discovery/test_candidate_lifecycle.py
tests/discovery/test_scoring.py
```

Các test LLM dùng fixture/structured response giả, không gọi provider thật.

### 16.2 PostgreSQL integration tests

- migration chạy từ schema hiện tại;
- FK/check/unique constraint hoạt động;
- project A không đọc record project B;
- concurrent run không tạo duplicate version;
- cùng corpus input cho cùng corpus hash;
- version cũ immutable;
- effective screening decision chọn đúng supersede chain.

### 16.3 Qdrant integration tests

- index/query filter đúng project + corpus version;
- không trả chunk project khác;
- deterministic point ID;
- reindex không nhân đôi;
- rebuild từ PostgreSQL;
- fallback khi Qdrant unavailable.

### 16.4 GraphRAG tests

- exact/alias query resolve đúng seed entity;
- traversal chỉ dùng edge thuộc requested graph version;
- `max_hops > 2` bị reject;
- context pack không vượt token/edge limit;
- không retrieve project/corpus khác;
- LLM citation ngoài context ID bị reject;
- evidence rỗng trả `insufficient_evidence`;
- Qdrant down vẫn trả được local graph result nếu PostgreSQL evidence đủ;
- response luôn có `graph_version_id`, `content_scope` và limitations.

### 16.5 Workflow tests

1. Happy path: search → screen → corpus ready.
2. Qdrant down: lexical fallback + warning.
3. Abstract unclear: interrupt → reviewer resume.
4. Empty eligible corpus: bounded fail.
5. Extraction quote không exact-match: edge rejected.
6. Entity ambiguous: reviewer queue.
7. Missing edge candidate nhưng novelty tìm thấy paper: existing work found.
8. Candidate pass validation → reviewer approve.
9. Graph version mới → candidate cũ stale.
10. Worker restart → resume từ PostgreSQL checkpoint, không duplicate artifact.

### 16.6 Regression

Toàn bộ test V1/V2 hiện tại phải pass. Endpoint và response cũ không đổi trong
cùng release.

---

## 17. Thứ tự triển khai

### Milestone 0 — Contract và migration foundation

- Chốt ontology, states, reason codes và API schemas.
- Thêm migrations protocol/paper/screening/corpus.
- Thêm repositories và project authorization tests.
- Chưa bật UI/feature flag production.

**Done khi:** migration chạy sạch; schema contract tests pass; không phá V1/V2.

### Milestone 1 — Corpus Curation MVP

- Protocol API/versioning.
- OpenAlex identification + canonical paper store.
- Deterministic dedupe.
- Qdrant ranking + lexical fallback.
- Title/abstract screening structured output.
- Screening HITL.
- Corpus version + flow statistics.

**Done khi:** tạo được included corpus reproducible và UI có dữ liệu vẽ flow.

### Milestone 2 — Graph Foundation

- Abstract chunks.
- Scientific extraction schema.
- Evidence validator.
- Entity resolution MVP.
- Edge assertions + graph version.
- Graph query API.
- GraphRAG local/hybrid retrieval tối đa 2 hop.
- Context packing + grounded citation response.

**Done khi:** mọi published edge có exact evidence; graph xem được theo project;
GraphRAG trả grounded answer/citation hoặc `insufficient_evidence` đúng contract.

### Milestone 3 — Combination Engine

- `MODEL_DATASET_TASK` rule.
- Candidate hashing/dedup/ranking.
- Candidate list/detail API.

**Done khi:** candidate được sinh deterministic từ graph version và chỉ mang
trạng thái `generated`.

### Milestone 4 — Validation

- Novelty search.
- Compatibility validator.
- Counterevidence retrieval.
- Scientific value/feasibility.
- Candidate lifecycle + HITL.

**Done khi:** existing work bị reject đúng; uncertain được giữ; reviewer có thể
approve/reject với toàn bộ provenance.

### Milestone 5 — Idea/Experiment Generation

- Research question/hypothesis.
- Contribution statement.
- Experiment proposal.
- Export artifact.

**Done khi:** chỉ candidate đạt gate mới sinh proposal và proposal trace được
về candidate/evidence/version.

### Milestone 6 — Scale/Advanced (sau khi có dữ liệu đánh giá)

- Multi-source metadata.
- Full-text ingestion có quyền truy cập.
- Durable external queue/object storage.
- Shared graph promotion policy.
- Sau cùng mới đánh giá nhu cầu Neo4j/GNN.

---

## 18. Feature flags

```text
CORPUS_CURATION_ENABLED=false
LLM_SCREENING_ENABLED=false
FULL_TEXT_ELIGIBILITY_ENABLED=false
SCIENTIFIC_GRAPH_ENABLED=false
DISCOVERY_ENABLED=false
CANDIDATE_VALIDATION_ENABLED=false
SHARED_GRAPH_PROMOTION_ENABLED=false
```

Thứ tự bật:

```text
internal test
→ one pilot project
→ selected projects
→ default on sau quality gate
```

Không bật `DISCOVERY_ENABLED` nếu graph quality gate chưa đạt.

---

## 19. Definition of Done bản đầu

Corpus Curation + Graph Foundation chỉ được coi là hoàn thành khi:

- [ ] Protocol version locked trước curation.
- [ ] Search run tái lập được từ query/filter/source.
- [ ] Duplicate được giải thích bằng match method.
- [ ] Mọi screening decision có stage, reason, source và timestamp.
- [ ] Embedding không tự động hard-exclude paper.
- [ ] Borderline case đi qua reviewer queue.
- [ ] Corpus version immutable và có reproducible hash.
- [ ] Qdrant có thể rebuild hoàn toàn từ PostgreSQL.
- [ ] Mọi graph edge publish có exact-match evidence.
- [ ] Graph query không leak cross-project.
- [ ] Candidate chưa validation không được gọi research gap.
- [ ] Worker restart không làm mất job hoặc tạo duplicate version.
- [ ] V1/V2 regression suite pass.
- [ ] Có gold set nhỏ để đo screening recall và edge precision.
- [ ] API schema, frontend typed client và tài liệu được cập nhật cùng release.

---

## 20. Tóm tắt cho dev bắt đầu code

Không rewrite ReviewGraph. Bắt đầu bằng migration và `CorpusCurationGraph`.

Thứ tự PR khuyến nghị:

```text
PR 1: protocol + paper + screening + corpus migrations/models
PR 2: repositories + Pydantic schemas + protocol API
PR 3: OpenAlex normalization + dedupe + search run persistence
PR 4: ResearchVectorStore + screening validation
PR 5: CorpusCurationGraph + job service + HITL
PR 6: corpus/flow API + integration/e2e tests
PR 7: graph migrations + ontology + extraction/evidence validation
PR 8: GraphBuildGraph + graph APIs
PR 9: MODEL_DATASET_TASK candidate generator
PR 10: validation pipeline + candidate HITL
```

Điểm nối duy nhất với flow cũ ở giai đoạn đầu là reuse OpenAlex adapter,
LLM routing/tracing, PostgreSQL job/checkpoint, Qdrant client pattern,
project authorization và reviewer/version infrastructure. Các artifact mới có
version riêng để không làm thay đổi contract V1/V2 đang chạy.
