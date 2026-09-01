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
| Engineering gate | 352 tests; 75.4% repository, 82.2% core and 95.9% security branch coverage | Code and local runtime behavior |
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

The model receives only bounded, redacted evidence. It can interpret evidence
or abstain, but it cannot create evidence, approve a result, publish or take an
operational action.

### What the review UI shows

The UI is an operator view of one durable analysis revision, not a chatbot and
not a stream of hidden model reasoning. It is designed to answer three
questions quickly: what happened, what supports the current explanation and
what decision is safe now.

| Area | What the reviewer can inspect |
| --- | --- |
| Incident header | Status, incident ID, severity and its reason, primary service, owner and tier |
| Decision brief | Current anchor event, strongest log group, relevant deployment, metrics and known gaps |
| Timeline | A bounded chronological view around the alert, including the anchor event |
| Ranked hypotheses | Candidate explanations ordered by score, with confidence, role and status |
| Evidence for each candidate | Supporting and contradicting evidence IDs instead of an unsupported summary |
| Evidence coverage | Which claims are grounded, which sources contributed and which evidence is still missing |
| Data quality | Source success, partial results, unavailable sources and the resulting uncertainty |
| Semantic correlation | The bounded model-assisted interpretation and its tool trace when that stage ran |
| Verification | Concrete read-only checks that could confirm or reject the leading explanation |
| Revision history | Added, corrected and removed evidence compared with the previous revision |
| Technical detail | The exact evidence pack and bounded execution information needed for audit or debugging |
| Review controls | Approve one displayed hypothesis, reject the revision or request specific additional evidence |

The incident list is the starting point. It links to the latest analysis and
shows enough lifecycle state to distinguish work waiting for review from work
that is still processing, rejected or complete.

The detailed page intentionally keeps contradictory evidence beside supporting
evidence. A high score is not allowed to hide disagreement between logs,
metrics and deployments. Missing or failed sources remain visible rather than
being silently treated as a healthy signal.

#### Review decisions

| Decision or state | Result |
| --- | --- |
| Approve | Selects one candidate from the pending revision and continues to deeper RCA; it does not prove causality |
| Reject | Records the reviewer feedback and stops that approval path |
| Request more evidence | Requires concrete feedback and sends the investigation through another bounded evidence pass |
| Abstained analysis | Approval is disabled because there is no supported candidate to select |
| Stale browser revision | The API returns `409 stale_incident_revision`; the reviewer must inspect the newer revision |

Every decision targets the exact `pending_revision`. The database row is
locked while the decision is committed, so two browser sessions cannot approve
different candidates for the same revision. Reviewer identity, request ID,
displayed evidence and rationale are retained in the audit record.

Corrections never overwrite the old analysis. They create a new revision with
its predecessor, evidence membership, candidate snapshot, data-quality state
and code/prompt/model context. This makes the visible result reproducible and
lets the UI show what actually changed.

### Postmortem draft and publication gates

Analysis approval continues to a deeper, bounded RCA pass and creates a
versioned local postmortem draft. The draft uses exactly these sections:

1. Executive Summary
2. Impact
3. Root Cause
4. Timeline
5. Resolution
6. What went well
7. What went poorly
8. Where we got lucky
9. Lessons learned
10. Follow-up Actions

The writer is constrained to the reviewed context and supplied timestamps. It
must use blameless language, stay below 600 words and say `unknown` or `not
established` when the evidence does not support a claim. Selecting a hypothesis
does not permit the draft to invent impact, recovery steps, process failures,
missing controls or remediation work.

Follow-up actions must come from an explicit evidence gap and use
`[owner-team] action`. Provider failure falls back to a deterministic draft;
it never removes the review boundary.

There are two separate human gates:

1. **Analysis review** selects a candidate for deeper investigation.
2. **Publication review** approves one exact draft version and its SHA-256
   digest for one configured publisher.

Editing the draft changes the digest and invalidates the earlier publication
approval. With `PUBLISH_EXTERNAL=false`, approval still produces only the
local HTML draft. If a configured publisher returns an ambiguous
acknowledgement, the durable attempt is held for operator reconciliation rather
than retried automatically.

### Inspect the graph with Phoenix

[Arize Phoenix](https://github.com/Arize-ai/phoenix) is an optional local
observability UI for understanding how one incident moved through LangGraph.
It is a debugging aid, not an evidence source, audit database or approval
system.

Install the optional packages in a native development environment:

```bash
.venv/bin/pip install -r requirements-observability.txt
```

If the API, database and native environment are already configured, the helper
starts Phoenix and the web UI together:

```bash
.venv/bin/python scripts/start_incident_agent.py --no-llm
```

Remove `--no-llm` only when the ignored `.env` contains an approved model
configuration. The helper opens:

- incident review UI: <http://127.0.0.1:8000/>
- Phoenix traces: <http://127.0.0.1:6006/>

Phoenix can also run separately:

```bash
.venv/bin/python scripts/start_phoenix.py
PHOENIX_ENABLED=true .venv/bin/uvicorn webhook.api:app --host 127.0.0.1 --port 8000
```

The local helper stores Phoenix data under ignored `.phoenix_data/`. A custom
OTLP collector can be selected through deployment configuration, but that is a
separate security and egress decision.

#### What to inspect in Phoenix

| Trace view | Useful question |
| --- | --- |
| Graph span order | Which branches and review loops ran for this incident? |
| Duration by node | Was time spent collecting evidence, interpreting it or waiting on a provider? |
| Error status | Which node failed, and did the graph degrade safely or stop? |
| Parallel collection | Did logs, metrics and deployments finish before aggregation? |
| Nested OpenAI spans | Which bounded model stage called the provider, and how long did it take? |
| Reinvestigation loop | Did reviewer feedback cause a new evidence pass and revision? |
| Publication path | Did execution stop at the expected review gate before the publisher? |

`PHOENIX_COMPACT_TRACES=true` is the default. It hides graph-state content,
prompts and model output while retaining the trace structure needed for timing
and failure analysis. Set it to `false` only for approved, synthetic local
debugging:

```bash
PHOENIX_ENABLED=true PHOENIX_COMPACT_TRACES=false \
  .venv/bin/uvicorn webhook.api:app --host 127.0.0.1 --port 8000
```

Expanded traces can contain the same sensitive material as an incident input.
Do not enable them for production telemetry, shared collectors or unreviewed
data. Phoenix retention is not a substitute for the redacted MySQL audit
record.

The runtime also appends a small `execution_log` with node name and duration.
That is useful in tests and local reports; Phoenix adds the interactive parent,
child, timing and error view.

### Why every node has a control boundary

One large model call would make failures, source gaps and unsafe transitions
difficult to isolate. The graph separates deterministic work, provider calls
and human authority so each transition can be bounded, tested and audited.

| Stage | Main control | Failure it prevents or exposes |
| --- | --- | --- |
| Ingest and classify | Authentication, replay checks, schema limits, normalization and redaction | Untrusted or oversized input entering analysis |
| Durable admission | Event and queue job in one transaction, content idempotency | Accepted alerts disappearing or duplicate deliveries multiplying work |
| Collection plan | Deployment-owned source allowlists and incident budgets | Alert text selecting arbitrary infrastructure or unlimited queries |
| Logs, metrics, deploys | Parallel bounded reads with source-specific provenance | One slow source hiding which data is partial or unavailable |
| Normalize and aggregate | Deterministic parsing, stable grouping and size limits | Model-dependent evidence identities and unbounded raw context |
| Detection and features | Versioned rules over canonical evidence | Hidden dataset labels or unsupported facts entering candidates |
| Correlation | Explicit supporting and contradicting evidence links | A temporal coincidence being presented as causality |
| Severity reassessment | Evidence-backed reason retained with the revision | Silent severity changes after collection |
| Scope expansion | Allowlisted read-only tools, iteration and deadline budgets | Recursive investigation, uncontrolled cost or arbitrary tool use |
| Candidate scoring | Deterministic ranking before interpretation | A provider response becoming the only explanation source |
| Context and evidence pack | Token, item and byte limits plus untrusted-data wrapping | Prompt injection and unlimited context growth |
| Semantic interpretation | Structured output validation, citation checks and abstention | Fabricated evidence IDs or forced answers when support is weak |
| Human review | Exact revision binding and reviewer identity | A stale or unseen result continuing to RCA |
| Deep RCA and draft | Approved context only, claim checks and versioned drafts | Approval being mistaken for proof or a draft inventing facts |
| Publication review | Exact draft digest and explicit publisher selection | An edited or different report being published under old approval |
| Publisher | Off by default, durable attempt guard, no ambiguous retry | Duplicate external work items after uncertain acknowledgement |

### Incident-response skills

[`skills/`](skills/) contains reusable `SKILL.md` playbooks for incident
classification, investigation, coordination, security response and
postmortems. They have three concrete uses in this project:

- **LangGraph runtime:** selected rules are compiled into small,
  phase-specific policy profiles by [`utils/skill_cards.py`](utils/skill_cards.py)
  and applied during semantic correlation and incident interpretation.
- **Agent runtimes:** tools that support YAML-frontmatter skills can load an
  individual `SKILL.md` directly.
- **Operators and contributors:** each file is a standalone playbook that can
  be reviewed and adapted without reading the application code.

| Skill | Use |
| --- | --- |
| `severity-classification` | Apply and adapt a SEV-1 through SEV-5 classification rubric |
| `alerting-principles` | Design actionable alerts with useful context and urgency |
| `incident-runbook` | Coordinate roles and decisions during an active incident |
| `postmortem-writer` | Structure a concise, blameless postmortem |
| `security-incident` | Work through a security-specific response checklist |
| `anti-patterns` | Recognize common incident-management failure modes |
| `agent-incident-responder` | Apply human-in-the-loop, transparency and graceful-degradation principles |
| `caveman` | Produce terse operator communication at `lite`, `full` or `ultra` level |

The application intentionally uses compact policy profiles instead of placing
entire skill files in model context. This keeps the active instructions small
and testable while the full playbooks remain available for compatible agents
and human review. See the [skills index](skills/README.md) for loading
instructions and source attribution.

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

### Optional Jira MCP output

The approved postmortem can create a Jira work item through Atlassian Rovo
MCP. Put the service-account email, scoped API token, Atlassian site URL and
project key in the ignored `.env`; then use the opt-in Compose override:

```bash
docker compose -f compose.yaml -f compose.jira-mcp.yaml up --build --wait
```

The override enables Jira only. The Jira call happens after the separate
exact-draft publication approval, uses the fixed `createJiraIssue` MCP tool and
does not retry an uncertain write. See [Jira MCP output](docs/operations/JIRA_MCP.md)
for variables, least privilege and the exact verification boundary.

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
| `clients/` | Loki, Prometheus, CloudWatch, GitHub, Jira MCP and model adapters |
| `utils/`, `rules/` | Redaction, evidence, correlation, budgets and safety rules |
| `prompts/` | Versioned interpretation, RCA and postmortem prompts |
| `fixtures/`, `evaluation/` | Evaluation data loaders, held-out labels and scoring |
| `tests/`, `scripts/` | Tests, migrations, verification and operational tools |
| `config/` | Service catalogue, source schemas, dashboards and environment examples |
| `skills/` | Portable incident-response and communication playbooks; not runtime-loaded |
| `docs/` | Current architecture, contracts, operations and evaluation |

## Documentation

| Need | Start here |
| --- | --- |
| Architecture and trust boundaries | [Architecture](docs/architecture/ARCHITECTURE.md) |
| Full workflow | [System flow](docs/architecture/SYSTEM_FLOW.svg) |
| Evaluation method and results | [Evaluation](docs/EVALUATION.md) |
| CloudWatch boundary and setup | [CloudWatch integration](docs/operations/CLOUDWATCH.md) |
| Jira output setup | [Jira MCP output](docs/operations/JIRA_MCP.md) |
| Portable response playbooks | [Skills index](skills/README.md) |
| API behavior | [OpenAPI contract](docs/contracts/OPENAPI_CONTRACT.md) |
| Evidence and hypothesis rules | [Evidence contract](docs/contracts/EVIDENCE_CONTRACT.md) and [hypothesis contract](docs/contracts/HYPOTHESIS_CONTRACT.md) |
| Local operation and recovery | [Docker Compose runbook](docs/operations/LOCAL_DOCKER_COMPOSE.md) and [operator runbooks](docs/operations/OPERATOR_RUNBOOKS.md) |
| Security boundary | [Security and operations](docs/operations/SECURITY_AND_OPERATIONS.md) |
| Human decisions and memory | [Memory and review contract](docs/contracts/MEMORY_AND_REVIEW_CONTRACT.md) |
| Production gate | [Production readiness](docs/operations/PRODUCTION_READINESS.md) |
| All documents | [Documentation index](docs/README.md) |
