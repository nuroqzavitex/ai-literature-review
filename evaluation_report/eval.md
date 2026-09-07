# LitReview Agent — Evaluation Metrics Report

> ## 🚨 KHÔNG DÙNG FILE NÀY ĐỂ PITCH
>
> Mọi con số trong file này **không truy được về dữ liệu thô**, và cột baseline
> ở mục 2 tự ghi rõ *"Không đo trong demo"* / *"Chỉ là số minh hoạ"*. Đưa 85.7%
> hay 56.7% ra trước nhà đầu tư rồi bị hỏi baseline lấy ở đâu là mất tín nhiệm
> cho toàn bộ phần còn lại.
>
> Số dùng được nằm ở **`benchmarks/results/<lượt chạy>/report.md`**: mọi tỷ lệ
> đều kèm tử số/mẫu số, mọi mục không đạt đều liệt kê được, và tính lại được từ
> artifact thô bằng `python -m benchmarks report <thư-mục>`.
>
> Giữ file này lại chỉ để đối chiếu lịch sử khung đánh giá ban đầu.

> **Mục đích:** Báo cáo đánh giá chất lượng LitReview Agent theo bốn metric cốt lõi: Core quality, Provenance, Completeness và Product value.

---

## 1. Bộ khung đánh giá (Evaluation Framework)

| # | Metric | Feature | Định nghĩa | Cách đo từ code | Target | Actual |
|---|---|---|---|---|---|---|
| 1 | **Core quality — Claim-support accuracy** | Claims & grounding | Tỷ lệ claim được reviewer kết luận `supported` trên mọi claim đã được review ở các job `approved`. | `supported_claims / claims_reviewed` | ≥ 80% | **85.7%** (48/56) |
| 2 | **Provenance — Reference validity** | References | Tỷ lệ reference được reviewer xác nhận `valid` trên mọi reference đã được kiểm tra ở các job `approved`. | `valid_references / references_checked` | 100% | **100%** (50/50) |
| 3 | **Completeness — Review coverage** | Reviewer workflow | Mức độ report được kiểm tra đầy đủ trước khi đưa vào KPI: cả claim và reference đều phải được review. | `claims_reviewed / total_claims = 1.0` **và** `references_checked / total_references = 1.0` | 100% cho cả hai | **100% / 100%** |
| 4 | **Product value — Median time reduction** | Literature-review workflow | Mức giảm thời gian của quy trình agent so với làm thủ công cho các tác vụ tương đương. | Median của `(manual_minutes - mvp_minutes) / manual_minutes` | ≥ 50% | **56.7%** |

> **Quy tắc pass MVP trong code:** cần tối thiểu 30 claims reviewed, 5 reports evaluated, đủ 100% claim/reference coverage, claim-support accuracy ≥ 80%, reference validity = 100%, và median time reduction ≥ 50%.

---

## 2. Evaluation baseline

| Metric | Baseline so sánh | Baseline value | LitReview Agent actual | Cách diễn giải improvement |
|---|---|---|---|---|
| Core quality | Draft sinh bởi LLM chưa qua reviewer | Không đo trong demo | 85.7% | Chỉ là số minh hoạ cho tỷ lệ claims được reviewer chấp nhận. |
| Provenance | Reference không được đối chiếu metadata nguồn | Không đo trong demo | 100% | Minh hoạ mục tiêu không có reference invalid. |
| Completeness | Review thủ công không có guard bắt buộc kiểm tra đủ mọi claim/reference | Không đo trong demo | 100% / 100% | Minh hoạ điều kiện coverage để hệ thống pass KPI. |
| Product value | Thời gian researcher làm literature map thủ công cho cùng topic và số paper | Không đo trong demo | 56.7% | Minh hoạ median của 5 case bên dưới. |


---

## 3. Chi tiết cách đo

### 3.1 Core quality — Claim-support accuracy

**Công thức:**

```text
Claim-support accuracy = supported_claims / claims_reviewed
```

**Nguồn dữ liệu:** bảng quyết định reviewer (`ReviewDecision`) của những job có trạng thái `approved`. Nếu một claim có nhiều quyết định, hệ thống chỉ dùng quyết định mới nhất.

| Case # | Topic | Claims reviewed | Supported claims | Claim-support accuracy |
|---|---|---:|---:|---:|
| 1 | Graph neural networks in drug discovery | 12 | 11 | 91.7% |
| 2 | Federated learning privacy attacks on edge devices | 12 | 10 | 83.3% |
| 3 | Mamba architecture for clinical time-series forecasting | 10 | 8 | 80.0% |
| 4 | Transformer models for low-resource machine translation | 11 | 9 | 81.8% |
| 5 | Diffusion models for protein structure prediction | 11 | 10 | 90.9% |
| | **TỔNG** | **56** | **48** | **85.7%** |

### 3.2 Provenance — Reference validity

**Công thức:**

```text
Reference validity = valid_references / references_checked
```

**Tiêu chí reviewer:** đối chiếu title, author và URL/DOI của reference với metadata do nguồn học thuật trả về. Chỉ verdict `valid` được tính vào tử số; verdict `invalid` phải được lưu cùng ghi chú reviewer.

| Case # | Topic | References checked | Valid references | Reference validity |
|---|---|---:|---:|---:|
| 1 | Graph neural networks in drug discovery | 10 | 10 | 100% |
| 2 | Federated learning privacy attacks on edge devices | 10 | 10 | 100% |
| 3 | Mamba architecture for clinical time-series forecasting | 10 | 10 | 100% |
| 4 | Transformer models for low-resource machine translation | 10 | 10 | 100% |
| 5 | Diffusion models for protein structure prediction | 10 | 10 | 100% |
| | **TỔNG** | **50** | **50** | **100%** |

### 3.3 Completeness — Review coverage

**Công thức:**

```text
Claim review coverage     = claims_reviewed / total_claims
Reference review coverage = references_checked / total_references
Completeness pass         = cả hai coverage = 1.0
```

Một report chưa review đủ không được coi là pass, ngay cả khi các claim/reference đã chấm đều hợp lệ. Cơ chế này tránh việc tỷ lệ cao được tạo ra từ một mẫu review chọn lọc.

| Case # | Total claims | Claims reviewed | Claim coverage | Total references | References checked | Reference coverage | Pass |
|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 12 | 12 | 100% | 10 | 10 | 100% | ✅ |
| 2 | 12 | 12 | 100% | 10 | 10 | 100% | ✅ |
| 3 | 10 | 10 | 100% | 10 | 10 | 100% | ✅ |
| 4 | 11 | 11 | 100% | 10 | 10 | 100% | ✅ |
| 5 | 11 | 11 | 100% | 10 | 10 | 100% | ✅ |

### 3.4 Product value — Median time reduction

**Công thức mỗi case:**

```text
Time reduction = (manual_minutes - mvp_minutes) / manual_minutes
```

**Metric aggregate:** lấy median của các time-reduction hợp lệ (chỉ dùng record có `manual_minutes > 0` và job đã `approved`). Đo thời gian tác vụ tổng thể, không tính thời gian chờ reviewer quyết định.

| Case # | Topic | Manual minutes | Agent minutes | Time reduction |
|---|---|---:|---:|---:|
| 1 | Graph neural networks in drug discovery | 120 | 50 | 58.3% |
| 2 | Federated learning privacy attacks on edge devices | 120 | 55 | 54.2% |
| 3 | Mamba architecture for clinical time-series forecasting | 120 | 62 | 48.3% |
| 4 | Transformer models for low-resource machine translation | 120 | 52 | 56.7% |
| 5 | Diffusion models for protein structure prediction | 120 | 48 | 60.0% |
| | **Median** | | | **56.7%** |

---

## 4. Guardrails và điều kiện dữ liệu

| Guardrail | Evidence trong hệ thống | Ý nghĩa đối với evaluation |
|---|---|---|
| Reviewer-only decision | API chỉ nhận review khi role là `reviewer`. | Không dùng LLM hoặc researcher để tự chấm claim/reference. |
| Approved jobs only | Hàm aggregate chỉ truy vấn job có status `approved`. | Không trộn output dang dở hoặc bị từ chối vào KPI. |
| Latest verdict wins | Aggregator de-duplicate theo `(job_id, claim_id)` và `(job_id, paper_id)`. | Không đếm lặp verdict qua nhiều vòng review. |
| Complete review required | `mvp_passed` yêu cầu cả hai coverage bằng 1.0. | KPI accuracy/validity không được pass với mẫu kiểm tra thiếu. |
| Bounded acceptance | Cần ≥ 30 claims reviewed và ≥ 5 report evaluations. | Tránh tuyên bố pass từ số mẫu quá nhỏ. |

---

## 5. Tóm tắt

| Metric | Target | Actual |
|---|---:|---:|
| Core quality — Claim-support accuracy | ≥ 80% | 85.7% | 
| Provenance — Reference validity | 100% | 100% | 
| Completeness — Claim + reference coverage | 100% / 100% | 100% / 100% | 
| Product value — Median time reduction | ≥ 50% | 56.7% | 


