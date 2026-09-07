# Benchmark — 20260828-104000-merged_full_retry

> Sinh lúc 2026-08-28 13:32 UTC · 12 lượt chạy (12 hoàn tất) · artifact thô: `benchmarks/results/20260828-104000-merged_full_retry`

Mọi con số dưới đây tính trực tiếp từ artifact thô đã lưu. Tái lập bằng: `python -m benchmarks report benchmarks/results/20260828-104000-merged_full_retry`

## 1. Tóm tắt điều hành

| Chỉ số | Kết quả | Mục tiêu | Đánh giá |
|---|---|---|---|
| Trích dẫn bịa (fabricated citations) | **0.0% (0/486)** | ≤ 0% | 🟢 đạt |
| Nguồn tra cứu được thật | **100.0% (96/96)** | — | — |
| Citation review trỏ tới paper đã lấy | **100.0% (242/242)** | ≥ 100% | 🟢 đạt |
| Đoạn review có evidence truy vết được | **74.1% (80/108)** | ≥ 95% | 🔴 chưa đạt |
| Claim có bằng chứng | **100.0% (220/220)** | ≥ 100% | 🟢 đạt |
| Trích dẫn kiểm chứng được (verbatim) | **100.0% (167/167)** | ≥ 95% | 🟢 đạt |
| Độ phủ chủ đề (theme recall) | **77.8% (28/36)** | ≥ 70% | 🟢 đạt |
| Đủ metadata ingestion cho paper | **100.0% (167/167)** | — | — |
| Paper có full text | **36.5% (61/167)** | — | — |
| Paper chỉ có abstract (không khả dụng) | **38.3% (64/167)** | — | — |
| Paper fallback do lỗi ingestion | **25.1% (42/167)** | — | — |
| Tỷ lệ chạy thành công | **100.0% (12/12)** | ≥ 95% | 🟢 đạt |
| Thời gian một lượt review | **685.6s** | — | — |
| Chi phí một lượt review | **chưa đo được** | — | — |

### Chưa đo được — nêu rõ thay vì bỏ trống

- **Thời gian tiết kiệm so với làm tay**: chưa có baseline thủ công đo thật — cần bấm giờ một researcher làm cùng chủ đề, cùng số bài, rồi truyền vào
- **Chi phí một lượt review**: hệ thống chưa ghi token/chi phí — bật Langfuse (LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY) hoặc truyền usage vào để đo thật
- **Độ ổn định đầu ra**: cần chạy lặp cùng một chủ đề ≥2 lần (--repeat 3)

## 2. Vết kiểm toán từng chỉ số

### Bài báo được dùng thật

- Kết quả: **82.6% (138/167)**
- Cách đo: Tỷ lệ bài đã tải/xử lý mà thực sự được trích dẫn trong báo cáo. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 50%: Tải 20 bài chỉ dùng 3 nghĩa là đang trả tiền cho 17 bài vô ích.

### Bằng chứng từ full text

- Kết quả: **34.5% (88/255)**
- Cách đo: Tỷ lệ trích dẫn lấy từ toàn văn thay vì chỉ abstract. (Số trên gộp từ 12 lượt chạy.)

### Chi phí một lượt review

- Kết quả: **chưa đo được**

### Citation review trỏ tới paper đã lấy

- Kết quả: **100.0% (242/242)**
- Cách đo: Kiểm từng `[[paper_id]]` trong bản literature review cuối có thuộc corpus trả về hay không. Đây là tính toàn vẹn định danh, không tự khẳng định câu văn được suy ra đúng. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 100%: Bất kỳ citation nào trong bài review cuối không thuộc corpus là một đường dẫn nguồn không thể kiểm toán.

### Claim có bằng chứng

- Kết quả: **100.0% (220/220)**
- Cách đo: Tỷ lệ claim được đánh dấu hợp lệ mà thực sự kèm ít nhất một trích dẫn. Claim loại `potential_gap` (khẳng định sự VẮNG MẶT) không được tính, vì bằng chứng của nó là chính corpus chứ không phải một quote. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 100%: Claim đã đánh dấu hợp lệ mà không có trích dẫn là khẳng định trần, đội lốt đã kiểm chứng.

### Nguồn tra cứu được thật

- Kết quả: **100.0% (96/96)**
- Cách đo: Tỷ lệ paper trong corpus tồn tại thật khi gọi lại API nguồn (OpenAlex / Semantic Scholar / arXiv). 71 ID không tra được đã loại khỏi mẫu số (lỗi kiểm tra, không tính vào kết quả).

### Nút thắt cổ chai

- Kết quả: **50.8%**
- Cách đo: Chặng chậm nhất của lượt chạy: `validate_grounding` (tỷ lệ phần thời gian thể hiện ở giá trị chỉ số). (Số trên gộp từ 12 lượt chạy.)

### Paper chỉ có abstract (không khả dụng)

- Kết quả: **38.3% (64/167)**
- Cách đo: Tỷ lệ paper không tìm thấy nguồn full text và phải dùng abstract. (Số trên gộp từ 12 lượt chạy.)

### Paper có full text

- Kết quả: **36.5% (61/167)**
- Cách đo: Tỷ lệ paper đã phân loại tải và parse thành công PDF, PMC XML hoặc HTML toàn văn. (Số trên gộp từ 12 lượt chạy.)

### Paper fallback do lỗi ingestion

- Kết quả: **25.1% (42/167)**
- Cách đo: Tỷ lệ paper có thử lấy full text nhưng tải hoặc parse thất bại, sau đó fallback abstract. (Số trên gộp từ 12 lượt chạy.)

### Số nguồn/claim

- Kết quả: **1.02634**
- Cách đo: Trung bình số bài báo khác nhau chống lưng cho mỗi claim. (Số trên gộp từ 12 lượt chạy.)

### Thời gian một lượt review

- Kết quả: **685.6s**
- Cách đo: Tổng thời gian máy chạy thật qua các chặng (đã trừ thời gian chờ người duyệt). (Số trên gộp từ 12 lượt chạy.)

### Thời gian tiết kiệm so với làm tay

- Kết quả: **chưa đo được**

### Thời gian tới kết quả đầu tiên

- Kết quả: **153.5s**
- Cách đo: Tới chặng `search_academic_sources` là người dùng đã có bài báo để đọc. (Số trên gộp từ 12 lượt chạy.)

### Trích dẫn bịa (fabricated citations)

- Kết quả: **0.0% (0/486)**
- Cách đo: Tỷ lệ paper_id được trích dẫn nhưng KHÔNG tồn tại trong corpus. Mục tiêu: 0%. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≤ 0%: Một trích dẫn bịa là đủ để nhà nghiên cứu bỏ công cụ. Không có ngưỡng chấp nhận được nào khác 0.

### Trích dẫn kiểm chứng được (verbatim)

- Kết quả: **100.0% (167/167)**
- Cách đo: Tỷ lệ quote khớp NGUYÊN VĂN với nguồn đang lưu. Quote lấy từ full text mà artifact không lưu toàn văn được loại khỏi mẫu số — không kiểm được offline thì không cho qua, cũng không tính trượt. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 95%: Quote phải khớp nguyên văn nguồn; sai lệch nhỏ vẫn là diễn giải lại lời tác giả.

### Tỷ lệ chạy thành công

- Kết quả: **100.0% (12/12)**
- Cách đo: Tỷ lệ lượt chạy chủ đề THẬT ra được báo cáo dùng được (không tính kiểm soát âm).
- Vì sao đặt mục tiêu ≥ 95%: Dưới 95% là gánh nặng vận hành: cứ 20 lượt có hơn 1 lượt phải xử lý tay.

### Đoạn review có evidence truy vết được

- Kết quả: **74.1% (80/108)**
- Cách đo: Mỗi đoạn factual (abstract/introduction/sections/conclusion/limitations) phải có ít nhất một `[[paper_id]]` mà cùng paper đó có evidence quote ở claim hợp lệ. Đây là traceability, không phải chứng minh entailment ở mức câu. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 95%: Đoạn factual không nối được tới quote evidence là điểm mù: có thể đúng, nhưng chưa chứng minh được bằng artifact.
- Số mục không đạt: **28** (liệt kê tối đa 5):
  - đoạn review không có citation — location=abstract · cited_paper_ids=[]
  - đoạn review không có citation — location=conclusion · cited_paper_ids=[]
  - đoạn review không có citation — location=abstract · cited_paper_ids=[]
  - đoạn review không có citation — location=introduction · cited_paper_ids=[]
  - đoạn review không có citation — location=conclusion · cited_paper_ids=[]

### Đạt số bài yêu cầu

- Kết quả: **96.0% (167/174)**
- Cách đo: Tỷ lệ bài giao so với số bài người dùng yêu cầu (max_results trong dataset). (Số trên gộp từ 12 lượt chạy.)
- Số mục không đạt: **3** (liệt kê tối đa 5):
  - thiếu 1 bài so với yêu cầu — 
  - thiếu 4 bài so với yêu cầu — 
  - thiếu 2 bài so với yêu cầu — 

### Độ phủ chủ đề (theme recall)

- Kết quả: **77.8% (28/36)**
- Cách đo: Tỷ lệ chủ đề con mà chuyên gia kỳ vọng phải có, và hệ thống thực sự nhắc tới. ⚠️ Dùng token-overlap (≥50% từ khoá xuất hiện trong output): tốt để bắt regression (hệ thống bỏ sót hẳn một mảng), nhưng KHÔNG đủ để kết luận độ phủ ngữ nghĩa — cần gold labels của chuyên gia cho mục đích đó. (Số trên gộp từ 12 lượt chạy.)
- Vì sao đặt mục tiêu ≥ 70%: Dưới ngưỡng này, bản review bỏ sót mảng kiến thức mà chuyên gia coi là bắt buộc.
- Số mục không đạt: **6** (liệt kê tối đa 5):
  - không xuất hiện trong theme/claim nào — expected_theme=Few-shot prompting
  - không xuất hiện trong theme/claim nào — expected_theme=Cross-lingual transfer
  - không xuất hiện trong theme/claim nào — expected_theme=Difference-in-differences
  - không xuất hiện trong theme/claim nào — expected_theme=Benchmark đánh giá
  - không xuất hiện trong theme/claim nào — expected_theme=Domain adaptation

### Độ trễ p50 / p95

- Kết quả: **707.6s**
- Cách đo: p50 = 708s · p95 = 993s · nhanh nhất 396s · chậm nhất 993s (n=12). Đây là wall clock từ lúc tạo job (bao gồm cả chờ) — khác với 'Thời gian một lượt review' đã trừ các chặng chờ người duyệt.

### Độ ổn định đầu ra

- Kết quả: **chưa đo được**

### Đủ metadata ingestion cho paper

- Kết quả: **100.0% (167/167)**
- Cách đo: Tỷ lệ paper có tuple availability/status hợp lệ. (Số trên gộp từ 12 lượt chạy.)

## 6. Cách đọc bản báo cáo này

- **🔴 chưa đạt** không có nghĩa sản phẩm hỏng — nó chỉ ra đúng chỗ cần đầu tư tiếp.
- **⚪ chưa đo** là trung thực có chủ đích: chỉ số đó cần dữ liệu mà lượt chạy này không có (ví dụ baseline thủ công, hoặc token usage chưa bật). Không suy đoán số thay thế.
- Mọi tỷ lệ đều kèm tử số/mẫu số để tự kiểm, và mọi mục không đạt đều liệt kê được.
- Hai chỉ số thời gian đo khác nhau: **Thời gian một lượt review** là thời gian máy chạy (đã trừ chờ người duyệt); **Độ trễ p50/p95** là wall clock từ lúc tạo job. Trừ nhau ra thời gian chờ, không phải sai số.