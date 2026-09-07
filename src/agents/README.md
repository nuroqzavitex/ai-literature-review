# Agent package boundaries

Each top-level package owns one product capability. Keep reusable technical
adapters such as LLM clients, authentication, search, ingestion, logging and
vector storage in `src/services`.

- `litreview`: review state, prompts, workflow, application orchestration and
  review-owned persistence.
- `research_gap`: gap-domain contracts, the independent graph and its job
  orchestration.
- `research_sandbox`: core-side application and infrastructure adapters for the
  separately deployed sandbox service.
- `document_review`: bounded document-review application logic.

Dependencies should point inward: routers call application services;
application services coordinate domain/workflow code and infrastructure;
domain modules do not import routers or infrastructure.
