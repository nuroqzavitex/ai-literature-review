# Evaluation Status Report

> Cập nhật 2026-09-01. File này phân biệt **metric có implementation** với
> **metric đã được đo**. Không suy ra KPI đã đạt chỉ vì endpoint hoặc test tồn tại.

## 1. Trạng thái KPI

| Metric | Target | Bằng chứng hiện có | Kết luận |
|---|---:|---|---|
| Reference validity | 1.0 | `GET /api/v1/metrics/mvp` và review/reference records | Có cơ chế tính; chưa có dataset kết quả phát hành trong file này |
| Claim-support accuracy | >= 0.8 | Metrics endpoint và reviewer decisions | Có cơ chế tính; chưa chứng minh đạt target |
| Time reduction (median) | >= 0.5 | `evaluation_records` khi có manual/MVP duration | Có cơ chế tính; chưa có đủ user evaluation được ghi tại đây |
| Review coverage | 1.0 | Review decisions/reference checks | Có schema và phép tính; final reviewer gate chưa được graph cưỡng chế |
| Test coverage | >= 60% | CI chạy `pytest tests/ --cov=src --cov-fail-under=60` | Là quality gate cấu hình; cần link CI của commit nộp để xác nhận pass |

## 2. Test và CI

- Workflow hiện tại: `.github/workflows/ci.yml`.
- Backend CI dùng Python 3.12, Ruff và pytest với coverage gate 60%.
- Frontend CI dùng Node.js 20, `npm run lint` và `npm run build`.
- Sandbox có PostgreSQL/runtime suite và frontend E2E job riêng.
- Repository hiện có 68 file `test_*.py` và 422 hàm test được đếm tĩnh trong
  `tests/` + `research-sandbox/tests/`; đây không phải số test pytest đã collect
  vì parametrization có thể làm số case khác.

Phiên audit tài liệu ngày 2026-09-01 chưa xác nhận một lần chạy full suite:
virtualenv trong workspace không thực thi được, còn Python hệ thống là 3.14 và
test collection bị chặn vì PostgreSQL cấu hình không sẵn sàng. Do đó file này
không ghi `CI green`, số test pass hay coverage thực tế nếu không có URL/run ID
của commit nộp.

## 3. Dữ liệu đánh giá người dùng

Chưa có artifact trong repository chứng minh đã thu thập đủ user evaluation để
kết luận KPI accuracy hoặc time reduction đạt target. `eval/topics.json` là bộ
topic thử nghiệm, không phải kết quả đo.

## 4. Những gì đã xác nhận từ code

- Academic search có adapter OpenAlex, Semantic Scholar và arXiv.
- Claim validation có exact/provenance checks và Qdrant retrieval khi bật.
- PostgreSQL là store nghiệp vụ/checkpoint; Redis và Qdrant là derived infra.
- Literature-review `review` mode dừng ở sub-query và paper selection.
- `human_review_node` hiện tự approve ở cả `review` và `autonomous`; không dùng
  reviewer API/schema để tuyên bố final reviewer gate đã hoàn chỉnh.

## 5. Việc cần làm trước khi công bố số liệu

- [ ] Chạy CI trên đúng commit nộp và gắn URL/run ID.
- [ ] Chạy workflow thật với provider keys hợp lệ.
- [ ] Thu thập reviewer decisions trên gold set đã version hóa.
- [ ] Thu thập manual/MVP duration đủ mẫu để tính median time reduction.
- [ ] Export payload metrics và ghi commit SHA, thời gian, cấu hình, dataset.
- [ ] Sửa final reviewer gate hoặc hạ requirement tương ứng trước khi công bố
      review coverage end-to-end.
