# PHÂN TÍCH NỖI ĐAU ĐỀ TÀI EDU-09
## LitReview Agent – Trợ lý AI tổng quan tài liệu và phân tích dữ liệu nghiên cứu

> Problem-framing artifact. Giữ làm nguồn bối cảnh sản phẩm; kiến trúc và trạng
> thái tính năng hiện tại nằm trong `docs/architecture/` và living PRD.

---

## 1. Tổng quan bài toán

LitReview Agent là hệ thống AI hỗ trợ người làm nghiên cứu trong toàn bộ quy trình tổng quan tài liệu:

```text
Xác định câu hỏi nghiên cứu
→ Tìm kiếm tài liệu
→ Sàng lọc tài liệu
→ Đọc và trích xuất thông tin
→ So sánh nhiều nghiên cứu
→ Tổng hợp kết quả
→ Xác định khoảng trống nghiên cứu
→ Kiểm tra nguồn trích dẫn
→ Hỗ trợ viết bản tổng quan
```

Bài toán không chỉ là “tóm tắt PDF”. Nỗi đau thực sự nằm ở việc người nghiên cứu phải biến hàng chục hoặc hàng trăm tài liệu rời rạc thành một bản tổng quan:

- Có cấu trúc.
- Có bằng chứng.
- Không bỏ sót tài liệu quan trọng.
- Không trích dẫn sai.
- Có thể truy ngược từng nhận định về đúng nguồn gốc.
- Đủ tin cậy để sử dụng trong luận văn, bài báo hoặc đề tài nghiên cứu.

---

# 2. Ai là người gặp nỗi đau?

## 2.1. Người dùng chính

### Sinh viên cao học và nghiên cứu sinh

Nhu cầu chính:

- Viết phần tổng quan nghiên cứu cho luận văn hoặc bài báo.
- Tìm các nghiên cứu liên quan đến đề tài.
- So sánh phương pháp, dữ liệu và kết quả.
- Xác định hướng nghiên cứu tiếp theo.
- Chuẩn bị đề cương hoặc bảo vệ đề tài.

### Nghiên cứu viên

Nhu cầu chính:

- Theo dõi nhanh một lĩnh vực nghiên cứu.
- Sàng lọc số lượng lớn công trình.
- Tổng hợp bằng chứng từ nhiều nghiên cứu.
- Tìm xu hướng, mâu thuẫn và khoảng trống.
- Truy vết nguồn cho từng kết luận.

### Giảng viên và reviewer

Nhu cầu chính:

- Kiểm tra chất lượng tổng quan tài liệu.
- Xác minh một nhận định có đúng nguồn hay không.
- Phát hiện citation không liên quan hoặc bị diễn giải quá mức.
- Đánh giá tính đầy đủ và nhất quán của báo cáo.

## 2.2. Người dùng thứ cấp

### Trưởng nhóm nghiên cứu

Cần:

- Phân công tài liệu cho từng thành viên.
- Theo dõi tài liệu đã đọc, đã duyệt hoặc đã loại.
- Tránh hai người cùng xử lý một tài liệu.
- Kiểm tra claim nào đã có bằng chứng.

### Bộ phận R&D trong doanh nghiệp

Cần:

- Nắm nhanh công nghệ mới.
- So sánh phương pháp và kết quả thực nghiệm.
- Rút ngắn thời gian khảo sát trước khi đầu tư.
- Xác định hướng thử nghiệm tiềm năng.

---

# 3. Nỗi đau xuất hiện ở đâu trong hành trình nghiên cứu?

```text
Bắt đầu đề tài
→ Không biết tìm bằng từ khóa nào
→ Tìm ra quá nhiều kết quả
→ Không biết bài nào đáng đọc
→ Phải đọc nhiều PDF dài
→ Ghi chú bị phân tán
→ Khó so sánh giữa các bài
→ Khó tổng hợp kết luận
→ Không nhớ nhận định lấy từ đâu
→ Dễ trích dẫn sai
→ Khó chứng minh khoảng trống nghiên cứu
→ Mất nhiều thời gian viết bản nháp
```

Ba khoảnh khắc đau nhất:

### Trước khi đọc

> “Tôi có quá nhiều kết quả nhưng không biết bài nào thực sự liên quan và đáng đọc.”

### Trong khi đọc

> “Tôi phải đọc hàng chục trang chỉ để tìm phương pháp, dữ liệu, kết quả chính và hạn chế.”

### Khi viết

> “Tôi nhớ đã đọc thông tin này nhưng không nhớ nó nằm trong bài nào, trang nào và nguồn có thực sự hỗ trợ nhận định đó hay không.”

---

# 4. Pain point cốt lõi

> Người nghiên cứu mất rất nhiều thời gian để chuyển một lượng lớn tài liệu rời rạc thành bản tổng quan có cấu trúc, có bằng chứng và có thể kiểm chứng.

Nỗi đau này gồm bốn vấn đề gốc:

- Quá tải thông tin.
- Công việc thủ công lặp lại.
- Khó kiểm chứng kết luận.
- Rủi ro sai citation và bỏ sót tài liệu.

---

# 5. Phân tích chi tiết từng nỗi đau và cách AI xử lý

## 5.1. Không biết tìm kiếm bằng từ khóa nào

### Ai đau?

- Sinh viên mới bắt đầu đề tài.
- Người chưa hiểu sâu thuật ngữ của lĩnh vực.
- Nghiên cứu viên chuyển sang chủ đề mới.

### Đau ở đâu?

Tại bước xây dựng truy vấn tìm kiếm.

### Đau như thế nào?

Một khái niệm thường có nhiều cách gọi. Ví dụ “AI Agent trong giáo dục” có thể xuất hiện dưới các thuật ngữ:

```text
AI agent
Intelligent tutoring agent
Pedagogical agent
Autonomous learning assistant
Multi-agent learning system
LLM-based educational assistant
Conversational tutor
Adaptive learning assistant
```

Nếu chỉ tìm bằng một cụm từ, người dùng có thể:

- Bỏ sót tài liệu quan trọng.
- Chỉ tìm thấy một nhánh nhỏ của lĩnh vực.
- Nhận nhiều kết quả không liên quan.
- Không biết kết hợp từ khóa bằng AND, OR, NOT.

### Nguyên nhân gốc

- Thiếu kiến thức miền.
- Thuật ngữ không thống nhất.
- Tên gọi thay đổi theo thời gian.
- Mỗi cơ sở dữ liệu lập chỉ mục khác nhau.

### AI giải quyết như thế nào?

AI thực hiện Query Planning và Query Expansion:

```text
Câu hỏi nghiên cứu
→ Tách các khái niệm chính
→ Sinh từ khóa đồng nghĩa
→ Sinh thuật ngữ chuyên ngành
→ Tạo nhiều truy vấn
→ Điều chỉnh truy vấn theo từng nguồn
```

Ví dụ:

```text
Câu hỏi:
LLM Agent hỗ trợ học tập cá nhân hóa như thế nào?

Các truy vấn AI sinh ra:
- "LLM agent" AND "personalized learning"
- "AI agent" AND "adaptive education"
- "large language model" AND "intelligent tutoring system"
- "multi-agent system" AND "personalized education"
- "autonomous tutor" AND "higher education"
```

### Giá trị AI tạo ra

- Tăng độ phủ tìm kiếm.
- Giảm phụ thuộc vào kinh nghiệm cá nhân.
- Giảm khả năng bỏ sót thuật ngữ liên quan.
- Giúp người dùng bắt đầu nhanh hơn.

---

## 5.2. Quá nhiều tài liệu nhưng không biết bài nào phù hợp

### Ai đau?

- Sinh viên cao học.
- Nghiên cứu viên thực hiện systematic review.
- Nhóm nghiên cứu xử lý hàng trăm tài liệu.

### Đau ở đâu?

Sau khi tìm kiếm tài liệu.

### Đau như thế nào?

Người dùng phải kiểm tra thủ công:

- Tiêu đề.
- Abstract.
- Năm xuất bản.
- Đối tượng nghiên cứu.
- Phương pháp.
- Loại công trình.
- Có thực nghiệm hay không.
- Có phù hợp tiêu chí chọn hay không.

Ví dụ:

```text
Tiêu chí chọn:
- Xuất bản từ năm 2020 trở đi
- Có sử dụng LLM
- Có thực nghiệm
- Liên quan đến giáo dục đại học

Tiêu chí loại:
- Chỉ là bài quan điểm
- Không có đánh giá thực nghiệm
- Không liên quan đến cá nhân hóa học tập
```

### Hệ quả

- Mất nhiều giờ hoặc nhiều ngày.
- Dễ bỏ sót bài phù hợp.
- Kết quả đánh giá thiếu nhất quán.
- Thành viên trong nhóm có thể hiểu tiêu chí khác nhau.

### AI giải quyết như thế nào?

AI thực hiện AI-assisted Screening:

```text
Title + Abstract + Metadata
→ So sánh tiêu chí chọn
→ So sánh tiêu chí loại
→ Include / Exclude / Maybe
→ Giải thích lý do
→ Chấm điểm tin cậy
→ Chuyển trường hợp không chắc chắn cho con người
```

Ví dụ:

```json
{
  "decision": "include",
  "relevance_score": 0.89,
  "matched_criteria": [
    "Có sử dụng LLM",
    "Có đánh giá thực nghiệm",
    "Đối tượng là sinh viên đại học"
  ],
  "reason": "Nghiên cứu đánh giá trợ lý học tập dựa trên LLM trong môi trường đại học.",
  "requires_human_review": false
}
```

### Vai trò của con người

AI không nên tự động loại tài liệu khi:

- Abstract thiếu thông tin.
- Độ tin cậy thấp.
- Tiêu chí có tính chủ quan.
- Tài liệu nằm ở vùng “Maybe”.

---

## 5.3. Tài liệu bị trùng lặp giữa nhiều nguồn

### Ai đau?

- Người tìm tài liệu từ nhiều cơ sở dữ liệu.
- Nhóm nghiên cứu nhập dữ liệu từ OpenAlex, Semantic Scholar, arXiv hoặc nguồn khác.

### Đau ở đâu?

Tại bước hợp nhất kết quả tìm kiếm.

### Đau như thế nào?

Cùng một bài có thể tồn tại dưới nhiều phiên bản:

- Preprint.
- Conference paper.
- Journal extension.
- Metadata khác nhau.
- Tiêu đề được viết khác nhau.
- Tác giả bị viết tắt.
- Có hoặc không có DOI.

### Hệ quả

- Đếm sai số lượng tài liệu.
- Một bài bị xử lý nhiều lần.
- Kết quả tổng hợp bị thiên lệch.
- Tăng chi phí embedding và LLM.

### AI và hệ thống giải quyết như thế nào?

```text
DOI matching
+ Title normalization
+ Author matching
+ Publication year
+ Semantic title similarity
→ Nhóm các bản ghi có khả năng trùng
→ Người dùng xác nhận khi không chắc chắn
```

AI phù hợp để phát hiện trường hợp gần trùng, nhưng quyết định cuối nên dựa trên DOI, source ID, tiêu đề chuẩn hóa và danh sách tác giả.

---

## 5.4. Đọc toàn văn mất quá nhiều thời gian

### Ai đau?

- Người phải đọc hàng chục hoặc hàng trăm PDF.
- Sinh viên có hạn nộp đề cương.
- Nghiên cứu viên cần theo dõi nhanh một lĩnh vực.

### Đau ở đâu?

Trong quá trình đọc tài liệu.

### Đau như thế nào?

Một bài báo thường dài từ 10 đến 30 trang. Người đọc chủ yếu cần:

- Vấn đề nghiên cứu.
- Câu hỏi nghiên cứu.
- Phương pháp.
- Dataset hoặc đối tượng.
- Baseline.
- Metrics.
- Kết quả.
- Hạn chế.
- Hướng phát triển.

Nhưng các thông tin nằm rải rác ở nhiều phần.

### Hệ quả

- Tốn thời gian.
- Dễ bỏ sót chi tiết.
- Khó nhớ chính xác số liệu.
- Có thể hiểu sai nếu chỉ đọc abstract.

### AI giải quyết như thế nào?

AI thực hiện Document Understanding:

```text
PDF
→ Phân tích cấu trúc
→ Tách section
→ Nhận diện bảng và đoạn văn
→ Trích xuất dữ liệu theo schema
→ Gắn page và evidence
```

Schema đề xuất:

```json
{
  "research_problem": "",
  "research_question": "",
  "methodology": "",
  "dataset_or_sample": "",
  "baseline_methods": [],
  "evaluation_metrics": [],
  "main_results": [],
  "limitations": [],
  "future_work": [],
  "evidence_ids": []
}
```

Mỗi thông tin cần kèm paper ID, page, section, đoạn nguồn và evidence ID.

---

## 5.5. Ghi chú nghiên cứu bị phân tán và thiếu cấu trúc

### Ai đau?

- Sinh viên ghi chú bằng Word, Excel, Notion hoặc giấy.
- Nhóm nghiên cứu dùng nhiều công cụ khác nhau.
- Người đọc nhiều bài trong thời gian dài.

### Đau ở đâu?

Trong quá trình lưu trữ và quản lý thông tin.

### Đau như thế nào?

Thông tin thường nằm rải rác ở:

- PDF.
- Excel.
- Word.
- Notion.
- Zotero.
- Mendeley.
- Tin nhắn nhóm.

### Hệ quả

- Không nhớ thông tin nằm ở đâu.
- Không nhớ nhận định thuộc bài nào.
- Khó so sánh theo cùng tiêu chí.
- Mỗi thành viên ghi chú theo một kiểu.
- Dữ liệu khó tái sử dụng.

### AI giải quyết như thế nào?

AI chuẩn hóa tất cả tài liệu về cùng một cấu trúc và tự động tạo Research Matrix:

| Paper | Problem | Method | Dataset | Metrics | Main Result | Limitation |
|---|---|---|---|---|---|---|
| Paper A | Cá nhân hóa | RCT | 120 SV | Accuracy | +12% | Mẫu nhỏ |
| Paper B | Phản hồi học tập | Case study | 50 SV | Satisfaction | +18% | Không có control |
| Paper C | Hỗ trợ giảng viên | Experiment | 200 SV | Time | Giảm 30% | Một môn học |

---

## 5.6. Khó so sánh nhiều nghiên cứu

### Ai đau?

- Người viết Related Work.
- Người thực hiện systematic review.
- Người cần lựa chọn phương pháp cho nghiên cứu mới.

### Đau ở đâu?

Sau khi đã đọc từng bài riêng lẻ.

### Đau như thế nào?

Mỗi bài sử dụng:

- Dataset khác nhau.
- Metric khác nhau.
- Cỡ mẫu khác nhau.
- Baseline khác nhau.
- Bối cảnh khác nhau.
- Thời gian thử nghiệm khác nhau.

### Hệ quả

- So sánh không công bằng.
- Dễ kết luận sai rằng phương pháp A tốt hơn B.
- Khó tìm điểm mạnh và hạn chế thực sự.

### AI giải quyết như thế nào?

AI thực hiện Structured Comparison:

```text
Structured summaries
→ Chuẩn hóa các trường
→ So sánh cùng dimension
→ Cảnh báo dữ liệu không tương đương
→ Tạo bảng đối chiếu
```

Các dimension so sánh:

- Mục tiêu.
- Đối tượng.
- Phương pháp.
- Dataset.
- Baseline.
- Metrics.
- Cỡ mẫu.
- Thời gian thử nghiệm.
- Kết quả.
- Hạn chế.

---

## 5.7. Khó tổng hợp kết quả của toàn bộ tập tài liệu

### Ai đau?

- Người đã đọc nhiều bài nhưng chưa viết được tổng quan.
- Người không biết nhóm nghiên cứu thành chủ đề.
- Nhóm có nhiều người đọc các tập bài khác nhau.

### Đau ở đâu?

Tại bước chuyển từ tóm tắt từng bài sang tổng hợp tri thức.

### Đau như thế nào?

Tóm tắt từng bài không trả lời được:

- Xu hướng chung là gì?
- Phương pháp nào phổ biến?
- Kết quả nào được nhiều nghiên cứu xác nhận?
- Kết quả nào mâu thuẫn?
- Hạn chế nào lặp lại nhiều lần?

### Hệ quả

- Literature review trở thành danh sách tóm tắt.
- Thiếu phân tích và lập luận.
- Không thể hiện mối liên hệ giữa các nghiên cứu.

### AI giải quyết như thế nào?

AI thực hiện Multi-document Synthesis:

```text
Tóm tắt có cấu trúc
→ Gom nhóm theo chủ đề
→ Tìm điểm đồng thuận
→ Tìm điểm khác biệt
→ Tìm mâu thuẫn
→ Tổng hợp thành các luận điểm
```

Mỗi kết luận tổng hợp phải kèm:

- Danh sách tài liệu hỗ trợ.
- Evidence tương ứng.
- Số lượng tài liệu đồng thuận.
- Các trường hợp ngoại lệ.
- Mức độ tin cậy.

---

## 5.8. Khó phát hiện mâu thuẫn giữa các nghiên cứu

### Ai đau?

- Người đọc nhiều bài nhưng không nhớ hết kết quả.
- Người cần xây dựng luận điểm phản biện.
- Reviewer muốn kiểm tra tính đầy đủ.

### Đau ở đâu?

Trong bước tổng hợp và phân tích.

### Đau như thế nào?

Hai nghiên cứu có thể kết luận trái ngược vì:

- Dataset khác nhau.
- Đối tượng khác nhau.
- Thời gian thử nghiệm khác nhau.
- Metric khác nhau.
- Cỡ mẫu khác nhau.

### AI giải quyết như thế nào?

AI có thể:

- Nhóm các claim cùng chủ đề.
- Phát hiện claim trái ngược.
- So sánh điều kiện thực nghiệm.
- Đề xuất nguyên nhân khả dĩ.
- Trình bày các nghiên cứu theo nhiều phía.

AI chỉ nên đưa ra “nguyên nhân tiềm năng”, không được khẳng định quan hệ nhân quả nếu thiếu bằng chứng.

---

## 5.9. Khó xác định khoảng trống nghiên cứu

### Ai đau?

- Sinh viên tìm hướng cho luận văn.
- Nghiên cứu viên chuẩn bị đề xuất.
- Trưởng nhóm muốn xác định hướng đầu tư.

### Đau ở đâu?

Sau khi tổng hợp tài liệu.

### Đau như thế nào?

Người dùng cần trả lời:

- Chủ đề nào chưa được nghiên cứu đủ?
- Đối tượng nào ít được khảo sát?
- Phương pháp nào chưa được đánh giá?
- Dataset nào còn hạn chế?
- Kết quả nào còn mâu thuẫn?

### Rủi ro

Không thấy trong tập tài liệu không đồng nghĩa với chưa từng được nghiên cứu. AI có thể bịa research gap hoặc khẳng định quá mức.

### AI giải quyết như thế nào?

AI chỉ nên đề xuất Candidate Research Gaps dựa trên:

- Hạn chế lặp lại nhiều lần.
- Nhóm đối tượng ít xuất hiện.
- Thiếu nghiên cứu dài hạn.
- Thiếu baseline.
- Thiếu nghiên cứu quy mô lớn.
- Kết quả mâu thuẫn.

Cách diễn đạt an toàn:

- “Khoảng trống tiềm năng”.
- “Chưa được khảo sát đầy đủ trong tập tài liệu hiện tại”.
- “Cần tìm kiếm bổ sung để xác nhận”.

---

## 5.10. Trích dẫn sai hoặc không truy vết được nguồn

### Ai đau?

- Sinh viên viết luận văn.
- Nghiên cứu viên viết bài báo.
- Reviewer và giảng viên hướng dẫn.

### Đau ở đâu?

Khi viết và kiểm tra citation.

### Đau như thế nào?

Các lỗi phổ biến:

- Trích sai tác giả hoặc năm.
- DOI không tồn tại.
- Citation không hỗ trợ claim.
- Dùng abstract để suy diễn kết luận chi tiết.
- Không nhớ claim lấy từ bài nào.
- LLM tự tạo tài liệu tham khảo.

### Hệ quả

- Giảm độ tin cậy.
- Có thể vi phạm chuẩn mực học thuật.
- Tốn thời gian kiểm tra lại.
- Có thể dẫn đến kết luận sai.

### AI giải quyết như thế nào?

Hệ thống cần Claim-level Citation Grounding:

```text
Claim
→ Evidence
→ Paper Chunk
→ Page
→ Section
→ Paper Metadata
```

Guardrail bắt buộc:

- Không cho phép DOI do LLM tự sinh.
- Citation phải tham chiếu paper tồn tại trong hệ thống.
- Claim factual phải có evidence.
- Evidence phải đến từ tài liệu được duyệt.
- Phân biệt abstract-only và full-text.
- Reviewer có thể mở đúng trang và đoạn gốc.

---

## 5.11. Khó đánh giá chất lượng của từng nghiên cứu

### Ai đau?

- Sinh viên chưa có kinh nghiệm phản biện.
- Người cần chọn nghiên cứu đáng tin cậy.
- Reviewer cần quality assessment.

### Đau ở đâu?

Trong quá trình đánh giá và tổng hợp.

### Đau như thế nào?

Người dùng cần xem:

- Cỡ mẫu.
- Nhóm đối chứng.
- Baseline.
- Metric.
- Ý nghĩa thống kê.
- Dữ liệu hoặc source code.
- Hạn chế.
- Khả năng tái lập.

### AI giải quyết như thế nào?

AI hỗ trợ trích xuất và cảnh báo theo checklist:

```json
{
  "has_control_group": true,
  "sample_size": 120,
  "has_baseline": true, hoặc giấy.
  "statistical_significance_reported": false,
  "reproducibility_assets": "Not found",
  "limitations_declared": true,
  "quality_warnings": [
    "Không báo cáo statistical significance",
    "Không cung cấp source code"
  ]
}
```

AI chỉ hỗ trợ trích xuất và cảnh báo, không thay thế đánh giá chuyên môn.

---

## 5.12. Viết bản nháp mất nhiều thời gian

### Ai đau?

- Sinh viên chuẩn bị luận văn.
- Nghiên cứu viên chuẩn bị paper.
- Nhóm cần hợp nhất ghi chú của nhiều người.

### Đau ở đâu?

Sau khi tìm, đọc và tổng hợp tài liệu.

### Đau như thế nào?

Người dùng vẫn phải:

- Tạo outline.
- Phân nhóm tài liệu.
- Viết từng đoạn.
- Chèn citation.
- Tránh lặp ý.
- Kiểm tra claim.
- Đảm bảo tính nhất quán.

### AI giải quyết như thế nào?

AI thực hiện Evidence-grounded Drafting:

```text
Research question
+ Structured summaries
+ Approved claims
+ Evidence
→ Sinh outline
→ Viết draft theo section
→ Chèn citation
→ Kiểm tra citation coverage
→ Reviewer duyệt
```

---

## 5.13. Làm việc nhóm thiếu đồng bộ

### Ai đau?

- Nhóm nghiên cứu nhiều thành viên.
- Đội 4 người cùng thực hiện đề tài.
- Trưởng nhóm theo dõi tiến độ.

### Đau ở đâu?

Xuyên suốt quy trình tìm, đọc, review và tổng hợp.

### Đau như thế nào?

- Hai người cùng đọc một bài.
- Không biết ai đã duyệt tài liệu.
- Ghi chú không đồng nhất.
- Không biết claim nào đã kiểm tra.
- Không có lịch sử chỉnh sửa.

### AI và hệ thống giải quyết như thế nào?

- Phân công tài liệu.
- Trạng thái New / Screening / Approved / Rejected.
- Reviewer workflow.
- Lịch sử thay đổi.
- Comment theo claim.
- Research matrix dùng chung.
- Audit trail cho quyết định của AI và con người.

---

# 6. Bảng ánh xạ Pain point và giải pháp AI

| Pain point | Người đau | Vị trí trong hành trình | AI xử lý |
|---|---|---|---|
| Không biết từ khóa | Người mới bắt đầu | Trước tìm kiếm | Query planning, query expansion |
| Bỏ sót thuật ngữ | Người chưa hiểu sâu lĩnh vực | Tìm kiếm | Semantic query generation |
| Quá nhiều kết quả | Sinh viên, researcher | Sau tìm kiếm | Semantic ranking, reranking |
| Tài liệu trùng | Nhóm dùng nhiều nguồn | Hợp nhất dữ liệu | Deduplication |
| Sàng lọc chậm | Researcher | Screening | Include/Exclude/Maybe |
| Đọc PDF lâu | Tất cả người dùng | Reading | Document understanding |
| Ghi chú rời rạc | Cá nhân và nhóm | Note-taking | Structured extraction |
| Khó so sánh | Người viết review | Analysis | Research matrix |
| Khó tổng hợp | Người viết literature review | Synthesis | Multi-document synthesis |
| Bỏ sót mâu thuẫn | Researcher | Analysis | Contradiction detection |
| Khó tìm gap | Sinh viên, researcher | Research design | Candidate gap analysis |
| Citation sai | Tác giả, reviewer | Writing | Claim-evidence grounding |
| Khó đánh giá chất lượng | Reviewer | Quality assessment | Checklist extraction |
| Viết draft lâu | Tác giả | Writing | Evidence-grounded drafting |
| Làm việc nhóm rời rạc | Đội nghiên cứu | Toàn quy trình | Workflow, review, audit |

---

# 7. AI trong hệ thống cần làm những gì?

## 7.1. Tìm kiếm thông minh

```text
Phân tích câu hỏi nghiên cứu
→ Tách khái niệm
→ Sinh từ khóa
→ Sinh nhiều truy vấn
→ Tìm kiếm nhiều nguồn
→ Xếp hạng tài liệu
```

## 7.2. Sàng lọc tài liệu

```text
Đọc title và abstract
→ Kiểm tra tiêu chí chọn
→ Kiểm tra tiêu chí loại
→ Include / Exclude / Maybe
→ Giải thích
→ Đánh dấu trường hợp cần con người duyệt
```

## 7.3. Đọc và trích xuất tài liệu

```text
Parse PDF
→ Tách section
→ Trích xuất problem, method, dataset, metric, result
→ Tạo summary có cấu trúc
→ Gắn evidence
```

## 7.4. Tổ chức tri thức

```text
Chuẩn hóa dữ liệu từng paper
→ Tạo research matrix
→ Gom nhóm theo topic
→ Gom nhóm theo method
→ Gom nhóm theo dataset
```

## 7.5. Tổng hợp nhiều tài liệu

```text
Structured summaries
→ Tìm đồng thuận
→ Tìm khác biệt
→ Tìm mâu thuẫn
→ Tổng hợp theo chủ đề
```

## 7.6. Đề xuất khoảng trống tiềm năng

```text
Tổng hợp limitations
→ Tìm bối cảnh ít xuất hiện
→ Tìm thiếu hụt dữ liệu
→ Tìm thiếu nghiên cứu dài hạn
→ Tìm kết quả mâu thuẫn
→ Đề xuất candidate research gaps
```

## 7.7. Kiểm chứng claim và citation

```text
Claim
→ Retrieval evidence
→ Kiểm tra mức độ hỗ trợ
→ Kiểm tra paper metadata
→ Kiểm tra DOI/source ID
→ Cảnh báo claim yếu
```

## 7.8. Hỗ trợ viết

```text
Approved evidence
→ Sinh outline
→ Sinh draft
→ Chèn citation
→ Kiểm tra citation coverage
→ Reviewer duyệt
```

---

# 8. AI không nên làm gì?

AI không nên:

- Tự tạo DOI, tác giả hoặc tài liệu.
- Tự khẳng định research gap là hoàn toàn mới.
- Tự loại tài liệu khi độ tin cậy thấp.
- Kết luận từ title mà chưa đọc abstract hoặc full text.
- Dùng abstract như thể đã đọc toàn văn.
- Trộn nội dung từ nhiều bài mà không lưu provenance.
- Viết claim factual không có evidence.
- Đánh giá chất lượng hoàn toàn tự động.
- Thay thế quyết định chuyên môn của researcher.

Vai trò đúng của AI:

> Giảm công việc lặp lại, cấu trúc hóa thông tin, hỗ trợ phân tích và cung cấp bằng chứng để con người ra quyết định nhanh hơn.

---

# 9. Kiến trúc giải pháp theo nỗi đau

```text
User Research Question
        |
        v
Query Planning Agent
        |
        v
Scholarly Search Connectors
        |
        v
Metadata Normalization
        |
        v
Deduplication
        |
        v
Screening Agent
        |
        v
Human Approval
        |
        v
PDF Processing
        |
        v
Chunking + Embedding
        |
        v
Evidence Retrieval
        |
        v
Structured Summary
        |
        v
Multi-document Synthesis
        |
        v
Claim-Citation Verification
        |
        v
Reviewer Approval
        |
        v
Export Literature Review
```

---

# 10. Phạm vi MVP phù hợp cho đội 4 người

Đội nên tập trung vào các nỗi đau có giá trị cao nhất:

```text
Tìm đúng tài liệu
→ Sàng lọc nhanh
→ Đọc và trích xuất có cấu trúc
→ Tổng hợp nhiều tài liệu
→ Kiểm chứng citation
```

## Chức năng MVP

- Tạo dự án nghiên cứu.
- Nhập research question.
- Khai báo tiêu chí Include/Exclude.
- AI sinh truy vấn.
- Tìm tài liệu từ ít nhất hai nguồn.
- Chuẩn hóa metadata.
- Loại trùng.
- AI sàng lọc.
- Người dùng duyệt.
- Upload PDF.
- Parse và chunk tài liệu.
- Tạo structured summary.
- Tạo research matrix.
- Tổng hợp theo chủ đề.
- Sinh claim có citation.
- Mở đúng đoạn nguồn để kiểm chứng.
- Reviewer approve, reject hoặc edit.
- Xuất báo cáo.

## Tính năng nâng cao

Chỉ nên chọn thêm một hướng:

- Dashboard phân tích corpus.
- Code sandbox phân tích dữ liệu.
- Knowledge graph.
- Tích hợp Zotero.
- Theo dõi xu hướng nghiên cứu theo thời gian.

---

# 11. Giá trị mang lại

## Giá trị chức năng

- Giảm thời gian tìm và đọc.
- Giảm công việc lặp lại.
- Chuẩn hóa ghi chú.
- Hỗ trợ so sánh nhiều bài.
- Tăng khả năng truy vết nguồn.
- Giảm nguy cơ citation giả.
- Hỗ trợ làm việc nhóm.
- Giúp tạo draft nhanh hơn.

## Giá trị chất lượng

- Claim có evidence.
- Citation có thể kiểm tra.
- Giảm diễn giải sai.
- Không phụ thuộc hoàn toàn vào trí nhớ người đọc.
- Người dùng vẫn giữ quyền quyết định.

## Giá trị khác biệt

Không nên định vị sản phẩm là:

> “AI có thể tóm tắt PDF.”

Nên định vị là:

> “AI giúp người nghiên cứu tổng hợp nhiều tài liệu thành kết luận có cấu trúc, đồng thời chứng minh từng kết luận được lấy từ đâu.”

---

# 12. Định nghĩa vấn đề

## Bản đầy đủ

> Sinh viên cao học và nghiên cứu viên phải xử lý hàng chục đến hàng trăm tài liệu để viết tổng quan nghiên cứu. Họ gặp khó khăn trong việc xây dựng truy vấn, sàng lọc tài liệu, đọc toàn văn, ghi chú, so sánh kết quả, phát hiện mâu thuẫn, xác định khoảng trống và kiểm tra nguồn trích dẫn. Quy trình hiện tại tốn nhiều thời gian, thiếu nhất quán và có nguy cơ bỏ sót tài liệu hoặc trích dẫn sai. LitReview Agent sử dụng AI để hỗ trợ tìm kiếm, sàng lọc, trích xuất có cấu trúc, tổng hợp đa tài liệu và kiểm chứng claim theo evidence, trong khi vẫn giữ con người trong vòng kiểm soát.

## Bản ngắn dùng khi thuyết trình

> Người nghiên cứu đau nhất khi có quá nhiều tài liệu nhưng không biết bài nào đáng đọc, phải tự tìm thông tin trong từng PDF và khi viết lại không nhớ mỗi nhận định đến từ nguồn nào. AI được sử dụng để tìm kiếm thông minh, sàng lọc, đọc và trích xuất tài liệu, tổng hợp nhiều nghiên cứu và kiểm chứng từng claim bằng đúng đoạn bằng chứng.

---

# 13. Trả lời trực tiếp: ai với ai, đau như nào, đau ở đâu?

## Ai đau?

- Sinh viên cao học.
- Nghiên cứu sinh.
- Nghiên cứu viên.
- Giảng viên.
- Reviewer.
- Trưởng nhóm nghiên cứu.

## Đau với ai?

- Sinh viên đau khi phải tự tìm và đọc quá nhiều tài liệu.
- Nghiên cứu viên đau khi phải sàng lọc và tổng hợp số lượng lớn công trình.
- Reviewer đau khi phải truy ngược nguồn cho từng nhận định.
- Trưởng nhóm đau khi thành viên ghi chú thiếu đồng nhất và khó theo dõi tiến độ.

## Đau như nào?

- Mất thời gian.
- Quá tải thông tin.
- Dễ bỏ sót tài liệu.
- Dễ ghi chú sai hoặc thiếu.
- Khó so sánh.
- Khó tổng hợp.
- Không nhớ nguồn.
- Dễ trích dẫn sai.
- Khó xác định research gap.
- Khó phối hợp nhóm.

## Đau ở đâu?

- Khi xác định từ khóa.
- Khi tìm kiếm.
- Khi sàng lọc.
- Khi đọc PDF.
- Khi ghi chú.
- Khi so sánh.
- Khi tổng hợp.
- Khi viết.
- Khi kiểm tra citation.
- Khi review nội dung.
- Khi làm việc nhóm.

## AI giải quyết như thế nào?

- Query Planning.
- Semantic Search.
- Reranking.
- Screening.
- PDF Understanding.
- Structured Extraction.
- Research Matrix.
- Multi-document Synthesis.
- Contradiction Detection.
- Candidate Gap Analysis.
- Claim-level Citation Verification.
- Human-in-the-loop Review.
- Evidence-grounded Drafting.

---

# 14. Chỉ số đánh giá hiệu quả

| Chỉ số | Ý nghĩa |
|---|---|
| Retrieval Recall@K | Có tìm được tài liệu quan trọng không |
| Screening Precision | Các bài AI chọn có phù hợp không |
| Screening Recall | AI có bỏ sót bài phù hợp không |
| Deduplication Accuracy | Loại trùng có đúng không |
| Extraction Accuracy | Trích xuất method, dataset, result có đúng không |
| Citation Validity | Citation có tồn tại không |
| Citation Coverage | Bao nhiêu claim có nguồn |
| Claim Support Rate | Bao nhiêu claim được evidence hỗ trợ |
| Human Acceptance Rate | Reviewer chấp nhận bao nhiêu kết quả |
| Time Saving | Giảm bao nhiêu thời gian so với thủ công |

Công thức tham khảo:

```text
Citation Coverage
= Số factual claim có citation
  / Tổng factual claim
```

```text
Claim Support Rate
= Số claim được evidence hỗ trợ
  / Tổng số claim
```

```text
Time Saving
= (Thời gian thủ công - Thời gian có AI)
  / Thời gian thủ công
```

---

# 15. Kết luận

Nỗi đau lớn nhất của đề tài không phải là người dùng thiếu một công cụ tóm tắt.

Nỗi đau thực sự là:

> Người nghiên cứu không có một quy trình thống nhất để chuyển hàng trăm tài liệu thành tri thức có cấu trúc, có bằng chứng và có thể kiểm chứng.

AI có giá trị nhất khi được sử dụng để:

```text
Giảm tải công việc lặp lại
+ Tăng khả năng tìm đúng tài liệu
+ Chuẩn hóa dữ liệu nghiên cứu
+ Hỗ trợ tổng hợp nhiều nguồn
+ Truy vết claim đến evidence
+ Giữ con người trong vòng kiểm soát
```

Định vị phù hợp nhất cho sản phẩm:

> LitReview Agent là trợ lý AI hỗ trợ toàn bộ quy trình tổng quan tài liệu, từ tìm kiếm, sàng lọc, đọc hiểu, tổng hợp đến kiểm chứng citation, giúp người nghiên cứu tiết kiệm thời gian nhưng vẫn bảo đảm khả năng truy vết và kiểm soát chất lượng.
