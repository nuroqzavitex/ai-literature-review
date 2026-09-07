# SCIENTIFIC RECOMBINATION GRAPH

> **Status: concept/proposal, chưa được wiring vào runtime hiện tại.** Các thư
> mục `src/corpus_curation/`, `src/scientific_graph/`, `src/discovery/`,
> `src/extraction/`, `src/retrieval/` và `src/shared_knowledge/` hiện không có
> source implementation. Không dùng tài liệu này như current architecture.

## Hệ thống phát hiện khoảng trống và sinh giả thuyết nghiên cứu bằng tái tổ hợp tri thức khoa học

**Phiên bản:** Concept / Technical Design v1
**Mục tiêu:** Biến literature review từ hệ thống “tìm và tóm tắt paper” thành hệ thống có khả năng cấu trúc tri thức, phát hiện các tổ hợp chưa được nghiên cứu, kiểm chứng novelty và đề xuất hướng nghiên cứu mới có bằng chứng truy vết.

---

# 1. Tóm tắt ý tưởng

Hệ thống thu thập các bài báo khoa học, sau đó không chỉ lưu chúng dưới dạng văn bản hoặc vector embedding mà còn chuyển nội dung nghiên cứu thành một **Scientific Knowledge Graph (đồ thị tri thức khoa học)**.

Graph biểu diễn các thành phần như:

* Paper
* Model
* Method
* Dataset
* Task
* Domain
* Metric
* Finding
* Limitation

và các quan hệ giữa chúng như:

```text
Paper ──uses──────────> Model
Paper ──evaluates_on──> Dataset
Model ──solves────────> Task
Dataset ──supports────> Task
Paper ──reports───────> Finding
Paper ──reports───────> Limitation
Finding ──measured_by─> Metric
```

Mục tiêu quan trọng nhất không phải chỉ hỏi:

> “Paper nào nói về Model X?”

mà tiến tới câu hỏi:

> “Có những tổ hợp Model × Dataset × Task nào hợp lý về mặt khoa học nhưng chưa được nghiên cứu?”

Từ đó hệ thống thực hiện:

```text
Literature
    ↓
Structured Extraction
    ↓
Scientific Knowledge Graph
    ↓
Existing Research Combinations
    ↓
Candidate Missing Connections
    ↓
Novelty Search
    ↓
Counterevidence Search
    ↓
Compatibility Validation
    ↓
Scientific Rationale
    ↓
Validated Research Opportunity
    ↓
Research Question / Hypothesis
    ↓
Proposed Experiment
```

Đây không còn đơn thuần là RAG.

Nó là một **Research Discovery System (hệ thống hỗ trợ khám phá nghiên cứu)**.

Các hướng nghiên cứu gần đây cho thấy cách biểu diễn literature thành graph để tái tổ hợp problem, method, mechanism và finding có thể hỗ trợ sinh ý tưởng khoa học có cấu trúc và khả năng truy vết tốt hơn flat retrieved text. Graph2Idea là một ví dụ gần với hướng này. Scientific Contribution Graph cũng cho thấy giá trị của việc mô hình hóa đóng góp khoa học ở mức chi tiết hơn citation giữa các paper.

---

# 2. Vấn đề hệ thống muốn giải quyết

Các hệ thống literature review hiện nay thường mạnh ở:

```text
Search
→ Retrieve
→ Summarize
→ Compare
→ Generate report
```

Nhưng vẫn phụ thuộc vào researcher để phát hiện:

```text
"A đã được thử với B."

"C cũng gần giống B."

"Nhưng hình như chưa ai thử A với C."

"Tại sao?"

"Nếu thử thì có ý nghĩa không?"
```

Đây chính là phần suy luận có giá trị cao trong quá trình nghiên cứu.

Hệ thống đề xuất sẽ cấu trúc những thông tin đó để máy có thể hỗ trợ phát hiện các tổ hợp.

---

# 3. Nguyên tắc quan trọng nhất

## Missing edge ≠ Research gap

Nếu graph có:

```text
Model A ──tested_on──> Dataset X
Model A ──tested_on──> Dataset Y

Model B ──tested_on──> Dataset X
Model B ──tested_on──> Dataset Y
Model B ──tested_on──> Dataset Z

Model A ───── ? ─────> Dataset Z
```

không được kết luận ngay:

> “Model A × Dataset Z là research gap.”

Graph chỉ được phép nói:

> “Đây là một **candidate missing relation (quan hệ còn thiếu ứng viên)** trong corpus hiện tại.”

Sau đó hệ thống phải kiểm tra:

1. Có paper nào đã thực hiện nhưng chưa nằm trong corpus không?
2. Model và dataset có tương thích về input/output không?
3. Dataset có thực sự hỗ trợ task mà model giải quyết không?
4. Có lý do khoa học để thử tổ hợp này không?
5. Có contribution mới hay chỉ là đổi dataset?
6. Kết quả có thể được đánh giá bằng metric phù hợp không?
7. Có counterevidence cho thấy hướng này đã thất bại hoặc không khả thi không?

Chỉ sau quá trình validation mới được nâng trạng thái thành:

```text
Validated Candidate Research Gap
```

---

# 4. Không nên thiết kế một node chứa “toàn bộ model”

Ý tưởng ban đầu có thể hình dung:

```text
[MODEL NODE]
- BERT
- GPT
- Llama
- ResNet

[DATASET NODE]
- Dataset A
- Dataset B
- Dataset C
```

Nhưng implementation như vậy sẽ làm mất khả năng biểu diễn relationship chi tiết.

Thiết kế phù hợp hơn là **typed graph (đồ thị có kiểu)**:

```text
MODEL
 ├── BERT
 ├── RoBERTa
 ├── Llama
 └── GPT

DATASET
 ├── Dataset A
 ├── Dataset B
 └── Dataset C
```

Trong database:

```text
Entity
--------------------
id
type = MODEL
canonical_name = BERT
```

và:

```text
Entity
--------------------
id
type = DATASET
canonical_name = Dataset A
```

Sau đó tạo edge:

```text
BERT ──EVALUATED_ON──> Dataset A
```

“Model”, “Dataset”, “Task” là **entity type (loại thực thể)** chứ không phải một entity chứa danh sách.

UI vẫn có thể hiển thị:

```text
Models
Datasets
Tasks
Methods
```

như các nhóm lớn.

---

# 5. Ontology đề xuất

MVP nên giới hạn ontology để tránh graph quá phức tạp.

## 5.1 Core node types

### Paper

Đại diện bài báo.

```text
Paper
- paper_id
- title
- abstract
- publication_year
- DOI
- OpenAlex ID
- authors
- source
```

### Model

```text
Model
- name
- model_family
- architecture
- modality
```

Ví dụ:

```text
BERT
RoBERTa
ResNet-50
Llama
```

### Dataset

```text
Dataset
- name
- domain
- modality
- language
- task
```

### Task

Ví dụ:

```text
Text Classification
Question Answering
Image Classification
Machine Translation
Named Entity Recognition
```

### Method

Các kỹ thuật không nhất thiết là model.

Ví dụ:

```text
Fine-tuning
RAG
Prompt Engineering
Contrastive Learning
Data Augmentation
```

### Finding

Kết quả khoa học chính.

```text
Finding
- statement
- polarity
- confidence
```

### Limitation

```text
Limitation
- statement
- category
```

Ví dụ:

```text
small sample
domain limitation
language limitation
compute limitation
generalization limitation
evaluation limitation
```

### Metric

Ví dụ:

```text
Accuracy
F1
BLEU
ROUGE
AUROC
```

---

# 6. Các edge type ban đầu

```text
Paper ──USES─────────────> Model

Paper ──USES_METHOD──────> Method

Paper ──EVALUATES_ON─────> Dataset

Paper ──ADDRESSES────────> Task

Dataset ──SUPPORTS────────> Task

Model ──APPLIED_TO───────> Task

Paper ──REPORTS───────────> Finding

Paper ──HAS_LIMITATION────> Limitation

Finding ──MEASURED_BY─────> Metric

Model ──EVALUATED_ON──────> Dataset

Method ──APPLIED_TO───────> Task

Paper ──CITES─────────────> Paper

Finding ──SUPPORTS────────> Finding

Finding ──CONTRADICTS─────> Finding
```

Giai đoạn sau có thể thêm:

```text
Population
Language
Environment
Hardware
ResearchProblem
ResearchQuestion
Application
Mechanism
```

Không nên cho tất cả vào MVP.

---

# 7. Evidence provenance

Đây là thành phần bắt buộc.

Một edge không được tồn tại chỉ vì LLM nói rằng nó tồn tại.

Ví dụ:

```text
BERT ──EVALUATED_ON──> SQuAD
```

phải trỏ ngược được tới evidence:

```text
Edge
 ↓
Paper P17
 ↓
Section: Experiments
 ↓
Page: 6
 ↓
Text span
```

Schema:

```text
graph_edges
----------------------------
edge_id
source_entity_id
relation_type
target_entity_id
confidence
status
created_at
```

và:

```text
edge_evidence
----------------------------
edge_id
paper_id
chunk_id
section
page
quote
extraction_method
confidence
```

Nguyên tắc:

```text
Graph fact
    ↓
Evidence
    ↓
Original paper
```

Nếu không trace được nguồn thì không được dùng fact đó để kết luận research gap.

---

# 8. Data ingestion pipeline

Nguồn ban đầu có thể tiếp tục sử dụng OpenAlex.

OpenAlex cung cấp scholarly works cùng các metadata như title, abstract dạng inverted index, topics, keywords, references và nhiều thuộc tính khác; vì vậy phù hợp cho tầng paper discovery và metadata enrichment.

Pipeline:

```text
Research Topic
       ↓
Search OpenAlex
       ↓
Candidate Papers
       ↓
Metadata normalization
       ↓
Deduplication
       ↓
Abstract reconstruction
       ↓
Paper embedding
       ↓
Full-text acquisition if available
       ↓
Structured extraction
```

---

# 9. Embedding strategy

Không nên embedding mỗi chunk một cách phẳng ngay từ đầu.

Đề xuất sử dụng hai tầng.

## Level 1 — Paper Retrieval

Tạo:

```text
paper_representation =
title
+ abstract
+ keywords
```

sau đó:

```text
embedding(paper_representation)
```

Mục tiêu:

> Paper nào liên quan đến research question?

Ví dụ:

```text
1,000,000 papers
       ↓
Paper embedding retrieval
       ↓
Top 100
```

---

## Level 2 — Evidence Retrieval

Với candidate papers:

```text
Paper
├── Introduction
├── Related Work
├── Method
├── Dataset
├── Experiments
├── Results
├── Discussion
└── Limitations
```

Tạo embedding theo section/chunk.

```text
chunk_embedding
```

Mục tiêu:

> Evidence nằm ở đoạn nào?

Pipeline:

```text
Query
 ↓
Paper retrieval
 ↓
Top 50 papers
 ↓
Full-text retrieval
 ↓
Top evidence chunks
 ↓
Reranker
```

---

# 10. Vai trò của PageIndex

PageIndex không thay Graph.

PageIndex xây `hierarchical tree index (chỉ mục cây phân cấp)` của tài liệu và dùng reasoning/tree search để điều hướng tài liệu thay vì dựa chủ yếu vào vector similarity.

Có thể sử dụng nó ở tầng:

```text
Candidate Paper
      ↓
Document Structure
      ↓
Method
Dataset
Results
Limitations
      ↓
Relevant pages
```

Do đó kiến trúc có thể là:

```text
             Query
               │
               ▼
       Abstract Retrieval
               │
               ▼
        Candidate Papers
               │
       ┌───────┴────────┐
       ▼                ▼
   PageIndex        Vector chunks
       │                │
 document path       evidence
       │                │
       └───────┬────────┘
               ▼
        Evidence extraction
```

PageIndex giải quyết:

> “Trong paper này nên đọc đâu?”

Graph giải quyết:

> “Các paper này liên quan với nhau như thế nào?”

---

# 11. Knowledge extraction pipeline

Với từng paper:

```text
Paper
 ↓
Section Selection
 ↓
LLM Structured Extraction
 ↓
Schema Validation
 ↓
Entity Resolution
 ↓
Relation Validation
 ↓
Graph Insert
```

Output LLM phải structured.

Ví dụ:

```json
{
  "models": [
    {
      "name": "Model A",
      "evidence_chunk_id": "chunk_182"
    }
  ],
  "datasets": [
    {
      "name": "Dataset X",
      "evidence_chunk_id": "chunk_190"
    }
  ],
  "tasks": [
    {
      "name": "Task Y"
    }
  ],
  "relations": [
    {
      "source": "Model A",
      "relation": "EVALUATED_ON",
      "target": "Dataset X",
      "evidence_chunk_id": "chunk_190"
    }
  ]
}
```

Sau LLM phải qua Pydantic/schema validation.

---

# 12. Entity Resolution

Đây là vấn đề rất quan trọng.

Paper 1 có thể viết:

```text
BERT-base
```

Paper 2:

```text
BERT Base
```

Paper 3:

```text
bert-base-uncased
```

Không được tạo ba entity độc lập nếu chúng nói về cùng một object ở mức ontology đang xét.

Pipeline:

```text
Extracted entity
      ↓
Normalize string
      ↓
Alias lookup
      ↓
Exact match?
      │
      ├─ Yes → existing entity
      │
      └─ No
          ↓
    embedding similarity
          ↓
    LLM/entity resolver
          ↓
    same / related / different
```

Cần bảng:

```text
entity_aliases
---------------------
alias
entity_id
source
confidence
```

---

# 13. Graph construction

Ví dụ sau khi ingest nhiều paper:

```text
                Model A
               /       \
     evaluated_on       applied_to
            /               \
     Dataset X             Task T
       │
   supports
       │
       └───────────────> Task T


                Model B
               /       \
     evaluated_on       applied_to
            /               \
     Dataset Y             Task T
```

Graph bắt đầu mô tả **research landscape (bức tranh nghiên cứu)**.

Microsoft GraphRAG cũng dựa trên việc trích xuất entities, relationships và claims từ raw text rồi xây graph/community structure; tuy nhiên hệ thống đề xuất ở đây dùng graph không chỉ cho retrieval mà còn cho scientific recombination.

---

# 14. Research Combination Engine

Đây là module mới quan trọng nhất.

Tên đề xuất:

```text
Research Combination Engine
```

Nhiệm vụ:

> Tìm những tổ hợp nghiên cứu tiềm năng dựa trên graph hiện có.

Không cần machine learning phức tạp ở MVP.

Có thể bắt đầu bằng graph rules.

---

# 15. Candidate type 1 — Model × Dataset

Graph có:

```text
Model A ──evaluated_on──> Dataset 1
Model A ──evaluated_on──> Dataset 2

Model B ──evaluated_on──> Dataset 1
Model B ──evaluated_on──> Dataset 2
Model B ──evaluated_on──> Dataset 3
```

Candidate:

```text
Model A × Dataset 3
```

Nhưng chỉ tạo candidate nếu:

```text
Dataset 3 supports Task T

AND

Model A applied_to Task T
```

tức:

```text
Model A
   │
 applied_to
   ▼
 Task T
   ▲
 supports
   │
Dataset 3
```

đồng thời chưa thấy:

```text
Model A ──evaluated_on──> Dataset 3
```

---

# 16. Candidate type 2 — Method transfer

Ví dụ:

```text
Method M
   │
works_for
   ▼
Problem A
```

Graph phát hiện:

```text
Problem B
   │
similar mechanism/domain
   ▼
Problem A
```

Candidate:

```text
Apply Method M to Problem B
```

Đây là kiểu **method transfer (chuyển phương pháp sang bài toán khác)**.

---

# 17. Candidate type 3 — Limitation-driven discovery

Đây có thể là một trong những loại mạnh nhất.

Ví dụ:

```text
Paper P
  ↓
Limitation:
"Method performs poorly on low-resource languages."
```

Graph:

```text
Method M
   │
limitation
   ▼
Low-resource language
```

Trong graph khác có:

```text
Method N
   │
addresses
   ▼
Low-resource adaptation
```

Candidate:

```text
Method M
   +
Method N
   ↓
New research direction
```

Không phải random combination.

Nó xuất phát trực tiếp từ limitation.

---

# 18. Candidate type 4 — Dataset transfer

```text
Model M
 ↓
Dataset A
 ↓
Task T
```

Dataset B:

```text
Dataset B
 ↓
same Task T
 ↓
different Domain D2
```

Candidate:

```text
Evaluate generalization of M
from Domain D1
to Domain D2.
```

Loại này đặc biệt phù hợp cho:

```text
cross-domain generalization
cross-language generalization
cross-population evaluation
```

---

# 19. Candidate type 5 — Contradictory findings

Ví dụ:

```text
Paper A
 ↓
Finding:
Method X improves accuracy
```

nhưng:

```text
Paper B
 ↓
Finding:
Method X does not significantly improve accuracy
```

Graph:

```text
Finding A
   │
CONTRADICTS
   ▼
Finding B
```

System có thể tìm khác biệt:

```text
Dataset?
Population?
Domain?
Metric?
Model version?
Experimental setup?
```

và sinh research question:

> Under what conditions does Method X actually improve performance?

Đây thường có giá trị nghiên cứu hơn một missing Model × Dataset đơn giản.

---

# 20. Candidate Generation Algorithm

MVP có thể dùng rule-based engine.

Pseudo flow:

```text
for model in models:

    tasks = graph.tasks_of(model)

    for task in tasks:

        datasets = graph.datasets_supporting(task)

        for dataset in datasets:

            if graph.has_edge(
                model,
                "EVALUATED_ON",
                dataset
            ):
                continue

            create_candidate(
                type="MODEL_DATASET",
                model=model,
                dataset=dataset,
                task=task
            )
```

Sau đó chưa hiển thị ngay.

Candidate phải đi qua scoring + validation.

---

# 21. Candidate scoring

Mỗi candidate có thể được tính:

```text
CandidateScore =
    Compatibility
  + EvidenceStrength
  + Novelty
  + ScientificMotivation
  + Feasibility
  - ExistingWorkRisk
```

MVP chưa cần train model.

Có thể heuristic:

```text
compatibility_score       0–1
evidence_score            0–1
novelty_score             0–1
motivation_score          0–1
feasibility_score         0–1
existing_work_risk        0–1
```

Ví dụ:

```text
score =
0.25 * compatibility
+ 0.20 * evidence
+ 0.20 * novelty
+ 0.20 * motivation
+ 0.15 * feasibility
- 0.30 * existing_work_risk
```

Weights này là cấu hình thử nghiệm, không phải chân lý khoa học.

Nó phải lưu trong configuration để evaluation sau này có thể thay đổi.

---

# 22. Validation Pipeline

Candidate:

```text
Model A × Dataset C
```

phải đi qua:

```text
Candidate
   ↓
1. Novelty Search
   ↓
2. Counterevidence Search
   ↓
3. Compatibility Validation
   ↓
4. Scientific Motivation
   ↓
5. Feasibility
   ↓
6. Contribution Assessment
   ↓
Validated / Rejected
```

---

# 23. Novelty Search

Tạo các search query khác nhau.

Ví dụ:

```text
"Model A" "Dataset C"

"Model A" AND "Task T"

"Dataset C" AND "Model A"

"Model A" evaluation "Dataset C"

aliases(Model A) × aliases(Dataset C)
```

Search OpenAlex và các nguồn được hỗ trợ.

Không tìm thấy không đồng nghĩa chắc chắn chưa tồn tại.

Vì vậy output:

```text
novelty_status =
    confirmed_existing
    likely_existing
    no_evidence_found
    uncertain
```

Không nên có:

```text
100% novel
```

---

# 24. Counterevidence Search

Agent chủ động tìm bằng chứng chống lại hypothesis.

Ví dụ candidate:

> Model A có thể hoạt động trên Dataset C.

Agent tìm:

```text
Model A limitation
Model A incompatible
Model A failure Dataset C
Task T limitation
Dataset C incompatibility
```

Output:

```text
supporting_evidence[]
counterevidence[]
```

Đây là phần giúp hệ thống tránh trở thành “idea generator sinh linh tinh”.

---

# 25. Compatibility Validator

Trước khi nói:

```text
Model A + Dataset C
```

phải kiểm tra:

```text
Input modality
Output type
Task
Label schema
Language
Domain
Data size
Required preprocessing
Model constraints
Evaluation metrics
```

Ví dụ:

```text
Model:
text classifier

Dataset:
image classification
```

→ reject ngay.

Không cần LLM reasoning tốn token.

---

# 26. Contribution Validator

Ngay cả khi chưa ai thử:

```text
Model A + Dataset C
```

vẫn chưa chắc có giá trị.

System phải hỏi:

> Nếu làm thí nghiệm này, kiến thức mới thu được là gì?

Ví dụ xấu:

```text
"Chạy model X trên một dataset khác."
```

Ví dụ tốt hơn:

```text
"Kiểm tra khả năng generalization của Model X
khi chuyển từ high-resource sang low-resource language."
```

Candidate phải có:

```text
scientific_question
expected_contribution
why_it_matters
```

Nếu không tạo được contribution hợp lý:

```text
reject: weak_scientific_value
```

---

# 27. Candidate lifecycle

```text
DISCOVERED
    ↓
RETRIEVING_EVIDENCE
    ↓
UNDER_VALIDATION
    ↓
┌───────────────┬─────────────────┐
▼               ▼                 ▼
VALIDATED      REJECTED          UNCERTAIN
                │
        ┌───────┼─────────┐
        ▼       ▼         ▼
     EXISTS incompatible weak_value
```

Database phải giữ lại rejected candidate.

Không delete.

Điều này tránh agent phát hiện cùng một “gap” sai nhiều lần.

---

# 28. Output của Research Opportunity

Một candidate cuối cùng nên có dạng:

```json
{
  "candidate_id": "gap_001",

  "type": "MODEL_DATASET_TRANSFER",

  "components": {
    "model": "Model A",
    "dataset": "Dataset C",
    "task": "Task T"
  },

  "research_question":
    "How well does Model A generalize to Dataset C for Task T?",

  "hypothesis":
    "Model A may retain performance under Domain C conditions.",

  "rationale":
    "...",

  "supporting_evidence": [
    "paper_17",
    "paper_28"
  ],

  "counterevidence": [
    "paper_93"
  ],

  "novelty": {
    "status": "no_evidence_found",
    "searches": 14
  },

  "compatibility_score": 0.91,
  "novelty_score": 0.82,
  "feasibility_score": 0.74,

  "confidence": 0.79,

  "limitations": [
    "Full-text coverage is incomplete."
  ],

  "status": "VALIDATED_CANDIDATE"
}
```

---

# 29. Experiment Proposal Generator

Validated candidate có thể tiếp tục thành:

```text
Research Opportunity
       ↓
Research Question
       ↓
Hypothesis
       ↓
Experimental Design
```

Output:

```text
Research Question

Hypothesis

Independent variables

Dependent variables

Dataset

Model

Baseline

Evaluation metrics

Experimental procedure

Expected outcomes

Possible failure cases

Required resources

Evidence supporting design
```

Điểm quan trọng:

**Agent đề xuất experiment, không khẳng định experiment sẽ thành công.**

---

# 30. Kiến trúc tổng thể

```text
                         USER
                           │
                           ▼
                     Next.js UI
                           │
                           ▼
                       FastAPI
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
   Research Agent    Copilot Chat     Discovery Agent
          │                                 │
          │                                 ▼
          │                       Research Combination
          │                              Engine
          │                                 │
          └───────────────┬─────────────────┘
                          │
                          ▼
                    Retrieval Layer
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
    Paper Search       Vector RAG       Graph Query
          │               │                │
          ▼               ▼                ▼
      OpenAlex          Qdrant        Graph Store
                          │                │
                          └────────┬───────┘
                                   ▼
                              Evidence Set
                                   │
                                   ▼
                           Grounding Validator
                                   │
                                   ▼
                                  LLM
                                   │
                                   ▼
                         Research Opportunity
```

---

# 31. Storage architecture

Không cần thêm database nặng ngay.

## MVP

Giữ:

```text
PostgreSQL
+
pgvector hoặc Qdrant
```

và biểu diễn graph bằng relational tables.

```text
entities
edges
edge_evidence
```

PostgreSQL vẫn là:

```text
source of truth
```

Graph traversal ở MVP có thể sử dụng:

```text
SQL JOIN
recursive CTE
```

Điều này đủ cho graph nhỏ/trung bình.

---

# 32. Khi nào cần Neo4j

Chỉ nên thêm graph database khi xuất hiện nhu cầu:

```text
multi-hop traversal lớn
community analysis
graph algorithms
link prediction
subgraph exploration
complex path queries
```

Kiến trúc lúc đó:

```text
PostgreSQL
     │
 source of truth
     │
     ▼
Graph projection/sync
     │
     ▼
Neo4j
```

Không nên để:

```text
Postgres data
Neo4j data
```

cùng là nguồn chuẩn độc lập.

Nếu không sẽ phát sinh consistency problem.

---

# 33. Database schema MVP

## papers

```text
id
openalex_id
doi
title
abstract
keywords
publication_year
source
metadata_json
created_at
```

## paper_chunks

```text
id
paper_id
section
page_start
page_end
text
embedding
```

## entities

```text
id
type
canonical_name
normalized_name
properties_json
created_at
```

## entity_aliases

```text
id
entity_id
alias
normalized_alias
source
confidence
```

## graph_edges

```text
id
source_entity_id
relation_type
target_entity_id
confidence
status
created_at
```

## edge_evidence

```text
id
edge_id
paper_id
chunk_id
quote
page
confidence
```

## findings

```text
id
paper_id
statement
polarity
confidence
```

## candidate_opportunities

```text
id
candidate_type
components_json
status

compatibility_score
evidence_score
novelty_score
motivation_score
feasibility_score
final_score

research_question
hypothesis
rationale

created_at
updated_at
```

## candidate_evidence

```text
candidate_id
paper_id
chunk_id
evidence_type

SUPPORT
COUNTEREVIDENCE
EXISTING_WORK
```

## validation_runs

```text
id
candidate_id
validator
input_json
output_json
status
created_at
```

---

# 34. Service structure đề xuất

```text
src/
│
├── ingestion/
│   ├── openalex.py
│   ├── paper_normalizer.py
│   └── fulltext.py
│
├── retrieval/
│   ├── paper_retriever.py
│   ├── chunk_retriever.py
│   ├── graph_retriever.py
│   └── reranker.py
│
├── extraction/
│   ├── entity_extractor.py
│   ├── relation_extractor.py
│   ├── finding_extractor.py
│   └── limitation_extractor.py
│
├── graph/
│   ├── entity_resolver.py
│   ├── graph_repository.py
│   ├── traversal.py
│   └── ontology.py
│
├── discovery/
│   ├── combination_engine.py
│   ├── candidate_generator.py
│   ├── candidate_ranker.py
│   └── patterns/
│       ├── model_dataset.py
│       ├── method_transfer.py
│       ├── limitation_driven.py
│       └── contradiction.py
│
├── validation/
│   ├── novelty.py
│   ├── compatibility.py
│   ├── counterevidence.py
│   ├── scientific_value.py
│   └── feasibility.py
│
├── hypothesis/
│   ├── question_generator.py
│   ├── hypothesis_generator.py
│   └── experiment_designer.py
│
└── evidence/
    ├── provenance.py
    └── grounding.py
```

---

# 35. API đề xuất

## Graph

```text
GET /projects/{id}/graph
GET /projects/{id}/entities
GET /projects/{id}/entities/{entity_id}
GET /projects/{id}/graph/neighbors/{entity_id}
```

## Research opportunities

```text
POST /projects/{id}/discover

GET /projects/{id}/opportunities

GET /projects/{id}/opportunities/{candidate_id}
```

## Validation

```text
POST /opportunities/{id}/validate

POST /opportunities/{id}/validate-novelty

POST /opportunities/{id}/validate-counterevidence
```

## Experiment

```text
POST /opportunities/{id}/generate-research-question

POST /opportunities/{id}/generate-experiment
```

---

# 36. Agent workflow

Không nên để một LLM tự thực hiện toàn bộ.

Workflow:

```text
START
  ↓
Understand Research Scope
  ↓
Search Papers
  ↓
Screen Papers
  ↓
Extract Structured Knowledge
  ↓
Resolve Entities
  ↓
Update Knowledge Graph
  ↓
Generate Candidate Combinations
  ↓
Rank Candidates
  ↓
────────────────────────────
For each candidate:
  ↓
Novelty Search
  ↓
Existing?
  ├─ YES → Reject
  │
  └─ NO / UNCERTAIN
          ↓
     Compatibility Check
          ↓
     Compatible?
       ├─ NO → Reject
       │
       └─ YES
           ↓
      Counterevidence Search
           ↓
      Scientific Value Check
           ↓
      Feasibility Check
           ↓
       Candidate Gap
           ↓
      Research Question
           ↓
         HUMAN
           ↓
     Approve / Reject
```

Human vẫn phải giữ quyền quyết định cuối.

---

# 37. Quan hệ với GraphRAG

GraphRAG không phải sản phẩm cuối của kiến trúc này.

Microsoft GraphRAG xây graph từ entities/relationships/claims và hỗ trợ các retrieval strategy trên graph/community structure.

Hệ thống này sử dụng một phần tư tưởng đó nhưng đi thêm bước:

```text
GraphRAG

Graph
 ↓
Retrieve
 ↓
Answer
```

trong khi hệ thống đề xuất:

```text
Scientific Graph
       ↓
Retrieve
       +
Analyze structure
       +
Find missing relationships
       +
Recombine knowledge
       +
Validate
       ↓
Research Opportunity
```

Vì vậy tên module không nên đơn thuần là:

```text
GraphRAG
```

Tên phù hợp hơn:

**Scientific Recombination Graph**

hoặc:

**Research Opportunity Graph**

---

# 38. Quan hệ với các nghiên cứu hiện tại

Có ba hướng đặc biệt liên quan.

### Graph2Idea

Graph2Idea biến literature được retrieve thành structured triples và xây target-centered knowledge graph, sau đó dùng graph-derived context để tìm direction và sinh candidate research ideas. Đây là hướng rất gần với việc “tái tổ hợp các thành phần khoa học” mà hệ thống này đề xuất.

### Scientific Contribution Graph

Scientific Contribution Graph biểu diễn individual scientific contributions và prerequisite relationships thay vì chỉ citation paper-to-paper. Công trình báo cáo graph gồm khoảng 2 triệu contribution nodes từ 230 nghìn open-access papers và dùng chúng cho bài toán scientific prerequisite prediction. Điều này củng cố lựa chọn thiết kế graph ở mức scientific component thay vì chỉ paper node.

### Literature-Based Discovery

Literature-based discovery đã nghiên cứu ý tưởng tìm các implicit/unpublished relationships giữa các knowledge units, và link prediction cũng đã được sử dụng để dự đoán các liên kết nghiên cứu có thể xuất hiện trong tương lai.

Do đó hệ thống này không phải một ý tưởng “random AI combine”.

Nó có thể được nhìn như:

```text
Scientific Knowledge Graph
        +
Literature-Based Discovery
        +
Graph Link Prediction
        +
RAG
        +
LLM Reasoning
        +
Human Validation
```

---

# 39. Một ví dụ end-to-end

Giả sử corpus giả định có:

```text
Paper P1
Model A
Dataset X
Task T

Paper P2
Model A
Dataset Y
Task T

Paper P3
Model B
Dataset Z
Task T
```

Graph:

```text
               Task T
              ▲      ▲
              │      │
          Model A  Model B
           │   │      │
           ▼   ▼      ▼
           X   Y      Z
```

System nhận thấy:

```text
Model A
   ↓
Task T

Dataset Z
   ↓
Task T
```

nhưng chưa có:

```text
Model A → Dataset Z
```

Tạo:

```text
Candidate C1
Model A × Dataset Z × Task T
```

### Novelty agent

Search literature.

Không tìm thấy trực tiếp.

```text
novelty = no_evidence_found
```

### Compatibility agent

Kiểm tra:

```text
modality          ✓
task              ✓
input format      ✓
output labels     ✓
metric            ✓
```

### Counterevidence agent

Tìm một paper cho thấy Model A gặp vấn đề trong domain giống Dataset Z.

Lưu:

```text
counterevidence = P18
```

### Scientific-value agent

Nhận thấy Dataset Z thuộc domain khác X/Y.

Do đó contribution có thể không còn là:

> “Thử Model A trên Dataset Z.”

mà thành:

> “Đánh giá khả năng cross-domain generalization của Model A từ domain X/Y sang domain Z.”

Research question lúc này có ý nghĩa hơn rất nhiều.

---

# 40. MVP thực tế

Không nên triển khai tất cả ngay.

## MVP 1 — Graph Foundation

Implement:

```text
Paper
Model
Dataset
Task
Finding
Limitation
```

và:

```text
USES
EVALUATES_ON
ADDRESSES
REPORTS
HAS_LIMITATION
```

Pipeline:

```text
OpenAlex
→ abstract
→ structured extraction
→ entity resolution
→ graph
```

Deliverable:

> Có thể nhìn graph của một research topic.

---

## MVP 2 — Combination Engine

Chỉ implement:

```text
Model × Dataset × Task
```

Rule:

```text
Model supports Task
Dataset supports Task
BUT
Model not evaluated on Dataset
```

Output:

```text
Candidate combinations
```

Không gọi chúng là gap.

---

## MVP 3 — Validation

Thêm:

```text
novelty search
compatibility check
counterevidence search
```

Output:

```text
Validated Candidate
Rejected Candidate
Uncertain Candidate
```

Đây là bước biến prototype thành research tool có giá trị.

---

## MVP 4 — Research Idea Generation

Từ validated candidate:

```text
Research Question
Hypothesis
Contribution
Experiment Proposal
```

Human approve.

---

## MVP 5 — Advanced Graph Intelligence

Sau khi có đủ graph data mới xem xét:

```text
Graph embedding
Link prediction
Community detection
GNN
Temporal graph
Scientific trend prediction
```

Không nên bắt đầu ở đây.

---

# 41. MVP không cần Graph Neural Network

Điều này rất quan trọng đối với dev.

Bản đầu không cần:

```text
GNN
Graph Transformer
knowledge graph embedding
link prediction model
```

Chỉ cần:

```text
typed entities
+
typed relations
+
SQL/graph traversal
+
rules
+
retrieval
+
LLM validation
```

là đủ chứng minh concept.

Khi có hàng chục nghìn hoặc hàng trăm nghìn validated relationships mới có dữ liệu thích hợp để thử learned link prediction.

---

# 42. Evaluation

Không đánh giá hệ thống bằng “câu trả lời nghe hay”.

Phải chia metric.

## Extraction

```text
Entity Precision
Entity Recall
Relation Precision
Relation Recall
```

## Retrieval

```text
Paper Recall@K
Evidence Recall@K
MRR
```

## Graph

```text
Entity resolution accuracy
Edge evidence coverage
Unsupported edge rate
```

## Gap discovery

Quan trọng nhất:

```text
Existing-work false positive rate
```

Tức:

> Bao nhiêu candidate mà hệ thống gọi là mới nhưng thực tế đã có paper làm?

Metric này càng thấp càng tốt.

Ngoài ra:

```text
Candidate compatibility rate

Candidate scientific-value approval rate

Counterevidence retrieval rate

Human acceptance rate
```

---

# 43. Acceptance Criteria cho bản đầu

Một candidate chỉ được hiển thị là `VALIDATED_CANDIDATE` nếu:

```text
✓ Có ≥2 supporting evidence paths

✓ Mọi critical graph edge đều có provenance

✓ Model/Dataset/Task compatibility pass

✓ Novelty search đã chạy

✓ Không tìm thấy direct existing work
  hoặc existing-work confidence thấp hơn threshold

✓ Counterevidence search đã chạy

✓ Có scientific rationale

✓ Có research question

✓ Có explicit uncertainty
```

Không đạt thì:

```text
UNCERTAIN
```

chứ không ép thành research gap.

---

# 44. UI cần hiển thị gì

Trang candidate không nên chỉ hiển thị một đoạn text AI.

Nên cho researcher thấy:

```text
Candidate Research Opportunity

Model A
   │
   │ proposed evaluation
   ▼
Dataset Z
   │
   ▼
Task T
```

Bên dưới:

```text
Why was this suggested?

✓ Model A used for Task T
  P1, P2

✓ Dataset Z supports Task T
  P7, P9

? Model A + Dataset Z
  no direct evidence found
```

Sau đó:

```text
Supporting Evidence

Counterevidence

Existing-work Search

Compatibility

Scientific Rationale

Proposed RQ

Proposed Experiment
```

Đây là **evidence trail (dòng truy vết bằng chứng)**.

Researcher phải có khả năng click từ:

```text
Candidate
→ relationship
→ paper
→ exact evidence
```

---

# 45. Nguyên tắc thiết kế cuối cùng

Hệ thống không được hoạt động theo:

```text
LLM:
"Em nghĩ đây là gap."
```

Mà phải hoạt động theo:

```text
Graph:
"Tôi phát hiện relationship này chưa xuất hiện."

Retriever:
"Tôi đã tìm literature liên quan."

Validator:
"Tôi chưa tìm thấy nghiên cứu trực tiếp."

Compatibility:
"Tổ hợp này technically compatible."

Counterevidence:
"Tôi tìm thấy các bằng chứng sau chống lại nó."

Reasoner:
"Nếu nghiên cứu, contribution có thể là..."

Human:
"Approve / Reject."
```

Đây là điểm khác biệt giữa một chatbot research thông thường và một **Research Discovery Agent có khả năng kiểm chứng**.

---

# 46. Kiến trúc mục tiêu cuối

```text
                        RESEARCHER
                            │
                            ▼
                     Research Question
                            │
                            ▼
                   Literature Retrieval
                            │
             ┌──────────────┼───────────────┐
             ▼              ▼               ▼
          OpenAlex       Embedding       Full Text
             │              │               │
             └──────────────┼───────────────┘
                            ▼
                  Structured Extraction
                            │
                            ▼
                 Scientific Knowledge Graph
                            │
               ┌────────────┼─────────────┐
               ▼            ▼             ▼
             Model       Dataset        Task
               │            │             │
               ├────────────┼─────────────┤
               │            │             │
               ▼            ▼             ▼
             Method       Finding      Limitation
               │            │             │
               └────────────┼─────────────┘
                            ▼
                 Combination Engine
                            │
                            ▼
                  Candidate Relations
                            │
                            ▼
                   Validation Pipeline
                ┌───────────┼────────────┐
                ▼           ▼            ▼
             Novelty    Compatibility Counterevidence
                │           │            │
                └───────────┼────────────┘
                            ▼
                    Scientific Value
                            │
                            ▼
                 Validated Opportunity
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
       Research Question Hypothesis   Experiment Plan
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                       HUMAN REVIEW
                            │
                            ▼
                    Research Direction
```

---

# 47. Kết luận

Giá trị cốt lõi của hệ thống không nên được định nghĩa là:

> “AI đọc paper và tìm research gap.”

Nên định nghĩa chính xác hơn:

> **Hệ thống xây dựng một biểu diễn có cấu trúc của landscape nghiên cứu, phát hiện những quan hệ hoặc tổ hợp khoa học chưa được quan sát trong corpus, chủ động tìm bằng chứng xác nhận và phản bác, đánh giá tính tương thích và giá trị khoa học, sau đó đề xuất các research opportunity có thể truy vết về literature gốc.**

Công thức tổng thể:

```text
Literature
    ↓
Evidence
    ↓
Structured Scientific Knowledge
    ↓
Graph
    ↓
Recombination
    ↓
Candidate
    ↓
Falsification
    ↓
Validation
    ↓
Research Opportunity
    ↓
Human Decision
```

Ba nguyên tắc phải giữ xuyên suốt dự án:

```text
1. Missing edge ≠ Research gap

2. Every important graph fact must have evidence provenance

3. AI proposes; evidence + researcher validate
```

Nếu giữ đúng ba nguyên tắc này, Scientific Recombination Graph có thể trở thành lớp discovery quan trọng nhất của Research Agent, thay vì chỉ là một GraphRAG bổ sung cho chatbot.
