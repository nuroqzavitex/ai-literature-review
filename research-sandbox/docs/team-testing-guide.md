# Kịch bản kiểm thử Research Sandbox cho team

## 1. Mục đích

Research Sandbox là khu vực thử nghiệm project-scoped, có reviewer gate và
lineage. Product hiện có hai chế độ:

| Chế độ | Dùng để làm gì | Đầu ra chính |
| --- | --- | --- |
| Giả thuyết | Biến câu hỏi/context thành giả thuyết có thể bác bỏ và thiết kế thực nghiệm | Hypothesis Draft, Experiment Draft |
| Phân tích dữ liệu | Phân tích CSV/Parquet trong Docker cô lập từ profile đến bundle tái lập | Profile, AnalysisPlan, Python code, artifacts, citations, Reproducibility Bundle |

Graph Overlay không còn xuất hiện trong frontend và không thuộc phạm vi kiểm thử
product hiện tại.

## 2. Chuẩn bị

1. Chạy `docker compose up -d --build --force-recreate`.
2. Đăng nhập và mở một project mà tài khoản có quyền truy cập.
3. Kiểm tra `GET /api/v1/projects/{project_id}/sandbox/capabilities` trả
   `enabled=true`, `available=true`, `modes.hypothesis=true` và
   `modes.data_analysis=true`.
4. Chuẩn bị hai file không nhạy cảm:
   - file khớp giả thuyết, có đúng các cột cần kiểm chứng;
   - file không khớp, không có bất kỳ cột bắt buộc nào.
5. Không đưa secret, PII hay dữ liệu nhạy cảm vào dataset test.

## 3. Kịch bản A — Giả thuyết độc lập

1. Mở tab **Giả thuyết** và tạo một session mới.
2. Nhập câu hỏi có thể kiểm chứng, ví dụ: “Phương pháp A có cải thiện điểm outcome
   so với baseline không?”.
3. Bấm **Tạo bản thảo**.
4. Xác nhận draft hiển thị statement, rationale, tiêu chí bác bỏ, dữ liệu cần có,
   limitations và evidence status.
5. Tạo thêm một draft; chọn lại version cũ và xác nhận nội dung không bị ghi đè.
6. Tick toàn bộ checklist limitations rồi phê duyệt draft.
7. Bấm **Tạo thiết kế** và xác nhận có independent variables, dependent variables,
   metrics, assumption checks và stopping criteria.

Kết quả đạt: session và version được lưu sau F5; draft cũ bất biến; reviewer gate
không cho phê duyệt khi chưa xác nhận limitations.

## 4. Kịch bản B — Giả thuyết chuyển sang Phân tích dữ liệu

1. Từ một Hypothesis/Experiment Draft không bị từ chối, bấm
   **Chuyển sang Phân tích dữ liệu**.
2. Xác nhận URL đổi sang `mode=data_analysis` và có session ID mới.
3. Xác nhận mục tiêu nghiên cứu, outcome, predictor và metrics được điền sẵn.
4. F5 và xác nhận session cùng thông tin handoff vẫn được khôi phục.
5. Tải file không khớp. Xác nhận UI hiển thị `MISMATCH_DATASET`, liệt kê cột thiếu
   và khóa nút clarification/plan/run.
6. Tải file khớp. Xác nhận cảnh báo biến mất và UI báo dataset tương thích.

Kết quả đạt: mỗi lần handoff tạo session phân tích mới; việc đối soát chỉ dùng
metadata cột trong deterministic profile; không có raw rows trong AI prompt/log.

## 5. Kịch bản C — Phân tích dữ liệu đầy đủ

1. Mở tab **Phân tích dữ liệu**, tạo session mới và tải CSV hoặc Parquet.
2. Chạy deterministic profile; đối chiếu row count, column count, dtype, missing và
   distribution với file nguồn.
3. Nhập câu hỏi nghiên cứu và các cột; bấm **Kiểm tra độ đầy đủ**.
4. Nếu hệ thống trả `question_incomplete`, bổ sung thông tin thay vì chấp nhận AI
   tự đoán.
5. Sinh AnalysisPlan, đọc method, preprocessing, assumptions, metrics và
   limitations; mở modal review rồi phê duyệt.
6. Bấm **Tạo run**.
7. Xác nhận thứ tự giao diện:
   - Kế hoạch phân tích;
   - Mã nguồn thực thi;
   - Trạng thái chạy trong Docker Sandbox;
   - Kết quả đầu ra.
8. Trong khối code, xác nhận có toàn bộ Python script, code hash, prompt version
   và nút **Sao chép code**. Đây phải là đúng source gắn với `code_version_id` của
   run, không phải snippet minh họa.
9. Theo dõi timeline `queued → running → completed_unvalidated →
   result_review_waiting` hoặc trạng thái lỗi rõ ràng.
10. Sau validation, kiểm tra bảng/biểu đồ, interpretation và AnalysisCitation.
11. Phê duyệt kết quả và tải Reproducibility Bundle; kiểm tra các hash lineage.
12. F5 và xác nhận profile, question, plan, run, code và artifacts được khôi phục.

Kết quả đạt: plan chưa duyệt không tạo được run; code bị AST policy từ chối không
được chạy; interpretation chỉ xuất hiện sau validation; numeric claim có citation.

## 6. Kiểm thử session và điều hướng

1. Tạo ít nhất hai session ở mỗi chế độ.
2. Xác nhận badge trên tab hiển thị tổng số session và session navigator cho phép
   chuyển giữa các phiên.
3. Chọn một session, đổi tab, quay lại và xác nhận lựa chọn được giữ.
4. F5 ở từng tab và xác nhận `mode`/`session` trong URL được khôi phục.
5. Session phân tích dùng dataset project-scoped: dataset đã upload có thể xuất
   hiện ở session khác trong cùng project. Đây là chủ đích; progress/plan/run vẫn
   tách theo lựa chọn dataset và session handoff.

## 7. Release gates

- `SANDBOX_ENABLED=false`: frontend ẩn/khóa Sandbox nhưng workspace core không lỗi.
- Không có tab, link hay route UI `graph_overlay`.
- Không có raw dataset rows trong Project AI payload hoặc application log.
- Runtime dùng network none, read-only root filesystem, non-root user và resource
  limits theo cấu hình.
- Request tạo run và review có `Idempotency-Key`; lỗi hiển thị correlation ID.
- Người dùng project khác không đọc được dataset, run, code hoặc artifacts.

## 8. Mẫu báo lỗi

```text
Project ID:
Session ID:
Mode: Hypothesis / Data Analysis
Dataset ID / Plan ID / Run ID (nếu có):
Bước thực hiện:
Kết quả mong đợi:
Kết quả thực tế:
Error code:
Correlation ID:
Ảnh chụp và log liên quan:
```
