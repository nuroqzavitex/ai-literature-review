# Research-job worker runtime

Research jobs are durable PostgreSQL rows. The API only creates a `queued` row;
it never keeps the research graph in an HTTP background task. A worker claims
queued/resuming rows using the existing database row lock and lease, then runs
the LangGraph workflow.

Redis Streams is the dispatch transport: API writes append a durable event and
workers consume it through a consumer group. Pending events are reclaimed after
the worker lease timeout. PostgreSQL remains authoritative for job ownership,
worker ID, heartbeat, lease expiry, and an incrementing execution fence. Status
polling is cached briefly in Redis; Redis loss falls back to the worker's
database scan and a cache miss reads the latest database state.

## Local development

Use the default configuration:

```env
WORKER_MODE=embedded
RUNTIME_ROLE=api
```

Starting `uvicorn src.main:app` starts an in-process worker alongside the API.

## Docker / production

`docker compose up --build` starts two processes:

- `backend`: API only (`WORKER_MODE=external`, `RUNTIME_ROLE=api`)
- `worker`: `python -m src.worker_main`, which claims and executes jobs

Both must use the same PostgreSQL database. `WORKER_MAX_CONCURRENT_JOBS` limits
how many jobs one worker process claims at once; the existing per-project limit
of two active reviews remains enforced in PostgreSQL.

Docker Compose also starts Redis and enables it for API and worker. For an
external deployment set the same `REDIS_URL` and `REDIS_ENABLED=true` on both
roles.

To scale, add worker replicas only after using a distributed provider rate
limiter for shared API keys (especially Semantic Scholar's 1 RPS key limit).

## Observability contract

API, worker, search, ingestion, vector-store and LLM events are structured JSON
messages emitted through the normal Python logger. Every asynchronous job event
has `job_id`, `run_id`, and (when it originated from HTTP) `request_id`; worker
events also include `worker_id`. This makes it possible to trace a request from
the API through a durable queue and into a worker without logging the user
prompt or reviewer feedback.

The stable event families are:

- `http.*`, `worker.*`, and `job.*` for request and durable-job lifecycle;
- `llm.*` for provider attempts, retries, successes, and failover;
- `search.*`, `ingestion.*`, `retrieval.*`, and `vector_store.*` for external
  dependencies and graceful degradation;
- `agent.node_failed` for a terminal graph node.

Events include `failure_code` and `error_type`, not raw provider responses.
The logging helper redacts keys containing credentials and content-bearing
fields such as prompts, payloads, feedback, and errors; it also bounds lists
and long strings. Do not bypass it with a raw exception message in a structured
event.

Recommended alerts: any `job.failed`; sustained `llm.failed` or
`search.provider_failed`; `worker.jobs_reclaimed`; and an abnormal increase in
`*.fallback`. Build dashboards from event counts and the existing
`duration_ms`, `papers_found`, `warning_count`, and `indexed_chunks` fields.
