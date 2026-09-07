# GitHub Repository Setup

Tài liệu này mô tả cấu trúc, setup và checks của repository hiện tại.

## 1. Repository map

```text
P-178/
├── src/                    # FastAPI, LangGraph, repositories/services
├── frontend/               # Next.js workspace UI
├── tests/                  # Backend unit/integration tests
├── research-sandbox/       # Controlled analysis subsystem
├── supabase/               # SQL migrations/schema artifacts
├── alembic/                # Alembic migrations
├── contracts/              # Versioned technical contracts
├── docs/                   # Architecture, product, operations, roadmap
├── data/                   # Local cache/artifacts; not the primary database
├── Makefile                # Common development commands
├── Dockerfile              # Backend image
└── docker-compose.yml      # Full local stack
```

## 2. Branch và pull request

- `main`: bản ổn định để demo/nghiệm thu.
- `feature/<short-name>`: tính năng hoặc tài liệu mới.
- `fix/<short-name>`: sửa lỗi có test tái hiện.
- Mỗi PR cần mô tả mục tiêu, phạm vi, ảnh hưởng schema/API, migration, cách test
  và rollback/deactivation khi áp dụng.
- Ít nhất một reviewer xác nhận thay đổi API, state machine hoặc guardrail.

## 3. Local setup

### Backend

```bash
cp .env.example .env
# Bỏ qua lệnh này nếu đã có PostgreSQL/Qdrant tương ứng trong .env
docker compose up -d postgres qdrant redis
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make run
```

Backend mặc định ở `http://localhost:8000`; health check là `/health`, API là
`/api/v1`. Điền provider key hợp lệ trong `.env` trước khi chạy review thật.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend mặc định ở `http://localhost:3000`. `NEXT_PUBLIC_API_BASE_URL` trỏ về
`http://localhost:8000/api/v1` khi chạy local.

### Docker Compose

```bash
docker compose up --build
```

Compose chạy frontend, backend, PostgreSQL, Redis, Qdrant và external worker.
PostgreSQL lưu application data/checkpoint; Redis và Qdrant là hạ tầng hỗ trợ.

## 4. Required checks trước khi merge

Backend:

```bash
make lint
ruff format --check src tests
make test
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
```

Smoke check tối thiểu: `GET /health`, tạo một review test, poll status, mở
structured report và kiểm tra flow reviewer `approve`/`request_changes`.

CI tại `.github/workflows/ci.yml` chạy Ruff, pytest với coverage, frontend
lint/build và các suite sandbox PostgreSQL/runtime. Required branch checks vẫn
phụ thuộc cấu hình GitHub repository, không chỉ nội dung workflow.

## 5. Secrets và dữ liệu

- Không commit `.env`, API key, token, database dump, abstract/paper dataset
  riêng tư hoặc artifact runtime.
- Dùng `.env.example` chỉ cho tên biến và giá trị placeholder.
- Log không in prompt chứa secret hoặc raw provider key.
- Cache/artifact local trong `data/` không phải backup PostgreSQL. Dataset nghiệm
  thu nên version hóa ở nơi được phê duyệt và ghi checksum.

## 6. Issue và release checklist

Issue phải ghi: mô tả, bước tái hiện, expected/actual, job ID (nếu có), log đã
ẩn secret, và phạm vi MVP liên quan.

Trước demo/release:

- [ ] `main` sạch, PR đã review.
- [ ] Ruff, format, pytest và frontend build pass.
- [ ] `.env` dùng key test hợp lệ, không xuất hiện trong diff.
- [ ] Có 2–3 topic nghiệm thu và lưu KPI reference validity, claim accuracy,
      time reduction.
- [ ] Screenshot/URL demo khớp structured report hiện tại.
- [ ] Tag/version và changelog phản ánh đúng commit đã kiểm tra.

## 7. Nguyên tắc mở rộng

Thay đổi schema/API phải cập nhật contract tương ứng và thêm migration/test.
Frontend chỉ phụ thuộc typed response, không tự suy đoán state của graph. Contract
lịch sử V1–V4 phải được gắn version; implementation hiện tại đã có multi-source,
PostgreSQL, durable worker, Qdrant và một phần capability ở các giai đoạn sau.
