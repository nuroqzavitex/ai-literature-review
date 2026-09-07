# Product Brief — LitReview Agent

> Cập nhật theo sản phẩm hiện tại ngày 2026-09-01. Các con số giảm thời gian/accuracy là mục tiêu đánh giá, không phải kết quả đã được chứng minh nếu chưa có acceptance artifact.

## Vấn đề

Người nghiên cứu phải tìm, sàng lọc và tổng hợp nhiều paper trong khi vẫn cần chứng minh mỗi kết luận bằng evidence. Chatbot tổng quát thường thiếu provenance, khó cộng tác với reviewer và không quản lý được lịch sử quyết định theo project.

## Giải pháp

LitReview Agent cung cấp workspace theo project với các luồng có kiểm soát:

- tìm paper từ OpenAlex, Semantic Scholar và arXiv;
- chọn corpus, tải/parse full text khi khả dụng và index bằng Qdrant;
- trích evidence, tạo/kiểm tra claim và compose literature review;
- phát hiện research-gap candidate và hỗ trợ counter-search;
- có invitation/assignment/reviewer API, quản lý report version và audit data;
- Copilot trả lời trên project context và action proposal có kiểm soát;
- document review và research sandbox cho phân tích dữ liệu.

## Người dùng

| Vai trò | Nhu cầu chính |
|---|---|
| Researcher/Owner | Tạo project, chạy review/gap, quản lý corpus/report và mời reviewer |
| Reviewer | Đọc evidence/claim/reference của assignment; final decision flow là capability chưa được graph cưỡng chế |

Identity production đến từ Clerk. Quyền truy cập được backend kiểm tra theo actor, project membership, assignment và capability; UI không phải nguồn quyết định quyền.

## Giá trị cốt lõi

1. **No source, no claim:** factual output phải có provenance.
2. **Human control:** người dùng duyệt sub-query và corpus; final reviewer gate là yêu cầu còn thiếu trong runtime hiện tại.
3. **Durable workspace:** project, job, report, conversation và checkpoint sống qua restart.
4. **Reproducible analysis:** sandbox giữ plan/artifact và boundary thực thi rõ ràng.

## Phạm vi kỹ thuật

Next.js 16 + Clerk ở frontend; FastAPI/Python ở backend; LangGraph cho workflow; PostgreSQL là source of truth; Redis hỗ trợ dispatch/status; Qdrant là semantic index; worker chạy embedded khi local hoặc external trong Docker/production.

## Success criteria

- Reference validity và claim-support accuracy được reviewer đo trên gold set.
- Job không bị mất khi API/worker restart hoặc Redis gián đoạn.
- Cross-project data bị chặn ở API/repository boundary.
- Reviewer có thể truy vết claim → evidence → paper/source.
- Thời gian tạo bản nháp được so sánh với baseline thủ công bằng artifact thực.

## Không tuyên bố

- Research gap là kết luận tuyệt đối cho toàn ngành.
- KPI đã đạt nếu chưa có evaluation dataset và reviewer record.
- Redis hoặc Qdrant là hệ thống lưu trữ nghiệp vụ chính.
- Nội dung AI thay thế trách nhiệm học thuật của người dùng.
- Final reviewer gate đã hoàn chỉnh khi `human_review_node` vẫn tự approve ở cả hai execution mode.
