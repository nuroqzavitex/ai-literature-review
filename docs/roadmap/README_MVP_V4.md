# Research Agent — MVP V4: Production Platform & Advanced Retrieval

> Historical roadmap baseline. PostgreSQL, Clerk, durable worker, Redis,
> Qdrant và multi-source retrieval đã xuất hiện trong implementation; danh sách
> bên dưới vẫn hữu ích như target/gap list nhưng không phải current-state audit.

> Trạng thái: **Roadmap nâng cao — chưa triển khai.**
> Kế thừa: [README_MVP_V1.md](README_MVP_V1.md), [README_MVP_V2.md](README_MVP_V2.md) và [README_MVP_V3.md](README_MVP_V3.md).
> Contract kỹ thuật chi tiết: [`contracts/contract_v4.md`](../../contracts/contract_v4.md).

---

## 1. Vị trí của V4

Sau V3, sản phẩm đã có đầy đủ core workflows:

```text
Literature review + Gap detection                    ← V1
Research Copilot + Memory + Tool calling             ← V2 & V3A
Data analysis + Code sandbox + Human approval        ← V3B
```

V4 **không tạo thêm chatbot mới**. Mục tiêu của V4 là đưa hệ thống này lên môi trường production thực sự (scale nhiều project, nhiều user, bảo mật, đo lường được) và **mở rộng Retrieval (RAG)** một cách có kiểm soát.

V4 chia thành 2 phần:
- **V4.1 (Bắt buộc):** Chuyển đổi kiến trúc sang production (PostgreSQL, Queue, Auth, Memory Governance, Evaluation).
- **V4.2+ (Feature Gated):** Multi-source, Full-text, Vector Search (chỉ bật khi có data chứng minh hiệu quả).

---

## 2. Điều kiện bắt đầu

- [ ] V1–V3 có acceptance report và dữ liệu KPI thật.
- [ ] Copilot V2–V3 có gold conversation/action set và không có mutation nào bị bypass (chưa xác nhận).
- [ ] Memory có gold set cho các thao tác write/retrieve/stale/supersede/delete.
- [ ] Đã xác định rõ bottleneck hiện tại (VD: abstract chưa đủ thông tin, OpenAlex thiếu bài quan trọng).
- [ ] Có kế hoạch migration từ SQLite/process-local tasks sang hạ tầng production.

---

## 3. V4.1 — Production Platform (Bắt buộc)

Phần này là nền tảng để vận hành SaaS/Enterprise, không thêm tính năng AI mới.

### 3.1. Infrastructure & Architecture
- **AuthN/AuthZ:** Xác thực thật, phân quyền RBAC (Admin, Researcher, Reviewer) theo cấp độ Project. Client không được tự giả mạo `role`.
- **Database:** PostgreSQL làm Source of Truth (thay thế SQLite).
- **Async Workers:** Durable job queue, idempotency, reconciliation cho các task dài (search, ingestion, sandbox).
- **Object Storage:** Có mã hóa, retention, scoped access.
- **Model Gateway:** Capability-aware routing, quản lý cost, quota, budget per-project, retry/failover.

### 3.2. Memory Governance
Memory (Session, Project, Evidence, User Preference) phải tuân thủ luật bảo mật:
- **Project Isolation:** Data của project A tuyệt đối không leak sang project B.
- **Lifecycle:** Có TTL (Session ngắn, Project theo retention), hỗ trợ Export và Delete hoàn toàn.
- **Consent:** User preference là opt-in.
- **No Hallucination:** LLM không được tự ý biến một hypothesis thành factual memory.

### 3.3. Evaluation Framework
Đánh giá Offline (Gold set) và Online (Reviewer feedback):
- Literature: Reference Validity, Claim-support Accuracy, Facet extraction, Gap precision.
- Copilot: Factual-answer citation coverage, unsupported answer rate.
- Analytics: Cost per job, latency, unconfirmed mutation rate.

---

## 4. V4.2+ — Advanced Retrieval (Feature Gated)

Các tính năng này tốn kém (compute, cost, latency), nên chỉ được release khi vượt qua **Release Gates**.

### V4.2: Multi-source Metadata
- **Tính năng:** Bổ sung arXiv, Semantic Scholar.
- **Gate:** Chỉ release nếu coverage tăng ≥ 15% ở topic mục tiêu và dedup precision ≥ 98%. Không cộng gộp citation count sai lệch.

### V4.3: Full-text Ingestion Quy Mô Lớn
- **Tính năng:** Tải TEI XML/PDF, parse section, validate quality, chunking.
- **Gate:** Abstract hiện tại được chứng minh là thiếu evidence quan trọng. Parse success ≥ 90%. Tuân thủ bản quyền, không vượt paywall trái phép.

### V4.4: Vector Retrieval, Reranker & Map-Reduce
- **Tính năng:** Qdrant vector search, hybrid search, hierarchical synthesis cho long-documents.
- **Quy tắc:** Qdrant chỉ là *derived index*, phải rebuild được từ PostgreSQL/Object Storage. Không gọi LLM tool `write_embedding`.
- **Gate:** Retrieval Recall@10 ≥ 0.80. Reranker/Map-reduce phải cải thiện quality đủ bù lại chi phí latency/cost tăng thêm.

---

## 5. Metrics & Release Gates (Quy định chất lượng)

**Security & Resilience:**
- Authorization bypass = 0.
- Job loss sau worker restart = 0.
- Cross-project / cross-user memory leakage = 0.
- Sandbox escape / unauthorized mutation = 0.

**AI Quality:**
- Reference Validity = 100%.
- Claim-support Accuracy ≥ 80%.
- Factual-answer citation coverage = 100%.
- Citation ngoài project/content scope = 0.
- Stale/superseded/deleted memory được dùng như current fact = 0.
- Giảm thiểu active-human-time median ≥ 50%.

---

## 6. Definition of Done V4

- [ ] AuthN/AuthZ và project isolation được backend enforce chặt chẽ.
- [ ] Project dashboard, reviewer assignment, audit log hoạt động tốt.
- [ ] PostgreSQL, Durable Workers, Object Storage vận hành ổn định, có backup/restore.
- [ ] Memory Service enforce đúng scope, consent, version, retention, export và delete.
- [ ] Tool permission, quota, budget được backend bảo vệ.
- [ ] Evaluation Framework chạy tự động theo version, hiện KPI/Regression dashboard.
- [ ] Qdrant/Queue/Storage được giấu sau Backend Services, không phải là công cụ (tool) mở cho LLM.
- [ ] Multi-source, Full-text, Vector search được bọc trong feature flag và chỉ mở khi đạt Gate.
- [ ] Các metrics bảo mật và chất lượng (mục 5) đều đạt yêu cầu.
