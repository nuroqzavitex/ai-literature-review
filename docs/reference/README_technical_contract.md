# Technical Contract — Index và quy tắc dùng chung

> Đây là file điều hướng và contract dùng chung của Research Agent. Contract
> V1–V4 là baseline/versioned decision records; trạng thái implementation phải
> đối chiếu với code, migration và test hiện tại.

## 1. Bản đồ contract

| Contract | Trạng thái | Phạm vi |
|---|---|---|
| [`contract_v1.md`](../../contracts/contract_v1.md) | Baseline lịch sử, compatibility còn tồn tại | Literature review, grounding và HITL |
| [`contract_v2.md`](../../contracts/contract_v2.md) | Nhiều capability đã có trong code | Project/Copilot, memory, action, gap và collaboration |
| [`contract_v3.md`](../../contracts/contract_v3.md) | Sandbox implementation đã tồn tại; acceptance cần kiểm riêng | Controlled data analysis và reproducibility |
| [`contract_v4.md`](../../contracts/contract_v4.md) | Một phần platform đã có | PostgreSQL, durable worker, Clerk, Redis/Qdrant và retrieval |

Roadmap sản phẩm vẫn nằm ở:

- [README_MVP_V1.md](../roadmap/README_MVP_V1.md) — MVP1 đã nghiệm thu;
- [README_MVP_V2.md](../roadmap/README_MVP_V2.md) — roadmap Research Copilot và gap;
- [README_MVP_V3.md](../roadmap/README_MVP_V3.md) — roadmap data analysis;
- [README_MVP_V4.md](../roadmap/README_MVP_V4.md) — roadmap production hóa.

Nếu roadmap/contract mô tả khác code đã merge, code + migration + test là bằng
chứng trạng thái hiện tại; contract vẫn là nguồn yêu cầu và phải được cập nhật
trong cùng thay đổi để tránh tiếp tục lệch.

## 2. Quy tắc bất biến xuyên các MVP

1. **No source, no claim:** không có nguồn/evidence hợp lệ thì không sinh kết
   luận factual.
2. Structured artifact là source of truth; chat, prompt và memory không thay
   thế paper, evidence, claim, report hoặc analysis artifact.
3. Mọi factual research answer phải có citation/provenance hoặc trả
   `insufficient_evidence`.
4. LLM không được tự tạo paper ID, DOI, URL, citation, tool name hoặc quyền
   authorization.
5. Evidence quote phải kiểm tra exact match với nội dung đã lưu và có locator
   phù hợp với `content_scope`.
6. Input từ user, abstract, full text và dataset đều là untrusted content;
   prompt injection không được thay đổi system/tool policy.
7. Mutation, search tốn chi phí, ingestion và code execution phải có actor,
   permission, confirmation, idempotency và audit.
8. Reviewer decision đi qua Reviewer API; không expose thành generic LLM tool.
9. Artifact có thay đổi tạo immutable version mới; không sửa lịch sử âm thầm.
10. Mọi retry, loop, search và execution đều bounded, có timeout và trace.
11. Dữ liệu ngoài project không được đọc, trích dẫn, retrieve hoặc ghi memory.
12. V1 regression và quality gates phải pass trước khi bật capability MVP sau.
13. Backend tạo CapabilitySnapshot và allowed tool set theo actor/data stage;
    LLM không tự cấp quyền hoặc tự nâng workflow stage.
14. Literature claim dùng paper/evidence provenance; numeric/data-analysis claim
    dùng AnalysisArtifact provenance. Hai loại không thay thế nhau.

## 3. Quy ước API/schema chung

- API hiện tại giữ base path `/api/v1`; thêm MVP không tự động tạo API major
  version mới.
- JSON dùng `snake_case`; datetime dùng ISO 8601 UTC.
- ID do server tạo và không lấy từ LLM output.
- Request/response ở API boundary phải được validate bằng Pydantic hoặc schema
  tương đương.
- Mutation nhận `Idempotency-Key`; payload khác nhau với cùng key trả conflict.
- Error body tối thiểu có `error_code`, `message`, `retryable`, `details` và
  `correlation_id`.
- Authorization lấy actor từ trusted auth context; không tin `role`, `user_id`
  hoặc `reviewer_id` do client gửi.
- V2+ project-scoped API reject các identity field trong body/query; chỉ legacy
  V1 endpoint được giữ tạm theo compatibility window của contract V2.
- Migration ưu tiên additive; không xóa hoặc đổi nghĩa field đang được V1 dùng
  trong cùng release.

## 4. Quy tắc compatibility và thay đổi

1. Đọc contract MVP hiện tại và roadmap MVP trước khi sửa schema/API.
2. Xác định contract nào bị ảnh hưởng và cập nhật contract trước code.
3. Giữ compatibility window cho endpoint V1; thay đổi phá vỡ phải có migration,
   deprecation window và test regression.
4. Mỗi schema/API change cần cập nhật fixture, frontend typed client và test.
5. Không gộp toàn bộ các MVP vào một graph hoặc một schema khổng lồ.
6. Capability V2–V4 phải được feature/capability gate theo contract và test,
   không suy ra toàn bộ MVP đã hoàn tất chỉ vì một module đã tồn tại.

## 5. Cách đọc và triển khai

```text
README_project.md
  → README_MVP_V1.md
  → README_technical_contract.md (file này)
  → contracts/contract_v1.md
  → README_MVP_V2.md + contracts/contract_v2.md
  → README_MVP_V3.md + contracts/contract_v3.md
  → README_MVP_V4.md + contracts/contract_v4.md
```

Không xem việc tạo file contract là đã hoàn thành MVP. Một MVP chỉ hoàn thành
khi code, migration, test, metric và acceptance gate tương ứng trong contract
đều đạt.
