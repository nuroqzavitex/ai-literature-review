# Kịch bản demo toàn bộ dự án LitReview

## 1. Mục tiêu và câu chuyện xuyên suốt

Video dài khoảng **14–18 phút**, trình bày một quy trình nghiên cứu hoàn chỉnh:

> Từ một câu hỏi ban đầu, người dùng tạo project, tìm và duyệt tài liệu khoa học,
> kiểm tra kết luận cùng nguồn, tạo mind map/slide từ báo cáo, phát triển một
> khoảng trống nghiên cứu thành giả thuyết có thể kiểm chứng, rồi dùng Research
> Sandbox để profile dữ liệu, duyệt AnalysisPlan, quan sát mã Python, chạy phân
> tích cô lập và tải gói tái lập.

Chủ đề dùng xuyên suốt:

> **Mối liên hệ giữa thời lượng ngủ và thời gian phản ứng ở sinh viên/người
> trưởng thành trẻ, có xét đến caffeine và thời gian học.**

Thông điệp chính của video:

1. LitReview hỗ trợ toàn bộ vòng đời từ tìm nguồn đến kết luận có bằng chứng.
2. AI không tự quyết định ở các điểm quan trọng; người dùng duyệt truy vấn, bài
   báo, kết luận, AnalysisPlan và kết quả.
3. Khoảng trống từ tổng quan tài liệu không dừng ở một nhận xét: nó có thể được
   chuyển thành giả thuyết và kiểm chứng trong Sandbox.
4. Sandbox không đưa raw rows vào prompt, kiểm tra mã bằng AST, chạy code trong
   môi trường cô lập và niêm phong lineage để tái lập.
5. Kết quả chỉ cho thấy **association**, không được diễn giải thành causation.

## 2. Chuẩn bị trước khi quay

### 2.1. Hạ tầng

Khởi động toàn bộ dự án:

```bash
docker compose up -d --build --force-recreate
```

Kiểm tra tối thiểu:

- Frontend mở được tại `http://localhost:3000`.
- Backend, database, frontend, `sandbox-control` và `sandbox-worker` đang chạy.
- Sandbox hiển thị AI thật đang bật.
- Docker runtime image đã được build trước để cảnh tạo run không phải chờ lâu.
- Tài khoản Clerk có quyền owner/researcher trong project demo.

Không mở `.env`, API key, Docker logs chứa secret hoặc dữ liệu nhạy cảm trong
khung hình.

### 2.2. Dữ liệu và nội dung cần copy sẵn

Dataset chính đã có trong repository:

```text
src/research_sandbox_service/docs/sandbox_demo_sleep_study.csv
```

Dataset kiểm tra guardrail tùy chọn:

```text
src/research_sandbox_service/docs/sandbox_demo_mismatch.csv
```

Dataset chính là dữ liệu synthetic, có 60 dòng và 5 cột:

| Cột | Vai trò |
| --- | --- |
| `participant_id` | Mã bản ghi, không dùng làm predictor |
| `sleep_hours` | Predictor chính |
| `reaction_time_ms` | Outcome, giá trị thấp hơn là tốt hơn |
| `caffeine_mg` | Covariate |
| `study_hours` | Covariate |

Chuẩn bị sẵn các đoạn prompt ở Mục 3 trong clipboard hoặc một file ghi chú
không chứa secret.

### 2.3. Dữ liệu nên tạo trước khi quay

Để video không bị kéo dài bởi thời gian chờ AI và tìm nguồn:

- Chạy thử một Literature Review với đúng prompt demo để làm nóng model.
- Nếu muốn trình bày **Tổng hợp dự án**, chuẩn bị thêm một báo cáo đã hoàn tất trong
  cùng project. Báo cáo thứ hai có thể dùng chủ đề “Ảnh hưởng của caffeine đến
  psychomotor vigilance và reaction time”.
- Khi quay chính, tạo một chat/session mới để timeline rõ ràng.
- Dùng một project sạch hoặc thu gọn các session cũ.

## 3. Nội dung nhập liệu chuẩn

### 3.1. Tên project

```text
Giấc ngủ và hiệu suất nhận thức
```

Mô tả project nếu giao diện yêu cầu:

```text
Tổng hợp bằng chứng và kiểm tra mối liên hệ giữa thời lượng ngủ, caffeine,
thời gian học và thời gian phản ứng.
```

### 3.2. Yêu cầu tìm tài liệu

```text
Tìm và tổng hợp các nghiên cứu từ năm 2018 đến nay về mối liên hệ giữa thời
lượng ngủ và thời gian phản ứng ở sinh viên hoặc người trưởng thành trẻ. Ưu tiên
nghiên cứu định lượng, nêu rõ cách đo reaction time, các yếu tố gây nhiễu như
caffeine và thời gian học, đồng thời chỉ ra khoảng trống có thể kiểm chứng bằng
dữ liệu bảng. Không diễn giải mối liên hệ quan sát được thành quan hệ nhân quả.
```

### 3.3. Các sub-query mong muốn

Khi Agent dừng để duyệt kế hoạch tìm kiếm, giữ hoặc chỉnh thành các truy vấn:

```text
sleep duration reaction time young adults observational study
sleep deprivation psychomotor vigilance reaction time caffeine
sleep duration cognitive performance university students covariates
```

### 3.4. Câu hỏi cho Project Copilot

```text
Trong các nguồn đã được duyệt, những yếu tố gây nhiễu nào cần được kiểm soát khi
phân tích mối liên hệ giữa thời lượng ngủ và thời gian phản ứng? Chỉ trả lời dựa
trên evidence của project và chỉ rõ nguồn hỗ trợ.
```

### 3.5. Câu hỏi/giả thuyết đưa vào Sandbox

Câu hỏi nghiên cứu:

```text
Trong bộ dữ liệu có các cột sleep_hours, reaction_time_ms, caffeine_mg và
study_hours, liệu sleep_hours cao hơn có liên quan với reaction_time_ms thấp hơn
sau khi kiểm soát caffeine_mg và study_hours không?
```

Giả thuyết mong đợi:

```text
Khi giữ caffeine_mg và study_hours không đổi, sleep_hours cao hơn có liên quan
với reaction_time_ms thấp hơn.
```

## 4. Kịch bản quay chi tiết

### Cảnh 1 — Landing, đăng nhập và Research Desk (0:00–0:45)

**Thao tác**

1. Mở trang chủ.
2. Chỉ nhanh vào thông điệp evidence-first và khả năng lưu công việc theo
   project.
3. Đăng nhập hoặc bấm mở Research Desk nếu đã đăng nhập.

**Lời thoại gợi ý**

> LitReview là không gian nghiên cứu evidence-first. Mỗi project giữ riêng câu
> hỏi, nguồn, báo cáo, quyết định reviewer và các thử nghiệm liên quan. Trong
> video này tôi sẽ đi từ tổng quan tài liệu đến một phân tích dữ liệu có thể tái
> lập.

### Cảnh 2 — Tạo project và giới thiệu workspace (0:45–1:30)

**Thao tác**

1. Bấm tạo project mới.
2. Nhập tên `Giấc ngủ và hiệu suất nhận thức`.
3. Mở project vừa tạo.
4. Chỉ vào sidebar chứa project/chat, khu vực Agent, danh sách báo cáo và đường
   dẫn quản lý thành viên.

**Lời thoại gợi ý**

> Project là ranh giới dữ liệu và cộng tác. Chat, báo cáo, evidence và Sandbox
> session đều được kiểm tra theo project ID; người ở project khác không thể đọc
> các artifact này.

**Tùy chọn nếu cần demo cộng tác**

- Mở **Members** trong tab mới.
- Cho thấy vai trò owner/researcher/reviewer và thao tác tạo invitation.
- Không cần gửi invitation thật trong video chính.

### Cảnh 3 — Hỏi kiến thức nhanh để phân biệt hai chế độ (1:30–2:00)

**Thao tác**

1. Chọn chế độ **Hỏi kiến thức**.
2. Nhập:

   ```text
   Vì sao reaction time thường được dùng để đánh giá sự tỉnh táo?
   ```

3. Cho thấy đây là câu trả lời giải thích, không tự chạy Literature Review.

**Lời thoại gợi ý**

> Chế độ hỏi kiến thức dùng cho giải thích nhanh. Khi cần kết luận dựa trên
> nguồn và muốn duyệt truy vấn/corpus trước khi tổng hợp, tôi chuyển sang chế độ
> tìm tài liệu.

Có thể bỏ cảnh này nếu video cần ngắn hơn.

### Cảnh 4 — Khởi tạo Literature Review (2:00–2:50)

**Thao tác**

1. Chọn **Tìm tài liệu** và chế độ **Người dùng duyệt**.
2. Dán yêu cầu ở Mục 3.2.
3. Xác nhận bắt đầu tìm kiếm.
4. Mở phần tiến trình Agent để người xem thấy các node đang chạy.

**Lời thoại gợi ý**

> Tôi chọn user-review để Agent phải dừng ở các điểm quyết định. Agent trước hết
> phân loại yêu cầu và lập kế hoạch; nó chưa được tự chọn truy vấn hay nguồn thay
> người dùng.

### Cảnh 5 — Duyệt kế hoạch tìm kiếm (2:50–3:40)

**Thao tác**

1. Khi flow dừng tại **Chờ duyệt truy vấn**, đọc các sub-query Agent đề xuất.
2. Sửa hoặc thêm ba truy vấn ở Mục 3.3.
3. Bấm **Xác nhận và tìm kiếm**.

**Lời thoại gợi ý**

> Reviewer có thể sửa, thêm hoặc xóa truy vấn trước khi hệ thống truy cập nguồn
> học thuật. Điều này giúp phạm vi tìm kiếm phản ánh đúng population, outcome và
> yếu tố gây nhiễu của câu hỏi nghiên cứu.

### Cảnh 6 — Chọn bài báo và quan sát provenance (3:40–4:50)

**Thao tác**

1. Trong lúc Agent chạy, mở **Tiến trình Agent** và chỉ vào số bài tìm thấy,
   nguồn, tác giả, năm và độ liên quan.
2. Khi flow dừng ở **Chọn bài báo để tổng hợp**, mở 1–2 link nguồn trong tab mới
   để chứng minh đây là nguồn thật.
3. Chọn thủ công các bài sát chủ đề nhất hoặc bấm **Dùng kết quả xếp hạng**.

**Tiêu chí chọn bài**

- Có population gần sinh viên/người trưởng thành trẻ.
- Có phép đo reaction time hoặc psychomotor vigilance.
- Nêu sleep duration/sleep deprivation.
- Ưu tiên nguồn có abstract/evidence đủ để trích xuất.

**Lời thoại gợi ý**

> Agent xếp hạng nhưng không che nguồn gốc. Tôi vẫn xem title, tác giả, năm và
> URL trước khi chọn corpus dùng cho tổng hợp.

### Cảnh 7 — Kiểm tra báo cáo, claim và evidence (4:50–6:20)

**Thao tác**

1. Chờ Agent trích xuất evidence, tổng hợp claim và kiểm tra grounding.
2. Mở report đã tạo và xem từng kết luận.
3. Đối chiếu phần **Bằng chứng từ nguồn** và danh sách references.
4. Chỉ vào evidence verdict/provenance và mở source URL để kiểm tra.
5. Không quay thao tác **Yêu cầu agent chỉnh sửa** hoặc **Duyệt và hoàn tất báo
   cáo** như một final gate: graph hiện tự approve ở bước `human_review`.

**Lời thoại gợi ý**

> Một câu văn nghe hợp lý chưa đủ để trở thành kết luận. Mỗi claim cần được đọc
> cùng evidence và URL nguồn. Bản demo này cho thấy grounding và provenance;
> final reviewer gate vẫn là hạng mục cần hoàn thiện trong runtime.

**Quy tắc khi quay**

- Không trình bày claim “ngủ thêm gây ra phản ứng nhanh hơn” như kết luận hợp lệ nếu nguồn chỉ cho
  thấy association.
- Không tuyên bố số lượng paper/claim cố định trước khi UI hiển thị.

### Cảnh 8 — Đọc báo cáo và hỏi Project Copilot (6:20–7:20)

**Thao tác**

1. Mở báo cáo đã hoàn tất.
2. Chỉ vào short answer, claims, evidence matrix, references và potential gaps.
3. Mở Project Copilot và nhập câu hỏi ở Mục 3.4.
4. Chỉ vào citation/source trong câu trả lời.

**Lời thoại gợi ý**

> Copilot không trả lời từ trí nhớ chung của model; nó đọc phiên bản báo cáo và
> evidence đã lưu trong project. Nhờ vậy câu trả lời follow-up vẫn nằm trong
> phạm vi corpus mà người dùng đã chọn.

### Cảnh 9 — Tạo LaTeX, mind map, slide và xuất báo cáo (7:20–8:30)

**Thao tác**

1. Từ báo cáo đã lưu, mở **Edit LaTeX** và chỉ nhanh vào nội dung nguồn.
2. Mở menu **Xuất**, cho thấy tùy chọn `.tex` và PDF.
3. Bấm **Tạo mind map**, cho thấy root, các nhánh và ý chính; thử xuất PNG/PDF.
4. Đóng mind map và bấm **Tạo slide**; lướt qua 2–3 slide cùng speaker notes.

**Lời thoại gợi ý**

> Các artifact trình bày không được tạo từ một prompt rời rạc. Chúng dùng báo cáo
> LaTeX đã lưu và corpus đã chọn, vì vậy mind map, slide và file xuất vẫn giữ
> cùng nội dung nguồn với Literature Review.

### Cảnh 10 — Tổng hợp cấp project (8:30–9:10, tùy chọn)

Chỉ quay cảnh này nếu project đã có ít nhất hai báo cáo đã hoàn tất.

**Thao tác**

1. Mở **Tổng hợp dự án**.
2. Chỉ vào số báo cáo, tổng số claim, sources, các theme và điểm mâu thuẫn/gap.

**Lời thoại gợi ý**

> Một project có thể tích lũy nhiều review. Trang tổng hợp giúp nhìn xuyên các
> báo cáo đã lưu thay vì trộn tất cả chat thành một câu trả lời duy nhất.

Nếu chỉ có một báo cáo, bỏ cảnh này và không gọi đó là “tổng hợp nhiều nghiên
cứu”.

### Cảnh 11 — Từ research gap sang Hypothesis Sandbox (9:10–10:20)

**Luồng ưu tiên**

1. Tại danh sách potential gaps/candidate đã duyệt, chọn candidate liên quan đến
   việc kiểm soát caffeine và thời gian học.
2. Bấm **Tạo giả thuyết** hoặc **Mở trong Sandbox**.
3. Cho thấy Sandbox mở ở mode Giả thuyết, tạo session project-scoped và giữ
   context nguồn.

**Luồng dự phòng nếu báo cáo không sinh đúng candidate**

1. Bấm **Mở trong Sandbox** trên câu trả lời/báo cáo đã hoàn tất.
2. Hoặc tạo session Giả thuyết mới và dùng câu hỏi ở Mục 3.5.
3. Nói rõ reviewer đang thu hẹp gap thành câu hỏi kiểm chứng được; không giả vờ
   candidate do Agent sinh nếu thực tế không có.

**Lời thoại gợi ý**

> Đây là cầu nối giữa tổng quan tài liệu và nghiên cứu thực nghiệm. Context được
> backend ký và ghim vào session; browser không tự gửi một khối context tùy ý.
> Sandbox chỉ tạo bản thảo, chưa chạy code và chưa sửa dữ liệu lõi.

### Cảnh 12 — Sinh và duyệt giả thuyết/thiết kế (10:20–11:35)

**Thao tác**

1. Tạo Hypothesis Draft.
2. Cuộn qua statement, rationale, falsification criteria, required data và
   limitations.
3. Chỉ vào version/hash để cho thấy draft bất biến.
4. Tick checklist limitations và phê duyệt.
5. Bấm **Tạo thiết kế** để sinh Experiment Draft.

**Điểm cần kiểm tra**

- Predictor là `sleep_hours`.
- Outcome là `reaction_time_ms`.
- Có `caffeine_mg` và `study_hours` trong required data/covariates.
- Tiêu chí bác bỏ đủ cụ thể.
- Không có tuyên bố nhân quả vượt quá thiết kế quan sát.

**Lời thoại gợi ý**

> Một giả thuyết tốt phải có khả năng bị bác bỏ, nêu dữ liệu cần có và thừa nhận
> giới hạn. Các version cũ không bị ghi đè để reviewer có thể kiểm tra lịch sử.

### Cảnh 13 — Handoff sang Data Analysis và guardrail dataset (11:35–12:35)

**Thao tác**

1. Bấm **Chuyển sang Phân tích dữ liệu**.
2. Cho thấy một session phân tích mới được tạo và mục tiêu được điền từ giả
   thuyết.
3. Tùy chọn: upload `sandbox_demo_mismatch.csv` để hiển thị
   `MISMATCH_DATASET` và nút tiếp tục bị khóa.
4. Upload `sandbox_demo_sleep_study.csv`.

**Lời thoại gợi ý**

> Handoff giữ lineage nhưng không dùng chung state giữa hai mode. Trước khi phân
> tích, hệ thống so cột của dataset với các biến cần kiểm chứng. Một file hoàn
> toàn không liên quan sẽ bị chặn thay vì cố chạy.

### Cảnh 14 — Deterministic Profile và AnalysisIntent (12:35–13:35)

**Thao tác**

1. Bấm **Chạy deterministic profile**.
2. Chỉ vào `60 rows`, `5 columns`, dtype và missing values bằng 0.
3. Điền form:

| Trường | Giá trị |
| --- | --- |
| Objective | `associate` |
| Research question | Câu hỏi ở Mục 3.5 |
| Outcome columns | `reaction_time_ms` |
| Predictor columns | `sleep_hours` |
| Group columns | để trống |
| Covariate columns | `caffeine_mg, study_hours` |
| Preferred metrics | `pearson_correlation, ols_beta, confidence_interval_95, p_value, r_squared` |

4. Bấm **Kiểm tra độ đầy đủ**.

**Lời thoại gợi ý**

> Profile chạy deterministic bằng code, không dùng LLM và không gửi raw rows ra
> ngoài. Nếu outcome, predictor hoặc thiết kế còn thiếu, hệ thống dừng ở
> question_incomplete thay vì để AI tự đoán.

### Cảnh 15 — Sinh và duyệt AnalysisPlan (13:35–14:25)

**Thao tác**

1. Bấm tạo plan từ metadata.
2. Kiểm tra objective, preprocessing, assumptions, method và metrics.
3. Xác nhận `participant_id` không được dùng làm predictor.
4. Phê duyệt AnalysisPlan.

**Lời thoại gợi ý**

> AI chỉ nhận profile metadata và research context. AnalysisPlan có version và
> hash bất biến; plan chưa được reviewer phê duyệt thì không thể tạo run.

### Cảnh 16 — Mã Python và execution cô lập (14:25–15:35)

**Thao tác**

1. Bấm **Tạo run**.
2. Trong khối **Mã nguồn thực thi**, cuộn qua script và bấm thử
   **Sao chép code**.
3. Chỉ vào code hash/prompt version.
4. Theo dõi timeline `queued → running → completed_unvalidated`.

**Điểm nên chỉ trên code**

- Truy cập cột bằng `df["sleep_hours"]` và `df["reaction_time_ms"]`.
- Ghi `analysis_result.json`, bảng CSV và biểu đồ PNG vào output allowlist.
- Không có `os`, `subprocess`, network client, `eval` hoặc `exec`.

**Lời thoại gợi ý**

> Đây là đúng source code gắn với run, không phải đoạn minh họa. AST checker chạy
> trước; sau đó worker thực thi code bằng runtime non-root, network-none, có giới
> hạn CPU, RAM, PID, timeout và luôn cleanup workspace.

Nếu demo trên VPS không dùng Docker, thay câu cuối bằng:

> Worker chạy code trong native virtualenv bị cô lập bằng Bubblewrap, vẫn giữ
> network namespace, resource limits, AST check và cùng pipeline validation.

### Cảnh 17 — Validation, output, citation và biểu đồ (15:35–16:45)

**Thao tác**

1. Chờ trạng thái validation pass.
2. Mở bảng summary, biểu đồ và interpretation.
3. Chỉ vào AnalysisCitation/locator của numeric claim.
4. Đối chiếu xu hướng hệ số/correlation âm.

Mốc kỳ vọng của dataset synthetic:

- Pearson correlation xấp xỉ `-0.914`.
- Hệ số OLS của `sleep_hours` xấp xỉ `-22.08 ms/giờ`.
- Khoảng tin cậy 95% xấp xỉ `[-23.89, -20.26]`.
- `R²` xấp xỉ `0.919`.

**Lời thoại gợi ý**

> AI chỉ được diễn giải sau khi schema và scientific validation đã pass. Kết quả
> cho thấy association âm: thời lượng ngủ cao hơn đi cùng reaction time thấp
> hơn trong dữ liệu synthetic này. Đây không phải bằng chứng nhân quả. Mỗi numeric
> claim phải truy về dataset hash, run ID, locator và value hash.

Không đọc một con số nếu UI không hiển thị artifact/citation tương ứng.

### Cảnh 18 — Result Review và Reproducibility Bundle (16:45–17:30)

**Thao tác**

1. Phê duyệt kết quả sau khi validation pass.
2. Tải Reproducibility Bundle.
3. Chỉ vào dataset hash, profile hash, plan hash, code hash, runtime digest,
   random seed, result hash và artifact hashes.

**Lời thoại gợi ý**

> Reviewer gate của Sandbox niêm phong toàn bộ lineage. Người kiểm tra có thể truy ngược
> kết luận về đúng dataset, profile, plan, code, runtime và artifact đã tạo ra
> nó.

### Cảnh 19 — Kết thúc (17:30–18:00)

**Lời thoại gợi ý**

> LitReview nối ba lớp công việc thành một quy trình: tìm và kiểm chứng evidence,
> phát triển research gap thành giả thuyết, rồi phân tích dữ liệu trong Sandbox
> có kiểm soát. AI giúp tăng tốc từng bước, còn phạm vi, nguồn, plan và kết quả
> cuối cùng vẫn do con người duyệt.

## 5. Shot list bắt buộc

| Thời gian | Khung hình | Dấu hiệu cảnh đạt |
| --- | --- | --- |
| 0:00 | Landing/Research Desk | Thấy thông điệp evidence-first |
| 0:45 | Project mới | Đúng tên chủ đề giấc ngủ |
| 2:00 | Prompt tìm tài liệu | Population, outcome, covariates rõ ràng |
| 2:50 | Duyệt sub-query | Reviewer có thể sửa truy vấn |
| 3:40 | Chọn papers | Có title, tác giả/năm, URL nguồn |
| 4:50 | Kiểm tra claims | Claim đi cùng evidence và reference; không gọi đây là final reviewer gate |
| 6:20 | Report/Copilot | Câu trả lời follow-up có nguồn |
| 7:20 | Mind map/slide | Artifact tạo từ báo cáo đã lưu |
| 9:10 | Mở Sandbox | Context/candidate đi vào Hypothesis |
| 10:20 | Hypothesis Draft | Falsification, limitations, version/hash |
| 11:35 | Handoff | Session Data Analysis mới |
| 12:35 | Profile | 60 dòng, 5 cột, missing 0 |
| 13:35 | Plan review | AnalysisPlan được duyệt |
| 14:25 | Generated code | Thấy toàn bộ code và code hash |
| 15:00 | Timeline | `queued → running` |
| 15:35 | Output | Validation pass, bảng và biểu đồ |
| 16:10 | Citation | Numeric claim có locator |
| 16:45 | Bundle | Đủ hash lineage |

## 6. Kế hoạch chống lỗi khi quay

### Không tìm thấy bài báo phù hợp

- Không chọn paper chỉ vì title có từ “sleep”.
- Sửa sub-query theo Mục 3.3 và chạy lại.
- Có thể dùng một report đã duyệt từ lần warm-up, nhưng phải nói rõ đây là báo
  cáo đã lưu trong project.

### Agent không tạo đúng research gap

- Dùng **Mở trong Sandbox** từ báo cáo/câu trả lời đã duyệt.
- Tạo session Hypothesis mới và nhập câu hỏi chuẩn ở Mục 3.5.
- Không khẳng định candidate do Agent sinh nếu UI không có candidate đó.

### AI phản hồi chậm

- Không bấm nút tạo nhiều lần vì request đã có idempotency.
- Có thể cắt đoạn chờ khi dựng nhưng giữ lại một phần Agent trace và Sandbox
  timeline.

### Claim hoặc hypothesis dùng ngôn ngữ nhân quả

- Đánh dấu chưa được hỗ trợ/yêu cầu sửa.
- Chỉ tiếp tục khi nội dung dùng “liên quan”, “association” hoặc cách diễn đạt
  tương đương.

### Generated code bị policy reject

- Giữ correlation ID để minh họa guardrail nếu cần.
- Với flow chính, tạo run mới sau code revision; không chỉnh code trực tiếp trong
  browser rồi tuyên bố đó là code do hệ thống tạo.

### Validation thất bại

- Kiểm tra metrics trong output có khớp plan đã duyệt không.
- Kiểm tra effect size/confidence interval khi có `p_value`.
- Kiểm tra artifact locator và numeric citation.
- Không phê duyệt output bị validation chặn.

### Không có biểu đồ

- Xác nhận code đã gọi `emit_chart` hoặc ghi PNG vào thư mục `charts/`.
- Tạo run mới từ plan/code version đã sửa; artifact của run cũ vẫn được giữ để
  audit.

## 7. Phiên bản demo rút gọn 8–10 phút

Nếu thời lượng bị giới hạn, giữ các cảnh sau:

1. Mở project đã chuẩn bị sẵn.
2. Duyệt sub-query và chọn paper.
3. Đối chiếu claim cùng evidence.
4. Cho thấy nhanh report, mind map và slide.
5. Mở candidate/report trong Hypothesis Sandbox.
6. Duyệt Hypothesis Draft và handoff.
7. Chọn dataset đã upload, mở deterministic profile.
8. Duyệt AnalysisPlan.
9. Cho thấy generated Python code và execution timeline.
10. Xem validation, chart, citation và tải bundle.

Không bỏ ba cảnh: **claim–evidence**, **generated Python code**, và
**Reproducibility Bundle**. Đây là ba điểm phân biệt sản phẩm với một chatbot
tổng hợp thông thường.

## 8. Checklist ngay trước khi bấm Record

- [ ] Tất cả service cần thiết đã running/healthy.
- [ ] Không có secret hoặc `.env` trên màn hình.
- [ ] Tài khoản có quyền với project demo.
- [ ] Language đang là tiếng Việt ở frontend và Sandbox.
- [ ] AI thật, Literature Review và Sandbox capability đều khả dụng.
- [ ] Project sạch hoặc session cũ đã được thu gọn.
- [ ] Dataset demo đúng file, UTF-8 và chưa bị chỉnh sửa.
- [ ] Prompt, sub-query và AnalysisIntent đã được copy sẵn.
- [ ] Đã warm-up model và runtime image.
- [ ] Browser zoom 90–100%, tắt notification và đóng DevTools.
- [ ] Biết điểm dừng nếu claim, hypothesis, plan, code hoặc validation không đạt.

## 9. Các câu nhấn mạnh nên xuất hiện

- “Agent xếp hạng nguồn; người dùng quyết định corpus.”
- “Không có nguồn thì không có kết luận.”
- “Khoảng trống đã duyệt được chuyển thành giả thuyết có thể bác bỏ.”
- “AI chỉ nhận profile metadata và research context, không nhận raw rows.”
- “Plan chưa được reviewer duyệt thì không thể tạo run.”
- “Đây là đúng Python source đã được gửi vào runtime Sandbox.”
- “Association không đồng nghĩa với causation.”
- “Mọi numeric claim phải có AnalysisCitation.”
- “Bundle niêm phong lineage từ nguồn và giả thuyết đến dữ liệu, code và kết quả.”

## 10. Tài liệu liên quan

- Kịch bản chi tiết riêng cho Sandbox:
  `src/research_sandbox_service/docs/video-demo-script.md`.
- Hướng dẫn test Sandbox cho team:
  `src/research_sandbox_service/docs/team-testing-guide.md`.
- Dataset chính:
  `src/research_sandbox_service/docs/sandbox_demo_sleep_study.csv`.
- Dataset mismatch:
  `src/research_sandbox_service/docs/sandbox_demo_mismatch.csv`.
