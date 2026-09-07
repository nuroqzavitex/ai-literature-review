# Sandbox readiness report — 2026-08-20

## Kết luận

Sandbox S0–S8 đã được nâng từ reference implementation dùng fake/in-memory thành
một deployment baseline có PostgreSQL, S3-compatible storage, worker riêng,
Docker runtime cô lập, service-to-service authentication và BFF cho frontend.

Codebase hiện đạt release gate tự động của repository. Việc bật production vẫn
cần đội triển khai cung cấp secret, immutable runtime digest và các adapter thật
cho Project AI/Graph/Adoption; cấu hình production sẽ fail-fast nếu thiếu.

## Kết quả xác minh

| Gate | Kết quả |
| --- | --- |
| Sandbox unit/security/scientific/integration/contract/E2E | 87 passed, 3 infrastructure tests skipped mặc định |
| Coverage | 75.61%, gate 70% |
| PostgreSQL migration + persistence/lease/idempotency opt-in | 1 passed |
| Docker runtime/seccomp opt-in | 2 passed |
| Core V1/V2/conversation/auth + Sandbox BFF regression | 58 passed |
| Alembic | `s0007 (head)` |
| Compose bootstrap | migration exit 0; PostgreSQL, MinIO và control healthy; worker ready |

Ba test skipped trong suite mặc định chính là ba test hạ tầng opt-in ở hai dòng
tiếp theo và đã được chạy riêng thành công trên Docker/PostgreSQL thật.

## Blocker đã đóng

- Persistence production và transaction append-only: PostgreSQL repository,
  schema guard S0007, atomic plan/result review, durable lease, idempotency và
  replay nonce.
- Storage production: S3-compatible adapter, upload compensation, tombstone-first
  delete và artifact download có kiểm tra hash.
- Runtime: Docker launcher thật, image/package pinning, no shell, network none,
  non-root, read-only filesystem, dropped capabilities, seccomp, timeout,
  heartbeat lease, active cancellation và host-side artifact quotas.
- Authentication: HMAC trên exact request bytes, content digest, timestamp,
  correlation/actor context, key rotation và durable replay protection.
- Frontend contract: BFF allowlist theo project, capabilities, session lifecycle,
  questions/plans/decisions, run history, validation/interpretation/citations,
  artifact content, review, reproducibility bundle và adoption hand-off.
- Observability: structured safe logging, Prometheus metrics, dependency-aware
  readiness cho control và worker.
- Supply chain: base image pinned theo digest và dependency lock có hash.
- Regression: sửa truy vấn PostgreSQL conversation context dùng untyped NULL;
  Sandbox kill switch không làm hỏng luồng lõi.

## Điều kiện trước khi bật production

1. Cấp secrets ngoài source: manifest signing, service auth, context signing,
   PostgreSQL và object storage; thiết lập quy trình rotation.
2. Build/push runtime image rồi điền digest thật và package manifest hash thật.
3. Inject implementation thật cho `ProjectAIClient`, `GraphSnapshotReader` và
   adoption bridge theo các mode được bật.
4. Chạy migration job trước control/worker và cấu hình retention/backup cho DB,
   bucket và audit records.
5. Chạy load test, provider-failure drill và security review trong hạ tầng đích;
   các bước này phụ thuộc môi trường nên không thể chứng nhận chỉ từ local suite.

## Handoff frontend

Frontend chỉ gọi main-backend BFF dưới
`/api/v1/projects/{project_id}/sandbox`; không gọi Sandbox Control Service trực
tiếp và không tự tạo HMAC headers. Bắt đầu bằng endpoint capabilities để quyết
định hiển thị mode/action, sau đó dùng open-session hoặc các proxy path được
allowlist. Chi tiết payload, state machines, polling và error envelope nằm trong
`docs/frontend-contract.md`.
