# Architecture Diagram

> Sơ đồ rút gọn của hệ thống đang chạy. Chi tiết trách nhiệm và dữ liệu xem tại [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart TB
    User([Owner / Researcher / Reviewer]) --> FE[Next.js 16<br/>App Router + Clerk]
    FE -->|REST /api/v1| API[FastAPI<br/>port 8000]

    API --> PG[(PostgreSQL<br/>application data + checkpoints)]
    API --> Redis[(Redis Streams<br/>dispatch + status cache)]
    Redis --> Worker[Durable worker<br/>lease + heartbeat + fence]
    Worker --> PG
    Worker --> LR[LitReview StateGraph]
    Worker --> RG[ResearchGapGraph]

    LR --> Search[AcademicSearchService]
    RG --> Search
    Search --> OA[OpenAlex]
    Search --> SS[Semantic Scholar]
    Search --> AX[arXiv]

    LR --> LLM[Configured LLM providers]
    RG --> LLM
    LR --> Q[(Qdrant<br/>rebuildable semantic index)]
    API --> Sandbox[Research Sandbox]
```

| Layer | Công nghệ hiện tại |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript 5 |
| Backend | FastAPI, Python 3.12 theo project/CI |
| Workflow | LangGraph |
| Database | PostgreSQL |
| Queue/cache | Redis Streams và status cache; PostgreSQL vẫn authoritative |
| Vector retrieval | Qdrant |
| Academic sources | OpenAlex, Semantic Scholar, arXiv |
| Authentication | Clerk |

Không sử dụng ChromaDB hay SQLite trong runtime hiện tại.
