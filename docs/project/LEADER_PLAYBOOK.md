# 📋 Leader Playbook — LitReview Agent MVP

> Historical onboarding plan. Các bước SQLite và kế hoạch theo ngày bên dưới
> ghi lại giai đoạn MVP ban đầu, không phải hướng dẫn runtime hiện tại. Setup
> hiện hành xem [GitHub Repo Setup](../product/GitHub_Repo_Setup.md) và
> [Architecture](../architecture/ARCHITECTURE.md).

> **Tài liệu hướng dẫn điều hành nhóm dành cho Tech Lead.**
> Dự án: LitReview Research Agent | Team: 4 người | Timeline: 2 tuần MVP

---

## 1. VAI TRÒ CỦA LEADER TRONG DỰ ÁN NÀY

Leader trong dự án này đảm nhận **3 vai trò đồng thời**:

| Vai trò | Mô tả | Thời gian ước tính |
|:--|:--|:--|
| **Tech Lead** | Thiết kế kiến trúc, chốt data contract, review code | ~30% thời gian |
| **Core Developer** | Viết LangGraph Agent (graph.py, state.py, prompts) | ~50% thời gian |
| **Project Manager** | Điều phối tiến độ, unblock team, báo cáo | ~20% thời gian |

**Nguyên tắc vàng:** Khi có xung đột giữa 3 vai trò, ưu tiên theo thứ tự:
1. **Unblock team** (nếu ai đó đang bị chặn → giải quyết ngay)
2. **Review code** (nếu có PR đang chờ → review trước khi code tiếp)
3. **Code của mình** (chỉ khi không ai cần hỗ trợ)

---

## 2. TRƯỚC KHI BẮT ĐẦU — CHECKLIST CHUẨN BỊ

### 2.1 Setup Git Repository

```
Branching strategy cho team 4 người:

main ─────────────────────────────── production
  │
  └── develop ────────────────────── integration branch
        │
        ├── feat/agent-graph ─────── Leader: LangGraph core
        ├── feat/openalex-tool ───── Member 2: OpenAlex API
        ├── feat/validation ──────── Member 3: Grounding validation
        └── feat/web-ui ──────────── Member 4: FastAPI + Next.js
```

**Quy tắc Git cho team:**
- Mỗi người làm việc trên nhánh riêng (feature branch).
- Muốn merge vào `develop` → tạo Pull Request → Leader review → merge.
- Cuối mỗi milestone → Leader merge `develop` vào `main`.
- **KHÔNG** push thẳng vào `main` hoặc `develop`.
- Commit message tiếng Việt hoặc tiếng Anh đều được, nhưng phải mô tả rõ thay đổi.

### 2.2 Setup môi trường phát triển

Đảm bảo cả team cài đặt giống nhau:

```bash
# Python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install

# Database
# SQLite tự tạo khi chạy, không cần setup riêng
```

### 2.3 Tạo file mock data

Trước khi Member 2 hoàn thành OpenAlex tool, Leader nên tạo sẵn **file mock data** để cả team có dữ liệu mẫu mà code:

```python
# src/tests/fixtures/mock_papers.py
MOCK_PAPERS = [
    {
        "paper_id": "W2741809807",
        "title": "Attention Is All You Need",
        "authors": ["Vaswani, A.", "Shazeer, N."],
        "year": 2017,
        "doi": "10.48550/arXiv.1706.03762",
        "url": "https://openalex.org/W2741809807",
        "abstract": "The dominant sequence transduction models...",
        "cited_by_count": 120000,
        "is_open_access": True
    },
    # ... thêm 9-19 bài nữa
]
```

Khi Member 2 hoàn thành tool thật, chỉ cần thay `MOCK_PAPERS` bằng kết quả từ OpenAlex API.

---

## 3. PHÂN CÔNG CHI TIẾT TỪNG THÀNH VIÊN

### 3.1 Leader (bạn) — Agent Core & Điều phối

**Tuần 1:**

| Ngày | Task | Output kỳ vọng | Ưu tiên |
|:--|:--|:--|:--|
| Ngày 1 | Họp kickoff. Trình bày MVP + Contract cho team. Chốt Definition of Ready | Team hiểu và đồng ý scope | 🔴 Cao |
| Ngày 1 | Setup Git repo, branching, tạo file mock data | Repo sạch, mỗi người có branch riêng | 🔴 Cao |
| Ngày 2 | Viết `AgentState` trong `state.py` (đúng Mục 4.13 trong contract) | File `state.py` hoàn chỉnh, import được | 🔴 Cao |
| Ngày 2-3 | Viết khung `graph.py`: tạo 12 node (ban đầu là hàm rỗng), nối edge, conditional routing | Graph compile thành công, chạy được với mock data | 🔴 Cao |
| Ngày 3-4 | Viết Prompt cho `extract_evidence_node` và `synthesize_claims_node` | LLM trả về JSON đúng schema `ClaimCandidate` | 🔴 Cao |
| Ngày 4-5 | Tích hợp OpenAlex tool (của Member 2) vào `search_openalex_node` | Graph chạy end-to-end với dữ liệu thật | 🟡 TB |
| Ngày 5 | **Milestone: Tích hợp lần 1** — chạy thử toàn bộ pipeline | Demo nội bộ cho team xem | 🔴 Cao |

**Tuần 2:**

| Ngày | Task | Output kỳ vọng |
|:--|:--|:--|
| Ngày 6-7 | Tích hợp validation (của Member 3) vào `validate_grounding_node`. Viết `revise_claims_node` | Claim giả bị reject, claim thật pass |
| Ngày 7-8 | Tích hợp HITL: `human_review_node` với `interrupt()` + `Command(resume=...)` | Graph pause và resume đúng |
| Ngày 8-9 | Kết nối Graph với FastAPI endpoints (của Member 4). Debug end-to-end | Nhập topic trên web → xem kết quả |
| Ngày 9-10 | Test với 2-3 topic thật. Fix bug. Chuẩn bị cho user test | MVP sẵn sàng cho user test |

---

### 3.2 Member 2 — OpenAlex Tool & Data Acquisition

**Nhiệm vụ chính:** Viết tool gọi OpenAlex API, lấy paper, parse abstract, validate metadata.

**File chịu trách nhiệm:** `src/services/academic_search.py` hoặc `src/tools/openalex.py`

| Ngày | Task | Output | Tiêu chí hoàn thành |
|:--|:--|:--|:--|
| Ngày 1-2 | Đọc OpenAlex API docs. Viết hàm `search_openalex(query, limit)` | Gọi API, trả về JSON | Gõ topic → nhận 10 paper JSON |
| Ngày 2-3 | Parse `abstract_inverted_index` thành text thuần | Hàm parse hoạt động | Abstract đọc được, đúng ngữ nghĩa |
| Ngày 3 | Deduplicate (loại bài trùng DOI/title). Validate paper (loại bài thiếu abstract) | Hàm validate | Không có paper trùng hoặc thiếu abstract |
| Ngày 4 | Viết unit test cho tool | File test | Test pass: parse, dedup, validate |
| Ngày 5 | Giao tool cho Leader tích hợp vào Graph | PR merge vào develop | Leader gọi được tool từ graph |

**Leader cần hỗ trợ Member 2:**
- Ngày 1: Gửi link OpenAlex API docs + ví dụ response JSON.
- Ngày 2: Gửi cấu trúc `Paper` (Mục 4.3 trong contract) để Member 2 biết trả về đúng format.
- Ngày 3: Review PR lần đầu.

---

### 3.3 Member 3 — Grounding Validation & Evaluation

**Nhiệm vụ chính:** Viết logic kiểm tra claim có bịa hay không. Chuẩn bị bộ test đánh giá.

**File chịu trách nhiệm:** `src/validation/grounding.py`, `tests/`

| Ngày | Task | Output | Tiêu chí hoàn thành |
|:--|:--|:--|:--|
| Ngày 1-2 | Đọc Mục 10 (Grounding Validation) trong contract. Viết hàm `validate_claim(claim, papers)` | Hàm validate | Claim có paper_id sai → reject |
| Ngày 2-3 | Viết logic kiểm tra evidence quote (substring match trong abstract) | Hàm quote check | Quote không có trong abstract → reject |
| Ngày 3-4 | Viết logic reject absolute wording ("no study", "never researched") cho potential_gap | Hàm wording check | Câu tuyệt đối → reject |
| Ngày 4-5 | Chuẩn bị Gold Set: 2-3 topic, mỗi topic có 10 paper thật từ OpenAlex + câu hỏi/trả lời mẫu | File JSON Gold Set | Có ít nhất 15 claim mẫu để test |
| Tuần 2 | Chuẩn bị form đánh giá Claim-support Accuracy cho Reviewer. Hỗ trợ user test | Form + kết quả đánh giá | Có bảng claim-by-claim evaluation |

**Leader cần hỗ trợ Member 3:**
- Ngày 1: Giải thích rõ `ClaimCandidate` vs `Claim` (Mục 4.5 trong contract).
- Ngày 3: Gửi sample output từ LLM (extract_evidence) để Member 3 test validation logic.

---

### 3.4 Member 4 — FastAPI Backend + Next.js Frontend

**Nhiệm vụ chính:** Dựng API endpoints và giao diện web cho Researcher + Reviewer.

**File chịu trách nhiệm:** `src/api/routers/literature_reviews.py`, `frontend/`

| Ngày | Task | Output | Tiêu chí hoàn thành |
|:--|:--|:--|:--|
| Ngày 1 | Dựng khung FastAPI: `GET /health`, database init (SQLite) | Server chạy, health check OK | `curl localhost:8000/health` → 200 |
| Ngày 2 | `POST /api/v1/reviews` — tạo job (Mục 7.2 trong contract) | Endpoint hoạt động | Gửi topic → nhận job_id |
| Ngày 3 | `GET /api/v1/reviews/{job_id}/status` + `GET /api/v1/reviews/{job_id}` | Endpoints hoạt động | Polling trả đúng state |
| Ngày 4 | `POST /api/v1/reviews/{job_id}/review` — Reviewer gửi đánh giá (Mục 7.5) | Endpoint hoạt động | Reviewer gửi verdict → lưu DB |
| Ngày 5 | Next.js: Trang Researcher (form nhập topic + hiển thị progress + Evidence Table) | UI cơ bản | Nhập topic → thấy kết quả trên web |
| Tuần 2 | Next.js: Trang Reviewer (danh sách claim + nút Supported/Unsupported + approve) | UI review | Reviewer chấm claim trên web |

**Leader cần hỗ trợ Member 4:**
- Ngày 1: Gửi toàn bộ Mục 7 (API Contract) và Mục 11 (Database Schema) trong contract.
- Ngày 3: Chốt cách kết nối FastAPI với LangGraph (background task + polling vs SSE).
- Ngày 5: Test API endpoint thật với Graph output.

---

## 4. LỊCH HỌP VÀ GIAO TIẾP

### 4.1 Lịch họp cố định

| Thời điểm | Loại họp | Thời lượng | Nội dung |
|:--|:--|:--|:--|
| **Ngày 1** | Kickoff | 60-90 phút | Trình bày MVP, Contract, phân công, chốt Definition of Ready |
| **Mỗi sáng** | Daily standup | 15 phút | 3 câu hỏi: Hôm qua / Hôm nay / Bị chặn gì? |
| **Cuối ngày 5** | Demo nội bộ lần 1 | 30 phút | Chạy pipeline end-to-end, xác định bug cần fix |
| **Cuối ngày 8** | Demo nội bộ lần 2 | 30 phút | Chạy full luồng Researcher → Reviewer trên web |
| **Cuối ngày 10** | Retrospective | 30 phút | Gì đã tốt? Gì cần cải thiện? Bài học rút ra? |

### 4.2 Kênh giao tiếp

| Kênh | Dùng cho |
|:--|:--|
| **Nhóm chat (Zalo/Discord/Slack)** | Hỏi nhanh, thông báo PR, báo bị chặn |
| **WORKLOG.md** | Ghi chép công việc hàng ngày (Leader ghi) |
| **Pull Request trên GitHub** | Review code, thảo luận kỹ thuật |
| **Họp trực tiếp/online** | Standup hàng ngày, demo milestone |

### 4.3 Quy tắc giao tiếp

1. **Bị chặn quá 2 tiếng → báo ngay trên nhóm chat**, không chờ đến standup sáng hôm sau.
2. **Muốn thay đổi contract → tạo Issue/Message riêng**, nêu lý do và đề xuất. Leader quyết định trong vòng 4 tiếng.
3. **Code xong 1 task → tạo PR ngay**, không gom nhiều task vào 1 PR lớn.

---

## 5. QUY TRÌNH REVIEW CODE

### 5.1 Checklist review cho Leader

Khi review PR của bất kỳ thành viên nào, kiểm tra theo thứ tự:

```
□ 1. Code có tuân thủ data contract không?
     - Dùng đúng class Paper, Claim, AgentState?
     - Không tự thêm field mới mà chưa qua Lead?

□ 2. Code có chạy được không?
     - Có test kèm theo không?
     - Test pass hết chưa?

□ 3. Code có an toàn không?
     - Không hardcode API key?
     - Không log toàn bộ abstract ra console?
     - Có xử lý lỗi (try/except) cho API call?

□ 4. Code có sạch không?
     - Đặt tên biến/hàm rõ ràng?
     - Có comment cho logic phức tạp?
     - Không có code thừa/commented out?
```

### 5.2 Quy trình merge

```
Member tạo PR → Leader review (trong 4 tiếng)
  → Nếu OK: Approve + Merge vào develop
  → Nếu cần sửa: Comment cụ thể chỗ cần sửa → Member fix → Review lại
```

---

## 6. XỬ LÝ RỦI RO VÀ TÌNH HUỐNG

### 6.1 Bảng rủi ro và phương án

| Rủi ro | Xác suất | Dấu hiệu nhận biết | Phương án của Leader |
|:--|:--|:--|:--|
| OpenAlex API chậm/lỗi | Trung bình | Member 2 báo timeout | Dùng mock data. Viết retry logic |
| LLM output sai format JSON | Cao | parse error trong graph | Thêm structured output (JSON mode). Thêm retry 1 lần |
| Member không biết code phần được giao | Trung bình | Standup báo "chưa hiểu" | Pair programming 1-2 tiếng. Gửi tài liệu/ví dụ |
| Team muốn thêm tính năng ngoài MVP | Cao | "Hay là mình làm thêm..." | Chỉ vào Mục 19 contract. Nói: "Sau MVP đạt KPI rồi làm" |
| Không kịp deadline 2 tuần | Thấp | Cuối tuần 1 chưa chạy end-to-end | Cắt scope: giữ Evidence Table + References, bỏ Themes + Gaps |
| Code conflict khi merge | Trung bình | Git merge conflict | Merge develop vào feature branch mỗi ngày |

### 6.2 Thứ tự cắt scope nếu không kịp (từ ít quan trọng → quan trọng nhất)

```
Cắt trước:  Potential Gaps (output phụ)
            ↓
            Thematic Summary (output phụ)
            ↓
            Reviewer view đầy đủ (dùng JSON thay UI)
            ↓
Giữ lại:    Evidence Table + Verified References + HITL cơ bản
            (Đây là lõi giá trị tối thiểu để demo được)
```

---

## 7. THEO DÕI TIẾN ĐỘ

### 7.1 Bảng theo dõi Milestone

Leader cập nhật bảng này mỗi ngày trong WORKLOG.md:

```markdown
## Milestone Tracker

| # | Milestone | Deadline | Owner | Status |
|:--|:--|:--|:--|:--|
| M1 | OpenAlex tool chạy được | Ngày 2 | Member 2 | ⬜ |
| M2 | AgentState + Graph khung compile | Ngày 3 | Leader | ⬜ |
| M3 | Validation logic hoạt động | Ngày 4 | Member 3 | ⬜ |
| M4 | FastAPI endpoints cơ bản | Ngày 4 | Member 4 | ⬜ |
| M5 | Tích hợp lần 1 (end-to-end) | Ngày 5 | Leader | ⬜ |
| M6 | HITL interrupt/resume hoạt động | Ngày 8 | Leader | ⬜ |
| M7 | Web UI Researcher + Reviewer | Ngày 9 | Member 4 | ⬜ |
| M8 | User test với 2-3 topic | Ngày 10 | Cả team | ⬜ |
```

### 7.2 Definition of Done — Checklist cuối cùng

Trước khi tuyên bố MVP hoàn thành, Leader kiểm tra từng mục (lấy từ README_MVP_V1.md Mục 9):

```markdown
- [ ] LangGraph StateGraph chạy đủ node, conditional edge và bounded retry.
- [ ] OpenAlex được gọi qua tool; agent state và decision trace có thể kiểm tra.
- [ ] Graph pause tại HITL interrupt và resume đúng job_id.
- [ ] Web app có URL deploy và chạy được luồng Researcher → Reviewer.
- [ ] Một topic trả về 10–20 bài có metadata và abstract hợp lệ.
- [ ] Evidence Table, Thematic Summary và scope disclaimer được tạo.
- [ ] Reviewer kiểm tra được từng claim và citation.
- [ ] Không phát hiện citation/DOI/URL do AI bịa.
- [ ] Claim-support Accuracy đạt >= 80%.
- [ ] Median Time Reduction đạt >= 50%.
- [ ] Có kết quả thử nghiệm và danh sách lỗi.
```

---

## 8. SAU MVP — QUYẾT ĐỊNH TIẾP THEO

Sau khi MVP hoàn thành và có kết quả user test, Leader họp team để quyết định:

| Kết quả user test | Hành động tiếp theo |
|:--|:--|
| Citation sai hoặc có nguồn bịa | Dừng mở rộng. Fix guardrail/validation trước |
| Claim accuracy < 80% | Thu hẹp loại claim hoặc bắt buộc evidence quote |
| Time reduction < 50% | Đơn giản hóa input/output, tìm bước gây chậm |
| Retrieval bỏ sót nhiều bài | Xem xét thêm arXiv/Semantic Scholar |
| **Đạt cả 3 KPI** | Chuyển sang Phase 2: Qdrant, full-text PDF, RAGAS, Code Sandbox |

---

## 9. TÓM TẮT — MỘT NGÀY CỦA LEADER

```
08:00 - 08:15  │ Daily standup (15 phút)
08:15 - 09:00  │ Review PR nếu có. Unblock team nếu ai bị chặn
09:00 - 12:00  │ Code phần core (graph.py, prompts, tích hợp)
12:00 - 13:00  │ Nghỉ trưa
13:00 - 14:00  │ Check nhóm chat. Trả lời câu hỏi kỹ thuật
14:00 - 17:00  │ Tiếp tục code. Tích hợp module của member
17:00 - 17:30  │ Cập nhật WORKLOG.md. Chuẩn bị task cho ngày mai
```

**3 câu hỏi Leader tự hỏi mình mỗi tối:**
1. Có ai trong team đang bị chặn mà tôi chưa giải quyết không?
2. Pipeline end-to-end hiện tại chạy được đến đâu rồi?
3. Có rủi ro nào đang tiến gần mà tôi chưa có phương án không?
