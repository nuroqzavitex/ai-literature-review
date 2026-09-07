# Vận hành benchmark literature review

Tài liệu này là runbook để chạy benchmark **từng topic**, giữ checkpoint, và
đọc kết quả mà không biến proxy thành số liệu quảng cáo. Toàn bộ lệnh bên dưới
chỉ dùng `benchmarks/`; workflow sản phẩm nằm ở `src/` không bị sửa. Tài liệu
này được chia thành hai phần trách nhiệm rõ rệt giữa hệ thống thực thi và coding
agent độc lập.

## Phân chia trách nhiệm

Benchmark chia thành hai phần tách biệt, không được trộn lẫn:

### Phần 1 — Hệ thống phụ trách

- Chạy benchmark từng topic theo runbook này.
- Tính các metric: Precision@K, MRR, NDCG@K, Recall@K (khi có gold), Context
  Precision, Context Recall, Faithfulness (RAGAS LLM-as-judge).
- Tổng hợp và xuất kết quả đánh giá (`report.md`, `metrics.json`).

### Phần 2 — Coding agent phụ trách (độc lập với hệ thống đang bị chấm)

Coding agent tạo **gold độc lập** để hệ thống được chấm có chuẩn đối chiếu
thực sự. Cụ thể:

- Gán nhãn `relevant / partially_relevant / irrelevant` cho các chunk — nhãn
  **không** được lấy từ chính pipeline đang bị benchmark.
- Xác định các chunk liên quan mà hệ thống có thể bỏ sót, để Recall@K có thể
  được tính thực tế (không phải `chưa đo được`).
- Viết `reference_answer` cho từng topic làm chuẩn đối chiếu cho Context
  Precision/Recall và RAGAS.
- Agent tự tìm paper từ arXiv/Semantic Scholar, không đọc `results/` hay output
  của `src/` trước khi tạo gold.

> **Điểm quan trọng:** Vấn đề hiện tại không chỉ thiếu Human-in-the-loop mà
> thiếu **gold độc lập**. Nếu coding agent tự sinh gold bằng LLM hoặc rule thì
> phải gọi đúng là **auto-label proxy** — có thể dùng để benchmark nội bộ nhưng
> chưa phải RAGAS chuẩn độc lập. Human review vẫn là cách đáng tin cậy nhất.

Nhãn bắt buộc phải ghi đúng:

| Cách tạo gold | Nhãn bắt buộc |
|---|---|
| Lấy từ output hệ thống + lexical rule | `auto-label proxy` |
| Coding agent tự tìm/chọn từ nguồn ngoài | `AI-curated independent gold` |
| Chuyên gia/human duyệt lại | `human/expert-validated gold` |

## Mục tiêu và giới hạn

Benchmark trả lời ba câu hỏi tách biệt:

1. Workflow có lấy paper, evidence và viết review chạy được không?
2. Review cuối có citation/evidence truy vết được và được evidence support không?
3. Retriever có đưa chunk liên quan lên đầu không?

Không gộp ba câu hỏi thành một "điểm RAGAS". Một số đo chưa có gold độc lập
phải ghi **chưa đo được**, không thay bằng 0% hoặc 100%.

## Trước mỗi lượt chạy

1. Kiểm tra code benchmark trước:

   ```bash
   python -m benchmarks selftest
   ```

   Chỉ tiếp tục khi toàn bộ selftest pass.

2. Khóa cấu hình phải được so sánh công bằng:

   - Provider/model LLM của worker.
   - `BAAI/bge-small-en-v1.5` (embedding model hiện dùng).
   - Dataset `benchmarks/datasets/topics.json`.
   - Git commit/dirty flag: runner tự lưu vào `run_env.json`.

3. Chọn **một topic**. Không đổi prompt/dataset chỉ để tăng điểm sau khi đã
   thấy kết quả. Ví dụ dùng `pos_03` trước (thuộc core scope).

## Chạy một topic từ đầu

Khởi động backend và một worker. Provider của worker quyết định model tạo
review; runner chỉ gọi API, không tự gọi LLM.

```bash
docker compose up -d backend

# Ví dụ smoke với Gemini; không sửa .env mặc định.
docker compose run -d --no-deps -e LLM_PROVIDER=google worker
```

Xác nhận container đang sống rồi chạy runner trong container cùng network với
backend:

```bash
docker compose ps
docker compose run --rm --no-deps -T worker \
  python -m benchmarks run \
  --base-url http://backend:8000/api/v1 \
  --only pos_03 \
  --timeout 3600 \
  --label gemini_pos01
```

Không chạy lại một topic chỉ vì terminal mất kết nối. Tìm checkpoint trước:

```bash
ls -dt benchmarks/results/* | head
```

Mỗi thư mục run là bất biến để audit, gồm:

- `runs.json`: index và trạng thái từng attempt;
- `<topic>_attempt<N>.json`: API artifact thô;
- `run_env.json`: commit, dirty flag, health snapshot;
- `report.md` và `metrics.json`: metric tổng hợp.

Khi hoàn tất smoke bằng worker tạm, xem chính xác tên container rồi dừng đúng
container đó để nó không nhận job khác:

```bash
docker ps --format '{{.Names}} {{.Status}}'
docker stop <temporary-worker-container-name>
```

Không dừng `backend`, database hoặc Qdrant khi chỉ muốn kết thúc worker tạm.

## Kiểm artifact trước khi tin kết quả

```bash
python -m benchmarks report benchmarks/results/<run-dir>
python -m benchmarks verify-sources benchmarks/results/<run-dir>
```

Đọc tối thiểu các phần sau của `report.md`:

- positive completion và negative-control refusal;
- citation bịa, quote có evidence, citation trong prose review;
- theme recall và số paper thực sự dùng;
- latency, bottleneck, chi phí (nếu token usage đã có).

`verify-sources` là bước riêng: nó tra lại paper ID tại nguồn học thuật. Nếu
chưa chạy hoặc provider lỗi, “Nguồn tra cứu được thật” phải là **chưa đo**.

## RAGAS evidence grounding

Lệnh này đọc artifact đã lưu và gọi evaluator LLM; nó **không chạy lại
workflow**:

```bash
docker compose run --rm --no-deps -T -e LLM_PROVIDER=google worker \
  python -m benchmarks ragas benchmarks/results/<run-dir> --only pos_01
```

Nó tách bốn tầng thay vì trộn điểm:

1. Paper có tồn tại thật (`verify-sources`).
2. Paper có liên quan (`ragas_gold.json` nếu đã freeze).
3. Citation/evidence từ paper có đi vào prose review (deterministic).
4. Faithfulness: evidence quote có support review cuối không (LLM-as-judge).

Faithfulness chỉ dùng để so sánh phiên bản với **cùng evaluator/model**. Nó
không chứng minh retrieval recall.

## Đo retrieval từ trace

Run mới lưu `retrieval_traces`: query, ranked top-K chunks, rank, score,
paper ID và provenance. Tạo candidate từ một run đã hoàn tất:

```bash
python -m benchmarks init-ragas-chunk-gold benchmarks/results/<run-dir>
```

Để có số regression nội bộ ngay, có thể tự gán nhãn bằng quy tắc lexical minh
bạch rồi tính proxy metric:

```bash
python -m benchmarks auto-label-ragas-chunk-gold \
  benchmarks/datasets/ragas_chunk_gold.json
python -m benchmarks score-ragas-retrieval \
  benchmarks/datasets/ragas_chunk_gold.json \
  --output benchmarks/results/<run-dir>/retrieval_proxy_metrics.json
```

Output có `Precision@1/3/5`, `MRR`, `NDCG@5` và cố ý để `Recall@5` là **chưa
đo được**: trace chỉ giữ chunk đã trả về, không biết các chunk liên quan bị bỏ
sót ngoài top-K.

`ragas_chunk_gold.json` có scope `chunk_level_relevance_auto_labeled` là
**proxy**, không được gọi là human/expert gold hay RAGAS chuẩn độc lập.

## Xây gold độc lập

Muốn chấm retrieval nghiêm túc, không lấy paper/chunk do hệ thống trả về làm
gold. Với từng topic:

1. Khóa topic và expected themes trước khi xem output.
2. Tìm một corpus độc lập (PMC, arXiv, DOI/publisher) và lưu URL/ID/version.
3. Chọn paper liên quan, trích evidence chunk, ghi nhãn relevance và reference
   answer.
4. Freeze gold rồi mới chạy/so sánh các phiên bản workflow.

Gold do AI curating phải ghi `AI-curated independent gold`; gold do chuyên gia
duyệt mới ghi `human/expert-validated`. Cả hai đều độc lập với output hệ thống,
nhưng độ tin cậy công bố khác nhau.

### Coding agent đóng vai curator độc lập

Khi không có human reviewer, **coding agent** (không phải hệ thống đang bị chấm)
có thể tự thực hiện toàn bộ bước curation. Điều kiện bắt buộc:

- Agent **không được đọc** bất kỳ file nào trong `benchmarks/results/` trước khi
  tạo gold (để không bị hệ thống ảnh hưởng lên lựa chọn paper/chunk).
- Agent **không được dùng** output của pipeline `src/` làm nguồn gold.
- Agent tự search arXiv API / Semantic Scholar API với query độc lập từ
  `topics.json`, tự đọc abstract/full-text, tự chọn paper liên quan, tự trích
  chunk cố định, tự gán nhãn `relevant / partially_relevant / irrelevant`.
- Paper chọn phải có DOI hoặc arXiv ID lưu được để audit sau.
- Output lưu tại `benchmarks/datasets/independent_gold_<topic_id>.json` với
  `"scope": "chunk_level_relevance_ai_curated_independent"` và
  `"independent": true`.

Quy trình cụ thể cho agent:

1. Đọc `topics.json`, lấy `topic`, `expected_themes` của topic cần làm.
2. Search arXiv (`http://export.arxiv.org/api/query`) và/hoặc Semantic Scholar
   (`https://api.semanticscholar.org/graph/v1/paper/search`) với query từ topic.
   **Không chạy pipeline, không đọc `results/`.**
3. Với mỗi paper tìm được: đọc abstract, đánh giá mức độ liên quan theo
   `expected_themes`. Giữ paper có relevance rõ ràng (loại ambiguous nếu không
   đủ evidence trong abstract).
4. Với paper đã chọn: trích 3–5 chunk đại diện (abstract, intro, conclusion,
   methodology). Gán label và lý do ngắn gọn.
5. Ghi `reference_answer`: một đoạn tóm tắt ngắn những gì một review tốt phải
   đề cập cho topic này, dựa trên các paper đã chọn.
6. Freeze file, không sửa lại sau khi hệ thống đã được chạy.

Nhãn đúng khi báo cáo: **`AI-curated independent gold`**, không phải
`human/expert-validated` và không phải `proxy auto-label`.

## Vận hành tuần tự 12 topic

Lặp đúng vòng sau cho `pos_03` rồi mới sang `pos_04`:

1. `selftest`.
2. Chạy một topic với label mới.
3. `report` + `verify-sources`.
4. Kiểm review/citation/evidence và retrieval trace.
5. Seed/freeze gold phù hợp, chạy RAGAS/proxy metrics.
6. Lưu đường dẫn artifact và quyết định pass/fail trong log vận hành.

Chỉ dùng `--repeat >=2` sau khi một lượt đơn đã sạch; repeat dùng đo độ ổn
định, không dùng để chọn lượt có điểm đẹp nhất.

## Khi nào được đưa số vào slide

- Có link đến artifact và `run_env.json`.
- Nêu rõ provider/model, embedding model, dataset và số topic.
- Ghi rõ metric là deterministic, RAGAS LLM-as-judge, auto-label proxy hay
  independent gold.
- Không ghi Recall@K nếu gold không chứa chunk relevant bị bỏ sót.
- Không ghi chi phí nếu chưa có token usage thật.

Một câu mô tả an toàn cho trạng thái hiện tại là: **“Trace-based,
RAGAS-inspired literature-review evaluation; retrieval proxy đo trên các
topic đã chạy.”** Chỉ gọi là **full RAGAS / retrieval benchmark chuẩn** khi
gold độc lập đã được freeze cho phạm vi topic đang báo cáo.
