# Plan

## Goal

One person on one machine runs a Day-2 SRE demo: a scripted fault hits a small shop backend, Prometheus pages an agent, the agent investigates with read-only observability and GitLab tools, posts a Teams card, and waits for a human before any write. The same path runs without a GPU.

## MVP

In:

- `docker compose --profile mock up` brings up Grafana LGTM, Alertmanager, three instrumented FastAPI services, a load generator, a mock LLM, a mock Teams receiver, a mock GitLab, and the agent UI.
- Three reversible faults via `POST /admin/failmode`: catalog 5xx (bad deploy), a memory leak in catalog, and checkout dependency latency. Each has an inject script and a reset script.
- The agent is a LangGraph state machine: triage, investigate, cited hypothesis, runbook step, `interrupt()` for approval, execute, verify, timeline and postmortem.
- Read-only tools: PromQL, LogQL, TraceQL, GitLab read, `get_runbook`. Write tools (`gitlab_open_revert_mr`, `set_failmode`) run only after an approval record.
- NeMo Guardrails (OpenAI engine, `base_url` pointed at vLLM or the mock): input self-check, sensitive-data masking, output self-check, and an execution rail (tool allowlist, writes blocked without approval). Default is read-only.
- Teams Adaptive Card via an incoming webhook, with Approve/Reject as `Action.OpenUrl` to the agent. `TEAMS_WEBHOOK_URL` swaps in a real Workflows URL. The mock receiver renders the card.
- A web page shows incidents, the timeline, evidence, approval, and live KPIs (time to first hypothesis, time to root cause, evidence count, writes blocked).
- Runbooks as YAML with a Markdown body and `approval_required` per step.
- GitLab CE is a compose profile. The mock speaks the same REST shape. A seed script creates the private project and the bad-deploy commit, tag, and deployment. Read and write tokens are separate. Deployment and pipeline webhooks land on the incident timeline.
- vLLM is a GPU compose profile (Qwen3-14B-AWQ, 7B fallback, hermes tool parser, context 8192). The mock LLM is the default.
- `uv run pytest` for runbook matching, unapproved writes, the Teams card, the GitLab client, and a scenario-1 run against the mock LLM.

Out:

- A second user, accounts, or a hosted control plane.
- A real Bot Framework bot, Grafana MCP, and the OpenTelemetry Demo as the target. Those are the roadmap.
- Training or fine-tuning a model.
- Production multi-cluster topology, paging rotations, or a durable incident database. State lives in the agent process.

## Tasks

1. Write this plan.
2. Add the uv project, compose file, and env example. Profiles: `mock` (default), `gitlab`, `gpu`.
3. Instrument gateway, catalog, and checkout. Ship traces and logs over OTLP, scrape `demo_*` metrics, and expose `/admin/failmode`.
4. Add Alertmanager rules, a Grafana dashboard, the load generator, and the three scenario scripts.
5. Add the mock GitLab (and the CE profile plus seed script), the mock Teams receiver, and the mock LLM.
6. Build the LangGraph agent, runbooks, guardrails, Teams cards, and the incident UI.
7. Cover the critical paths with pytest. Run scenario 1 on the mock stack.

## Stack

- Python 3.12 and uv: the owner asked for uv, not Bun. Same override as the image-alignment demo.
- FastAPI: the shop services, the agent API, and the mock adapters are one dependency.
- OpenTelemetry SDK: traces, logs, and span status on the shop services, exported to `grafana/otel-lgtm`.
- `prometheus-client`: stable `demo_*` series for alert rules. The LGTM image still ingests OTLP metrics.
- LangGraph: the state machine and `interrupt()` for human approval.
- NeMo Guardrails: input, output, and tool rails against an OpenAI-compatible base URL.
- Grafana `otel-lgtm` and Alertmanager: one prebuilt observability backend plus the webhook the agent already accepts.
- GitLab CE and vLLM images: official containers, behind compose profiles so the mock path stays light.
- pytest: critical logic only. No UI snapshots.

## Deferred

- Microsoft Bot Framework with real Adaptive Card actions.
- Grafana MCP instead of hand-written PromQL, LogQL, and TraceQL clients.
- The OpenTelemetry Demo as the target system.
- A git hook. `uv run pytest` is one command.

## PostgreSQL monitoring

### Goal

Catalog and checkout talk to a real PostgreSQL 16. The agent can see locks, connection pressure, and slow statements, and it still waits for a person before it terminates a backend or builds an index.

### In

- Shop database, separate from GitLab CE, with `pg_stat_statements`, `track_io_timing`, seed data, and psycopg 3 pools.
- postgres_exporter scraped by Prometheus, plus alerts for saturation, lock waits, deadlocks, and slow statements. The original Day-2 alerts stay.
- A provisioned PostgreSQL Grafana dashboard linked from the Day-2 dashboard, and OpenTelemetry database spans on the service traces.
- Read tools `pg_activity` and `pg_top_statements` on a `pg_monitor` role. `pg_terminate_backend`, `pg_cancel_query`, and `pg_create_index` are writes. SQL literals are masked before the model sees them.
- Scenario 3 is a real Postgres scan. Added scenarios: row-lock contention, connection saturation, and a missing index whose runbook proposes `CREATE INDEX CONCURRENTLY`. The mock LLM can run them.

### Out

- A replica. Replication-lag series are exported and stay at zero on this primary.
- Using or changing GitLab CE's embedded database.
- Killing sessions or creating indexes without an approval record.
