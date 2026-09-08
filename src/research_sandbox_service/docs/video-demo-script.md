# Kịch bản quay video demo Research Sandbox

## 1. Mục tiêu video

Video dài khoảng 8–10 phút, trình bày một câu chuyện xuyên suốt:

> Từ một câu hỏi nghiên cứu về giấc ngủ, người dùng tạo và duyệt giả thuyết,
> chuyển giả thuyết sang luồng phân tích dữ liệu, chạy mã Python do AI sinh trong
> Docker Sandbox, kiểm tra kết quả có citation và tải gói tái lập.

Video cần làm rõ bốn giá trị chính của sản phẩm:

1. AI chỉ tạo bản thảo; các điểm quan trọng đều có reviewer gate.
2. Dữ liệu thô không được đưa vào prompt AI; profiling chạy deterministic.
3. Mã Python được kiểm tra AST và chạy trong container cô lập.
4. Kết quả có lineage, citation và Reproducibility Bundle.

Graph Overlay đã được gỡ khỏi product hiện tại, vì vậy video chỉ trình bày hai
chế độ **Giả thuyết** và **Phân tích dữ liệu**.

## 2. Câu chuyện nghiên cứu

### Bối cảnh

Một nhóm nghiên cứu muốn kiểm tra liệu thời lượng ngủ dài hơn có liên quan với
thời gian phản ứng tốt hơn hay không. Thời gian phản ứng thấp hơn được xem là tốt
hơn. Hai yếu tố có thể gây nhiễu là lượng caffeine và thời gian học trong ngày.

### Câu hỏi dùng xuyên suốt video

```text
Trong bộ dữ liệu có các cột sleep_hours, reaction_time_ms, caffeine_mg và
study_hours, liệu sleep_hours cao hơn có liên quan với reaction_time_ms thấp hơn
sau khi kiểm soát caffeine_mg và study_hours không?
```

### Giả thuyết mong đợi

```text
Khi giữ caffeine_mg và study_hours không đổi, sleep_hours cao hơn có liên quan
với reaction_time_ms thấp hơn.
```

Đây là giả thuyết về **association**, không phải causation. Không dùng các câu
như “ngủ thêm chắc chắn làm phản ứng nhanh hơn” trong lời thoại hoặc kết luận.

## 3. Bộ dữ liệu demo chính

Tên file: `sandbox_demo_sleep_study.csv`

Phân loại: `non_sensitive`

Dữ liệu hoàn toàn synthetic, không đại diện cho người thật và không được dùng để
đưa ra kết luận khoa học ngoài video demo.

### Ý nghĩa các cột

| Cột | Kiểu dữ liệu | Ý nghĩa | Vai trò phân tích |
| --- | --- | --- | --- |
| `participant_id` | text | Mã bản ghi synthetic | Định danh, không dùng làm predictor |
| `sleep_hours` | float | Số giờ ngủ trung bình | Predictor chính |
| `reaction_time_ms` | integer | Thời gian phản ứng, thấp hơn là tốt hơn | Outcome |
| `caffeine_mg` | integer | Lượng caffeine trong ngày | Covariate |
| `study_hours` | float | Số giờ học trong ngày | Covariate |

### Nội dung CSV

Lưu nguyên khối dưới đây bằng UTF-8 với tên
`sandbox_demo_sleep_study.csv`:

```csv
participant_id,sleep_hours,reaction_time_ms,caffeine_mg,study_hours
S001,5.7,316,150,5.9
S002,4.6,337,200,1.5
S003,4.7,342,250,4.9
S004,6.5,306,100,5.5
S005,8.4,266,0,4.7
S006,6.7,285,200,5.9
S007,8.1,255,250,5.6
S008,6.9,314,0,7.6
S009,7.9,289,100,6.1
S010,4.8,353,150,7.3
S011,6.9,296,150,2.4
S012,6.8,307,0,6.3
S013,5.8,305,150,3.6
S014,8,268,150,2
S015,5.4,311,300,3.9
S016,5.8,296,100,1.5
S017,5.5,330,150,5.5
S018,8.1,277,150,7.2
S019,4.6,350,200,5.6
S020,7.6,266,150,3.1
S021,6.6,303,150,6.7
S022,6.1,323,50,4.9
S023,5.1,333,250,4
S024,6,317,50,4.2
S025,7,292,150,3.5
S026,6.5,305,250,5.9
S027,4.8,346,0,4
S028,7.6,279,50,1.8
S029,5,322,200,1.2
S030,7.4,302,250,7.9
S031,5.2,340,50,5.8
S032,5.8,299,250,4.8
S033,6.1,318,150,6.8
S034,6.7,290,200,3.2
S035,6,326,100,4.6
S036,6.6,311,100,6.3
S037,4.7,335,100,2.5
S038,4.7,337,100,6.6
S039,6.9,299,200,5.9
S040,7.9,281,0,4.9
S041,6.5,295,100,1.1
S042,5.9,313,250,7.6
S043,6.2,300,300,4.1
S044,4.6,347,250,5.2
S045,6.9,283,150,5.1
S046,5.6,309,250,5.2
S047,7,288,250,4.5
S048,7.8,263,150,4.3
S049,5,351,250,7.1
S050,7.9,250,300,1.6
S051,7.2,274,50,2.7
S052,6.3,315,200,6.2
S053,6.3,302,250,3.7
S054,8.1,266,150,2.7
S055,6.1,324,0,5.5
S056,5.4,322,200,1.3
S057,8.4,254,100,3.7
S058,6.9,304,200,4.5
S059,6.2,298,150,4.2
S060,4.9,319,150,1.7
```

### Mốc kiểm tra dữ liệu

Các số dưới đây dùng để kiểm tra video, không cần đọc hết trong lời thoại:

- Số dòng: `60`.
- Số cột: `5`.
- Missing values: `0` ở tất cả các cột.
- `sleep_hours`: từ `4.6` đến `8.4`, trung bình khoảng `6.345`.
- `reaction_time_ms`: từ `250` đến `353`, trung bình khoảng `305.07`.
- Tương quan Pearson giữa `sleep_hours` và `reaction_time_ms`: khoảng `-0.914`.
- OLS với covariates `caffeine_mg` và `study_hours`:
  - hệ số `sleep_hours`: khoảng `-22.08 ms/giờ`;
  - sai số chuẩn: khoảng `0.91`;
  - khoảng tin cậy 95% xấp xỉ `[-23.89, -20.26]`;
  - `R²`: khoảng `0.919`.

Kết quả thực tế có thể được trình bày khác đôi chút tùy AnalysisPlan và code mà
AI sinh, nhưng dấu của hệ số phải âm và xu hướng chính phải nhất quán.

## 4. File kiểm tra guardrail tùy chọn

Tên file: `sandbox_demo_mismatch.csv`

```csv
city,temperature_c,rainfall_mm
Hanoi,31.2,12
DaNang,29.8,4
HoChiMinhCity,32.5,18
```

File này không có bất kỳ biến bắt buộc nào của giả thuyết. Chỉ dùng nếu muốn
quay thêm cảnh hệ thống hiển thị `MISMATCH_DATASET`. Không dùng trong flow chính
để tránh làm danh sách dataset bị rối.

## 5. Chuẩn bị trước khi quay

1. Dùng một project mới hoặc project đã dọn các session/dataset test cũ.
2. Kiểm tra Docker Desktop đang chạy.
3. Chạy:

   ```bash
   docker compose up -d --build --force-recreate
   ```

4. Chờ các service `backend`, `frontend`, `sandbox-control` và
   `sandbox-worker` healthy/running.
5. Mở trang Sandbox và xác nhận chỉ có hai tab **Giả thuyết** và
   **Phân tích dữ liệu**.
6. Đảm bảo capability hiển thị AI đang bật, không phải adapter mock.
7. Chạy thử flow một lần trước khi quay để warm up image, model route và cache.
8. Khi quay thật, tạo session mới để timeline và timestamp sạch.
9. Đặt zoom trình duyệt 90–100%, đóng DevTools và tắt notification không liên
   quan.
10. Không mở `.env`, terminal chứa key hoặc log có thông tin nhạy cảm trong video.

## 6. Kịch bản quay chính

### Cảnh 1 — Giới thiệu không gian Sandbox (0:00–0:40)

**Thao tác**

- Mở project và vào Research Sandbox.
- Dừng chuột ở hai tab để người xem thấy rõ hai chế độ.
- Chỉ nhanh vào nhãn project-scoped và trạng thái AI.

**Lời thoại gợi ý**

> Research Sandbox là không gian thử nghiệm tách biệt theo từng project. AI có
> thể hỗ trợ tạo giả thuyết, kế hoạch và code, nhưng không tự thay đổi dữ liệu
> lõi. Những bước quan trọng đều cần người dùng kiểm tra và phê duyệt.

### Cảnh 2 — Tạo session giả thuyết (0:40–1:30)

**Thao tác**

1. Chọn tab **Giả thuyết**.
2. Bấm tạo session mới.
3. Đặt tên session: `Giấc ngủ và thời gian phản ứng`.
4. Dán câu hỏi nghiên cứu ở Mục 2.
5. Bấm **Tạo bản thảo**.

**Lời thoại gợi ý**

> Tôi bắt đầu bằng một câu hỏi có thể kiểm chứng và ghi rõ tên các biến dự kiến.
> Sandbox ghim context của session rồi yêu cầu Project AI tạo một bản thảo; bước
> này chưa cần dataset và chưa chạy bất kỳ code nào.

### Cảnh 3 — Review Hypothesis Draft (1:30–2:20)

**Thao tác**

- Cuộn chậm qua statement, rationale, falsification criteria, required data và
  limitations.
- Chỉ vào version/hash để nhấn mạnh draft bất biến.
- Tick toàn bộ checklist limitation.
- Bấm **Phê duyệt**.
- Bấm **Tạo thiết kế** để sinh Experiment Draft.

**Điểm cần nói**

> AI phải nêu điều gì có thể bác bỏ giả thuyết, dữ liệu nào còn thiếu và các giới
> hạn. Reviewer phải xác nhận limitations trước khi duyệt; draft đã tạo được lưu
> theo version thay vì bị ghi đè.

Nếu AI dùng từ ngữ nhân quả, hãy nói rõ đây là điểm reviewer cần sửa hoặc từ
chối. Không duyệt một draft tuyên bố causation từ dữ liệu association.

### Cảnh 4 — Handoff sang Phân tích dữ liệu (2:20–2:50)

**Thao tác**

- Bấm **Chuyển sang Phân tích dữ liệu**.
- Cho người xem thấy tab đổi sang **Phân tích dữ liệu** và một session mới được
  tạo.
- Chỉ vào mục tiêu/câu hỏi đã được điền từ giả thuyết.

**Lời thoại gợi ý**

> Handoff không dùng lại session giả thuyết. Hệ thống tạo một session phân tích
> mới và mang theo mục tiêu, biến cần kiểm chứng cùng metrics. Nhờ vậy lineage
> giữa giả thuyết và run vẫn rõ ràng.

### Cảnh 5 — Upload và deterministic profiling (2:50–3:50)

**Thao tác**

1. Upload `sandbox_demo_sleep_study.csv`.
2. Chỉ vào trạng thái file hợp lệ và content hash.
3. Bấm **Chạy deterministic profile**.
4. Khi profile hoàn tất, chỉ vào `60 rows`, `5 columns`, kiểu dữ liệu và missing
   bằng `0`.

**Lời thoại gợi ý**

> File synthetic này không chứa dữ liệu nhạy cảm. Trước khi gọi AI, hệ thống xác
> thực định dạng thật, lưu content hash và profile hoàn toàn bằng code
> deterministic. Raw rows không được đưa vào prompt; AI chỉ nhận metadata của
> profile và research context.

**Cảnh guardrail tùy chọn, thêm 20–30 giây**

- Upload `sandbox_demo_mismatch.csv` trước file chính.
- Cho thấy cảnh báo `MISMATCH_DATASET` và nút tiếp tục bị khóa.
- Sau đó chọn/upload file chính để cảnh báo biến mất.

### Cảnh 6 — Làm rõ câu hỏi nghiên cứu (3:50–4:35)

Điền form như sau:

| Trường | Giá trị |
| --- | --- |
| Objective | `associate` |
| Research question | Câu hỏi ở Mục 2 |
| Outcome columns | `reaction_time_ms` |
| Predictor columns | `sleep_hours` |
| Group columns | để trống |
| Covariate columns | `caffeine_mg, study_hours` |
| Preferred metrics | `pearson_correlation, ols_beta, confidence_interval_95, p_value, r_squared` |

Bấm **Kiểm tra độ đầy đủ**.

**Lời thoại gợi ý**

> Sandbox không tự đoán biến hoặc mục tiêu còn thiếu. Nếu câu hỏi chưa đủ thông
> tin, state sẽ dừng ở question_incomplete. Ở đây tôi chọn association, xác định
> outcome, predictor và hai covariates một cách tường minh.

### Cảnh 7 — Tạo và review AnalysisPlan (4:35–5:35)

**Thao tác**

1. Bấm **Tạo plan từ metadata**.
2. Đọc nhanh objective, preprocessing, assumption checks và metrics.
3. Xác nhận plan dùng correlation/OLS hoặc phương pháp association tương đương.
4. Mở review và bấm phê duyệt.

**Điểm reviewer phải kiểm tra trước khi duyệt**

- Outcome là `reaction_time_ms`.
- Predictor chính là `sleep_hours`.
- Covariates gồm `caffeine_mg` và `study_hours`.
- Không diễn giải association thành causation.
- Có assumption checks và không dùng `participant_id` làm predictor.
- Metrics trong plan là những metrics kết quả sẽ báo cáo.

**Lời thoại gợi ý**

> AnalysisPlan là object bất biến có hash. Run chỉ được tạo từ một plan đã được
> reviewer phê duyệt, nên code generation không thể tự thay đổi mục tiêu phân
> tích sau bước này.

### Cảnh 8 — Generated Python Code và Docker run (5:35–6:45)

**Thao tác**

1. Bấm **Tạo run**.
2. Khi khối code xuất hiện, cuộn qua toàn bộ script.
3. Chỉ vào code hash, prompt version và nút **Sao chép code**.
4. Theo dõi timeline `queued → running → completed_unvalidated`.

**Những điểm nên chỉ trên code**

- Dữ liệu được đọc từ đường dẫn stage an toàn hoặc qua `sandbox_sdk`.
- Cột được truy cập bằng `df["sleep_hours"]`, không dùng attribute access.
- Output được ghi vào `/workspace/output/analysis_result.json`.
- Bảng được ghi vào `/workspace/output/tables/summary.csv`.
- Không có `os`, `subprocess`, network client, `eval` hoặc `exec`.

**Lời thoại gợi ý**

> Đây là chính xác source code gắn với code_version_id của run, không phải đoạn
> minh họa. Trước khi chạy, AST policy checker kiểm tra package và API bị cấm.
> Worker sau đó dispatch code sang container non-root, network-none và có giới
> hạn CPU, RAM, PID cùng timeout.

### Cảnh 9 — Validation, kết quả và citation (6:45–7:50)

**Thao tác**

- Chờ validation pass.
- Mở bảng summary và biểu đồ nếu run tạo chart.
- Chỉ vào interpretation và AnalysisCitation.
- Đối chiếu nhanh hệ số âm hoặc correlation âm với các mốc ở Mục 3.

**Lời thoại gợi ý**

> AI chỉ được diễn giải sau khi output vượt qua schema và scientific validation.
> Với bộ dữ liệu demo, sleep_hours có association âm mạnh với reaction_time_ms;
> mô hình OLS dự kiến cho hệ số khoảng âm 22 mili giây trên mỗi giờ ngủ thêm.
> Đây không phải bằng chứng nhân quả. Mọi numeric claim trong interpretation phải
> truy về dataset hash, run, locator và value hash qua AnalysisCitation.

Không đọc một con số nếu UI không hiển thị citation tương ứng. Nếu kết quả khác
đáng kể, dừng quay và kiểm tra AnalysisPlan/code thay vì cố giải thích tại chỗ.

### Cảnh 10 — Review và Reproducibility Bundle (7:50–8:40)

**Thao tác**

1. Mở review kết quả.
2. Phê duyệt kết quả đã validation pass.
3. Bấm tải Reproducibility Bundle.
4. Chỉ vào các hash lineage hiển thị trên UI hoặc trong bundle.

**Lời thoại gợi ý**

> Sau reviewer gate cuối, hệ thống niêm phong Reproducibility Bundle. Bundle giữ
> dataset hash, profile hash, plan hash, code hash, runtime image digest, random
> seed, result hash và artifact hashes. Một kết luận vì thế có thể truy ngược về
> đúng dữ liệu, plan, code và môi trường đã tạo ra nó.

### Cảnh 11 — Kết thúc (8:40–9:00)

**Lời thoại gợi ý**

> Research Sandbox biến một ý tưởng nghiên cứu thành workflow có kiểm soát: giả
> thuyết có thể bác bỏ, plan được duyệt, code quan sát được, execution cô lập và
> kết quả có thể tái lập. Sandbox hỗ trợ nhà nghiên cứu ra quyết định; nó không tự
> thay thế reviewer hay biến association thành kết luận nhân quả.

## 7. Shot list rút gọn

| Thời gian | Khung hình bắt buộc | Dấu hiệu cảnh đạt |
| --- | --- | --- |
| 0:00 | Header và hai tab Sandbox | Chỉ có Hypothesis/Data Analysis |
| 0:40 | Form tạo session | Session có tên rõ ràng |
| 1:30 | Hypothesis Draft | Có limitations và version/hash |
| 2:20 | Nút handoff | Tạo session phân tích mới |
| 2:50 | Dataset và profile | 60 rows, 5 columns, missing 0 |
| 3:50 | AnalysisIntent | Objective `associate`, đủ cột |
| 4:35 | AnalysisPlan review | Plan approved |
| 5:35 | Generated Python Code | Thấy code hash và nút copy |
| 6:10 | Execution timeline | `queued → running` |
| 6:45 | Validation/kết quả | Validation pass |
| 7:10 | Citation | Numeric claim có locator |
| 7:50 | Result review | Result approved |
| 8:10 | Reproducibility Bundle | Đủ hashes lineage |

## 8. Kế hoạch chống lỗi khi quay

### AI phản hồi chậm

- Chờ tối đa theo timeout đã cấu hình; không bấm nút tạo nhiều lần.
- Có thể cắt đoạn chờ khi dựng video nhưng giữ ít nhất một phần timeline.
- Pre-warm model bằng một session thử trước khi quay.

### AI tạo draft/plan không đúng

- Không duyệt để “cho video chạy tiếp”.
- Dùng reviewer gate để yêu cầu thay đổi hoặc tạo version mới.
- Giữ nguyên câu hỏi và tên cột chính xác như kịch bản để giảm độ biến thiên.

### Code bị policy reject

- Giữ lại correlation ID và quay cảnh guardrail nếu muốn minh họa bảo mật.
- Với flow chính, tạo run mới sau khi code revision hoàn tất; không sửa source
  trực tiếp trong browser.

### Validation thất bại

- Kiểm tra metrics trong `analysis_result.json` có nằm trong plan đã duyệt không.
- Kiểm tra artifact locator và numeric citation.
- Không phê duyệt hoặc diễn giải output đã bị validation chặn.

### Dataset cũ xuất hiện ở session mới

Đây là hành vi project-scoped có chủ đích, không phải lỗi. Dataset thuộc project,
trong khi question/plan/run được khôi phục theo progress của session và dataset đã
chọn. Dùng project sạch khi quay để danh sách dễ nhìn.

## 9. Checklist ngay trước khi bấm Record

- [ ] Docker Desktop đang chạy và tất cả service cần thiết healthy.
- [ ] Không có secret hoặc `.env` trên màn hình.
- [ ] Project demo sạch, tài khoản có quyền truy cập project.
- [ ] AI thật đang bật và model route hoạt động.
- [ ] Hai file CSV đã được lưu đúng UTF-8.
- [ ] Câu hỏi nghiên cứu đã được copy sẵn vào clipboard.
- [ ] Browser zoom 90–100%, notification đã tắt.
- [ ] Đã chạy thử một flow để warm up image/model.
- [ ] Có đủ dung lượng quay ít nhất 12 phút.
- [ ] Biết vị trí dừng nếu plan/code/validation không đạt.

## 10. Câu nhấn mạnh nên xuất hiện trong video

- “AI chỉ nhận profile metadata và research context, không nhận raw rows.”
- “Plan chưa được reviewer duyệt thì không thể tạo run.”
- “Đây là đúng Python source đã gửi vào Docker Sandbox.”
- “Association không đồng nghĩa với causation.”
- “Mọi numeric claim phải có AnalysisCitation.”
- “Bundle niêm phong đầy đủ lineage để kiểm tra khả năng tái lập.”
