# AI Log — Gate 1

> Historical Gate 1 record. Các quyết định OpenAlex-only/MVP1 bên dưới ghi lại
> thời điểm nộp Gate, không mô tả runtime multi-source hiện tại.

## 1. Phạm vi và nguyên tắc

AI được dùng như công cụ hỗ trợ phân tích, soạn thảo và review kỹ thuật. Team
không coi nội dung do AI sinh ra là bằng chứng khoa học; mọi quyết định về scope,
guardrail, KPI và deliverable đều được đối chiếu với code, README và yêu cầu Gate 1.

## 2. Các nhóm tác vụ đã dùng AI hỗ trợ

### A. Problem framing

- Phân tích pain point của người làm literature review.
- So sánh chatbot hỏi–đáp với constrained research workflow.
- Chắt lọc value proposition thành hai KPI: claim-support accuracy và time
  reduction.

**Quyết định của team:** ưu tiên evidence/provenance và reviewer kiểm chứng,
không tối ưu số lượng tính năng.

### B. Technical design và contract review

- Rà soát LangGraph StateGraph, node responsibility, conditional routing,
  checkpoint/HITL và bounded retry.
- Kiểm tra schema report cấu trúc (papers, claims, evidence_rows, themes,
  potential_gaps, references, decision_trace).
- Phát hiện các mô tả cũ trong tài liệu như React/Vite, 12 node, Markdown report
  và roadmap đảo thứ tự; thay bằng trạng thái thực tế của MVP 1.

**Quyết định của team:** OpenAlex-only + metadata/abstract ở V1; full text,
multi-source, Qdrant, sandbox và chatbot được giữ ở roadmap.

### C. Code/API/UI review

- Đối chiếu route FastAPI với frontend: create job, status polling, report,
  reviewer queue, review decision và evaluation.
- Kiểm tra rằng frontend dùng Next.js và các block Evidence/Claims/Themes/
  References/Review Inspector phản ánh structured API.
- Kiểm tra các guardrail: không có nguồn thì không claim, scope disclaimer,
  HITL state và lỗi 409/422 cho thao tác không hợp lệ.

### D. Gate 1 documentation

- Soạn lại Brief, PRD và Wireframe/UI Flow theo đúng MVP 1.
- Bổ sung tài liệu GitHub Repo Setup: cấu trúc repo, branch/PR, checks, secrets,
  local run và release checklist.
- Tạo trang chỉ mục để nộp một link chứa toàn bộ deliverables.

## 3. Prompt/task patterns đã sử dụng

1. “Đối chiếu tài liệu yêu cầu với code hiện tại; chỉ ra phần nào đã triển khai,
   phần nào chỉ là roadmap.”
2. “Viết PRD cho constrained LangGraph literature-review agent, có provenance,
   HITL và KPI đo được; không đưa tính năng tương lai vào MVP.”
3. “Rà soát UI flow theo API thực tế và sửa các endpoint/role/status không khớp.”
4. “Thiết kế repo setup có thể onboarding người mới mà không commit secret.”

Các prompt trên là nhóm tác vụ tóm tắt, không phải nguồn độc lập để chứng minh
độ đúng của paper hay claim.

## 4. Cách kiểm chứng của con người

- Đọc chéo `README_project.md`, `README_MVP_V1.md`, technical contract V1,
  `src/api/routers/literature_reviews.py`, `frontend/app/page.tsx`, `Makefile` và Docker Compose.
- Dùng ảnh `UI.png` làm visual reference, sau đó viết screen spec bám vào dữ liệu
  và endpoint đang có.
- Chạy/đối chiếu lint, test và kiểm tra diff tài liệu trước khi nộp. Số liệu KPI
  nghiệm thu phải lấy từ các run thực tế, không lấy từ nội dung AI log.

## 5. Nội dung bị loại hoặc hạ mức cam kết

- Không ghi “đã đạt accuracy/time KPI” nếu chưa có bảng thử nghiệm reviewer.
- Không gọi MVP 1 là chatbot hoặc full-text RAG.
- Không tuyên bố potential gap là gap đã được chứng minh trên toàn ngành.
- Không ghi React/Vite, PDF export hay 12 node khi code hiện tại dùng Next.js,
  structured report và flow bounded trong README MVP V1.

## 6. Trách nhiệm và truy vết

AI hỗ trợ tạo bản nháp tài liệu; người phụ trách dự án chịu trách nhiệm cuối về
đề tài, yêu cầu, test, dữ liệu nghiệm thu và nội dung nộp Gate 1. Mỗi claim trong
ứng dụng phải truy vết được về OpenAlex/evidence; AI log không thay thế citation.
