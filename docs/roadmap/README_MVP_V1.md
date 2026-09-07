# LitReview Research Agent — MVP Validation Plan

> Historical V1 validation baseline. Runtime hiện tại đã mở rộng sang
> multi-source, PostgreSQL, durable worker, Qdrant và project-scoped APIs; không
> dùng file này để mô tả kiến trúc đang chạy.

> Trạng thái: **Đã triển khai lõi kỹ thuật; đang ở giai đoạn nghiệm thu MVP V1.**
> Code chạy end-to-end tới HITL không đồng nghĩa MVP đã được kiểm chứng. V1 chỉ
> được đóng khi có deployment thử nghiệm, reviewer thật và dữ liệu KPI theo
> Definition of Done bên dưới.
>
> Loại sản phẩm: **constrained research agent chạy end-to-end theo StateGraph, có tool use, conditional routing và HITL; không phải chatbot hỏi–đáp.**

## 1. Vấn đề thực sự cần giải quyết

Sinh viên/nghiên cứu viên ở giai đoạn chuẩn bị đề cương phải dành nhiều ngày để tìm bài, kiểm tra nguồn và lập bản tổng quan đầu tiên. Công việc lặp lại, dễ bỏ sót tài liệu và các công cụ AI thông thường có thể bịa tác giả, DOI hoặc gắn nguồn không hỗ trợ cho kết luận.

MVP cần kiểm chứng câu hỏi:

> Một trợ lý AI chỉ tổng hợp từ bài báo thật có giúp người dùng tạo bản đồ bằng chứng đầu tiên nhanh hơn ít nhất 50%, trong khi ít nhất 80% khẳng định được reviewer xác nhận là có nguồn hỗ trợ hay không?

MVP không được đánh giá bằng số lượng tính năng hoặc độ đẹp của demo.

## 2. Persona và thời điểm sử dụng

### Persona chính

Sinh viên năm cuối hoặc học viên cao học tại Đại học X đang chuẩn bị đề cương/khóa luận và đã có một chủ đề nghiên cứu bằng tiếng Anh.

### Thời điểm đau nhất

Người dùng mới bắt đầu literature review, chưa biết 10–20 bài nào quan trọng và cần nhanh chóng tạo:

- danh sách tài liệu ban đầu;
- bảng bằng chứng để biết từng bài đã làm gì;
- bản tổng hợp chủ đề có nguồn để tiếp tục đọc sâu.

Giảng viên và reviewer là persona phụ, chỉ tham gia kiểm tra kết quả.

## 3. Giả thuyết giá trị

Nếu agent:

1. tìm 10–20 bài liên quan từ một nguồn học thuật đáng tin cậy;
2. lập bảng bằng chứng từ metadata và abstract;
3. chỉ tạo khẳng định khi có nguồn hỗ trợ;
4. cho reviewer kiểm tra từng khẳng định;

thì người dùng sẽ tạo được bản nháp literature map đầu tiên nhanh hơn ít nhất 50% so với làm thủ công, đồng thời giữ claim-support accuracy từ 80% trở lên.

## 4. MVP này là agent như thế nào?

Agent nhận một goal là chủ đề nghiên cứu, tự điều phối các bước chuyên biệt và dừng ở Human-in-the-loop để Reviewer quyết định. MVP bắt buộc triển khai bằng LangGraph `StateGraph`; một hàm tuần tự gọi API rồi gọi LLM không được xem là đạt contract.

```text
START
  ↓
plan_search_node
  ↓
search_openalex_node ── uses OpenAlex tool
  ↓
assess_sources_node
  ├─ 0 bài sau retry → fail
  ├─ 1–9 bài, còn lượt → refine_query_node ─┐
  └─ đủ bài hoặc hết lượt                  │
                    ↑───────────────────────┘
  ↓
screen_papers_node
  ↓
extract_evidence_node
  ↓
validate_grounding_node
  ├─ claim lỗi, còn lượt → revise_claims_node ─┐
  ├─ không còn claim hợp lệ → fail             │
  └─ claim extraction hợp lệ                   │
                    ↑───────────────────────────┘
  ↓
synthesize_claims_node
  ↓
validate_grounding_node ── kiểm tra thêm theme/gap claims
  ↓
human_review_node ── LangGraph interrupt
  ├─ approve → finalize_node → END
  └─ request_changes → revise_claims_node → validate → HITL/END
```

Agent được xem là đạt yêu cầu khi có đủ:

- `AgentState` dùng chung xuyên suốt graph;
- OpenAlex được đóng gói thành tool và chỉ được gọi từ search node;
- mỗi node có một trách nhiệm, input/output rõ ràng;
- conditional edges quyết định retry, skip gap, reject claim và fail;
- giới hạn tối đa hai lần tìm kiếm và một lần sửa claim để kiểm soát chi phí;
- checkpoint theo `job_id` để graph có thể pause/resume;
- HITL dùng interrupt, không chỉ là một nút “Approve” nằm ngoài workflow;
- lưu decision trace để giải thích agent đã retry/reject vì sao.

Đây là agent có ràng buộc, không phải autonomous agent tự do. Agent không tự chọn thêm nguồn, không tự mở rộng goal và không chat ngoài nhiệm vụ literature review.

Từ `local-deep-research`, MVP chỉ học ba pattern: source adapter tách khỏi agent, progress theo phase/node và citation provenance lấy từ source record. Repo tham khảo không phải runtime dependency và các subsystem lớn của nó không được kéo vào MVP.

## 5. Phạm vi MVP

### 5.1 Input

- Một chủ đề nghiên cứu bằng tiếng Anh.
- Số bài cần khảo sát: mặc định 10, tối đa 20.

MVP chưa tự dịch truy vấn tiếng Việt và chưa xử lý nhiều câu hỏi nghiên cứu trong một lần chạy.

### 5.2 Nguồn dữ liệu

- Chỉ dùng **OpenAlex** làm nguồn chính trong MVP.
- Chỉ giữ bài có tiêu đề, tác giả, năm, URL và abstract.
- DOI/URL được lấy trực tiếp từ metadata của OpenAlex, không cho LLM tự tạo.

Chọn một nguồn giúp team kiểm thử chất lượng retrieval và citation nhanh. arXiv và Semantic Scholar chỉ bổ sung sau khi MVP đã qua kiểm chứng.

### 5.3 AI được dùng cho việc gì?

AI chỉ nhận metadata và abstract đã thu thập để:

- trích xuất phương pháp nếu abstract có đề cập;
- trích xuất dữ liệu/tập mẫu nếu abstract có đề cập;
- tóm tắt đóng góp chính;
- trích nguyên văn hạn chế nếu tác giả nêu rõ;
- tổng hợp các chủ đề lặp lại trong tập bài.

AI không được:

- dùng kiến thức bên ngoài tập nguồn để bổ sung sự kiện;
- tạo DOI, URL, tên bài hoặc tác giả;
- khẳng định một research gap là chưa từng được nghiên cứu trên thế giới;
- điền thông tin không xuất hiện trong metadata/abstract.

### 5.4 Output

MVP tạo ba đầu ra:

#### A. Evidence Table

| Trường | Yêu cầu |
|---|---|
| Bài báo | Tiêu đề, tác giả, năm và URL thật |
| Phương pháp | Trích từ abstract hoặc ghi “Không đủ thông tin” |
| Dữ liệu/tập mẫu | Trích từ abstract hoặc ghi “Không đủ thông tin” |
| Đóng góp chính | Tóm tắt 1–2 câu, gắn `paper_id` |
| Hạn chế | Chỉ hiển thị khi có câu bằng chứng nguyên văn |
| Evidence quote | Câu nguồn để reviewer đối chiếu |

#### B. Thematic Summary

- Tối đa 3–5 chủ đề chính xuất hiện trong tập tài liệu.
- Mỗi khẳng định thực tế phải liên kết tới ít nhất một `paper_id`.
- Không có nguồn hỗ trợ thì không sinh khẳng định.

#### C. Potential Gaps to Investigate

Chỉ đưa ra các điểm cần điều tra thêm, với cách diễn đạt:

> “Trong N bài thu thập từ OpenAlex cho truy vấn X, chưa thấy khía cạnh Y được đề cập.”

Đây là gợi ý để người dùng đọc tiếp, không phải kết luận research gap đã được xác nhận.

### 5.5 Hai vai trò tối thiểu

| Vai trò | Hành động trong MVP |
|---|---|
| Researcher | Nhập chủ đề, chạy review, xem Evidence Table và Thematic Summary |
| Reviewer | Mở cùng báo cáo, đánh dấu claim `supported`/`unsupported`, ghi chú và approve/request changes |

MVP có thể dùng role switch hoặc review link; chưa cần JWT, đăng ký tài khoản hay quản trị người dùng.

### 5.6 Web app

- Có một URL deploy để Researcher và Reviewer truy cập.
- Luồng chính phải hoàn thành trên trình duyệt, không yêu cầu dùng terminal.
- Giao diện chỉ cần phục vụ tốt một luồng: nhập topic → xem report → review.

## 6. Guardrails bắt buộc

1. **Không có nguồn thì không có câu trả lời.**
2. Mỗi bài phải trace được từ output về `paper_id` và URL OpenAlex.
3. Mỗi claim trong phần tổng hợp phải có danh sách `paper_id` hỗ trợ.
4. Limitation chỉ được gắn `explicit` khi evidence quote xuất hiện nguyên văn trong abstract.
5. Trường thiếu dữ liệu phải ghi “Không đủ thông tin”, không suy đoán.
6. Nếu tìm được dưới 10 bài hợp lệ, hệ thống cảnh báo dữ liệu chưa đủ và không đưa ra Potential Gaps.
7. Báo cáo luôn có scope disclaimer và trạng thái chờ reviewer.
8. Reviewer, không phải AI, chịu trách nhiệm phê duyệt nội dung cuối.
9. Mọi loop phải có giới hạn; agent không được retry vô hạn.
10. Mọi lần refine query, reject claim và chuyển route phải được lưu trong decision trace.

## 7. Metric và điều kiện đạt/rớt

### Metric 1 — Reference Validity

**Cách đo:** Kiểm tra toàn bộ citation trong báo cáo có mở được đúng bài, đúng tiêu đề và đúng tác giả hay không.

**Ngưỡng đạt:** `100%` citation trong báo cáo khớp metadata nguồn; `0` DOI/URL do AI bịa.

### Metric 2 — Claim-support Accuracy

**Cách đo:** Reviewer lấy mẫu tối thiểu 30 claim từ các báo cáo và đánh dấu:

- `supported`: nguồn được gắn thực sự hỗ trợ claim;
- `unsupported`: nguồn không hỗ trợ, hỗ trợ không đủ hoặc claim thêm thông tin ngoài nguồn.

```text
Claim-support Accuracy =
supported claims / total reviewed claims
```

**Ngưỡng đạt:** `>= 80%`.

MVP chưa cần RAGAS đầy đủ; bảng đánh giá thủ công của reviewer là metric cơ bản bắt buộc.

### Metric 3 — Time Reduction

**Tác vụ chuẩn:** Tạo bảng 10 bài và một bản tổng hợp 300–500 từ cho một chủ đề.

**Cách đo:** So sánh thời gian người dùng làm tác vụ bằng quy trình hiện tại với thời gian dùng MVP, tính từ lúc nhận topic đến lúc có bản nháp sẵn sàng cho reviewer.

```text
Time Reduction =
(manual time - MVP time) / manual time
```

**Ngưỡng đạt:** Median time reduction của nhóm thử nghiệm `>= 50%`.

### Metric 4 — Reviewer Acceptance

**Cách đo:** Reviewer chọn `approve` hoặc `request changes` sau lần sinh đầu tiên.

**Ngưỡng tham khảo:** Ít nhất `4/5` báo cáo có thể approve sau tối đa một vòng chỉnh sửa.

Metric này là tín hiệu bổ sung, không thay thế Reference Validity và Claim-support Accuracy.

## 8. Kế hoạch thử nghiệm MVP

### Tập thử

- 5–8 người thuộc persona chính.
- 2–3 chủ đề nghiên cứu bằng tiếng Anh.
- Mỗi chủ đề có tối thiểu 10 bài hợp lệ.
- Ít nhất một giảng viên/nghiên cứu viên làm reviewer.

### Quy trình

1. Ghi nhận thời gian baseline bằng quy trình hiện tại.
2. Cho người dùng thực hiện tác vụ tương đương bằng MVP.
3. Ghi thời gian đến khi có bản nháp.
4. Reviewer kiểm tra citation và tối thiểu 30 claim.
5. Tổng hợp lỗi theo nhóm: retrieval sai, extraction sai, synthesis sai hoặc citation sai.
6. Quyết định tiếp tục, thu hẹp hoặc thay đổi MVP dựa trên ngưỡng đạt/rớt.

Để giảm bias học tập, nên dùng hai chủ đề có độ khó tương đương và đổi thứ tự manual/MVP giữa các người tham gia.

## 9. Definition of Done

MVP chỉ được xem là hoàn thành khi:

- [ ] LangGraph StateGraph chạy đủ node, conditional edge và bounded retry đã chốt.
- [ ] OpenAlex được gọi qua tool; agent state và decision trace có thể kiểm tra.
- [ ] Graph pause tại HITL interrupt và resume đúng `job_id`.
- [ ] Web app có URL deploy và chạy được luồng Researcher → Reviewer.
- [ ] Một topic trả về 10–20 bài có metadata và abstract hợp lệ.
- [ ] Evidence Table, Thematic Summary và scope disclaimer được tạo.
- [ ] Reviewer kiểm tra được từng claim và citation.
- [ ] Không phát hiện citation/DOI/URL do AI bịa.
- [ ] Claim-support Accuracy đạt `>= 80%`.
- [ ] Median Time Reduction đạt `>= 50%`.
- [ ] Có kết quả thử nghiệm và danh sách lỗi, không chỉ có ảnh/video demo.

Nếu chưa đo hai KPI chính thì trạng thái là **prototype**, chưa phải MVP đã được kiểm chứng.

## 10. Ngoài phạm vi MVP

- Đọc và phân đoạn full-text PDF.
- Kết hợp arXiv, Semantic Scholar hoặc nhiều search engine.
- Qdrant, embedding và neural reranker.
- Kết luận research gap có độ tin cậy cao trên 50–100 bài.
- Phân tích dữ liệu, sinh code và code interpreter sandbox.
- RAGAS evaluation đầy đủ.
- JWT, đăng ký tài khoản và phân quyền production.
- Dashboard quản lý nhiều dự án.
- Export Word/PDF và citation styles.
- SSE/Socket.IO, distributed queue và tối ưu hạ tầng lớn.
- Chatbot hỏi–đáp tự do, ReAct loop mở và multi-agent.

Các mục này chỉ được đưa vào roadmap sau khi MVP đạt metric hoặc khi kết quả thử nghiệm cho thấy chúng trực tiếp xử lý nguyên nhân MVP chưa đạt.

## 11. Kế hoạch triển khai nhanh cho team

### Tuần 1 — Chứng minh grounded workflow

- Chốt `AgentState`, graph nodes, conditional edges và checkpoint.
- Chốt schema `Paper`, `Claim`, `Evidence` và `ReviewDecision`.
- Tích hợp OpenAlex và tạo dataset cố định cho 2–3 topic thử nghiệm.
- Tạo Evidence Table và guardrail “no source, no claim”.
- Chuẩn bị form chấm Reference Validity và Claim-support Accuracy.

### Tuần 2 — Web, HITL và validation

- Hoàn thiện một luồng web Researcher → Reviewer.
- Deploy môi trường demo.
- Chạy thử với 5–8 người dùng.
- Đo thời gian, citation validity và claim-support accuracy.
- Tổng hợp quyết định: tiếp tục, sửa hoặc thu hẹp.

Không mở rộng sang Qdrant, full text, code sandbox hoặc dashboard trong hai tuần này.

## 12. Quy tắc ra quyết định sau MVP

| Kết quả | Hành động |
|---|---|
| Citation sai hoặc có nguồn bịa | Dừng mở rộng; sửa provenance/guardrail |
| Claim accuracy dưới 80% | Thu hẹp loại claim hoặc bắt buộc evidence quote |
| Time reduction dưới 50% | Đơn giản hóa input/output và quan sát bước gây chậm |
| Gap bị Reviewer bác bỏ nhiều | Xây facet/counterevidence workflow ở V2 |
| Retrieval bỏ sót nhiều bài | Ghi bottleneck; chỉ bật multi-source/reranker khi có gold-set evidence |
| Đạt accuracy/time và V2 gate | Chuyển sang data-analysis workflow V3 |

## 13. Tóm tắt MVP trong một câu

> Với một chủ đề tiếng Anh, LitReview Research Agent tự điều phối việc tìm, sàng lọc, trích bằng chứng, tổng hợp và kiểm tra grounding trên 10–20 bài trước khi pause cho Reviewer, với mục tiêu giảm ít nhất 50% thời gian và đạt ít nhất 80% claim-support accuracy.

Đề bài và ràng buộc gốc: [README_project.md](../product/README_project.md). Technical
contract V1 nằm tại [contracts/contract_v1.md](../../contracts/contract_v1.md), được
điều hướng từ [README_technical_contract.md](../reference/README_technical_contract.md).
Các phiên bản kế tiếp được tách theo giá trị sản phẩm, không theo danh sách công
nghệ: [MVP V2](README_MVP_V2.md) kiểm chứng evidence và research gap,
[MVP V3](README_MVP_V3.md) xây workflow phân tích dữ liệu an toàn, và
[MVP V4](README_MVP_V4.md) production hóa cùng retrieval/evaluation nâng cao.
Chỉ bắt đầu phiên bản sau khi các gate bắt buộc của phiên bản trước đã có bằng
chứng nghiệm thu.
