# Literature-source evaluation — RAGAS evidence grounding

> Câu hỏi đo: **Hệ thống có lấy paper thật, liên quan chủ đề, và dùng evidence từ paper đó để viết literature review không?**

> RAGAS là LLM-as-judge cho phần evidence → review. Nó chỉ để so sánh các phiên bản cùng judge/model; không thay thế kiểm tra citation/evidence tất định hoặc gold do người duyệt.

> Artifact thô: `benchmarks/results/20260828-104000-merged_full_retry` · 12/12 lượt có score.

## 1. Paper có tồn tại thật?

- **Nguồn tra cứu được thật**: 100.0% (96/96)
- Cách đo: Tỷ lệ paper trong corpus tồn tại thật khi gọi lại API nguồn (OpenAlex / Semantic Scholar / arXiv). 71 ID không tra được đã loại khỏi mẫu số (lỗi kiểm tra, không tính vào kết quả).

## 2. Paper có liên quan chủ đề?

| Chỉ số | Kết quả |
|---|---|
| Paper relevance precision (gold) | **chưa đo được** |
| Paper relevance recall (gold) | **9.8% (13/132)** |

- **Paper relevance precision (gold)**: gold hiện là positive-only: chưa gán nhãn exhaustive cho toàn bộ paper trả về; chỉ paper recall/hit rate được đo.

Paper relevance so sánh `result.papers` cuối với paper IDs do reviewer chọn/sửa. Đây không phải Precision@K/Recall@K theo raw retrieval chunk.

## 3. Evidence từ paper có đi vào literature review?

| Kiểm tra tất định | Kết quả |
|---|---|
| Citation review trỏ tới paper đã lấy | **100.0% (242/242)** |
| Đoạn review có evidence truy vết được | **74.1% (80/108)** |

`Citation review trỏ tới paper đã lấy` kiểm citation trong prose cuối; `Đoạn review có evidence truy vết được` đòi hỏi citation đó nối tới quote của claim hợp lệ. Hai số này kiểm đường dẫn, chưa tự chứng minh câu văn suy ra đúng.

## 4. RAGAS: evidence có support nội dung review?

| Chỉ số | Kết quả | Mục tiêu |
|---|---|---|
| RAGAS Faithfulness | **72.7%** | ≥90% |
| RAGAS Context Precision | **11.2%** | ≥80% |
| RAGAS Context Recall | **21.1%** | ≥80% |

### Điểm từng lượt

| Topic | Faithfulness | Context precision | Context recall |
|---|---:|---:|---:|
| `pos_01` | 75.0% | 0.0% | 100.0% |
| `pos_02` | 90.0% | 0.0% | 28.6% |
| `pos_03` | 68.4% | 18.3% | 57.1% |
| `pos_04` | 81.8% | 29.5% | 0.0% |
| `pos_05` | 100.0% | 0.0% | 0.0% |
| `pos_06` | 81.8% | 8.0% | 14.3% |
| `pos_07` | 14.3% | 6.2% | 16.7% |
| `pos_08` | 80.4% | 8.3% | 16.7% |
| `pos_09` | 62.5% | 23.3% | 0.0% |
| `pos_10` | 41.7% | 0.0% | 20.0% |
| `pos_11` | 76.9% | 7.5% | 0.0% |
| `pos_12` | 100.0% | 33.3% | 0.0% |
## Phạm vi đo

- Faithfulness so sánh **chỉ literature review cuối** với evidence quote của các claim hợp lệ.
- Context Precision/Recall chỉ chạy khi gold đã review có `reference_answer` do người viết; chúng mô tả tập evidence cuối.
- Run mới lưu `retrieval_traces` (top-K chunk, rank, score, provenance). Chỉ khi có gold chunk do reviewer duyệt mới được dùng chúng để chấm Precision@K/Recall@K/MRR/NDCG; report này không tự suy ra gold từ ranking của hệ thống.