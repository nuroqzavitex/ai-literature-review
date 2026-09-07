# Hợp đồng frontend

## Ranh giới tin cậy

Frontend gọi BFF backend chính tại `/api/v1/projects/{project_id}/sandbox`.
Frontend không biết URL control service, service-auth key, object-store key hay
runtime manifest. Xác thực và project membership kế thừa từ session core.

Luôn gọi trước:

```http
GET /api/v1/projects/{project_id}/sandbox/capabilities
```

Chỉ render khi `enabled=true` và `available=true`; nếu `enabled=true` nhưng
`available=false`, hiển thị trạng thái chưa kết nối và không làm hỏng workspace
chính. Mỗi mode chỉ render khi cờ tương ứng trong `modes` là true. Field
`demo_mode=true` phải được gắn nhãn “Demo local”, không được trình bày đầu ra như
kết quả mô hình thật. Các field `ai_enabled`, `graph_context_enabled`,
`result_interpretation_enabled`, `supported_dataset_formats` và
`max_dataset_bytes` dùng để điều khiển UI. Product hiện chỉ hiển thị hai mode
`hypothesis` và `data_analysis`; Graph Overlay cũ không còn được frontend khởi
tạo hoặc điều hướng tới.

## Chạy local với backend chính

Compose mặc định nối Sandbox Control vào backend chính bằng signed internal HTTP.
Backend dùng kết nối này để kiểm tra project scope và tạo Research Context đã ký:

```dotenv
SANDBOX_ENVIRONMENT=development
SANDBOX_DEMO_MODE=false
SANDBOX_CORE_BACKEND_URL=http://backend:8000
```

Sau khi đổi `.env`, phải dùng `docker compose up -d --build --force-recreate`;
`docker restart` không nạp lại biến môi trường. Session mở từ resource của core
chỉ gửi resource ID; BFF tự phân quyền và ký Research Context. Adapter demo chỉ
dành cho test cô lập khi không có backend thật.

## Dùng Project AI thật trong môi trường local

Để hypothesis, experiment, AnalysisPlan, code generation/revision và result
interpretation gọi model thật, thay riêng factory Project AI bằng adapter HTTP:

```dotenv
SANDBOX_AI_ENABLED=true
SANDBOX_RESULT_INTERPRETATION_ENABLED=true
SANDBOX_PROJECT_AI_FACTORY=sandbox_service.adapters.project_ai:create_project_ai_client
SANDBOX_AI_PROVIDER=auto
SANDBOX_AI_FALLBACK_ORDER=google,ollama
SANDBOX_AI_TIMEOUT_SECONDS=90

GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-3.1-flash-lite
OLLAMA_API_KEY=...
OLLAMA_HOST=https://ollama.com
OLLAMA_MODEL=gemma4:31b-cloud
```

`SANDBOX_AI_PROVIDER=auto` thử các provider đã cấu hình theo fallback order;
`google`/`gemini` hoặc `ollama` sẽ khóa vào một provider. Có thể dùng pool key
phân tách bằng dấu phẩy qua `GOOGLE_API_KEYS` và `OLLAMA_API_KEYS`. Nếu Ollama
chạy trực tiếp trên máy host trong khi Sandbox chạy bằng Docker Desktop, đặt
`SANDBOX_OLLAMA_HOST=http://host.docker.internal:11434`.

Compose chỉ truyền các biến provider vào `sandbox-control` và `sandbox-worker`;
browser không nhận key. Adapter không log prompt, completion hay secret, và mọi
completion đều phải qua Pydantic schema validation. Nếu cả hai route lỗi, API
trả `503/PROJECT_AI_UNAVAILABLE` với `retryable=true`. Project AI là adapter độc
lập với backend chính và runtime Docker.

## Quy tắc HTTP

- Gửi `Idempotency-Key` khi tạo run và review plan/result.
- Giữ `X-Correlation-Id` và hiển thị correlation ID trong lỗi.
- Xem `404/SANDBOX_FEATURE_DISABLED` là capability tắt, không phải lỗi core.
- Chỉ retry khi `detail.retryable=true`; tôn trọng `Retry-After`.
- Không tự tạo URL object storage; dùng `download_url` từ artifact summary.

Envelope lỗi:

```json
{"detail":{"error_code":"SANDBOX_RUN_STATE_INVALID","message":"...","retryable":false,"details":{},"correlation_id":"..."}}
```

## Mở session

```http
POST /api/v1/projects/{project_id}/sandbox/open-session
Content-Type: application/json

{"mode":"hypothesis | data_analysis","entrypoint":"manual | graphrag_answer | validated_candidate | experiment_proposal","source_resource_id":"required except manual","source_parent_id":"required for graphrag_answer","title":"...","initial_question":"optional"}
```

Với GraphRAG/Discovery, chỉ gửi resource ID core. BFF tự tải record đã phân
quyền, loại context stale/sai project/chưa review, tạo và ký snapshot bất biến ở
server, rồi trả `201`. Sau đó gọi path trong allowlist qua
`/api/v1/projects/{project_id}/sandbox/{sandbox_public_path}`.

## Luồng giả thuyết

Tạo draft bằng `POST sandbox-sessions/{session_id}/hypotheses`, đọc bằng `GET`
và review bằng `POST .../hypotheses/{hypothesis_id}/review`. Experiment dùng
`POST/GET .../experiments[/{experiment_id}]`. Draft được lưu khi chưa có
dataset; hiển thị rõ `evidence_status=unverified` và limitation.

Sau khi có Hypothesis Draft hoặc Experiment Draft không bị từ chối, frontend cho
phép chuyển sang Phân tích dữ liệu. Hành động này luôn tạo một session
`data_analysis` mới, mang theo câu hỏi nghiên cứu, giả thuyết, outcome/predictor
và metrics. Handoff được giữ theo session để khôi phục sau F5.

## Luồng phân tích dữ liệu

Upload/list/detail/delete tại `datasets`; upload multipart yêu cầu
`X-Dataset-Classification: non_sensitive`. Profile tại
`datasets/{dataset_id}/profile`, đọc version tại
`datasets/{dataset_id}/profiles/{version}`. Làm rõ câu hỏi tại
`datasets/{dataset_id}/analysis-questions`; nếu `question_incomplete`, chỉ hỏi
clarification được trả về, không suy đoán.

Tạo/list plan tại `datasets/{dataset_id}/analysis-plans`, review version với
`Idempotency-Key`, tạo run tại
`analysis-plans/{plan_id}/versions/{version}/runs`, poll `GET
sandbox-runs/{run_id}` và hủy bằng `POST sandbox-runs/{run_id}/cancel`. Sau
execution đọc status-history, validation, interpretation, citations, artifacts;
tải artifact qua `download_url`, review kết quả rồi lấy bundle tái lập.

Nếu session được tạo từ giả thuyết, frontend đối soát `required_columns` với tên
cột trong deterministic profile. Khi thiếu cột, hiển thị `MISMATCH_DATASET` và
khóa clarification, plan và run. Việc đối soát chỉ dùng metadata cột, không gửi
raw rows tới AI.

Sau khi tạo run, đọc đúng source code bất biến qua `GET
sandbox-runs/{run_id}/code`. UI trình bày tuần tự Kế hoạch phân tích → Mã nguồn
thực thi → Trạng thái Docker Sandbox → Kết quả đầu ra. Source code được
project-scope và phải là phiên bản gắn với `code_version_id` của run.

Polling nên bắt đầu mỗi 1 giây, exponential backoff tối đa 5 giây và dừng khi
terminal status hoặc component unmount.

## State machine

- Session: `draft/context_ready -> active -> waiting_for_user -> completed`; có thể discard.
- Plan: `draft -> in_review -> approved | rejected | changes_requested`.
- Run: `queued -> running -> completed_unvalidated -> result_review_waiting -> approved | rejected`; lỗi gồm `failed`, `timed_out`, `policy_rejected`, `cancelled`.

Dùng endpoint status-history cho timeline; không tự suy diễn transition thiếu.

## Client sinh tự động

Sinh TypeScript type từ OpenAPI control trong CI, nhưng browser client phải trỏ
vào prefix BFF. BFF giữ body/header an toàn của route allowlist và loại manifest,
lease, storage field nội bộ.
