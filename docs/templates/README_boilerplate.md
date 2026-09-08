# LitReview Agent — AI Research Assistant

> Nghiên cứu tài liệu thủ công, khó truy vết trích dẫn và khó xác định research gap → trợ lý AI tìm, sàng lọc, tổng hợp bằng chứng có kiểm duyệt → dành cho sinh viên, nghiên cứu viên và reviewer.

## Vấn đề

Người làm nghiên cứu phải đọc và đối chiếu nhiều bài báo trước khi có một bản tổng quan đáng tin cậy. Việc này tốn thời gian, dễ bỏ sót nguồn quan trọng và các công cụ AI thông thường có thể tạo claim, tác giả hoặc DOI không có bằng chứng.

- **Người gặp vấn đề:** sinh viên năm cuối, học viên cao học, nghiên cứu viên và reviewer.
- **Chi phí hiện tại:** repository chưa có baseline thủ công đủ mẫu; thời gian tiết kiệm và các KPI chi tiết phải được chứng minh bằng evaluation artifact.
- **Khoảng trống của giải pháp hiện có:** kết quả cần truy vết về nguồn học thuật và có bước reviewer duyệt thay vì tự xem bản tổng hợp AI là kết luận cuối.

## Giải pháp

LitReview Agent là workspace nghiên cứu dựa trên bằng chứng, trong đó AI tạo bản nháp còn con người quyết định việc chấp nhận.

- **Literature review có căn cứ:** tìm kiếm, sàng lọc paper, trích xuất evidence và tổng hợp claim có kiểm tra grounding.
- **Research gap có kiểm duyệt:** phân tích các khoảng trống tiềm năng, hiển thị nguồn và hỗ trợ counter-search trước khi chấp nhận.
- **Human-in-the-Loop:** `review` mode dừng để duyệt sub-query và paper. Final reviewer API có trong code nhưng graph chưa dừng ở bước cuối, nên không tuyên bố claim-level final gate đã hoàn chỉnh.
- **Research Sandbox:** không gian thử nghiệm tách biệt cho giả thuyết và phân tích dữ liệu; Graph Overlay là capability backend cũ đang bị tắt và không có trong frontend hiện tại.

## Người dùng mục tiêu

- **Chính:** sinh viên năm cuối, học viên cao học và nghiên cứu viên đang bắt đầu literature review hoặc chuẩn bị đề cương.
- **Phụ:** giảng viên, reviewer và chủ project cần kiểm tra nguồn, claim và tiến độ nghiên cứu.

## Tech Stack

| Layer | Technology |
| --- | --- |
| AI Agent | LangGraph StateGraph; Gemini, OpenAI hoặc Ollama qua lớp LLM routing |
| Backend | FastAPI, Python 3.12+, Pydantic và SQLAlchemy |
| Frontend | Next.js 16, React 19, TypeScript, App Router |
| Data | PostgreSQL cho application data/checkpoint; Redis cho dispatch/cache; Qdrant cho retrieval |
| Integration | OpenAlex, Semantic Scholar, arXiv; Clerk cho xác thực |
| DevOps | Docker Compose; runbook deploy Ubuntu VPS |

## Quick Start

### Yêu cầu

- Python 3.12+
- Node.js 20+
- Google Gemini API key, OpenAI hoặc Ollama
- Supabase account hoặc PostgreSQL local

```bash
# 1. Clone và cấu hình môi trường
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-178.git
cd P-178
cp .env.example .env

# 2. Chạy backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make run

# 3. Chạy frontend (một terminal khác)
cd frontend
npm install
npm run dev
```

- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:3000`

Để chạy toàn bộ stack bằng Docker, dùng `docker compose up --build`. Hướng dẫn vận hành chi tiết nằm tại [runbook Ubuntu VPS](../operations/DEPLOY_UBUNTU_VPS_NATIVE.md).

## Cấu trúc dự án

```text
P-178/
├── frontend/                  # Next.js application
├── src/
│   ├── agents/                # LangGraph state, nodes và tools
│   ├── api/                   # FastAPI routers
│   ├── services/              # Nghiệp vụ, job và LLM routing
│   ├── research_sandbox_service/ # Sandbox tách biệt cho phân tích dữ liệu
│   ├── models/                # Schema và data model
│   └── validation/            # Grounding và kiểm tra evidence
├── contracts/                 # API/data contracts V1–V4
├── docs/                      # Architecture, product, roadmap và runbook
├── eval/                      # Evaluation artifacts
├── tests/                     # Test suite
├── docker-compose.yml         # Full stack local
└── README.md                  # Điểm bắt đầu của repository
```

## API Endpoints chính

| Method | Endpoint | Mô tả |
| --- | --- | --- |
| `GET` | `/health` | Kiểm tra trạng thái dịch vụ |
| `POST` | `/projects` | Tạo project mới |
| `GET` | `/projects` | Danh sách project của người dùng |
| `POST` | `/projects/{id}/reviews` | Khởi chạy AI research job |
| `GET` | `/projects/{id}/reviews` | Lấy danh sách review và trạng thái |
| `GET` | `/projects/{id}/report-versions` | Lấy các phiên bản report |
| `POST` | `/projects/{id}/conversations` | Tạo phiên Research Copilot |
| `POST` | `/conversations/{id}/messages` | Gửi tin nhắn Copilot |
| `GET` | `/review-assignments` | Lấy review được giao cho reviewer |

## Deliverables

- [x] Source code và [README](../../README.md)
- [x] [Architecture diagram](../architecture/architecture_diagram.md)
- [x] [Team worklog](../../WORKLOG.md) và [weekly journal](../project/JOURNAL.md)
- [x] Gate G2 — MVP đã pass
- [x] [Evaluation artifacts](../../eval/)
- [x] Video demo Gate G2 (được ghi trong worklog)
- [ ] Live URL public
- [ ] Pitch deck đã xác định đường dẫn

## Team

| Member | Phạm vi đóng góp theo worklog | Student ID |
| --- | --- | --- |
| Nguyễn Xuân Kiên | Sandbox, kiểm thử và demo | Chưa có thông tin |
| Nhữ Văn Hùng | Tính năng research gap, LaTeX và mind map | Chưa có thông tin |
| Tạ Hồng Quí | GraphRAG, benchmark, slide và UI | 1538 |
| Xuân Phượng | Frontend, tích hợp, deploy và merge code | 01874 |

## Tài liệu liên quan

- [Kiến trúc hệ thống](../architecture/ARCHITECTURE.md)
- [Product brief](../product/PRODUCT.md)
- [Kế hoạch MVP V1](../roadmap/README_MVP_V1.md)
- [Technical contract](../reference/README_technical_contract.md)
- [Tổng hợp tài liệu dự án](../project/PROJECT_DOCS.md)

## License

Chưa có file license được xác định trong repository.
