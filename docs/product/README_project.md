**LitReview Agent: Trợ lý AI tổng quan tài liệu và phân tích dữ liệu nghiên cứu**

> Product vision và mục tiêu KPI. Các mục “công nghệ đề xuất” không tự động là
> bằng chứng triển khai; xem [current architecture](../architecture/ARCHITECTURE.md)
> và [living PRD](PRD.md) cho trạng thái hiện tại.

📌 **Thực trạng:** Nghiên cứu viên và SV nghiên cứu Trường đại học X tốn nhiều tuần để làm tổng quan tài liệu (literature review) và bước đầu phân tích dữ liệu; công việc lặp lại, dễ sót nguồn quan trọng.

🎯 **Vấn đề:** Xây trợ lý AI hỗ trợ tổng quan tài liệu (tìm, sàng lọc, tóm tắt, tổng hợp chủ đề, phát hiện khoảng trống nghiên cứu, dựng bảng so sánh) và phân tích dữ liệu ban đầu (gợi ý phương pháp, sinh code phân tích, diễn giải kết quả) — mục tiêu giảm ≥50% thời gian ra bản dự thảo đầu tiên với ≥80% độ chính xác thông tin.

🔒 **Ràng buộc:** Mọi khẳng định phải grounded trên bài báo thật có trích dẫn đầy đủ (chống bịa nguồn — rủi ro lớn nhất của LLM trong nghiên cứu); đo độ chính xác thông tin ≥80% và mức giảm thời gian (KPI); nghiên cứu viên rà soát và chịu trách nhiệm nội dung cuối (HITL); cảnh báo giới hạn khi dữ liệu không đủ; kiểm soát chi phí xử lý nhiều tài liệu dài.

### Công nghệ đề xuất

* LLM (model mạnh cho tổng hợp)
* RAG với Qdrant lưu embedding bài báo + reranker
* Tích hợp API học thuật (Semantic Scholar/OpenAlex/arXiv) để lấy metadata + trích dẫn
* Agent multi-step (LangGraph): search → screen → summarize → synthesize
* Code interpreter sandbox cho phân tích dữ liệu
* Eval RAGAS (faithfulness, citation accuracy) đo độ chính xác + đo thời gian tiết kiệm
* Guardrails chống bịa DOI/trích dẫn
* Backend FastAPI
* Frontend Next.js
* Deploy Docker + cloud

### Cơ bản

* Web app deploy, ≥2 vai trò (nghiên cứu viên/reviewer)
* Nhập chủ đề, agent tìm + tóm tắt + tổng hợp tài liệu có trích dẫn kiểm chứng được
* Người dùng rà soát (HITL)
* Metric cơ bản: độ chính xác trích dẫn trên tập mẫu

### Nâng cao

* Pipeline đầy đủ search-screen-synthesize + phân tích dữ liệu với code sandbox
* Eval RAGAS đạt ≥80% + đo giảm ≥50% thời gian dự thảo
* Dashboard quản lý dự án review nhiều đề tài
* Guardrails chống bịa trích dẫn + tối ưu chi phí bằng map-reduce summarization.
