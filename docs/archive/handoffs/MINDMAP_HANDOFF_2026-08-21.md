# Bàn giao phiên sau — nhánh `feature/mindmap`

> **Archived handoff:** snapshot ngày 2026-08-21, không phải trạng thái `main`
> hiện tại. Chỉ dùng khi cần khôi phục bối cảnh lịch sử của nhánh mindmap.

Cập nhật: 2026-08-21. Nhánh `feature/mindmap`, đã commit sạch, **chưa push**.

**File này đủ để nối tiếp công việc benchmark.** Nhưng nó KHÔNG mô tả sản phẩm là gì —
phần đó đọc `../../../README.md`, `../../architecture/ARCHITECTURE.md`,
`../../project/spec.md`. Hai skill hỗ trợ tự nạp khi cần:
`debug-stack` (đã commit trong `.claude/skills/`, riêng cho stack này) và `verify-first`
(cấp user, `~/.claude/skills/` — **nằm ngoài repo**, nên máy khác sẽ không có).

---

## 0. ĐỌC TRƯỚC — 3 điều dễ làm hỏng hệ thống

**a) Nhánh này PHẢI dùng database riêng.** `feature/mindmap` và `feature/research-layer`
không chung gốc git → chuỗi alembic xung khắc. Luôn khởi động bằng:

```bash
docker compose -f docker-compose.yml up -d backend worker
```

Thiếu file override → backend trỏ vào DB `litreview` (của research-layer, đang ở `0017`) →
Backend hiện dùng database duy nhất `litreview` và tự chạy migration khi khởi động.

**b) KHÔNG `git checkout` nhánh khác khi backend đang chạy.** Backend có `--reload` +
bind-mount → tự chạy migration của nhánh mới lên DB dùng chung. Muốn xem code nhánh khác
thì dùng `git show <nhánh>:<file>`. Buộc phải checkout thì `docker compose stop backend worker` trước.

**c) `worker` KHÔNG có `--reload`.** Sửa code trong `src/agents/`, `src/services/`,
`src/workers/` xong phải `docker compose ... restart worker`, nếu không job vẫn chạy code cũ,
âm thầm, không báo lỗi.

**d) Image đã được rebuild trong phiên này** (`build backend worker`) để lấy `markitdown[pdf]`
và `python-multipart`. Xem mục 2.3 — image cũ chính là nguyên nhân full-text = 0%.

---

## 1. TRẠNG THÁI — mục 2, 3.1, 3.2, 3.3, 4 của bản bàn giao trước đã XONG

8 commit chưa push trên `feature/mindmap`. Bộ đo tự kiểm: **46/46 đạt**
(`make bench-selftest`, offline ~1 giây). `tests/test_benchmarks.py`: **48 passed**.
`ruff check benchmarks/`: sạch.

| Việc | Trạng thái |
|---|---|
| 2.1 `claim_grounding_rate` báo oan `potential_gap` | ✅ xong — 97.9% → **100%** |
| 2.2 `theme_recall` đọc sai trường | ✅ xong — 43.8% → **62.5%** |
| 2.3a Full-text = 0% | ✅ **tìm ra nguyên nhân & sửa** — image thiếu `markitdown` |
| 2.3b Số nguồn/claim = 1.05 | ✅ điều tra xong — là **kiến trúc**, không phải prompt |
| 3.1 Chi phí/lượt (Langfuse) | ✅ xong — **$0.0272/lượt**, key vốn đã có sẵn |
| 3.2 Tích hợp ResearchQA | ✅ xong — code + chạy thật 5 câu: **12.5%**, xem mục 3 |
| 3.3 Độ phủ chủ đề | ✅ gộp vào 2.2 |
| 4 Cảnh báo `eval.md` | ✅ xong — thêm banner "không dùng để pitch" |
| 3.4 Metric ngữ nghĩa (RAGAS) | ⛔ **bị chặn** — xem mục 5 |

---

## 2. BỘ SỐ CHÍNH THỨC — n=10, đã tính lại sau khi sửa bộ đo

`benchmarks/results/20260820-191252-day-du/` — 5 chủ đề × 2 lần
(6 chủ đề thật hoàn tất, 4 kiểm soát âm từ chối đúng thiết kế).

```bash
python -m benchmarks report benchmarks/results/20260820-191252-day-du
```

| Chỉ số | Trước | **Nay** | Mục tiêu | |
|---|---|---|---|---|
| Trích dẫn bịa | 0.0% (0/215) | **0.0% (0/215)** | ≤0% | 🟢 |
| Kiểm soát âm | 100% (4/4) | **100% (4/4)** | ≥100% | 🟢 |
| Trích dẫn khớp nguyên văn | 100% (116/116) | **100% (116/116)** | ≥95% | 🟢 |
| Tỷ lệ chạy thành công | 100% (6/6) | **100% (6/6)** | ≥95% | 🟢 |
| Claim có bằng chứng | 97.9% 🔴 | **100% (93/93)** | ≥100% | 🟢 |
| Độ phủ chủ đề | 43.8% 🔴 | **62.5% (10/16)** | ≥70% | 🔴 |
| Bài báo được dùng thật | 81.3% | **81.3% (61/75)** | ≥50% | 🟢 |
| **Chi phí/lượt** | chưa đo được | **$0.0272** | — | 🟢 |
| Thời gian/lượt | 176s | **176s** (p50 163 · p95 286) | — | |
| Độ ổn định đầu ra | 84% | **84%** | — | |
| Số nguồn/claim | 1.05 | **1.05** | — | ⚠️ mục 4b |
| Bằng chứng từ full text | 0.0% | **0.0%** (dữ liệu cũ) | — | đã sửa gốc, xem 4a |

**6/8 chỉ số có mục tiêu đều đạt tuyệt đối trên 215 trích dẫn.** Đây là bộ số dùng được
để pitch: mọi tỷ lệ đều truy được về artifact thô.

### Độ phủ chủ đề 62.5% — phần còn lại là thật, không phải lỗi đo nữa

6 chủ đề còn trượt đã soi tận nơi:

| Chủ đề kỳ vọng | Vì sao trượt | Loại |
|---|---|---|
| Generative models (×2) | Từ `generative` **không xuất hiện** ở bất kỳ đâu trong đầu ra | thiếu thật |
| Resource-constrained deployment (×2) | Không từ nào trong 3 từ xuất hiện | thiếu thật |
| MIMIC-III benchmark (×2) | Bài review nói **MIMIC-IV**, không phải MIMIC-III | lệch thật |
| State space models | Trượt ở lần 2, đạt ở lần 1 | dao động giữa 2 lần chạy |

Đây là **điểm yếu độ phủ có thật**. Muốn kéo lên ≥70% thì phải sửa khâu sinh, không
phải sửa bộ đo. **Đừng nới stopword hay hạ ngưỡng khớp để làm đẹp số** — đó chính là
gaming cái bộ đo mà mình vừa mất công sửa cho trung thực.

---

## 3. LỚP RESEARCHQA — đã tích hợp và chạy thật

`benchmarks/external/researchqa.py` + lệnh `python -m benchmarks researchqa`.

🚨 **Điểm này KHÔNG so sánh được với mốc công bố (~75%) của họ.** Bộ gốc chấm bằng
`gpt-4.1-mini`; ở đây chấm bằng provider sẵn có. Đổi giám khảo là đổi thước đo. Con số
chỉ dùng **nội bộ** để so các phiên bản của chính sản phẩm này. Cảnh báo này được in
tự động ở đầu mọi báo cáo và **có phép thử khoá lại**.

**Phải chạy trong container** (cần client LLM của `src/`):

```bash
make bench-researchqa      # 20 câu từ test_mini
# hoặc chấm lại từ artifact đã lưu, không chạy lại pipeline:
docker compose -f docker-compose.yml run --rm --no-deps -T \
  -v $(pwd)/benchmarks:/app/benchmarks worker \
  python -m benchmarks researchqa --judge /app/benchmarks/results/<thư-mục>
```

### Kết quả mẫu 5 câu — `benchmarks/results/20260820-201325-researchqa-5/`

| Chỉ số | Kết quả |
|---|---|
| **Độ phủ rubric** | **12.5% (5/40)** — mẫu con 5/776 câu của `test_mini` |
| Số câu chấm được | 5/5 |
| Tỷ lệ chạy thành công | 60% (3/5) |
| Chi phí/lượt | $0.0147 |
| Trích dẫn bịa | 0.0% (0/19) |

Đọc con số này cho đúng:

- **2/5 câu hệ thống TỪ CHỐI trả lời** ("không có bài báo nào phù hợp"). Không bịa —
  đúng thiết kế — nhưng với một câu hỏi hợp lệ thì đó là **thiếu độ phủ truy xuất thật**,
  và bị chấm 0% chứ không được miễn điểm (xem mục 3, lỗi thứ ba).
- Câu duy nhất làm tốt (`...-s18`, 5/8 rubric) là câu có 7 bài. Câu 4 bài phủ 0/8.
  → **độ phủ rubric bám rất sát số bài truy xuất được.**
- ResearchQA gồm 75 lĩnh vực chuyên sâu (địa kỹ thuật, điện hoá…), khó hơn hẳn 3 chủ đề
  AI trong `topics.json`. 12.5% là số đáng tin về **điểm yếu truy xuất ở lĩnh vực ngoài AI**,
  không phải bản án cho chất lượng tổng hợp.
- Mọi mục rubric trượt đều liệt kê kèm lý do trong `researchqa_report.md`.

### Ba ràng buộc được khoá bằng phép thử

- **Giám khảo hỏng ≠ sản phẩm kém.** Output sai khuôn / thiếu mục / bài trả lời rỗng đều
  thành *chưa chấm được* **kèm lý do**, bị loại khỏi mẫu số chứ không tính là trượt.
- **Giám khảo chỉ đọc văn bản hệ thống sinh ra**, không đọc abstract nguồn — nếu không thì
  khâu truy xuất đang tự chấm điểm cho khâu viết.
- **Rubric đi theo artifact** trong `runs.json` → chấm lại offline được mãi về sau.

### Ba lỗi chỉ lộ ra khi chạy thật — bằng chứng cho nguyên tắc "viết xong phải chạy"

1. `content` của provider là **danh sách content-block**, không phải chuỗi. `str()` lên nó
   ra repr Python với nháy đơn → JSON không parse được → **mọi câu im lặng rơi vào "chưa
   chấm được"**. Không phép thử offline nào thấy được.
2. `except Exception` nuốt mất lý do → "thiếu API key" trông y hệt "review rỗng". Nay trả
   `JudgeOutcome(items, error)` và báo cáo in rõ từng câu hỏng vì sao.
3. **Im lặng được miễn điểm.** Hệ thống từ chối trả lời một câu hợp lệ → bài trả lời rỗng
   → bản đầu chấm "chưa đo được". Nghĩa là một hệ thống không bao giờ trả lời sẽ trông như
   *không đo được* thay vì *phủ 0%*. Nay tách theo pipeline có tới trạng thái cuối không:
   tới nơi rồi mới rỗng = phủ 0% thật; harness hỏng mới là chưa đo được. Riêng lỗi này đổi
   con số từ 20.8% xuống **12.5%** — tức nó đang thổi điểm lên gần gấp đôi.

Cả ba đã có phép thử hồi quy.

---

## 4. HAI PHÁT HIỆN VỀ SẢN PHẨM (không phải lỗi đo)

### 4a. Full-text = 0% — nguyên nhân là IMAGE CŨ, đã sửa

Truy vết: `source_warnings` của mọi lượt đều có
`PDF_FALLBACK:<paper_id>:MarkItDown is not installed`.

- `markitdown[pdf]>=0.1.3` **có** trong `requirements.txt` và `pyproject.toml`
- Nhưng image đang chạy được build **trước** khi dependency đó được thêm
- → mọi PDF tải về đều rơi về abstract → `downloaded=False` → `has_full_text=False`
  → `source_level` luôn là `"abstract"` → 0%

**Đã rebuild và kiểm chứng hai tầng:**

```
downloaded=True | chunks=25          # ingest_papers trên arxiv:1706.03762
source_level: {'full_text': 1}       # qua pipeline thật, lượt ResearchQA sau rebuild
```

Trước rebuild con số này là 0 tuyệt đối trên 116 trích dẫn. **Đây là bằng chứng đường
full-text đã sống lại.**

⚠️ **Lượt n=10 hiện tại vẫn là dữ liệu cũ.** Muốn có con số full-text đại diện thì phải
**chạy lại `make bench`** trên image mới. Đây là việc đáng làm sớm nhất ở phiên sau.

**Trần còn lại của full-text là paywall, không phải code.** Sau rebuild, `PDF_FALLBACK`
không còn báo "MarkItDown is not installed" nữa mà chuyển sang:

```
PDF_FALLBACK:W4210246467:Client error '403 Forbidden' ... sciencedirect.com/.../pdf
```

Elsevier chặn tải trực tiếp. Muốn nâng tỷ lệ full-text thì phải ưu tiên nguồn OA thật
(arXiv, PMC, DOAJ) ở khâu chọn bài — nhánh `research-layer` từng có bộ lọc chỉ nhận bài
tải được PDF, nhánh này **không có**.

Ngoài ra `source_warnings` còn cho thấy **429 RESOURCE_EXHAUSTED** ở khâu embedding trong
4/6 lượt → Qdrant index hụt → claim-evidence retrieval rơi về abstract. Chạy lại nên giãn
nhịp hoặc đổi backend embedding.

### 4b. Số nguồn/claim = 1.05 — là KIẾN TRÚC, không phải prompt

Bản bàn giao trước ngờ prompt `synthesize_claims`. Sai. Nguyên nhân nằm ở
`src/agents/nodes/litreview.py:1079`:

```python
supporting_paper_ids=[paper_id],   # cứng đúng MỘT phần tử
```

`extract_evidence_node` trích claim **theo từng bài một**, và **không có chặng nào gộp các
claim trùng nội dung từ nhiều bài lại**. Chỗ duy nhất gom nhiều nguồn là nhánh dựng theme
dự phòng (`litreview.py:1387`), mà nhánh đó chỉ chạy khi LLM sinh theme thất bại.

Nên 1.05 là **hệ quả tất yếu của thiết kế**: sửa prompt không thay đổi được gì. Muốn có
claim được nhiều nguồn xác nhận chéo thì phải thêm một chặng hợp nhất claim (gom claim
tương đương giữa các bài rồi hợp `supporting_paper_ids`). Đây là việc sản phẩm, không phải
việc bộ đo.

---

## 5. VIỆC CÒN LẠI, THEO ƯU TIÊN

### 5.1. Chạy lại `make bench` trên image mới (rẻ nhất, giá trị cao nhất)

Image nay đã có `markitdown` → lần đầu tiên đo được **Bằng chứng từ full text** thật, và
`Trích dẫn kiểm chứng được` sẽ bắt đầu có quote "không kiểm được offline" (xem 5.3).
Nhớ `python -m benchmarks costs <thư-mục>` sau đó để có luôn chi phí.

### 5.2. Mở rộng ResearchQA lên 20 câu

`make bench-researchqa`. Một câu mất **~4 phút** (đo thật: 5 câu/1.148 giây máy chạy),
nên 20 câu ≈ **1,3 tiếng**, không phải 45 phút như ước tính cũ. Đừng chạy chồng với
`make bench` — cùng đụng OpenAlex/Semantic Scholar và cùng bộ key LLM.

Mẫu 5 câu đã đủ chỉ ra hướng điều tra: **tỷ lệ từ chối 2/5 và độ phủ rubric bám sát số
bài truy xuất được**. Nếu 20 câu vẫn giữ nguyên hình dạng đó thì việc cần làm là khâu
truy xuất cho lĩnh vực ngoài AI, không phải khâu tổng hợp.

### 5.3. Metric ngữ nghĩa (3.4 cũ) — ĐANG BỊ CHẶN, cần sửa pipeline trước

Ý tưởng: quote **diễn giải đúng ý nhưng khác chữ** hiện bị xếp vào "không kiểm được
offline". Một metric ngữ nghĩa sẽ lấp đúng tầng đó.

**Nhưng chưa làm được, vì artifact không lưu văn bản nguồn của quote full-text.**
`papers[].abstract` có, `evidence_rows` chỉ có metadata thư mục
(`paper_id`, `citation_label`, `title`, `url`, `year`) — **không có đoạn văn gốc**. Không
có nguồn để đối chiếu thì mọi phép đo ngữ nghĩa đều là bịa.

**Phải làm trước:** cho pipeline lưu đoạn full-text đã dùng vào ngay cạnh quote
(`EvidenceQuote` trong `src/models/schemas/literature_reviews.py`, và chỗ dựng quote ở
`litreview.py:1066-1074`). Sau đó mới viết metric.

Ghi chú: **không cần kéo RAGAS vào.** Plumbing giám khảo đã có sẵn ở
`benchmarks/external/researchqa.py` (tiêm judge, parse có kiểm, "hỏng thì nói hỏng"), viết
thẳng một metric trong `benchmarks/metrics/` rẻ hơn là thêm một dependency nặng phải cấu
hình provider riêng.

### 5.4. Kéo độ phủ chủ đề lên ≥70%

Xem bảng ở mục 2. Đây là việc khâu sinh, không phải khâu đo.

### 5.5. Thêm chặng hợp nhất claim

Xem 4b. Đây là điểm yếu chất lượng tổng hợp thật.

---

## 6. Bộ benchmark — cách dùng

```bash
make bench-selftest    # 46 phép thử, offline, ~1s — KHÔNG cần API/DB
make bench-quick       # 1 chủ đề thật + 1 kiểm soát âm
make bench             # đầy đủ, --repeat 2
make bench-researchqa  # lớp rubric bên thứ ba (trong container)

python -m benchmarks report <thư-mục>   # tính lại số từ artifact cũ
python -m benchmarks costs  <thư-mục>   # gắn chi phí thật từ Langfuse (chạy trong container)
```

Đọc `benchmarks/README.md` để biết từng con số nói lên điều gì.

**Lưu ý test:** `tests/test_benchmarks.py` không chạy được bằng `pytest tests/` thuần, vì
`tests/conftest.py` import `src.main` → kéo theo migration. Chạy bằng:

```bash
docker compose -f docker-compose.yml run --rm --no-deps -T \
  -v $(pwd)/tests:/bm -v $(pwd)/benchmarks:/app/benchmarks worker \
  python -m pytest /bm/test_benchmarks.py -q --rootdir=/app
```

---

## 7. Bản đồ các bên thứ ba (đã khảo sát — đừng khảo sát lại)

### Nhóm A — Framework đo RAG/chatbot (LLM chấm)

| Tên | Cho gì | Đánh giá |
|---|---|---|
| **RAGAS** | `faithfulness`, `answer_relevancy`, `context_precision/recall` | Bỏ qua — plumbing judge đã tự có, xem 5.3 |
| **DeepEval** | Kiểu pytest, `G-Eval`, tích hợp CI | Hợp vì dự án đã dùng pytest; cân nhắc sau |
| **TruLens** | "RAG triad" | Trùng RAGAS |
| **Giskard** | Sinh test đối kháng | Hợp nếu muốn chủ động tìm cách phá hệ thống |

### Nhóm B — Quan trắc + chi phí

| Tên | Ghi chú |
|---|---|
| **Langfuse** | ✅ **đã tích hợp** — key có sẵn trong `.env`, xem `benchmarks/external/langfuse_usage.py` |
| **LangSmith** | Tự nhiên vì dự án dùng LangGraph, nhưng hosted/trả phí |
| Phoenix/Arize, Opik, Braintrust | Thay thế được Langfuse, không cần xét nữa |

### Nhóm C — Bộ dữ liệu chuẩn

| Tên | Đo gì | Hợp không |
|---|---|---|
| **realliyifei/ResearchQA** | Rubric coverage cho bài trả lời học thuật dài | ✅ **đã tích hợp** |
| **khoj-ai/ResearchQA** | Trích dẫn đúng đoạn khi chat với 1 bài báo | Bỏ — sai hình dạng đầu vào |
| **ALCE** | Citation precision/recall | Đáng học **cách chấm**, viết thẳng vào `trust.py` |
| **CRAG** (Meta) | Benchmark RAG toàn diện | Chưa xét |
| **SciFact** | Kiểm chứng luận điểm khoa học | Hợp với tầng validate_grounding |
| **BEIR / MTEB** | Chấm riêng tầng truy xuất / embedding | Dùng nếu sau này tối ưu retrieval |

### Bốn nguyên tắc khi tích hợp bất kỳ bên nào

1. **Không để LLM-judge thay lõi tất định** — điểm LLM chấm bị dồn cục, không phân biệt
   được hệ thống; metric trích dẫn tất định thì phân biệt rõ (bằng chứng: paper khoj-ai).
2. **Không để sản phẩm tự chấm điểm mình.** PaperPulse mắc lỗi này.
3. **Viết xong phải chạy thật ít nhất 1 lần.** Phiên này là bằng chứng thứ ba: hai lỗi ở
   mục 3 không phép thử offline nào bắt được.
4. **Đổi judge = mất khả năng so sánh.** Phải ghi rõ trong báo cáo.

---

## 8. Ghi chú về `PaperPulse/` (dự án tham khảo)

- **Nên học:** kiểm soát âm (chủ đề vô nghĩa → phải rỗng), kiểm `paper_id` resolve thật ở
  nguồn → **đã đưa cả hai vào `benchmarks/`**
- **Tránh:** `tests/test_research_gap/llm_judge.py` được import nhưng **không tồn tại** →
  toàn bộ tầng LLM-judge của họ là code chết; eval của họ đọc `quality_score` do chính
  production sinh ra; `quality_breakdown` lưu *trước* khi nhân hệ số phạt còn
  `quality_score` lưu *sau* → tính lại từ file sẽ ra số lệch 3.6 lần
