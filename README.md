# Incident Agent

Incident Agent is a durable, human-governed incident-analysis service built on
FastAPI, LangGraph and MySQL. It accepts signed alerts, collects bounded
evidence, ranks causal hypotheses, pauses for human review, creates a
postmortem draft and requires a second approval before any external
publication can be attempted.

The repository includes a production-shaped local topology: one migration
process, one API process and two independent workers sharing a MySQL-backed
queue and LangGraph checkpointer.

> **Current status:** the core is hardened and extensively tested for local
> multi-process execution, retries, crash recovery, schema migration,
> backup/restore and publication idempotency. The included Compose stack uses
> synthetic data, disabled external connectors, no hosted LLM and
> `PUBLISH_EXTERNAL=false`. It is safe for local evaluation; it is not by
> itself evidence that an external environment is production-ready.

## Fastest start

Prerequisites: Docker Engine/Desktop with Compose v2, 4 GB available memory and
host ports `8000`, `3307`, `9101` and `9102` free.

```bash
docker compose up --build --wait
docker compose --profile tools run --rm --no-deps verify
```

Then open:

- review UI: `http://127.0.0.1:8000/`
- API contract: `http://127.0.0.1:8000/docs`
- readiness: `http://127.0.0.1:8000/readyz`
- API metrics: `http://127.0.0.1:8000/metrics`
- worker metrics: `http://127.0.0.1:9101/metrics` and `:9102/metrics`

Local review credentials are `incident-reviewer` / `local-review-only`. They
are deliberately non-secret and must never be reused outside local Compose.

The complete preflight, expected output, failure drills and reset procedure are
in the [`Docker Compose runbook`](docs/operations/LOCAL_DOCKER_COMPOSE.md).

## What starts locally

```text
signed synthetic alert
        |
        v
 API :8000  ---> MySQL :3306 (host inspection :3307)
        |          | durable event + queue transaction
        |          | revisions + checkpoints + review state
        |          |
        |       +--+----------------+
        |       |                   |
        |   worker-1 :9100      worker-2 :9100
        |       |                   |
        +-------+----- LangGraph ---+
                        |
                 human review UI
                        |
                 local HTML draft
                 external publish OFF
```

The `migrator` service runs first under a DDL-capable identity and exits. API
and worker users only receive data-plane grants. The API becomes ready only
after the current migration exists, MySQL and the queue respond, and at least
two current worker heartbeats are visible.

## Why the system exists

Operational alerts are noisy, incomplete and frequently misleading. This
system converts them into a reviewable evidence trail without allowing an LLM
or an untrusted webhook to become an autonomous operator. Its design goals are:

- preserve every accepted event and its provenance;
- acknowledge only after event and work are durably committed together;
- bound source queries, model calls, token use, cost and incident scope;
- distinguish observations, hypotheses, contradictions and unknowns;
- make human decisions explicit, version-bound and auditable;
- recover work after process loss without duplicating durable analysis effects;
- default to abstention and local drafts when evidence or dependencies fail;
- prohibit automatic remediation.

## End-to-end lifecycle

1. **Authenticate and constrain intake.** The API bounds request size and
   batch width, validates JSON and the alert contract, enforces caller/global
   rate limits, checks HMAC authentication and rejects tenant mismatches.
   Shadow/production signatures include timestamp and nonce replay protection.

2. **Normalize and redact.** Alertmanager/Grafana-shaped alerts and supported
   CloudWatch EventBridge events become a canonical incident alert. Untrusted
   fields are size-bounded and secrets/PII are redacted before durable state,
   prompts, logs and reports.

3. **Commit event and job atomically.** MySQL stores the incident event,
   idempotency digest and queue row in one transaction. An identical delivery
   returns `duplicate_event`; it does not create another job.

4. **Lease work.** Independent workers use transactional claims, renewable
   leases, worker heartbeats and an incident lock. A crashed worker's expired
   lease can be reclaimed. Retry exhaustion creates a dead letter instead of
   silently dropping work.

5. **Run the checkpointed graph.** LangGraph state is stored directly in MySQL
   with immutable checkpoint/write conflict checks, so another process can
   continue the same thread. The graph plans collection, gathers bounded logs,
   metrics and deployment evidence, normalizes data, extracts features,
   correlates signals and scores hypotheses.

6. **Interpret cautiously.** Deterministic correlation remains primary.
   Optional semantic/model stages receive bounded, redacted context and are
   charged against per-incident call, token, cost and deadline budgets. Source
   or model failure can produce an explicit abstention rather than invented
   evidence.

7. **Pause for analysis review.** The reviewer sees evidence, contradictions,
   ranked hypotheses and uncertainty. Approve, reject or request more evidence
   is tied to the current pending revision; stale browser decisions fail.

8. **Create a postmortem draft.** Approval continues RCA and drafting. Drafts
   are versioned and local by default.

9. **Pause for publication review.** A second decision is bound to the exact
   draft version and SHA-256 digest. The first review never implicitly approves
   external publication.

10. **Guard any external effect.** Before a publisher call, MySQL records a
    unique publication attempt. Completed attempts deduplicate. If provider
    acknowledgement is uncertain after a crash, automatic retry is blocked for
    operator reconciliation.

The full graph is available as [`SYSTEM_FLOW.svg`](docs/architecture/SYSTEM_FLOW.svg),
and record-level invariants are in
[`CANONICAL_SCHEMAS.md`](docs/architecture/CANONICAL_SCHEMAS.md).

## Delivery and consistency semantics

| Boundary | Guarantee |
| --- | --- |
| Webhook redelivery | Content-based idempotency; identical accepted event is not re-enqueued |
| Event to queue | Event row and job row commit atomically |
| Queue execution | At-least-once after lease expiry/reclaim |
| Analysis revision | Job-id idempotency prevents duplicate durable revision effects |
| Checkpoint write | Database-direct, multi-process-safe keys with immutable conflict checks |
| Human decision | Bound to the current pending revision and reviewer identity |
| Publication approval | Bound to exact draft version and SHA-256 |
| Aggregate publication | Durable at-most-once attempt guard; uncertainty blocks automatic retry |

“Exactly once” is not claimed for arbitrary external providers. Provider-side
idempotency and reconciliation remain destination-specific operational work.

## Main components

| Path | Responsibility |
| --- | --- |
| `webhook/` | FastAPI routes, auth, intake, durable incident store, queue, lifecycle and worker runtime |
| `graph/` | LangGraph state, workflow, nodes, routing and MySQL checkpointer |
| `clients/` | Loki, Prometheus, CloudWatch, GitHub, Slack and model adapters |
| `utils/` | Redaction, evidence, correlation, budgets, audit, MySQL pooling and observability |
| `prompts/` | Versioned interpretation, semantic correlation, RCA and postmortem prompts |
| `rules/` | Deterministic detection rules with safe checks |
| `config/` | Service catalog, source schemas, suppressions, dashboards, alerts and environment examples |
| `evaluation/` | Public/synthetic dataset loaders, scoring and reports |
| `fixtures/` | Safe local alert and benchmark fixtures |
| `scripts/` | Entrypoints, migrations, quality gates, evaluations and recovery drills |
| `tests/` | Unit, contract, security, integration, MySQL and multi-process tests |
| `docker/` | Local database bootstrap used by Compose |
| `docs/` | Architecture, contracts, operations, development decisions and historical reports |

The code deliberately remains in explicit top-level Python packages. Moving it
under `src/` would not improve runtime isolation and would create unnecessary
import/deployment churn; documentation and operational artifacts are grouped
instead of mixed into root.

## Repository root

Only high-signal entrypoints and deployment files live at root:

- `README.md` — this overview;
- `compose.yaml` and `Dockerfile` — local topology and immutable runtime image;
- `app.py`, `settings.py`, `langgraph.json` — application entry/configuration;
- `pyproject.toml` and `requirements*.{txt,in,lock}` — tooling and locked dependencies;
- `railway*.toml` — existing shared-development deployment definitions;
- `.env.example` — native local configuration reference.

Generated reports, local databases, caches, `.env` and runtime state are
ignored by Git.

Compose mounts `/app/output` as the only persistent writable application path.
It contains generated HTML and the bounded local SQLite raw-log cache needed by
cross-process graph continuation. Durable events, canonical evidence, queue,
reviews and checkpoints remain in MySQL. Production retention/object-storage
policy for raw source data is an explicit deployment decision.

## Docker Compose operation

### Start and verify

```bash
docker compose config --quiet
docker compose up --build --wait
docker compose --profile tools run --rm --no-deps verify
docker compose ps
```

The E2E verifier requires two workers, sends a signed synthetic alert, retries
the same body, proves deduplication, waits for completion and verifies a durable
analysis revision.

### Follow logs

```bash
docker compose logs --follow --tail=200 api worker-1 worker-2 mysql
```

### Preserve or erase state

```bash
docker compose down
```

The command above preserves named volumes. This permanently erases local
Compose state and should only be used for disposable data:

```bash
docker compose down --volumes
```

See the [`local runbook`](docs/operations/LOCAL_DOCKER_COMPOSE.md) before
performing kill/recovery tests.

## Native local development

Docker Compose is the preferred shareable path. For debugger access or focused
tests, use Python 3.11 and MySQL 8.4 directly:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.1.2 setuptools==84.0.0
.venv/bin/python -m pip install --require-hashes -r requirements.lock
cp .env.example .env
```

Phoenix is optional and intentionally excluded from the server image because a
transitive package is not published for every Linux target. To use
`scripts/start_phoenix.py` on a supported developer workstation, install its
extra dependencies separately:

```bash
.venv/bin/python -m pip install -r requirements-observability.txt
```

Create the configured MySQL database, then apply migrations under the migrator
role:

```bash
PROCESS_ROLE=migrator RUNTIME_SCHEMA_DDL_ENABLED=false \
  .venv/bin/python scripts/migrate_database.py apply
```

Start the same separated topology without Docker:

```bash
.venv/bin/python scripts/start_local_cluster.py --workers 2
```

Or start components in separate terminals with
`scripts/start_api.py` and `scripts/run_worker.py`. When workers are separate,
set `API_DRAIN_JOBS=false` for every process. More details are in
[`SETUP_GUIDE.md`](docs/operations/SETUP_GUIDE.md).

## HTTP surface

The running service publishes its exact OpenAPI schema at `/openapi.json` and
interactive docs at `/docs`. Important routes are:

| Method and path | Purpose |
| --- | --- |
| `POST /v1/alerts` | Signed alert intake; `/alerts` is a compatibility alias |
| `GET /` | Pending-review dashboard |
| `GET /incidents/{thread_id}` | Current review screen |
| `POST /alerts/{thread_id}/review` | Analysis decision or request for more evidence |
| `POST /alerts/{thread_id}/publish` | Exact-draft publication decision |
| `POST /v1/incidents/{thread_id}/reprocess` | Enqueue a new analysis run |
| `POST /v1/dead-letters/{job_id}/replay` | Controlled dead-letter replay |
| `GET /alerts/{thread_id}/review/status` | Pending review status |
| `GET /v1/canary/jobs/{job_id}` | Authenticated synthetic-canary status |
| `GET /healthz` | Process liveness only |
| `GET /readyz` | Runtime configuration, DB, queue and worker readiness |
| `GET /metrics` | Prometheus-format API/runtime metrics |

Do not treat `/healthz` as permission to route traffic. `/readyz` is the
deployment gate.

## Configuration model

Configuration is loaded from environment variables through `settings.py`.
`.env.example` documents the complete native-local surface; secure environment
baselines are in `config/shadow.env.example`.

Important groups:

| Group | Key examples | Safety rule |
| --- | --- | --- |
| Runtime | `ENVIRONMENT`, `PROCESS_ROLE`, `SERVICE_VERSION` | Secure modes fail closed on unsupported combinations |
| Database | `MYSQL_*`, `CHECKPOINTER`, `RUNTIME_SCHEMA_DDL_ENABLED` | API/worker roles have no DDL; migrator is separate |
| Queue | `JOB_LEASE_SECONDS`, `MIN_ACTIVE_WORKERS`, `MAX_PENDING_JOBS` | Heartbeat and lease timings are validated |
| Intake | `WEBHOOK_SHARED_SECRET`, size/rate limits, tenant/environment allowlists | Reject before analysis when contract fails |
| Sources | `LOG_SOURCE`, `METRIC_SOURCE`, connector URLs and limits | Source selection comes from deployment config, never alert fields |
| Model | provider/model, retry, deadline, token and cost limits | Secure modes forbid missing hosted credentials or `SKIP_LLM=true` |
| Review | basic local values or `OIDC_*`, CSRF/session secrets and role sets | Shadow/production require OIDC and explicit roles |
| Publishing | `PUBLISH_EXTERNAL` | Default false; approval and durable attempt guard still required |
| Observability | OTLP/Phoenix, metrics token, version labels | Prompt/state content is hidden by default in traces |

`ENVIRONMENT=shadow` and `production` invoke strict startup validation for
managed secrets, HTTPS URLs, OIDC, TLS-verified MySQL, tenant isolation,
explicit CORS/egress, current migrations, dedicated roles and worker topology.

## Security boundaries

All of the following are treated as untrusted: webhook payloads, connector
responses, model output, reviewer feedback and future publisher responses.
Controls include:

- HMAC authentication, timestamp/nonce replay defense and constant-time checks;
- body, batch, field, query, retry, token, cost and queue limits;
- service/environment/tenant allowlists;
- recursive secret and PII redaction before persistence or model use;
- output escaping and explicit untrusted-data wrappers;
- deployment-owned connector selection and egress allowlists;
- separate local/basic and secure/OIDC review modes with CSRF/session controls;
- append-only events, audit records and version-bound decisions;
- non-root, read-only application containers;
- external publication off by default and no automatic remediation.

The threat model and remaining environment controls are documented in
[`SECURITY_AND_OPERATIONS.md`](docs/operations/SECURITY_AND_OPERATIONS.md).

## MySQL, migrations and recovery

MySQL is the system of record for accepted events, queue state, incident and
analysis revisions, canonical evidence, reviews, postmortem drafts, lifecycle,
dead letters, worker heartbeats, publication attempts, audit records and
LangGraph checkpoints.

Current migrations are versioned in `scripts/migrate_database.py`. They execute
under a named advisory lock and record completion in `schema_migrations`:

```bash
PROCESS_ROLE=migrator RUNTIME_SCHEMA_DDL_ENABLED=false \
  python scripts/migrate_database.py apply
PROCESS_ROLE=migrator RUNTIME_SCHEMA_DDL_ENABLED=false \
  python scripts/migrate_database.py check
```

Runtime schema creation must remain disabled for API and workers. Additive
migrations support code-first rollback: stop intake, restore the previous
application version, leave compatible columns in place and verify readiness.
Destructive schema rollback requires a tested restore point.

Recovery tools include:

```bash
python scripts/verify_distributed_runtime.py --jobs 64 --workers 4
python scripts/run_resilience_soak.py --cycles 5 --jobs-per-cycle 50 --workers 4
python scripts/check_pitr_readiness.py --minimum-retention-seconds 86400
python scripts/verify_backup_restore.py
```

The backup verifier restores into a new isolated database and checks both an
incident event and a checkpoint. It never overwrites the source database. See
[`OPERATOR_RUNBOOKS.md`](docs/operations/OPERATOR_RUNBOOKS.md).

## Observability and operations

The API and workers emit structured events and Prometheus-format metrics for
intake outcomes, queue depth, active/stale workers, lease/retry/dead-letter
state, MySQL pool use, connector/model failures, latency, budgets and
publication status. Version labels connect evidence to the application,
analysis-code and prompt releases.

Repository artifacts include:

- `config/incident_agent_dashboard.json` — dashboard baseline;
- `config/incident_agent_alerts.yml` — alert rules;
- `config/recording_rules.example.yml` — derived metric examples;
- `scripts/production_preflight.py` — combined secure-config/schema/PITR/HA gate;
- `docs/operations/RELEASE_EVIDENCE.md` — immutable release evidence template.

## Tests and quality gate

Install development tools from the locked requirements, then run:

```bash
.venv/bin/python scripts/quality_gate.py
```

The gate performs:

- value-suppressing repository secret scanning;
- local Markdown link validation;
- Compose topology/safety validation;
- Ruff, scoped mypy and Python compilation;
- prompt-budget checks;
- the complete MySQL-backed test suite with branch coverage;
- whole-repository, core-path and security-path coverage thresholds.

CI additionally runs four-worker process/SIGKILL tests, repeated resilience
soak, isolated backup/restore, deploy artifact validation, dependency audit,
SBOM generation, scheduled dependency-security evidence and a real Compose
build/start/two-worker E2E canary. GitHub-hosted Code Scanning is deliberately
not used while this private repository does not have GitHub Advanced Security.

Focused commands:

```bash
.venv/bin/ruff check .
.venv/bin/python -m unittest discover -s tests
.venv/bin/python scripts/check_markdown_links.py
.venv/bin/python scripts/validate_compose_config.py
.venv/bin/python scripts/validate_deploy_artifacts.py
```

## Evaluation data

The repository includes synthetic scenarios and the public LogHub 2.0 sample
datasets with provenance files. Evaluations cover grouping, evidence quality,
impact assessment, deterministic generalization and bounded model behavior.
Generated outputs remain under ignored `output/`; dated reviewed evidence is
kept under `docs/reports/`.

Public benchmark success does not prove target-environment performance. Before
external use, run harmless incidents from every actual alert and evidence
source and compare results with operator truth.

## Production boundary

Code-level multi-process and recovery foundations do not replace environment
work. Before opening external ingress:

- provision managed MySQL with encrypted storage, verified TLS, separate
  migrator/API/worker users, backups and tested point-in-time recovery;
- place webhook, model, OIDC, connector, metrics and publication credentials in
  an approved secret manager;
- run separate API and at least two worker instances across failure domains;
- configure HTTPS, DNS, WAF/rate limiting and provider signature/retry behavior;
- configure OIDC roles, tenant isolation, explicit CORS and outbound egress;
- connect real read-only evidence sources and validate their query/retention
  contracts;
- keep `PUBLISH_EXTERNAL=false` through shadow approval;
- alert on queue depth, expired leases, dead letters, stale workers, MySQL/PITR,
  source/model failures and model cost;
- assign owners for migrations, release approval, dead-letter replay, secret
  rotation, publication reconciliation and incident response;
- run `scripts/production_preflight.py` and attach release evidence.

The authoritative checklist is
[`PRODUCTION_READINESS.md`](docs/operations/PRODUCTION_READINESS.md). It is the
source of truth over informal “production ready” claims.

## Documentation map

Start with [`docs/README.md`](docs/README.md). The main sections are:

- `docs/architecture/` — topology, data model, memory and ADRs;
- `docs/contracts/` — input, API, connector, evidence, hypothesis and review contracts;
- `docs/operations/` — Compose, setup, runbooks, security and readiness;
- `docs/development/` — project compass, tests, governance and deferred work;
- `docs/reports/` — dated evaluation and readiness evidence.

Historical reports explain what was proven at a point in time. Current code,
contracts and production-readiness criteria take precedence.

## Safe defaults and explicit non-goals

- No automatic remediation is implemented.
- Local Compose does not call real telemetry, GitHub, Slack or a hosted model.
- External publication is disabled by default.
- Model confidence is ranking evidence, never proof of causality.
- A healthy API process is not the same as a ready incident system.
- Local credentials, unverified MySQL transport and fixture evidence must not be
  promoted into shadow or production.

That boundary is intentional: the agent assists incident responders while
durability, authorization and final decisions remain explicit system controls.
