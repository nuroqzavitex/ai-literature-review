# Implementation Plan: AI Agent Observability + Background Execution

> Historical proposal written before the current durable-worker runtime. Phase
> 2 is now implemented with PostgreSQL leases/checkpoints and Redis Streams,
> not Celery or request-bound `asyncio.create_task`. Structured application
> events exist, but the proposed `ai_interaction_logs` table/trace API is not a
> current capability. The “hiện trạng” and unchecked file checklist below are
> preserved as planning history, not as a description of code on 2026-09-01.

## 1. Mục tiêu thực tế
- Ghi lại được toàn bộ vòng đời một lượt chạy AI theo dạng structured events, đủ để debug, audit, và đo chất lượng prompt.
- Đưa việc chạy AI ra khỏi request path của API để không còn phụ thuộc vào lifetime của HTTP request.
- Giữ nguyên checkpoint, resume, và HITL flow hiện có, không rewrite toàn bộ graph runtime trong một bước.

## 2. Hiện trạng cần tôn trọng
- `src/services/jobs.py` đang là lõi điều phối job, có stream update và snapshot/checkpoint.
- `src/api/routers/literature_reviews.py` đã có một dạng background in-process cho v1 bằng `asyncio.create_task`, nhưng nó chưa phải worker bền vững.
- `src/services/research_copilot.py` đang gọi `await self.job_service.run(...)` trực tiếp trong luồng xử lý action.
- `src/services/llm.py` hiện là lớp tạo client và route provider, chưa có logging/tracing ở cấp mỗi lần gọi AI.
- `src/agents/nodes/litreview.py` có log lỗi cục bộ ở vài node, nhưng chưa có log xuyên suốt theo `job_id` và `node_name`.

## 3. Nguyên tắc thiết kế
- Làm observability trước, background execution sau.
- Không để logging làm chậm đường chạy AI; log là best-effort nhưng phải có thống kê lỗi ghi log.
- Không log raw prompt/response vô điều kiện; phải có redaction và giới hạn kích thước.
- Không đưa Celery/Redis vào giữa chừng nếu chưa có điểm enqueue rõ ràng; chỉ tách worker khi API contract đã ổn định.
- Mọi event log phải join được với `job_id`, `node_name`, `provider`, `model`, và `attempt`.

## 4. Kiến trúc đích
### 4.1. Dữ liệu
- Có bảng bền vững cho AI trace logs.
- Có bảng/job record hiện tại để lưu trạng thái job.
- Có API đọc trace theo job, theo node, và theo khoảng thời gian.

### 4.2. Luồng chạy
- API tạo job record.
- API enqueue job vào worker.
- Worker chạy `LitReviewJobService.run()` hoặc `resume()`.
- Mỗi lần gọi LLM phát sinh một AI trace event.
- UI poll status/job trace thay vì chờ request sync.

## 5. Phase 1: Observability / AI Logging
### 5.1. Mục tiêu phase này
- Biết chính xác AI đang chạy node nào.
- Biết provider/model nào được dùng.
- Biết mỗi lần gọi AI mất bao lâu, có lỗi gì, có retry/fallback không.
- Có thể tra cứu lại event theo `job_id`.

### 5.2. Schema đề xuất cho `ai_interaction_logs`
- `id`: UUID
- `job_id`: UUID hoặc string theo chuẩn job hiện tại
- `trace_id`: string để nối nhiều event trong cùng một job run
- `node_name`: string
- `provider`: string
- `model`: string
- `event_type`: string, ví dụ `llm_request`, `llm_response`, `llm_error`, `llm_retry`
- `attempt`: integer
- `status`: string, ví dụ `ok`, `error`, `fallback`, `timeout`
- `prompt_preview`: text ngắn đã redacted/truncated
- `response_preview`: text ngắn đã redacted/truncated
- `prompt_payload`: json/text nếu cần lưu raw đã kiểm soát
- `response_payload`: json/text nếu cần lưu raw đã kiểm soát
- `tokens_prompt`: integer nullable
- `tokens_completion`: integer nullable
- `latency_ms`: integer
- `error_type`: string nullable
- `error_message`: text nullable
- `created_at`: UTC datetime

### 5.3. Quy tắc logging
- Log theo event, không chỉ theo raw prompt/response.
- Ghi nhận start/end/error/fallback của một call.
- Nếu log DB fail thì không làm hỏng AI run, nhưng phải có fallback warning log ở app logger.
- Giới hạn payload dài để tránh phình DB.
- Redact secrets, token, email, và PII nếu có.

### 5.4. Chỗ cần sửa
- `src/services/llm.py`: thêm lớp/wrapper tracing cho mỗi lần invoke.
- `src/agents/nodes/litreview.py`: truyền `job_id`, `trace_id`, `node_name` vào context khi gọi LLM.
- `src/services/repositories/`: thêm repository để persist AI logs.
- `src/models/schemas/`: thêm response model để đọc trace từ API.
- `src/api/routers/`: thêm endpoint query trace/logs nếu cần hiển thị ở UI.

## 6. Phase 2: Background Execution
### 6.1. Mục tiêu phase này
- API trả về nhanh sau khi tạo job.
- AI job tiếp tục chạy dù request gốc kết thúc.
- Worker có thể restart mà không làm mất job state.
- Resume/HITL tiếp tục hoạt động đúng.

### 6.2. Quyết định kiến trúc
- Dùng queue/worker bền vững cho job chạy dài.
- Nếu project đã sẵn sàng cho infra mới, chọn Redis + Celery.
- Nếu chưa muốn mở rộng infra ngay, tách dispatcher/worker interface trước, rồi cắm backend queue sau.
- Không giữ `asyncio.create_task` là giải pháp cuối cùng cho job dài vì nó chết theo process web.

### 6.3. Luồng đích
- `POST /reviews` tạo job record và enqueue worker task.
- `execute_action()` không `await job_service.run(...)` trực tiếp nữa.
- Worker gọi `LitReviewJobService.run(job_id, initial_state)`.
- Status cập nhật theo từng node update và cuối cùng theo snapshot/state.
- `resume()` cũng chạy qua worker hoặc cùng execution backend.

### 6.4. Yêu cầu kỹ thuật
- Job phải idempotent theo `job_id`.
- Enqueue retry không được tạo duplicate execution vô hạn.
- Checkpoint storage phải là nguồn sự thật cho resume.
- Nếu job đang chạy rồi, endpoint enqueue phải trả về trạng thái đã nhận job, không chạy lại song song.

## 7. Checklist triển khai theo từng file
### 7.1. `src/services/llm.py`
- [ ] Thêm context object cho `job_id`, `trace_id`, `node_name`, `attempt`.
- [ ] Thêm wrapper/tracer quanh `ainvoke()` và `with_structured_output()`.
- [ ] Ghi event `llm_request`, `llm_response`, `llm_error`, `llm_retry`, `llm_fallback`.
- [ ] Lưu provider/model thực tế được chọn từ route.
- [ ] Tính latency và status cho từng call.
- [ ] Đảm bảo logging thất bại không phá luồng chính.

### 7.2. `src/agents/nodes/litreview.py`
- [ ] Mỗi node chính phải gắn `node_name` vào AI trace context.
- [ ] Các node gọi `ainvoke()` phải dùng tracer chung thay vì log rải rác.
- [ ] Khi fallback sang provider khác, emit event riêng để debug.
- [ ] Giữ log lỗi cục bộ cho các node phụ nhưng không thay thế trace chuẩn.

### 7.3. `src/services/jobs.py`
- [ ] Giữ `run()` và `resume()` là execution core.
- [ ] Emit trạng thái start/running/completed/error rõ ràng.
- [ ] Chuẩn hóa progress payload để frontend và API status đọc thống nhất.
- [ ] Nếu dùng queue worker, đây là nơi worker gọi vào core execution.
- [ ] Không nhét logic enqueue vào đây nếu có thể tách ra service riêng.

### 7.4. `src/services/research_copilot.py`
- [ ] Bỏ kiểu `await self.job_service.run(...)` đồng bộ trong `execute_action()`.
- [ ] Chuyển sang enqueue background task và trả kết quả sớm.
- [ ] Giữ liên kết giữa action, job, và report version.
- [ ] Xử lý duplicate enqueue và trạng thái job đã tồn tại.

### 7.5. `src/api/routers/literature_reviews.py`
- [ ] Giữ `POST /reviews` trả `202 Accepted` hoặc tương đương.
- [ ] Tách rõ bước create-job và step chạy worker.
- [ ] Thay `asyncio.create_task` bằng cơ chế worker/dispatcher bền vững nếu đây là đường chạy production.
- [ ] Bổ sung endpoint đọc trace/log nếu UI cần.

### 7.6. `src/models/schemas/literature_reviews.py`
- [ ] Thêm schema cho AI trace summary nếu API trả về logs.
- [ ] Nếu cần, mở rộng `JobStatusResponse` để có `trace_count` hoặc `last_trace_at`.
- [ ] Giữ payload status nhỏ để poll nhanh.

### 7.7. `src/services/repositories/literature_reviews.py`
- [ ] Bổ sung các hàm lưu/read AI logs theo job.
- [ ] Bổ sung hàm cập nhật job status an toàn khi worker chạy song song.
- [ ] Chuẩn hóa update-progress để không ghi đè state quan trọng.

### 7.8. `src/services/repositories/ai_interaction_logs.py` mới
- [ ] Tạo repository riêng cho log trace.
- [ ] Có hàm insert event, list events theo job, và filter theo node.
- [ ] Có khả năng truncate/redact payload trước khi persist.

### 7.9. `src/tasks/` hoặc `src/workers/` mới
- [ ] Tạo entrypoint worker cho job execution.
- [ ] Worker chỉ gọi service core, không chứa business logic.
- [ ] Nếu dùng Celery, tách task definition khỏi job logic.

### 7.10. `frontend/app/page.tsx`
- [ ] Hiển thị trạng thái job theo queue/running/resuming/completed/error.
- [ ] Nếu có AI trace API, hiển thị timeline node/event.
- [ ] Không poll quá dày để tránh làm nặng backend.

### 7.11. `frontend/app/legacy/page.tsx`
- [ ] Đồng bộ label phase/status nếu trang này còn dùng.
- [ ] Hiển thị current node và last decision nhất quán với API mới.

### 7.12. Tests
- [ ] `tests/test_agents/test_graph.py`: bảo toàn luồng graph khi thêm tracing.
- [ ] `tests/test_api/test_v2_core.py`: verify action enqueue trả về đúng.
- [ ] `tests/test_checkpoint_integration.py`: verify resume vẫn hoạt động.
- [ ] Thêm test mới cho logging repository và job lifecycle.

## 8. Thứ tự thực hiện khuyến nghị
1. Thêm schema/repository cho AI logs.
2. Gắn tracing vào `src/services/llm.py`.
3. Gắn `job_id`/`trace_id` qua các node AI.
4. Chuẩn hóa job lifecycle trong `src/services/jobs.py`.
5. Tách execution sang background worker.
6. Chuyển `execute_action()` và endpoint tạo review sang enqueue.
7. Thêm API/UI để đọc trace nếu cần.
8. Viết test regression cho job, checkpoint, retry, và background execution.

## 9. Acceptance criteria
- [ ] Có thể xem lịch sử AI trace theo `job_id`.
- [ ] Mỗi call LLM có `node_name`, `provider`, `model`, `latency`, `status`.
- [ ] API khởi tạo job trả nhanh, không chờ AI chạy xong.
- [ ] Job vẫn hoàn tất dù process web restart sau khi enqueue.
- [ ] Resume/HITL vẫn hoạt động sau khi tách worker.
- [ ] Logging fail không làm job fail trừ khi policy yêu cầu.
- [ ] Không có duplicate execution cho cùng `job_id` trong cùng một thời điểm.

## 10. Ghi chú triển khai
- Nếu muốn rủi ro thấp, làm Phase 1 trước rồi deploy nhỏ, sau đó mới bật Phase 2.
- Nếu muốn nhanh ra sản phẩm, vẫn phải giữ Phase 1 trước Phase 2 để có trace khi debugging worker.
- Không nên làm đồng thời logging schema, worker infra, và UI trace trong một PR lớn nếu team nhỏ.
