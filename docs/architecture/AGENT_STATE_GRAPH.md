# LitReview Agent — Luồng thực thi chính

Tài liệu này là nguồn mô tả chuẩn cho luồng literature review trong `src/agents/graph.py`; các nhánh điều kiện lấy từ hàm `after_*`. Ảnh render (nếu cần) nằm tại `docs/architecture/agent_input_flow.png`.

## Luồng bao quanh graph (không nằm trong LangGraph)

```mermaid
flowchart LR
    FE["Frontend<br/>Project workspace"] -->|"POST /api/v1/projects/{project_id}/reviews"| API["research_copilot.py<br/>link project + tạo queued job"]
    API --> DB[("PostgreSQL<br/>jobs + checkpoints")]
    API -->|"notify, best effort"| R[("Redis Streams")]
    R --> W
    W["Worker<br/>(embedded / external)<br/>lease + heartbeat + fence"] -->|poll| DB
    W -->|"astream(initial_state)"| G["LangGraph<br/>intent_guardrail → …"]
    G -->|mỗi node| DB
    G -->|"⏸ subqueries / papers"| DB
    FE -->|"POST /api/v1/reviews/{job_id}/resume<br/>subqueries hoặc papers"| DB
    FE -.->|"final reviewer API tồn tại nhưng graph hiện không chờ ở bước cuối"| DB
```

- Graph được compile với `AsyncPostgresSaver` trong `src/services/jobs.py` và chạy bằng `astream(..., stream_mode="updates")`.
- Hai HITL stage đang hoạt động là `subqueries` và `papers`; response được lưu
  trong PostgreSQL rồi worker resume checkpoint.
- `human_review_node` hiện tự đặt `hitl_decision="approve"` cho cả `review` và
  `autonomous`, đúng với test `test_final_review_is_approved_automatically`.
  Project-scoped final reviewer API/schema vẫn còn để tương thích, nhưng không
  phải một gate có thể đạt tới sau khi graph hoàn tất. Đây là implementation gap,
  không được trình bày như chức năng đã cưỡng chế.

## State graph đầy đủ (18 node, 8 nhánh điều kiện)

```mermaid
flowchart TD
    START(["👤 User query<br/>POST /api/v1/projects/{project_id}/reviews"]) --> IG

    subgraph PHASE1["1️⃣ Guard & Planning"]
        IG["🛡 intent_guardrail<br/>phân loại intent bằng LLM"]
        PS["📋 plan_search<br/>sinh sub-queries + terms"]
        RSQ["👀 review_subqueries<br/>HITL duyệt sub-queries"]
    end

    IG -->|"intent = litreview"| PS
    IG -->|"ngoài phạm vi"| OOS["🚫 out_of_scope"]
    OOS --> DONE_END(["⏹ END"])
    PS --> RSQ
    RSQ --> SEARCH

    subgraph PHASE2["2️⃣ Retrieval loop"]
        SEARCH["🔎 search_academic_sources<br/>OpenAlex + Semantic Scholar + arXiv"]
        AS{"📊 assess_sources"}
        REF["🔁 refine_query"]
    end

    SEARCH --> AS
    AS -->|"error"| FAIL
    AS -->|"0 paper sau ≥2 lần thử"| FAIL
    AS -->|"<10 paper, còn lượt"| REF
    REF --> SEARCH
    AS -->|"đủ nguồn"| SCREEN

    subgraph PHASE3["3️⃣ Corpus selection"]
        SCREEN{"🧹 screen_papers<br/>lọc + rank relevant"}
        RP["👀 review_papers<br/>HITL chọn paper + ingest/index"]
    end

    SCREEN -->|"error / no match"| FAIL
    SCREEN -->|ok| RP
    RP --> EX

    subgraph PHASE4["4️⃣ Evidence & Claims"]
        EX["📄 extract_evidence<br/>quote từ full text/abstract đã chuẩn bị"]
        SYN["🧠 synthesize_claims<br/>LLM sinh claims từ evidence"]
        VG{"✅ validate_grounding<br/>entailment check từng claim"}
        REV["✏️ revise_claims<br/>sửa/tách claim bị loại"]
    end

    EX -->|"error"| FAIL
    EX -->|ok| VG
    SYN --> VG
    REV --> VG
    VG -->|"error"| FAIL
    VG -->|"0 claim valid + còn papers"| COMP
    VG -->|"0 claim valid + hết papers"| FAIL
    VG -->|"có claim bị loại, lần sửa 1"| REV
    VG -->|"chưa synthesize"| SYN
    VG -->|"đã synthesize, chưa gap"| GAP
    VG -->|"đã xong gap"| COMP

    subgraph PHASE5["5️⃣ Report & finalize"]
        GAP["🕳 analyze_research_gaps"]
        COMP["📝 compose_literature_review<br/>report + citations [n]"]
        HR["human_review<br/>legacy bridge: tự approve"]
        FIN["🏁 finalize"]
    end

    GAP --> COMP
    COMP --> HR
    HR -->|"continue"| FIN
    FIN --> DONE_END

    FAIL["💥 fail_node"] --> FAIL_END(["⏹ END + lý do lỗi"])

    style RSQ fill:#fff3bf
    style RP fill:#fff3bf
    style HR fill:#e7f5ff
    style FAIL fill:#ffe3e3
    style FAIL_END fill:#ffe3e3
```

## Bản đồ node → code

| Node | File | Vai trò |
|---|---|---|
| `intent_guardrail` | `src/agents/nodes/litreview.py` | LLM phân loại intent; chặn query ngoài phạm vi |
| `plan_search` / `review_subqueries` | `litreview.py` | Sinh sub-queries, HITL duyệt (review mode) |
| `search_academic_sources` | `litreview.py` + `src/services/academic_search.py` | Gọi OpenAlex / Semantic Scholar / arXiv |
| `assess_sources` / `refine_query` | `litreview.py` | Đánh giá số lượng nguồn, refine nếu <10 paper (tối đa 2 lần) |
| `screen_papers` / `review_papers` | `litreview.py` + `paper_ingestion.py` / `vector_store.py` | Lọc relevant, HITL chọn corpus, tải OA full text khi có và index Qdrant |
| `extract_evidence` | `litreview.py` | Trích quote từ full-text context đã chuẩn bị hoặc abstract fallback |
| `synthesize_claims` / `revise_claims` | `litreview.py` | Sinh / sửa claims gắn quote |
| `validate_grounding` | `litreview.py` | Entailment check từng claim so với quote gốc |
| `analyze_research_gaps` | `litreview.py` | Phát hiện research gap từ claims |
| `compose_literature_review` | `litreview.py` | Tổng hợp report + citation marker `[n]` |
| `human_review` / `finalize` / `fail` | `litreview.py` | Tự approve ở runtime hiện tại, hoàn tất, hoặc kết thúc lỗi có lý do |

## Quy tắc routing (`after_*` trong graph.py)

- `after_intent_guardrail`: chỉ `intent == "litreview"` mới vào pipeline, ngược lại `out_of_scope` → END.
- `after_assess_sources`: `error` hoặc 0 paper sau ≥2 lần thử → `fail`; <10 paper còn lượt → `refine_query` → quay lại search; đủ → `screen_papers`.
- `after_screen_papers`: corpus rỗng sau lọc → `fail` terminal (không cho report rỗng gây hiểu lầm).
- `after_validate_grounding` (node phân nhánh nhiều nhất):
  - 0 claim valid nhưng còn papers → vẫn `compose_literature_review` (report minh bạch giới hạn evidence);
  - có claim bị loại và chưa sửa lần nào → `revise_claims` → quay lại validate;
  - chu trình synthesize → validate → gap → compose tạo **2 vòng** qua `validate_grounding`.
- `after_human_review` vẫn có nhánh `request_changes` để tương thích checkpoint
  cũ, nhưng state mới luôn nhận `approve` từ `human_review_node` và đi thẳng tới
  `finalize`.

## Evidence và research gap trong luồng chính

`synthesize_claims` tạo theme và `potential_gaps` từ corpus đã được kiểm tra grounding. `analyze_research_gaps` chỉ phân loại và chuẩn bị thông tin review; nó không được phép khẳng định một chủ đề hoàn toàn chưa từng được nghiên cứu ngoài corpus hiện có.

Mỗi gap cần giữ phạm vi, evidence quote và truy vấn counter-search. API/UI có
thao tác review gap riêng sau khi report tồn tại; graph literature review hiện
không chờ reviewer ở bước cuối. Với chi tiết của workflow research-gap độc lập,
xem [RESEARCH_GAP_FLOW.md](RESEARCH_GAP_FLOW.md).
