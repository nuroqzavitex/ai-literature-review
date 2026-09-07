# Benchmark — những con số biết nói

Bộ đo này trả lời đúng bốn câu hỏi mà một người bỏ tiền sẽ hỏi:

1. **Tin được không?** — hệ thống có bịa nguồn không
2. **Đủ không?** — có bỏ sót mảng kiến thức nào không
3. **Rẻ và nhanh không?** — một lượt tốn bao lâu, bao nhiêu tiền
4. **Ổn định không?** — chạy 100 lượt thì hỏng mấy lượt

## Nguyên tắc thiết kế

**Mọi con số đều truy được về artifact thô.** Runner chỉ sinh bằng chứng (JSON
nguyên bản API trả về); report mới tính số. Nên có thể tính lại metric trên dữ
liệu cũ mà không chạy lại pipeline, và một bug trong công thức đo không âm thầm
viết lại lịch sử.

**Không bao giờ bịa số thay cho "chưa đo được".** `0/0` không phải 0%, cũng
không phải 100% — nó là *chưa đo*. Chi phí chưa gắn đo token thì báo là chưa đo,
không ước lượng. Đây là điểm khác biệt lớn nhất so với một bản báo cáo đẹp mà
rỗng.

**Bộ đo tự nó phải được kiểm.** `python -m benchmarks selftest` chạy toàn bộ phép thử
với lỗi cài sẵn có chủ đích, chứng minh từng metric bắt đúng thứ nó hứa — chạy
offline, không cần API hay DB.

## Chuẩn bị

Stack hiện tại dùng một database duy nhất: `litreview`.

```bash
docker compose up -d backend worker
```

## Chạy

```bash
python -m benchmarks selftest                  # kiểm bộ đo (offline, ~1 giây)
python -m benchmarks run                       # chạy thật, cần backend + worker sống
python -m benchmarks run --only pos_03,neg_01  # chạy nhanh vài chủ đề core
python -m benchmarks run --repeat 3            # lặp 3 lần để đo độ ổn định
python -m benchmarks report benchmarks/results/<thư-mục>   # tính lại số, không chạy lại
python -m benchmarks snapshot-corpus benchmarks/results/<thư-mục>  # freeze corpus đã trả về, không tải PDF
python -m benchmarks verify-sources benchmarks/results/<thư-mục>  # tra lại từng paper ở API gốc
python -m benchmarks init-ragas-gold benchmarks/results/<thư-mục>  # seed candidate gold relevance từ baseline
# reviewer sửa paper_ids, viết reference_answer, đặt reviewed=true trong benchmarks/datasets/ragas_gold.json
python -m benchmarks ragas benchmarks/results/<thư-mục>    # đánh giá paper thật / relevance / evidence→review từ artifact
```

Mặc định `run` chỉ chạy topic có `evaluation_scope=core`. Topic mang
`unsupported_domain` (ví dụ biomedical khi chưa có source adapter/corpus phù
hợp) vẫn giữ trong dataset để audit, nhưng chỉ chạy khi gọi rõ `--only pos_02`
và không được tính vào score core.

Lớp ResearchQA (bên thứ ba, chấm bằng LLM) **phải chạy trong container** vì nó
cần client LLM của `src/` và cần DNS mà host không phân giải được:

```bash
docker compose -f docker-compose.yml run --rm --no-deps -T \
  -v $(pwd)/benchmarks:/app/benchmarks worker \
  python -m benchmarks researchqa --limit 20 --base-url http://backend:8000/api/v1
# chấm lại từ artifact đã lưu, không chạy lại pipeline:
#   python -m benchmarks researchqa --judge /app/benchmarks/results/<thư-mục>
```

Kết quả nằm ở `benchmarks/results/<timestamp>/`: `runs.json` (nhật ký),
`*.json` (artifact thô từng lượt), `report.md`, `metrics.json`.

## Từng con số nói lên điều gì

### Nhóm 1 — Tin cậy (đây là hào kinh tế của sản phẩm)

| Chỉ số | Mục tiêu | Nói lên điều gì |
|---|---|---|
| **Trích dẫn bịa** | 0% | Tỷ lệ `paper_id` được trích nhưng không có trong corpus. Khác 0 là sản phẩm bịa nguồn — một lần là nhà nghiên cứu bỏ công cụ vĩnh viễn. |
| **Citation review trỏ tới paper đã lấy** | 100% | Kiểm từng `[[paper_id]]` trong prose của literature review cuối có nằm trong corpus hay không; không chỉ kiểm claim trung gian. |
| **Đoạn review có evidence truy vết được** | ≥95% | Mỗi đoạn factual phải có citation nối được đến một quote evidence của claim hợp lệ. Đây là traceability, không phải tự khẳng định mọi câu đều entail từ quote. |
| **Kiểm soát âm** | 100% | Nhồi chủ đề vô nghĩa (`"quantum blockchain telepathy"`), hệ thống **phải** trả rỗng. Đây là ranh giới giữa công cụ nghiên cứu và máy sinh văn bản: một hệ luôn tìm ra thứ gì đó sẽ đạt điểm cao ở mọi chỉ số khác mà vẫn vô dụng. |
| **Claim có bằng chứng** | 100% | Claim mang nhãn "hợp lệ" mà không kèm trích dẫn nào = khẳng định trần đội lốt đã kiểm chứng. |
| **Trích dẫn kiểm chứng được** | ≥95% | Quote có khớp **nguyên văn** nguồn không. Khác khoảng trắng thì bỏ qua; khác nội dung là diễn giải lại lời tác giả. |
| **Nguồn tra cứu được thật** | — | Gọi lại API gốc (OpenAlex / Semantic Scholar / arXiv — tách theo tiền tố `paper_id`) kiểm từng paper trong corpus có tồn tại thật. Ba chỉ số trên chứng minh nhất quán nội bộ; chỉ số này chứng minh corpus là thật. Chạy hậu kỳ bằng `verify-sources`, giống `costs`: kết quả lưu vào `runs.json` để `report` đọc thuần. |

### Nhóm 2 — Độ phủ (chặn việc "an toàn hoá" để lách nhóm 1)

Một hệ thống có thể đạt 100% mọi chỉ số tin cậy bằng cách trả về đúng một câu
an toàn. Nhóm này chặn điều đó.

| Chỉ số | Mục tiêu | Nói lên điều gì |
|---|---|---|
| **Độ phủ chủ đề** | ≥70% | So với `expected_themes` — nhãn vàng do người am hiểu lĩnh vực khai trong dataset. Dưới ngưỡng = bỏ sót mảng kiến thức bắt buộc. |
| **Bằng chứng từ full text** | — | Tỷ lệ trích dẫn lấy từ toàn văn thay vì abstract. Đây là thứ tách sản phẩm khỏi "search engine gắn thêm bộ tóm tắt". |
| **Bài báo được dùng thật** | ≥50% | Tải 20 bài chỉ trích 3 nghĩa là đang trả tiền LLM cho 17 bài vô ích — hiện thẳng vào chi phí đơn vị. |
| **Số nguồn/claim** | — | Phân biệt "được trích một lần, yếu" với "được nhiều nguồn xác nhận". |

### Nhóm 3 — Kinh tế đơn vị

| Chỉ số | Nói lên điều gì |
|---|---|
| **Thời gian một lượt review** | Đo từ `node_trace` thật, **đã trừ thời gian chờ người duyệt** — nếu không sẽ đang đo tốc độ phản xạ của người vận hành chứ không phải sản phẩm. |
| **Nút thắt cổ chai** | Chặng chậm nhất chiếm bao nhiêu % tổng thời gian. Trả lời: một giờ tối ưu nên đổ vào đâu, và chi phí có khả năng giảm thật không. |
| **Thời gian tới kết quả đầu tiên** | Khác tổng thời gian: đo đúng cảm giác chờ của người dùng trước khi màn hình hết trống. |
| **Chi phí một lượt** | Chỉ báo khi lượt chạy có ghi token thật. Chưa bật đo thì báo "chưa đo được" — một con số chi phí sai sẽ sống rất lâu trong slide gọi vốn. |
| **Thời gian tiết kiệm so với làm tay** | Chỉ tính khi có `manual_baseline_minutes` **đo thật** (bấm giờ một researcher làm cùng chủ đề, cùng số bài). Không bao giờ tự đoán — đây là con số dễ bị hỏi vặn nhất. |

### Nhóm 4 — Độ tin cậy vận hành (số của một lượt chạy đẹp không bán được hàng)

| Chỉ số | Mục tiêu | Nói lên điều gì |
|---|---|---|
| **Tỷ lệ chạy thành công** | ≥95% | Dưới ngưỡng là gánh nặng vận hành: cứ 20 lượt có hơn 1 lượt phải xử lý tay. |
| **Độ trễ p50 / p95** | — | p95 mới là số đặt timeout và định hình khối lượng hỗ trợ. Trung vị che mất những lượt khiến người dùng bỏ cuộc. |
| **Độ ổn định đầu ra** | — | Chạy lặp cùng chủ đề: lần này 12 claim, lần sau 3 claim là không dùng được, **dù từng claim đều có nguồn**. Cần `--repeat ≥2`. |
| **Phân loại lỗi** | — | Một lỗi lặp 15 lần (sửa được) khác hẳn 15 lỗi khác nhau (sản phẩm mong manh). |

## Hai điều bộ đo này cố tình không làm

**Không để sản phẩm tự chấm điểm mình.** Không đọc `quality_score` do chính
pipeline sinh ra. Nếu bộ chấm điểm sai, benchmark phải phát hiện được — nên mọi
metric ở đây tính lại từ dữ liệu thô.

**Không tính "chưa kiểm được" thành đạt hay trượt.** Quote lấy từ full text mà
artifact không lưu toàn văn thì báo là *không kiểm được offline*, không lẳng
lặng cho qua. Nhận đã kiểm thứ mình không đọc được chính là kiểu gian lận mà bộ
đo này sinh ra để chặn.

## Lần chạy thật đầu tiên đã bắt được lỗi của chính bộ đo

Đáng ghi lại, vì nó cho thấy vì sao phép thử offline vẫn chưa đủ.

Chạy kiểm soát âm lần đầu, hệ thống trả về:

> *"Không có bài báo nào phù hợp để tổng hợp cho truy vấn này. Hệ thống sẽ không
> bịa thêm nguồn hoặc cố suy diễn từ tài liệu lạc đề."*

Đây chính xác là hành vi **đúng** — và runner chấm nó là **thất bại**, vì job kết
thúc ở trạng thái `error`. Nói cách khác: bộ đo đang **phạt sản phẩm vì nó trung
thực**. Phép thử offline không bắt được vì fixture giả định chủ đề vô nghĩa sẽ
kết thúc "sạch", không nghĩ tới việc pipeline báo lỗi để từ chối.

Đã sửa ba chỗ:
- Kiểm soát âm chấm theo **output có rỗng không**, không quan tâm pipeline dừng kiểu gì
- Thêm trạng thái `refused` — khác hẳn `failed`
- `Tỷ lệ chạy thành công` chỉ tính chủ đề thật, không gộp kiểm soát âm

Và thêm 2 phép thử hồi quy để lỗi này không quay lại. Bài học: **một phép thử
offline chỉ kiểm được tình huống người viết nghĩ ra được** — phải chạy thật ít
nhất một lần mới biết bộ đo có đúng không.

## Chi phí thật, lấy từ Langfuse

`benchmarks/external/langfuse_usage.py` đọc token và chi phí của từng lượt qua
REST API của Langfuse (`sessionId` = `job_id`), gắn `usage` vào `runs.json` rồi
`report` tự tính `Chi phí một lượt review`:

```bash
docker compose -f docker-compose.yml run --rm --no-deps -T \
  -v $(pwd)/benchmarks:/app/benchmarks worker \
  python -m benchmarks costs /app/benchmarks/results/<thư-mục>
```

Lấy hậu kỳ chứ không đếm trong lúc chạy: pipeline gọi LLM ở hàng chục chỗ qua
LangGraph, cộng tay vừa dễ sót vừa dễ đếm trùng, trong khi Langfuse đã gom sẵn.
Cách này cũng giữ đúng ranh giới runner/report — chạy benchmark không đụng
Langfuse, và chi phí lấy về sau được mà không phải chạy lại lượt nào.

**Chi phí = 0 được báo là "chưa đo được", không phải miễn phí.** Gần như luôn là
Langfuse chưa có bảng giá cho model đó; in `$0.0000` ra báo cáo là một con số
sai trông rất thuyết phục.

## Literature-source evaluation — RAGAS evidence grounding

`python -m benchmarks ragas <thư-mục>` trả lời đúng câu hỏi: **hệ thống có lấy
paper thật, liên quan chủ đề, và dùng evidence từ paper đó để viết literature
review không?** Lệnh chỉ đọc artifact đã lưu, gọi evaluator LLM cấu hình sẵn
của project, rồi ghi `ragas_judgements.json`, `ragas_paper_gold.json` và
`ragas_report.md`. Nó không chạy lại pipeline.

- **Paper thật**: chạy `verify-sources` trước. Nó tra lại ID của từng paper ở
  OpenAlex / Semantic Scholar / arXiv và lưu kết quả vào `runs.json`; RAGAS
  report sẽ hiển thị lại kết quả đó. Nếu chưa chạy, trạng thái là *chưa đo*.
- **Paper liên quan chủ đề**: **Paper relevance precision/recall (gold)** so
  sánh `result.papers` cuối với `paper_ids` do reviewer chọn/sửa. Đây là phép
  so ID tất định, dùng để bắt regression của tập paper cuối.
- **Evidence → review (tất định)**: kiểm citation trong prose review có trỏ
  tới paper đã lấy không, và mỗi đoạn factual có nối tới quote evidence của
  claim hợp lệ không.
- **Faithfulness (RAGAS)** được chấm trên **chỉ literature review cuối** và
  evidence quote gắn với các claim hợp lệ. Nó hỏi phần semantic còn lại: nội
  dung review có được support bởi evidence không? Mục tiêu nội bộ: ≥90%.
- **Context Precision** và **Context Recall** chỉ chạy khi gold đã được reviewer
  duyệt (`reviewed=true`) có `reference_answer` do người viết. Không tự lấy
  output của agent làm ground truth. Mục tiêu nội bộ: ≥80% mỗi chỉ số.
- Run mới lưu `retrieval_traces`: top-K chunk đã xếp hạng, score và provenance
  cho extraction/synthesis/grounding. Khi reviewer tạo gold chunk relevance,
  dữ liệu này sẽ dùng để chấm Precision@K/Recall@K/MRR/NDCG. Trước thời điểm đó,
  Context Precision/Recall vẫn phản ánh chất lượng tập evidence cuối, không tự
  biến ranking của hệ thống thành ground truth.

`init-ragas-gold` chỉ seed một candidate từ lượt baseline hoàn tất đầu tiên của
mỗi topic dương. File tạo ra luôn có `reviewed=false`; reviewer phải bỏ paper
không liên quan, thêm paper bắt buộc nếu biết, viết `reference_answer`, rồi mới
đặt `reviewed=true`. Lệnh từ chối ghi đè file gold đã có để gold ổn định giữa
các lần retrieval live.

Gold active được chọn qua `benchmarks/datasets/gold_manifest.json` (mỗi topic
chỉ một file). Các bản version cũ phải chuyển vào `datasets/archive/`; loader
không tự chọn bằng glob khi manifest tồn tại. Mỗi run RAGAS lưu snapshot
`ragas_paper_gold.json`, vì vậy có thể truy ngược chính xác bản gold đã dùng.

RAGAS là LLM-as-judge và phụ thuộc judge/model đang dùng. Nó chỉ phù hợp theo
dõi regression giữa các phiên bản cùng cấu hình, **không thay thế** các gate
tất định: citation bịa, quote khớp nguồn, nguồn tra cứu được và reviewer.

## Mở rộng

Thêm chỉ số: viết hàm thuần nhận JSON kết quả, trả `MetricResult`
(`benchmarks/metrics/base.py`), thêm vào `compute_metrics()` và **thêm phép thử
tương ứng vào `selftest.py`**. Chỉ số chưa có phép thử thì chưa được tin.

Thêm chủ đề: sửa `benchmarks/datasets/topics.json`. Chủ đề dương cần
`expected_themes`; chủ đề âm cần `"kind": "negative_control"` và `expect_empty`.
