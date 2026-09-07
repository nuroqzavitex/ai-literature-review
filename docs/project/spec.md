# Technical Specification — LitReview Agent

> Tài liệu này tóm tắt các ràng buộc kỹ thuật, stack, ranh giới hệ thống và yêu cầu phi chức năng của dự án P-178.  
> Chi tiết product requirements → [`docs/product/PRD.md`](../product/PRD.md)  
> Chi tiết kiến trúc component → [`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md)

---

## 1. Tech Stack

| Layer | Công nghệ | Ghi chú |
|---|---|---|
| **Frontend** | Next.js 16 (App Router, TypeScript) | Clerk Auth, i18n VI/EN |
| **Backend API** | FastAPI (Python ≥ 3.12) | REST `/api/v1`, port 8000 |
| **AI Orchestration** | LangGraph (StateGraph) | 18 nodes lit-review + research-gap workflow |
| **LLM** | Gemini / OpenAI / Ollama / OpenCode / OpenRouter | Multi-provider fallback |
| **Academic Search** | OpenAlex · Semantic Scholar · arXiv | Parallel fetch, normalize, deduplicate |
| **Vector Store** | Qdrant | Derived index — có thể tái tạo, không phải source of truth |
| **Primary DB** | PostgreSQL | Application data + LangGraph checkpoint |
| **Cache/Queue** | Redis | Worker wake-up + status cache; fallback về PG polling |
| **Auth** | Clerk | Bearer token, JWT verification phía backend |
| **Email** | Resend (tùy chọn) | Reviewer invitation |
| **Container** | Docker Compose | Local + production |

---

## 2. Ranh giới hệ thống

```
Browser → Frontend (Next.js) → API (FastAPI) → PostgreSQL (source of truth)
                                             → Redis (dispatch + cache)
                                             → Worker → LangGraph workflows
                                                       → Academic APIs
                                                       → LLM providers
                                                       → Qdrant (index)
                              → Sandbox BFF  → Research Sandbox (isolated)
```

**Nguyên tắc ranh giới:**
- Frontend không gọi trực tiếp Sandbox service hay bất kỳ backend internal service nào.
- Worker không expose HTTP; nhận công việc qua lease/heartbeat từ PostgreSQL và Redis.
- Qdrant không chứa dữ liệu nghiệp vụ duy nhất — mất Qdrant không mất job/report.
- Research Sandbox chỉ truy cập qua BFF của core backend; browser không giữ service credential.

---

## 3. Yêu cầu phi chức năng (NFR)

### Độ tin cậy
- Worker phải resume job sau restart bằng lease + heartbeat + execution fence trong PostgreSQL.
- Mọi mutation quan trọng phải idempotent (idempotency key).
- Redis lỗi không được làm mất job đã tạo.

### Bảo mật
- Backend suy ra actor từ trusted auth context (Clerk JWT); không tin `role`/`user_id` do client khai.
- Dữ liệu project A không được truy cập từ actor chỉ thuộc project B.
- Secret chỉ ở backend/secret manager; không commit secret vào repository.
- Metadata, DOI và URL phải đến từ academic provider, không do LLM tự sinh.
- Artifact từ Sandbox là untrusted content; kiểm tra type, size và quyền trước khi phục vụ.

### Truy vết (Provenance)
- Mọi factual claim phải trỏ về paper và evidence nguồn.
- Mọi action AI quan trọng đi qua reviewer gate hoặc proposal confirmation.
- Kết quả Sandbox phải gắn với plan, code version, environment và artifact checksum.

### Hiệu năng
- API không giữ request HTTP trong khi job chạy; trả `202` + `job_id` và dùng polling.
- Frontend hủy polling khi người dùng rời màn hình hoặc khi job đạt terminal state.
- Giới hạn retry, revision và tool execution call trong mọi workflow node.

### Vận hành
- Health check riêng cho API và worker.
- Log rotation; không bind-mount source code trong production.
- Deploy chỉ được coi là thành công sau health check và smoke test các luồng chính.
- Migration đi theo roll-forward; không chạy destructive migration tự động.

---

## 4. Môi trường chạy

| Môi trường | Worker mode | Hạ tầng |
|---|---|---|
| Local | `WORKER_MODE=embedded` (API + worker cùng process) | PostgreSQL bắt buộc; Redis/Qdrant tùy chọn |
| Docker Compose | Tách `backend` và `worker` container | PostgreSQL + Redis + Qdrant + frontend |
| Production | Worker container riêng | PostgreSQL bắt buộc; Redis/Qdrant theo deployment |

---

## 5. Ràng buộc phát triển

- Python `>=3.12` (khai báo trong `pyproject.toml`; CI dùng 3.12).
- Frontend build phải nhận `NEXT_PUBLIC_*` đúng tại build time.
- Schema/API thay đổi phải cập nhật migration, contract và test liên quan trong cùng PR.
- Không giảm test coverage tổng xuống dưới 80%.
- Không sửa/xóa lịch sử dữ liệu production để giải quyết migration.

---

## 6. Tài liệu liên quan

| Tài liệu | Nội dung |
|---|---|
| [`PRD.md`](../product/PRD.md) | Product requirements, actors, functional requirements |
| [`ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) | Sơ đồ component, luồng AI, runtime và triển khai |
| [`AGENT_STATE_GRAPH.md`](../architecture/AGENT_STATE_GRAPH.md) | Chi tiết 18 node LangGraph lit-review |
| [`RESEARCH_GAP_FLOW.md`](../architecture/RESEARCH_GAP_FLOW.md) | Luồng research-gap workflow |
| [`WORKER_RUNTIME.md`](../operations/WORKER_RUNTIME.md) | Lease, heartbeat, fence và recovery |
| [`README_technical_contract.md`](../reference/README_technical_contract.md) | API contract |
| [`WORKLOG.md`](../../WORKLOG.md) | Quyết định kỹ thuật theo thời gian |
