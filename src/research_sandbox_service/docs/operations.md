# Runbook vận hành

## Thứ tự triển khai

1. Build và quét lỗ hổng control image cùng runtime image đã pin.
2. Publish runtime bằng digest bất biến; tính SHA-256 của
   `sandbox_runtime/requirements.lock` cho `SANDBOX_PACKAGE_MANIFEST_HASH`.
3. Cấp PostgreSQL và bucket S3 riêng, có mã hóa, retention/lifecycle và credential tối thiểu.
4. Chạy `alembic -c alembic.ini upgrade head` bằng migration job một lần.
5. Khởi động control, kiểm tra `/healthz`, `/readyz`, `/metrics`.
6. Khởi động worker với `SANDBOX_WORKER_ID` ổn định, workspace dùng chung và launcher được duyệt.
7. Bật cờ tổng, sau đó bật từng mode theo staged rollout.

Không dùng secret/digest placeholder của Compose cục bộ trong production.

## Cấu hình production bắt buộc

- `SANDBOX_ENVIRONMENT=production`, `SANDBOX_ENABLED` và các mode cần dùng.
- `SANDBOX_PERSISTENCE_BACKEND=postgres`, `SANDBOX_DATABASE_URL`.
- `SANDBOX_OBJECT_STORAGE_BACKEND=s3` cùng bucket/endpoint/credential/SSE.
- Current/previous key ID và key của service-auth, context-signing.
- `SANDBOX_MANIFEST_SIGNING_KEY`.
- `SANDBOX_RUNTIME_IMAGE_DIGEST=name@sha256:<64 hex>`.
- `SANDBOX_PACKAGE_MANIFEST_HASH=<64 hex>`.
- Factory Project AI, graph-reader và adoption-sink tương ứng capability bật.
- Runtime workspace/seccomp path cùng worker lease/poll setting.

Production fail-fast nếu dùng persistence/storage local, local actor header,
placeholder key hoặc runtime identity có thể thay đổi.

## Kiểm soát runtime

Launcher phải dùng UID/GID 10001, root read-only, drop toàn bộ capability,
`no-new-privileges`, seccomp, `network=none`, 1 CPU, 2 GiB RAM, 32 PID, timeout
120 giây, log/output quota. Code, dataset và output mount cố định; chỉ output được ghi.
Worker gia hạn lease khi chạy và signal runtime khi cancel hoặc mất lease.

Mount Docker socket trao quyền host rất lớn. Production nên dùng node worker
riêng hoặc runtime proxy bị giới hạn, không đặt chung workload khác.

## Probe và telemetry

- `/healthz`: chỉ kiểm tra process còn sống.
- `/readyz`: kiểm tra PostgreSQL/object storage/runtime; trả `503` thì loại instance khỏi service.
- `/metrics`: Prometheus text exposition của control/worker.

Log là structured log với safe field. Không log request body, dataset row, stdout/stderr
child, secret hoặc signed manifest. Cảnh báo queue wait, lease loss, duplicate/idempotency,
policy rejection, timeout, validation failure, orphan cleanup, storage failure và readiness.

## Xoay key

1. Thêm key ID/key mới làm current, giữ key cũ ở chế độ verify-only.
2. Deploy verifier control trước signer core.
3. Deploy signer core dùng current key mới.
4. Chờ lâu hơn request age tối đa rồi drain instance cũ.
5. Xóa key cũ. Nonce service-auth được tiêu thụ atomically trong storage dùng chung nên vẫn chống replay khi restart/multi-replica.

Không dùng lại key ID với bytes khác.

## Migration và rollback

Backup database Sandbox trước migration. Alembic append-only và độc lập core.
Rollback: tắt toàn bộ Sandbox flag, dừng worker, chờ container kết thúc, restore
control image tương thích; chỉ downgrade DB khi revision chứng minh không mất dữ liệu.
Core V1/V2/GraphRAG vẫn hoạt động khi Sandbox tắt.

## Release gate

CI phải chạy:

```powershell
python -m alembic -c alembic.ini heads
python -m compileall -q sandbox_service sandbox_runtime/sandbox_sdk
python -m pytest tests -q --cov=sandbox_service --cov-fail-under=70
```

Môi trường release phải chạy thêm PostgreSQL migrate/reload, container security
thật, BFF authentication/project-scope và product journey với adapter production.
Từ chối release nếu có raw-row leakage, runtime network/host escape, request
service unsigned/replay, cross-project access, duplicate execution hoặc bundle tái lập thiếu.
