# Research Experiment Sandbox (S0–S8)

Thư mục này chứa control plane Sandbox có thể triển khai độc lập, worker bền vững và runtime phân tích được gia cố. Sandbox sở hữu chuỗi Alembic riêng (`s0001` đến head hiện tại), schema PostgreSQL và object storage. Trình duyệt phải đi qua BFF đã xác thực của backend lõi, không gọi trực tiếp control service.

## Thành phần

- `sandbox_service`: FastAPI control API, domain service và adapter.
- `sandbox_service.worker`: worker xử lý job có lease bền vững.
- `sandbox_runtime`: container non-root, không mạng và `sandbox_sdk` nội bộ.
- `migrations`: các revision Alembic độc lập của Sandbox.
- `tests`: test unit, contract, security, scientific, integration và product-flow.
- `docker-compose.sandbox.yml`: PostgreSQL, MinIO, migration job, control và worker.

Công tắc tổng `SANDBOX_ENABLED=false` là mặc định. Các cờ mode không thể vượt qua công tắc này. Luồng core V1/V2/GraphRAG không import mã Sandbox và không gửi request Sandbox nếu người dùng chưa chủ động gọi action qua BFF.

## Kiểm tra cục bộ

Dùng một môi trường Python 3.12+ duy nhất và cài package cùng dependency test.

```powershell
cd research-sandbox
python -m pip install -e ".[dev]"
python -m alembic -c alembic.ini heads
python -m pytest tests -q
```

Bộ security bằng container thật cần Docker nên được bật riêng:

```powershell
docker build -t research-sandbox-runtime:test sandbox_runtime
$env:RUN_DOCKER_SANDBOX_TESTS = "1"
$env:SANDBOX_RUNTIME_SMOKE_IMAGE = "research-sandbox-runtime:test"
python -m pytest tests/security/test_runtime_container.py -q
```

Lock dependency control được sinh từ `pyproject.toml` vào `requirements.control.lock`; lock runtime được sinh từ `sandbox_runtime/requirements.in`. Cả hai image đều cài lock với `--require-hashes`.

## Stack cục bộ

Từ thư mục gốc repository, một lệnh sẽ khởi động toàn bộ ứng dụng và các service
Sandbox:

```powershell
docker compose up --build
```

Khi cần chạy riêng Sandbox để debug, vẫn có thể dùng:

```powershell
cd research-sandbox
docker compose -f docker-compose.sandbox.yml up --build
```

Compose build runtime image, khóa image ID và package-manifest hash, rồi mới khởi
động control/worker. PostgreSQL, console MinIO, probe control và worker chỉ bind
loopback. Migration và các bootstrap job phải hoàn tất trước control/worker.
Worker chỉ dùng Docker daemon để tạo container runtime đã gia cố riêng.

Mặc định Compose tắt mọi cờ sản phẩm. Muốn thử mode, phải bật cờ rõ ràng và cung cấp adapter factory/secret thật. Production sẽ fail-closed nếu thiếu PostgreSQL, S3 dùng chung, signing key không phải key dev, image digest bất biến hoặc package-manifest hash thật.

## Tích hợp trình duyệt

Dùng endpoint backend lõi:

- `GET /api/v1/projects/{project_id}/sandbox/capabilities`
- `POST /api/v1/projects/{project_id}/sandbox/open-session`
- `/api/v1/projects/{project_id}/sandbox/{allowlisted_sandbox_path}`

Backend lõi lấy actor và membership từ session đã xác thực, ký đúng byte request đi ra và chỉ chuyển tiếp method/path trong allowlist. Actor hoặc HMAC header do trình duyệt gửi bị bỏ qua. Khi Sandbox tắt hoặc không khả dụng, BFF trả capability giới hạn hoặc `503` có kiểu lỗi rõ ràng mà không làm hỏng API lõi.

Xem [Hợp đồng frontend](docs/frontend-contract.md) và [Runbook vận hành](docs/operations.md).

## Bất biến bảo mật

- Raw dataset row không đi vào AI prompt hoặc application log.
- Python sinh ra phải qua AST policy trước dispatch.
- Runtime non-root, read-only, không capability, giới hạn PID/CPU/RAM/thời gian và không mạng.
- Mount dataset/output cố định; SDK và host collector chặn traversal, symlink, loại file lạ và vượt quota.
- Mọi đọc/ghi giới hạn theo project; reviewer decision append-only và idempotent.
- Context, manifest, plan, code, result, artifact và bundle đều có hash; request/context snapshot được ký và chống replay.
- Sandbox không ghi trực tiếp core graph; adoption proposal được duyệt chỉ chuyển thành core draft.

## Điều kiện production

Deployment phải cung cấp implementation theo dự án cho `ProjectAIClient`, graph snapshot reader và approved adoption sink. Các adapter phải dùng cùng cơ chế phân quyền project và audit model-routing với nền tảng lõi.
