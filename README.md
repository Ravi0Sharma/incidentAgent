# Incident Agent

Incident Agent turns an alert into a reviewable, evidence-backed incident
analysis. It ranks possible explanations, shows uncertainty and waits for a
human decision. It does not remediate systems or publish reports by itself.

**Current status:** verified for local synthetic use, including an explicit
OpenAI test mode. It is not approved for production traffic.

## How the reported results were obtained

This project does not train or fine-tune a model. It evaluates the complete
analysis pipeline:

1. Start with synthetic fixtures or public raw logs.
2. Normalize and redact the data without access to the expected answer.
3. Build evidence and candidate explanations using deterministic contracts.
4. Optionally ask the model to interpret only the bounded evidence pack.
5. Validate citations, claims and output structure.
6. Freeze the analysis.
7. Join the held-out labels only after the output is frozen.
8. Score grouping, grounding, supported answers and safe abstention.

Labels and fault metadata are never inserted into alerts, rules, prompts or
model requests. A weak result becomes a regression test or a general contract
improvement; dataset-specific answers are not added as hidden rules.

### Evidence used

| Evidence | Purpose |
| --- | --- |
| Synthetic fixtures | Verify alert contracts, safety behavior and known pipeline branches |
| Public HDFS, Hadoop, BGL, OpenStack and Spark data | Test normalization, grouping, signal retention and evidence grounding |
| Held-out labels | Score the already-frozen output; never guide the analysis |
| Bounded live OpenAI runs | Verify provider transport, structured output, grounding and abstention |
| Synthetic high-volume run | Verify admission, bucketing, queueing and model-budget fallback |
| Process-loss and recovery tests | Verify leases, checkpoints and idempotent durable revisions |

### Current checked results

| Check | Result | What it measures |
| --- | --- | --- |
| Engineering gate | 345 tests; 75.4% repository, 82.2% core and 95.9% security branch coverage | Code and local runtime behavior |
| HDFS 2k grouping | 100% pair precision; 96.60% recall; 14/14 templates retained | Log grouping on one public corpus |
| HDFS v3/TraceBench grouping | 100% pair precision; 98.83% recall; 75/75 labels retained | Grouping on a second corpus |
| Curated BGL/OpenStack pair gate | 73/73 pairs; 100% precision, recall and specificity | Reviewed normalization contracts |
| Spark 2k grouping | 2,000/2,000 parsed; 100% precision; 98.91% recall; 99.45% F1 | Parsing and grouping, not root-cause accuracy |
| HDFS v1/OpenStack audit | 575,061 HDFS traces and 207,820 primary OpenStack events processed label-last | Signal retention and impact boundaries at larger public-data scale |
| Hadoop pre-review | 55/55 grounded; 0 unknown evidence IDs; 0 unsupported predictions; 98.18% exact result or honest abstention | Evidence and abstention boundary |
| Live model check | 22 successful bounded calls; 0 unknown evidence IDs or unsupported percentages | Model transport and grounded output on limited cases |
| Local admission load | 100,000 synthetic events; 12 revisions; 12 model calls; 0 dead letters | Bucketing, queueing and budget fallback |

Do not combine these checks into one “AI accuracy” number:

- Test coverage measures exercised code, not incident accuracy.
- Grouping precision and recall measure log normalization, not root cause.
- Grounding means claims cite known evidence; it does not prove causality.
- Hadoop's 98.18% includes honest abstention. Raw exact agreement was 32.73%
  because many supplied labels were absent from or conflicted with the
  recoverable evidence.
- The live-model result contains only 22 calls and is not provider-reliability
  or production-quality evidence.
- The 100,000-event run is synthetic local evidence, not a capacity, SLO or
  cost-calibration claim.

Full methods and limitations are in [Evaluation](docs/EVALUATION.md).

Reproduce the main checks:

```bash
.venv/bin/python scripts/quality_gate.py
.venv/bin/python scripts/evaluate_pre_review.py
.venv/bin/python scripts/evaluate_hadoop_typed_review.py --cases 55 \
  --output output/hadoop-typed-review-all-55.json
```

Generated JSON and HTML reports are written below the ignored `output/`
directory. Public datasets and generated derivatives are also ignored.

## How a result is produced

1. The API authenticates, validates, normalizes and redacts the alert.
2. MySQL commits the accepted event and its queue job together.
3. A worker collects bounded logs, metrics and deployment evidence.
4. Deterministic rules extract signals, contradictions and candidates.
5. Optional model stages interpret the bounded evidence and may abstain.
6. The exact evidence and analysis revision are stored for review.
7. Human approval continues to RCA and a local postmortem draft.
8. A separate decision is required for the exact draft before any publisher
   can be called.

![Incident Agent system flow](docs/architecture/SYSTEM_FLOW.svg)

The review page contains:

- the important evidence and timeline around the alert;
- ranked explanations with supporting and contradicting evidence;
- confidence, known gaps and an explicit abstention when required;
- the analysis revision and human review controls; and
- a versioned local postmortem draft after analysis approval.

The model receives only bounded, redacted evidence. It can interpret evidence
or abstain, but it cannot create evidence, approve a result, publish or take an
operational action.

### CloudWatch path

The project has an opt-in, read-only boto3 path for CloudWatch Logs Insights
and GetMetricData. Deployment-owned configuration selects the region, log
groups, namespaces and dimensions; alert content cannot choose them.

The public test suite uses sanitized AWS-shaped fake clients to verify queries,
polling, pagination, partial results, error mapping and provenance. It does not
contain credentials, private infrastructure names, raw telemetry or proof of a
completed call against a real AWS account. The standalone EventBridge alarm
translator is not yet wired into `/v1/alerts`.

See [CloudWatch integration](docs/operations/CLOUDWATCH.md) for the exact
boundary and safe setup.

## Key guarantees

| Boundary | Guarantee |
| --- | --- |
| Webhook redelivery | Content-based idempotency; an identical accepted event is not enqueued twice |
| Event to queue | The event row and job row commit in one MySQL transaction |
| Queue execution | Leased work is at-least-once and can be reclaimed after worker loss |
| Analysis revision | Job-key idempotency prevents duplicate durable revision effects |
| Graph checkpoint | Database-direct writes support continuation by another process and reject conflicting immutable writes |
| Human review | A decision is bound to the current pending analysis revision and reviewer identity |
| Publication review | Approval is bound to the exact draft version and SHA-256 digest |
| External publication | A durable at-most-once attempt guard blocks automatic retry after an uncertain provider acknowledgement |

MySQL is the system of record for accepted events, queue state, analysis
revisions, canonical evidence, reviews, drafts, lifecycle, dead letters,
worker heartbeats, publication attempts, audit records and LangGraph
checkpoints.

### High-volume incident bucketing

Matching alerts share a five-minute incident bucket. Every event is stored,
but each bucket keeps one pending analysis job and at most one follow-up while
analysis is running. This prevents an alert storm from becoming one model call
per event.

In the 100,000-event run, the system created 12 durable analysis revisions and
made 12 successful model calls. The per-incident model budget then blocked six
later calls and used deterministic fallback. No jobs entered the dead-letter
queue.

## Run locally

Requirements: Docker Engine or Docker Desktop with Compose v2, 4 GB free
memory, 5 GB free disk and free host ports `8000`, `3307`, `9101` and `9102`.

### Choose a mode

| Mode | Evidence and interpretation | External effects |
| --- | --- | --- |
| Default Compose | Synthetic fixtures and deterministic interpretation; no hosted model or real telemetry | Publishing off |
| OpenAI override | Synthetic fixtures plus bounded, redacted model requests | Publishing off |

### Default no-cost run

```bash
docker compose up --build --wait
docker compose --profile tools run --rm --no-deps verify
```

### Run with OpenAI

Put `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL` in the ignored
`.env` file, then run:

```bash
docker compose -f compose.yaml -f compose.openai.yaml up --build --wait
docker compose -f compose.yaml -f compose.openai.yaml --profile tools run --rm --no-deps verify
```

The OpenAI run sends only redacted synthetic evidence. External publication
remains disabled.

### What verification proves

The verifier does more than ping the API. It:

1. requires readiness to see two independent workers;
2. sends a signed synthetic `payments` alert;
3. sends the identical body again and requires `duplicate_event`;
4. waits for the durable job to finish;
5. requires one controlled processing attempt; and
6. requires at least one durable analysis revision.

Open <http://127.0.0.1:8000/> after verification. The local review credentials
are `incident-reviewer` / `local-review-only`. Approving the analysis creates a
postmortem draft and a separate publication review; it does not publish.

### Useful endpoints

| Endpoint | Purpose |
| --- | --- |
| <http://127.0.0.1:8000/> | Review UI |
| <http://127.0.0.1:8000/docs> | Interactive API contract |
| <http://127.0.0.1:8000/healthz> | API process liveness only |
| <http://127.0.0.1:8000/readyz> | Database, queue, migration and worker readiness |
| <http://127.0.0.1:8000/metrics> | API and runtime metrics |
| <http://127.0.0.1:9101/metrics> | Worker 1 metrics |
| <http://127.0.0.1:9102/metrics> | Worker 2 metrics |

Use `/readyz`, not `/healthz`, as the deployment gate.

Common local operations:

```bash
docker compose logs --follow --tail=200 api worker-1 worker-2 mysql
docker compose down
```

`docker compose down` preserves named volumes. `docker compose down --volumes`
permanently erases the local Compose state and should be used only for
disposable data.

For setup, recovery drills, stress tests and reset procedures, use the
[Docker Compose runbook](docs/operations/LOCAL_DOCKER_COMPOSE.md). For native
Python development, use the [setup guide](docs/operations/SETUP_GUIDE.md).

## Safety and failure behavior

All webhook fields, source responses, model output, reviewer feedback and
publisher responses are untrusted. Inputs and queries are size-bounded, and
secret/PII-like values are redacted before persistence, prompts, logs and
reports.

| Situation | System response |
| --- | --- |
| Invalid, oversized, unauthenticated or replayed alert | Reject before analysis |
| Identical accepted delivery | Return `duplicate_event`; do not create another job |
| Optional evidence source fails | Record the source gap and continue with lower confidence when safe |
| Model fails, times out or exceeds budget | Use a deterministic/degraded result or abstain; never bypass review |
| Evidence is missing, contradictory or materially tied | Return “No supported root cause yet” with gaps and the next safe evidence step |
| Worker crashes after leasing a job | Reclaim after lease expiry without duplicating the durable revision |
| Reviewer submits a stale revision | Reject the decision instead of applying it to newer evidence |
| Publisher acknowledgement is uncertain | Block automatic retry for operator reconciliation |

Core safety boundaries:

- Human approval is required.
- Automatic remediation is not implemented.
- External publishing is off by default.
- Connector selection comes from deployment configuration, not alert content.
- Evidence collection, retries, model calls, tokens, cost and deadlines are
  bounded per incident.
- Model confidence ranks evidence; it is not proof of causality.
- Local fixtures, credentials and evaluation results are not a
  production-readiness claim.

## Before connecting a target environment

Complete the [production-readiness checklist](docs/operations/PRODUCTION_READINESS.md).

## Main code

| Path | Purpose |
| --- | --- |
| `webhook/` | API, authentication, durable queue and review lifecycle |
| `graph/` | LangGraph workflow, state, nodes, routing and checkpoints |
| `clients/` | Loki, Prometheus, CloudWatch, GitHub and model adapters |
| `utils/`, `rules/` | Redaction, evidence, correlation, budgets and safety rules |
| `prompts/` | Versioned interpretation, RCA and postmortem prompts |
| `fixtures/`, `evaluation/` | Evaluation data loaders, held-out labels and scoring |
| `tests/`, `scripts/` | Tests, migrations, verification and operational tools |
| `config/` | Service catalogue, source schemas, dashboards and environment examples |
| `docs/` | Current architecture, contracts, operations and evaluation |

## Documentation

| Need | Start here |
| --- | --- |
| Architecture and trust boundaries | [Architecture](docs/architecture/ARCHITECTURE.md) |
| Full workflow | [System flow](docs/architecture/SYSTEM_FLOW.svg) |
| Evaluation method and results | [Evaluation](docs/EVALUATION.md) |
| CloudWatch boundary and setup | [CloudWatch integration](docs/operations/CLOUDWATCH.md) |
| API behavior | [OpenAPI contract](docs/contracts/OPENAPI_CONTRACT.md) |
| Evidence and hypothesis rules | [Evidence contract](docs/contracts/EVIDENCE_CONTRACT.md) and [hypothesis contract](docs/contracts/HYPOTHESIS_CONTRACT.md) |
| Local operation and recovery | [Docker Compose runbook](docs/operations/LOCAL_DOCKER_COMPOSE.md) and [operator runbooks](docs/operations/OPERATOR_RUNBOOKS.md) |
| Security boundary | [Security and operations](docs/operations/SECURITY_AND_OPERATIONS.md) |
| Human decisions and memory | [Memory and review contract](docs/contracts/MEMORY_AND_REVIEW_CONTRACT.md) |
| Production gate | [Production readiness](docs/operations/PRODUCTION_READINESS.md) |
| All documents | [Documentation index](docs/README.md) |
