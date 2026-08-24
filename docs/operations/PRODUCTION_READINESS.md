# Incident Agent - Production Readiness Checklist

> This document turns the project purpose in `PROJECT.md` into testable delivery
> criteria. It is both a current-state audit and the Definition of Done (DoD)
> for production releases.

The concrete verification methods and pass/fail rules for areas 1-15 are in
[`TEST_STRATEGY.md`](../development/TEST_STRATEGY.md).
The deduplicated execution order and project-wide progress view are in
[`PROJECT_MASTER_CHECKLIST.md`](../development/PROJECT_MASTER_CHECKLIST.md). This file remains
the authoritative acceptance list.

## How To Use This Document

- `[x]` means the capability exists in the repository and was verified during
  the audit date below. It does **not** mean the whole surrounding area is
  production-ready.
- `[ ]` means missing, incomplete, or not yet verified with production-like
  evidence.
- `P0` is a release blocker. `P1` is required before general availability.
  `P2` is an important improvement that may follow the first controlled
  production release.
- A criterion is complete only when its acceptance statement is true and the
  required test, metric, or operational evidence is linked from the release.
- Update this file in the same change that implements or invalidates a
  criterion. Do not mark work complete based only on a local manual demo.

## Audit Snapshot

**Audit date:** 2026-08-24

**Current maturity:** locally production-hardened candidate; not approved for
external production traffic until environment-specific staging gates pass.

**Hardening update (2026-08-24):** MySQL checkpoints now use database-direct
sync and async paths with immutable conflict detection. Real exec-process tests
exercise concurrent workers, per-incident serialization, unique worker
identities, durable results, SIGKILL lease recovery and job-keyed idempotent
revisions. CI repeats load/race probes, logical backup/isolated restore with
readable canaries, migration checks, SBOM/dependency audit and a scheduled
dependency-security evidence run. A second
exact-draft interrupt now precedes external publishing, which uses a durable
at-most-once attempt guard and blocks ambiguous retries. Managed-environment
failover, real provider contracts, per-destination publication recovery and
long-duration SLO evidence remain open.

**Planning update (2026-07-22):** the active finish line is now
[`Local-Safe v0.1`](../development/SAFE_COMPLETION_PLAN.md), not Shadow-Ready. It permits
fixture/replay-only local use with no production telemetry, hosted deployment,
or publishing/remediation effects. The default runtime makes no external calls;
the explicit, synthetic OpenAI smoke override is the narrow exception used to
verify model behaviour. The Shadow-Ready DoD below remains a future, unchanged
safety gate. Hosted deployment is out of the active scope.

**Verification note:** this is fresh local evidence, not a Shadow/production
claim. The suite ran against the configured local MySQL test database.

Current local baseline:

- `python scripts/quality_gate.py`: 349/349 test methods
  passed, including MySQL lifecycle/persistence, security/observability, API,
  evidence, hypothesis, connector-policy, CloudWatch adapter, Hadoop, HDFS_v1,
  OpenStack, signal-retention and adversarial-boundary coverage. The same run
  passed Ruff, scoped mypy, compileall, prompt budgets and the repository
  secret scan. Branch coverage measured 75.4% repository-wide, 82.2% for the
  explicit core scope and 95.9% for the explicit security-control scope.
- The default local workflow supports alert ingestion, bounded collection,
  normalization, grouping, detection, ranking, semantic interpretation,
  human review, RCA, postmortem drafting, and local HTML output.

Current local checks:

- `.venv/bin/python -m compileall -q app.py clients graph prompts scripts
  settings.py tests utils webhook`: passed.
- `.venv/bin/python scripts/check_prompt_budget.py`: passed. Interpretation was
  5 064 characters, RCA 4 047, postmortem 3 743, and the evidence pack 4 192.
- The original Local-Safe closure record and the current evidence refresh are in
  [`LOCAL_SAFE_CLOSURE_2026-08-09.md`](../reports/LOCAL_SAFE_CLOSURE_2026-08-09.md)
  and
  [`LOCAL_SAFE_CLOSURE_2026-08-24.md`](../reports/LOCAL_SAFE_CLOSURE_2026-08-24.md).
- Opt-in OpenAI bucket-load evidence: 100,000 synthetic webhook events with two
  workers produced 12 durable analysis jobs/revisions, 12 successful provider
  calls and 0 dead letters. The per-incident 12-call budget then blocked 6
  later calls and used the deterministic fallback. This proves local admission,
  coalescing and fallback behaviour only; it is not capacity, cost-calibration
  or production-provider evidence.
- HDFS_v1: 575 061 traces counted and truth-joined only after label-free
  artifacts; 500 balanced sampling cases passed boundary/signal retention.
- OpenStack: 207 820 primary events parsed; all continuation lines accounted
  for; all high-signal shapes retained after sampling. The implemented
  leave-one-out peer baseline established latency impact for 4/4 anomaly and
  0/12 selected normal cases, without creating a root-cause candidate.
- Full label-last feature audit: 2 064 complete OpenStack spawn traces and all
  575 061 HDFS event traces. OpenStack anomalies remained same-cohort and
  same-hour duration outliers; HDFS `E7` occurred in 3 303 failed and zero
  successful traces. This authorizes only peer-relative latency impact and
  `E7` block-operation failure observations, never label-derived root cause.
- Implemented distributed impact rerun: 4 OpenStack latency deviations and 6
  HDFS explicit I/O failures are `established`; 3 HDFS metadata observations
  remain `not_established`. Grounding and impact-contract gates pass 100%,
  with zero unsafe baseline features, identifier leaks, or new cause
  candidates.
- Blind distributed OpenAI smoke test: 4/4 official API calls, schema parses,
  raw boundary decisions, grounding checks, and final boundary decisions
  passed. The model produced 0 hypotheses, 0 unknown evidence IDs and 0
  non-read-only proposals across 9 078 provider-reported tokens. This run
  exposed a wording issue that conflated successful completion with recovery.
- Successful-completion/recovery split: implemented and rerun. OpenStack
  retains 4/4 anomaly and 0/12 normal latency observations with established
  impact. The expanded blind OpenAI regression passed 12/12 provider, schema,
  raw boundary, grounding, and final boundary checks; all 4 latency answers
  said successful-but-slow, with 0 recovery-wording defects, 0 hypotheses,
  0 unknown evidence IDs, and 0 non-read-only proposals.
- Hadoop entity/impact review: all 55 held-out labels were scored only after
  pipeline/review construction; grounding passed 55/55 with zero unknown
  evidence IDs, zero unsupported predictions and zero supported label
  mismatches. Impact-recoverable accuracy was 18/18 and exact result or honest
  abstention was 54/55. Fifteen recovered faults remained visible as
  observation-only rather than being promoted to causes.
- The narrowed review matrix passed 3/3 for clear evidence, insufficient
  evidence and tied candidates without an OpenAI call. It now checks that the
  supported revision is approvable in HTML, abstained revisions are not, the
  analysis and bounded timeline precede the decision controls, and technical
  provenance remains available behind details. Provider-failure tests remain
  deliberately scoped to the shared review gate and
  `DEFERRED_CONNECTION_FAILURE_TESTS.md`.

The strongest current foundations are the time-bounded evidence flow,
deterministic preprocessing, compact LLM context, semantic event-reference
validation, human interruption, and disabled-by-default external publishing.

The most important production blockers are:

1. Targeted tool samples can be reprocessed and rescored locally, but connector
   observations are not yet appended as durable canonical evidence revisions
   through a complete multi-round investigation loop.
2. Independent workers, local multi-process recovery, migrations and logical
   restore drills exist; managed multi-host failover, scheduled encrypted
   backups and measured production RPO/RTO remain unverified.
3. There is no curated cross-incident knowledge memory with provenance,
   approval, retention, deletion, and retrieval evaluation.
4. OIDC/RBAC, CSRF, replay protection and redaction controls exist locally;
   real identity registration, immutable audit storage, encryption,
   retention/deletion and penetration evidence remain incomplete.
5. Separate draft publication approval and an aggregate at-most-once attempt
   guard exist. Provider-specific idempotency and safe retry of only a failed
   destination remain incomplete.
6. Pre-review LLM/tool calls now share an incident deadline and
   provider-reported usage ledger, but initial connectors still lack cooperative
   mid-request cancellation and the cost estimate is not reconciled to billing.
   Strict structured output across every generation stage also remains open.
7. The local tests, public-dataset loops and synthetic 100,000-event OpenAI
   run provide a stronger contract, MySQL, grounding, data-retention and
   admission-control baseline, but there is still no SRE-adjudicated production
   gold set or sufficient SLO-based E2E, soak, adversarial, concurrency and
   controlled fault-injection evidence for production quality or calibration
   claims.
8. A durable MySQL job queue exists, but there is no independent continuously
   deployed worker, production packaging, CI/CD pipeline, deployment
   definition, or managed operations model.

## Target Release Stages

| Stage | Purpose | External effects | Entry gate |
| --- | --- | --- | --- |
| Local prototype | Develop the reasoning flow with fixtures and a local model | Local files only | Existing baseline |
| Shadow | Read production telemetry and compare with real incidents without influencing response | No messages, tickets, remediation, or final documents | All Shadow DoD items below |
| Controlled pilot | Show decision support to a small reviewer group | Drafts only; explicit human approval for every external write | P0 complete and pilot metrics met |
| General availability | Reliable, supported production service | Approved documentation only; remediation remains out of scope | All P0/P1 release gates complete |

## 1. Product Scope And Safety Contract

Supporting artifact: [`OPERATING_CONTRACT.md`](../contracts/OPERATING_CONTRACT.md). It
documents completed supporting work below without claiming that the remaining
runtime P0/P1 controls are complete.

- [x] `SCP-001` The project purpose states that the agent is decision support
  for incident handlers and must explain what most likely went wrong.
- [x] `SCP-002` The non-goals exclude unattended production remediation,
  unsupported certainty, unrestricted raw-log prompts, and unreviewed final
  postmortems.
- [ ] `SCP-003` `P0` Define the supported v1 matrix: alert sources, telemetry
  backends, deployment source, environments, service naming rules, maximum
  incident duration, and supported incident volume. Acceptance: unsupported
  inputs fail with a documented error instead of being silently interpreted.
- [x] `SCP-003a` The current v0 support boundary and known enforcement gaps are
  documented in `OPERATING_CONTRACT.md`.
- [x] `SCP-003b` Intake now rejects services outside `config/services.yaml` and
  unsupported environments through the versioned alert contract, covered by
  the `A01-T01` contract-test subset. Volume and production matrix ratification remain open.
- [ ] `SCP-006` `P0` Define the fail-open/fail-closed policy for intake,
  analysis, review, and publishing. External writes and authorization must fail
  closed; unavailable optional evidence must produce an explicit degraded state.
- [x] `SCP-006a` The current and target failure policy is documented, and the
  currently implemented authentication/signature and optional-source failure
  behavior is covered by the `A01-T03` subset in `tests/test_scope_safety.py`.
- [ ] `SCP-007` `P1` Define when the agent must abstain. Acceptance: insufficient,
  contradictory, stale, or untrusted evidence produces “no supported root cause”
  plus next-best collection steps rather than a forced hypothesis.
- [x] `SCP-007a` The target abstention contract is documented in
  `OPERATING_CONTRACT.md`; runtime enforcement and evaluation remain open.
- [x] `SCP-007b` Deterministic no-evidence/source-failure/material-tie cases now
  return **No supported root cause yet** before invoking a model, covered by a
  focused `A01-T04` subset. Full stale/untrusted/false-alert evaluation remains open.
- [x] `SCP-007c` A generated interpretation that fails the current format,
  citation, evidence, or risky-action guardrails is replaced by a safe
  abstention before review, covered by an `A01-T04` subset.
- [ ] `SCP-008` `P1` Establish a change policy for prompts, models, rules,
  schemas, and source mappings, including required evaluation.
- [x] `SCP-008a` The required change record, evaluation and approval
  policy is documented in `OPERATING_CONTRACT.md`; CI enforcement remains open.

## 2. Alert Intake And Incident Lifecycle

Supporting artifact: [`ALERT_INPUT_CONTRACT.md`](../contracts/ALERT_INPUT_CONTRACT.md).

- [x] `ING-001` Grafana/Alertmanager payloads can be normalized into the
  internal alert shape.
- [x] `ING-002` Production webhook requests require an HMAC signature when a
  shared secret is configured.
- [x] `ING-003` Incident IDs are reused for the same fingerprint, service,
  tenant, and fixed event-time bucket through a durable MySQL mapping.
  Concurrent first observations recheck under the sequence lock and converge
  on one mapping.
- [x] `ING-004` A pending incident is protected from duplicate workflow starts
  by the local pending-review registry.
- [x] `ING-005` `P0` Define and enforce a versioned Pydantic/JSON input schema.
  Acceptance: required fields, types, timestamps, maximum lengths, label count,
  batch size, and allowed status values have positive and negative contract
  tests. The `grafana-alertmanager/v1` contract is enforced before workflow
  invocation and covered by the `A02-T01` subset in
  `tests/test_alert_contract.py`.
- [x] `ING-006` `P0` Enforce request-body limits before parsing and batch limits
  before workflow state. Oversized input returns `413`, is counted, and never
  enters workflow state.
  Configurable body and batch limits reject oversized requests before workflow
  invocation and record a process-local rejection reason; the `A02-T03` subset
  covers both declared and actual body size.
- [x] `ING-007` `P0` Signed timestamp/nonce verification uses a bounded,
  durable MySQL nonce store. A captured valid webhook is atomically rejected
  across workers for the replay window; `A02-T02` covers the replay path.
- [x] `ING-007a` Production signatures bind timestamp, nonce, and raw body;
  timestamp bounds and duplicate nonce rejection are covered by `A02-T02`.
- [x] `ING-008` `P0` The versioned endpoint atomically persists the redacted
  normalized event, idempotency key, and a MySQL analysis job before returning
  `accepted`; a lease-based worker analyses it after the response. `A02-T04`
  and `A02-T05` local integration coverage is in
  `tests/test_mysql_incident_lifecycle.py`.
- [x] `ING-009` `P0` Implement a durable incident lifecycle with at least
  `received`, `collecting`, `analyzing`, `awaiting_analysis_review`,
  `drafting_postmortem`, `awaiting_publish_review`, `completed`, `degraded`, and
  `failed` states.
- [x] `ING-009a` The versioned `incident-lifecycle/v1` state machine persists
  ordered intake/review transitions and rejects illegal transitions; the
  `A02-T08` subset covers legal and illegal paths. Durable workers and full
  production lifecycle states remain open.
- [x] `ING-009b` Lifecycle and pending-review records persist in MySQL with
  ordered history, row-level transaction locking, and lease-based job claims;
  `A02-T09` verifies the durable lifecycle path.
- [ ] `ING-010` `P0` Append new alerts, logs, metrics, deploys, resolved events,
  and reviewer notes to the existing incident. Acceptance: a late observation
  updates the timeline and hypothesis versions without deleting verified prior
  evidence.
- [x] `ING-010a` Incoming alerts and submitted reviewer notes are append-only
  events with immutable arrival order and a time-sorted incident timeline.
  Connector-observation append paths remain open.
- [x] `ING-010b` Every completed local analysis revision now links the exact
  connector-derived timeline membership to queryable immutable MySQL evidence
  records. Late observations append a new membership without mutating the
  previously reviewed revision; resolved incidents reopen through an atomic
  `received` → `collecting` → `analyzing` path. Real connector/backend E2E proof
  remains open.
- [x] `ING-011` `P0` Replace “deduplicated pending review” as the only update
  behavior with idempotent event ingestion. Exact retries do nothing; genuinely
  new observations are durably appended. Pending observations coalesce into the
  newest event under a per-incident lock and bounded debounce; observations
  arriving during a lease create one pending follow-up revision. The MySQL
  integration suite covers sequential, leased, and concurrent burst paths.
- [x] `ING-012` `P0` Preserve event time, source time, receive time, and clock
  quality separately. Out-of-order events are sorted by event time but retain
  arrival order for audit. `A02-T07` timeline-order coverage is in
  `tests/test_mysql_incident_lifecycle.py`.
- [x] `ING-013` `P0` Handle Alertmanager `resolved` notifications and document
  how resolution affects analysis, review, and postmortem state.
- [x] `ING-013a` Local resolved alerts now transition a known active/completed
  incident to `resolved` idempotently without creating analysis or publishing;
  lifecycle tests cover permitted resolution transitions. Durable/reopen policy remains open.
- [x] `ING-014` `P0` Add optimistic concurrency/version checks. Two workers or
  reviewers cannot overwrite a newer incident revision.
- [x] `ING-014a` MySQL lifecycle and pending-review writes accept an expected
  version and reject stale writers inside a `FOR UPDATE` transaction; `A02-T09`
  verifies both conflict paths. Review submissions carry the displayed
  `pending_revision`; queue leases prevent double worker ownership.
- [x] `ING-014b` A locked per-incident revision head now allocates unique
  monotonic revisions. Four concurrent writers passed repeatedly, and an
  out-of-order worker-completion test preserves the allocated parent chain.
  Multi-process/deployed-worker evidence remains open.
- [ ] `ING-015` `P1` Support safe reprocessing from stored normalized evidence
  with a selected code/prompt/model version, without duplicating external side
  effects.
- [x] `ING-015a` The authenticated reprocess endpoint queues stored normalized
  evidence with explicit code/prompt/model versions and persists that context
  with the new revision; reprocessing is analysis-only. `A02-T12` local queue
  coverage is in `tests/test_mysql_incident_lifecycle.py`; reproducibility
  tolerance across real hosted models remains open.
- [x] `ING-016` `P1` Create a dead-letter path for permanently invalid or failed
  events with redacted diagnostics and an operator replay procedure.
- [x] `ING-016a` Exhausted jobs enter MySQL `incident_dead_letters` with
  redacted diagnostics; authenticated `POST /v1/dead-letters/{job_id}/replay`
  queues an analysis-only replay, covered by `A02-T11` integration tests.
- [x] `ING-017` `P1` Version the HTTP API and publish an OpenAPI contract with
  authentication, idempotency, state, and error semantics.
- [x] `ING-017a` The current alert payload contract has an explicit version and
  documented responses in [`ALERT_INPUT_CONTRACT.md`](../contracts/ALERT_INPUT_CONTRACT.md).
- [ ] `ING-018` `P1` Rate-limit by trusted caller and globally. Load tests prove
  one noisy source cannot starve other sources or the review UI.
- [x] `ING-018a` A bounded local global/per-caller intake rate limiter returns
  `429` with `Retry-After`, covered by a boundary test. Caller identity comes
  from the direct source address; `X-Forwarded-For` is accepted only from a
  configured trusted proxy, and an optional source-CIDR filter returns `403`
  before nonce consumption. Distributed fairness and load-test proof remain
  open.
- [x] `ING-018b` Runtime counters are now shared through MySQL and store only a
  hash of the resolved source address. An arbitrary client-ID header cannot
  split the caller budget; secure-runtime CIDR syntax is startup-validated.
  Load/fairness evidence remains required before closing `ING-018`.

## 3. Telemetry And Change-Source Connectors

Supporting artifact: [`CONNECTOR_CONTRACT.md`](../contracts/CONNECTOR_CONTRACT.md).

- [x] `SRC-001` Loki supports bounded log queries, an exact-count attempt, and
  targeted log search.
- [x] `SRC-002` Prometheus provides error-rate, latency, and request-rate
  features with per-query error reporting.
- [x] `SRC-003` GitHub supplies recent change/deploy context and can create a
  postmortem issue.
- [x] `SRC-004` Source failure/degradation is represented in `source_status`
  rather than silently treated as empty evidence.
- [x] `SRC-005` HTTP evidence sources use bounded retries, timeouts, and an
  in-process circuit breaker.
- [ ] `SRC-006` `P0` Define a connector interface and contract suite covering
  authentication, pagination, time range, query limits, cancellation, error
  mapping, rate-limit handling, and redacted diagnostics.
- [x] `SRC-006a` The current connector capabilities, target result contract, and
  test mapping are documented in `CONNECTOR_CONTRACT.md`; the production
  interface and real-backend suite remain open.
  Local progress: CloudWatch Logs Insights and GetMetricData now use bounded,
  injected SDK clients with explicit polling/pagination budgets. Contract tests
  use AWS-shaped fixtures. Loki collection is severity-aware and samples across
  incident time slices plus high-signal shapes under the configured hard cap
  (default 5,000); provenance records the strategy and truncation. A real AWS
  sandbox suite is
  still required.
- [ ] `SRC-007` `P0` Make all timeouts, retry policies, concurrency limits, and
  circuit thresholds configurable per source and observable at runtime.
- [x] `SRC-007a` Loki, Prometheus, CloudWatch, GitHub, and Slack now use configurable
  per-source timeout, retry, backoff, and circuit-open policies. The `A03-T04`
  subset in `tests/test_connector_policy.py` verifies the policy at the HTTP
  boundary; concurrency limits and production observability remain open.
- [ ] `SRC-008` `P0` Distinguish “no matching data” from unavailable, forbidden,
  rate-limited, invalid query, truncated, and stale data in every connector.
- [x] `SRC-008a` Connector results now represent `empty`, `partial`, `forbidden`,
  `rate_limited`, `invalid_query` and `failed` distinctly with sanitized
  diagnostics; local empty/429 and CloudWatch partial/terminal-state contract
  tests pass.
- [x] `SRC-009` `P0` Record query provenance: backend, tenant, sanitized query
  fingerprint, time window, collection time, result count, truncation, and
  source request ID.
- [x] `SRC-009a` Collector status includes redacted backend, query fingerprint,
  window, collection time, count, truncation and request-ID provenance.
- [x] `SRC-009b` `connector-provenance/v2` adds explicit source schema,
  connector version, stable query ID and a sanitized `incident-query/v1`
  replay specification. Query IDs survive log grouping and evidence-graph
  construction; raw PromQL and backend URL paths/credentials are excluded.
- [ ] `SRC-010` `P0` Validate that production credentials are read-only for
  evidence sources and scoped to approved services/environments.
- [ ] `SRC-011` `P0` Verify that the configured deployment source represents
  actual production deployments, not merely repository commits. Store
  environment, service, artifact/version, actor/system, and deployment status.
- [ ] `SRC-012` `P1` Add an actual distributed-trace backend connector. A
  `trace_id` lookup must retrieve a bounded trace graph rather than only search
  logs already stored for the incident.
- [ ] `SRC-013` `P1` Add production-relevant change sources such as Kubernetes
  events, configuration changes, feature flags, and infrastructure deploys, or
  explicitly mark them out of v1 scope.
- [ ] `SRC-014` `P1` Support per-service/per-environment backend routing without
  accepting arbitrary caller-provided URLs or credentials.
  Local progress: CloudWatch service-to-log-group/metric routing is read from a
  versioned operator-owned source map; incoming alarm fields cannot select
  endpoints, regions, credentials, groups, namespaces or dimensions. Multiple
  account/environment routing remains open.
- [ ] `SRC-015` `P1` Test source pagination, high cardinality, partial responses,
  malformed records, timezone/clock skew, duplicate records, and provider rate
  limits.
- [ ] `SRC-016` `P2` Add freshness SLOs and warn when a source is reachable but
  its newest sample is older than the incident window.

## 4. Evidence Reduction, Provenance, And Timeline

Supporting artifact: [`EVIDENCE_CONTRACT.md`](../contracts/EVIDENCE_CONTRACT.md).

- [x] `EVD-001` Incident collection is anchored to alert timestamps and bounded
  by a maximum investigation window.
- [x] `EVD-002` Logs are normalized to canonical labels and levels.
- [x] `EVD-003` Messages and common sensitive labels are redacted or
  pseudonymized before normalized logs are persisted.
- [x] `EVD-004` High-volume logs are fingerprinted, grouped, bucketed, sampled,
  and summarized before an LLM sees context.
- [x] `EVD-005` Truncated samples are not presented as exact full-window group
  counts.
- [x] `EVD-006` Known benign groups can be suppressed with an explicit reason.
- [x] `EVD-007` Logs, metrics, deploys, and the alert are ordered in a timeline
  with offsets from an anchor event.
- [x] `EVD-008` A bounded evidence pack is built separately from the raw log
  store.
- [ ] `EVD-009` `P0` Redact every persisted and exported alert field, including
  the full annotations map, URLs, nested objects, exception strings, review
  feedback, tool arguments/results, and connector metadata.
- [x] `EVD-009a` Alert annotations, nested structured values, and generator URLs
  are recursively redacted before normalized alert state. The `A04-T02` subset
  in `tests/test_evidence_contract.py` covers this current boundary.
- [x] `EVD-009b` HTML export, pending-review persistence and local log storage
  apply recursive redaction at their sink boundaries, covered by contract tests.
- [ ] `EVD-010` `P0` Create a versioned canonical evidence schema with stable
  evidence IDs, source lineage, collection revision, event time, receive time,
  service/environment, classification, and integrity hash.
- [x] `EVD-010a` Normalized logs now persist the `incident-log/v1` schema version
  and its current/target fields are documented in `EVIDENCE_CONTRACT.md`.
- [x] `EVD-010b` Canonical normalized evidence has stable IDs, lineage,
  collection revision, time fields and integrity hash; clock-invalid/future
  records are low quality in the local contract suite.
- [ ] `EVD-011` `P0` Make stored evidence append-only or versioned. Corrections
  create a superseding record and audit link; they do not silently rewrite the
  evidence previously reviewed.
- [x] `EVD-011a` Targeted collection rounds append
  `investigation-revision/v1` records with query IDs, compact result status,
  added-record count and candidate snapshot to checkpointed state. A standalone
  queryable evidence-revision store and correction/supersession flow remain
  open under `EVD-011`.
- [x] `EVD-011b` Local analysis snapshots now use a standalone append-only
  evidence-revision store. Unchanged content reuses its immutable record;
  corrected content creates a version with an explicit supersession link.
  Production migration, retention and tamper-proofing remain open.
- [x] `EVD-011c` Stored evidence content hashes and exact revision membership
  are verified before diffing or approval. A controlled MySQL manipulation is
  detected and blocks approval while still allowing the reviewer to reject the
  corrupt analysis. Tamper-evident external audit and production recovery
  evidence remain open.
- [ ] `EVD-012` `P0` Ensure every factual hypothesis/postmortem statement can
  cite one or more resolvable evidence IDs. A validator blocks unresolved or
  type-incompatible citations.
  Local progress: the pre-review grounding gate now resolves evidence by role,
  not only existence. Cause, mechanism, impact, contradiction, recovery and
  successful-completion IDs cannot substitute for one another. Postmortem
  statement validation remains open.
- [ ] `EVD-013` `P0` Treat logs, labels, commit messages, alert annotations,
  reviewer text, and retrieved documents as untrusted data. Delimit them and
  test that embedded instructions cannot change system policy or invoke tools.
- [x] `EVD-013a` The untrusted-evidence rule is documented in
  `EVIDENCE_CONTRACT.md`; runtime prompt/tool boundary enforcement remains open.
- [x] `EVD-013b` Prompt builders delimit redacted external material as
  `untrusted-evidence`; a malicious reviewer-text test confirms it cannot alter
  prompt policy.
- [ ] `EVD-014` `P0` Normalize timestamps to UTC while preserving the original
  timestamp and timezone. Invalid or future timestamps are quarantined or
  marked low quality.
- [x] `EVD-014a` Canonical evidence keeps original time/zone, normalized UTC and
  explicit clock quality; invalid/future timestamps are quarantined as low quality.
- [ ] `EVD-015` `P1` Quantify sampling bias. Evidence packs must preserve rare
  high-severity events, cross-service representatives, first/peak/last samples,
  and explicitly state what was omitted.
- [x] `EVD-015a` Log reduction records sampling share, first/peak/last policy,
  service representation and high-signal groups; its contract test passes.
- [ ] `EVD-016` `P1` Add historical and peer baselines for metrics; do not infer
  “spike” from only the first and last sample when seasonality matters.
- [ ] `EVD-017` `P1` Represent supporting, contradicting, alternative, and
  missing evidence as typed graph edges, not only prose.
- [ ] `EVD-018` `P1` Recompute only affected summaries when new observations
  arrive and prove that unchanged evidence keeps the same stable ID.
- [x] `EVD-018a` Local late-observation tests prove that unchanged evidence
  keeps both its stable evidence ID and immutable record ID across analysis
  revisions. Selective graph-node recomputation remains open.
- [ ] `EVD-019` `P1` Version detection, normalization, suppression, code-map,
  service-registry, and evidence-pack configuration in every analysis revision.
- [x] `EVD-019a` Every new local job, reprocess and analysis revision carries a
  `pipeline-config-manifest/v1` with content hashes for detection rules,
  normalization, suppressions, code map and service registry plus the evidence-
  pack version. Tests prove stability and component-specific change detection.
  Artifact signing and deployed-config reconciliation remain open.
- [ ] `EVD-020` `P2` Add data-quality scoring for coverage, freshness,
  truncation, clock quality, source health, and service attribution.
- [x] `EVD-020a` `source-quality/v1` measures usable/quarantined/duplicate,
  missing-field/time, parse/source-error, timestamp-quality, event-range and
  freshness values per current evidence source. A calibrated combined quality
  score and production SLO remain open.

## 5. Deterministic Detection, Correlation, And Hypotheses

Supporting artifact: [`HYPOTHESIS_CONTRACT.md`](../contracts/HYPOTHESIS_CONTRACT.md).

- [x] `COR-001` Version-controllable Markdown rules detect several known failure
  patterns before model reasoning.
- [x] `COR-002` Candidate scores expose reasons, evidence, weaknesses, and a
  suggested verification step.
- [x] `COR-003` Same-service deploy timing contributes to a candidate only when
  the deploy precedes the first matching error.
- [x] `COR-004` Service registry dependencies, observed services, discovered
  services, and trace/request pivots constrain scope expansion.
- [x] `COR-005` Severity is initially based on service importance and alert
  severity, then can escalate from measured error rate.
- [x] `COR-006` Semantic correlation rejects references to unknown event IDs and
  caps confidence according to evidence quality.
- [x] `COR-006a` `investigation-loop/v1` reruns semantic collection only when
  newly integrated evidence leaves a deterministic gap and budget remains.
  Stop reasons distinguish enough evidence, query/round/byte/time exhaustion,
  source unavailability and safe abstention.
- [ ] `COR-007` `P0` Define a versioned, typed hypothesis schema containing
  rank, cause, mechanism, impact link, confidence, supporting evidence,
  contradicting evidence, assumptions, gaps, and next verification.
- [x] `COR-007a` Deterministic candidates now use the versioned
  `deterministic-candidate/v1` contract and are validated before entering the
  assessment. The final LLM hypothesis schema remains open.
- [x] `COR-007b` Deterministic candidates model trigger, root-cause status,
  symptoms, contributing factors and recovery actions in the typed contract.
- [x] `COR-007c` Pre-review model interpretation now uses
  `model-interpretation/v1` with zero-to-three candidate-bound hypotheses,
  typed cause/mechanism/impact claims, qualitative confidence, evidence IDs,
  assumptions, gaps and next verification. RCA/postmortem typed migration
  remains open under `COR-007`.
- [ ] `COR-008` `P0` Require a causal mechanism. Temporal proximity or a deploy
  alone may raise suspicion but cannot be labeled root cause without an
  evidence-backed failure path or explicit inference marker.
- [x] `COR-008a` Deterministic candidates explicitly require verification and
  cannot claim a causal mechanism or root cause. Deploy correlation is limited
  to same-service deploys preceding the first error; `A05-T03` subset covers it.
- [x] `COR-008b` Direct catalog matches first become `observed-signal/v1`.
  Hash-minimized workload/execution dimensions and `signal-impact-link/v2`
  separate operation effects, adverse lifecycle and recovery context. A
  recovered signal without adverse impact remains observation-only, and
  competing observed failure categories force abstention.
- [x] `COR-008c` `impact-assessment/v1` separates fault, impact, outcome,
  recovery and contradiction evidence. Typed entity/time relations prevent a
  conflicting execution or a pre-signal outcome from establishing impact.
- [ ] `COR-009` `P0` Add a hard grounding gate after interpretation, RCA, and
  postmortem generation. Unsupported critical claims are removed, downgraded,
  or sent back for review.
- [x] `COR-009a` `claim-grounding/v1` independently gates interpretation before
  review: unknown/incompatible IDs reject claims, causal overstatement is
  downgraded, mechanisms require validated cross-event links, and unsafe
  unapproved actions are removed. Known but role-incompatible IDs are now also
  removed from hypotheses, blast radius and next steps before review.
  RCA/postmortem gates remain open.
- [ ] `COR-010` `P0` Allow the valid result “insufficient evidence.” The system
  must not manufacture three plausible causes solely to fill a template.
- [x] `COR-010a` Deterministic assessment returns an explicit abstention for
  insufficient/tied evidence rather than filling a candidate template.
- [ ] `COR-011` `P0` Calibrate confidence against labeled incidents. Display
  qualitative labels until numeric probabilities have demonstrated calibration.
- [x] `COR-011a` Current candidates label numerical scores as `not_calibrated`
  and expose qualitative confidence only; labeled calibration remains open.
- [ ] `COR-012` `P1` Evaluate deterministic rules independently for precision,
  recall, overlap, suppression errors, and service/environment portability.
- [ ] `COR-013` `P1` Detect contradictions between sources, such as healthy
  dependency metrics versus timeout logs, and lower confidence explicitly.
- [x] `COR-013a` A factual log-versus-metric contradiction lowers deterministic
  candidate support in the local contract suite.
- [ ] `COR-014` `P1` Re-rank hypotheses on every new evidence revision while
  showing what changed and why compared with the reviewer’s previous version.
- [x] `COR-014a` Each local pending review now carries an
  `analysis-revision-diff/v1` record with added/changed/removed/unchanged
  evidence and before/after candidate changes. The dynamic reviewer page now
  renders a bounded, escaped summary of evidence, rank, qualitative confidence,
  uncalibrated score and candidate evidence changes. Production E2E evidence
  remains open.
- [ ] `COR-015` `P1` Separate trigger, root cause, contributing factors,
  symptoms, impact, and recovery actions in both schemas and UI.
  Local progress: grounded review output now exposes cause, mechanism, impact,
  contradiction, outcome, recovery and successful-completion evidence as
  separate roles. Full trigger/contributing-factor/recovery-action migration
  across RCA and postmortem remains open.
- [ ] `COR-016` `P1` Validate recommendations against the read-only scope. The
  agent may suggest a verification/remediation step but must never claim it was
  executed without action evidence.
- [x] `COR-016a` Deterministic candidates expose only `verification` and
  `next_verification` actions; the contract documents that they are not executed
  actions or remediation claims. The pre-review grounding gate now uses a
  positive read-only verb policy: mutating or unknown actions require explicit
  `proposal` plus approval, executed-action claims are removed, and an unsafe
  fallback is replaced with a generic read-only verification.
- [ ] `COR-017` `P2` Add service-specific rule packs with expiry/review dates,
  test fixtures, and safe fallback when a pack fails to load.
  Deferred until the target services and representative incident
  types are known; no generic packs will be invented from generic public data.

## 6. LLM Boundary, Efficiency, And Model Operations

- [x] `LLM-001` The model endpoint, key, and model name are configurable through
  an OpenAI-compatible interface, allowing local development and later OpenAI
  use.
- [x] `LLM-002` Interpretation, RCA, and postmortem output-token limits are
  configurable.
- [x] `LLM-003` Raw logs are omitted from the normal prompt; the model receives
  compact decision/evidence context.
- [x] `LLM-004` Tool calls and remote evidence units are bounded, cached inside
  the investigation, and skipped for a strong deterministic assessment.
- [x] `LLM-005` A deterministic stub mode supports development without an LLM.
- [x] `LLM-006` Semantic-correlation JSON is parsed and validated against known
  evidence before use.
- [x] `LLM-007a` All current OpenAI-compatible completion calls pass through a
  shared bounded timeout/retry/circuit policy, covered by a local fault test.
- [x] `LLM-010a` Interpretation, RCA, and postmortem model failures return the
  existing deterministic/degraded fallback rather than skipping review.
- [ ] `LLM-007` `P0` Configure explicit connect/read/total timeouts, retry limits,
  backoff, provider circuit breaking, and cancellation for every model call.
- [ ] `LLM-008` `P0` Use strict structured outputs/schema validation for the
  interpretation, RCA, and postmortem—not Markdown parsing as the source of
  truth. Rendering happens after validation.
- [x] `LLM-008a` Interpretation requires `model-interpretation/v1` JSON and
  review Markdown is rendered only from its validated form. RCA/postmortem
  remain open under `LLM-008`.
- [ ] `LLM-009` `P0` Persist provider, model snapshot, prompt/template version,
  parameters, request ID, token usage, latency, finish reason, tool count, and
  calculated cost for every call without storing sensitive prompt content.
- [x] `LLM-009a` Analysis revisions persist the configured model, prompt and
  code versions without retaining raw prompt content; provider usage/cost and
  request telemetry remain open.
- [x] `LLM-009b` The shared provider boundary now records each successful and
  failed real attempt with stage, provider, model, prompt version, safe request
  parameters, provider request ID, reported usage or conservative reservation,
  latency, finish/error status, and configured cost estimate. Prompt content is
  not copied into the ledger, and the ledger is visible in both review views.
- [ ] `LLM-010` `P0` Add graceful failure behavior to every LLM stage. Provider
  failure returns a deterministic brief/degraded state and never loses the
  incident or bypasses review.
- [ ] `LLM-011` `P0` Enforce a hard per-incident budget for calls, input/output
  tokens, remote queries, wall time, and currency. Exhaustion produces a useful
  partial result and is visible to the reviewer.
- [x] `LLM-011a` Model calls now share an incident-wide hard call/input/output/
  total-token/currency preflight at the provider boundary. Retries count as
  calls, failed attempts retain their conservative reservation, exhaustion
  blocks before the next network call, and fallback/review retains the stop
  reason plus remaining budget. Local development may explicitly disable the
  currency gate with a zero cap; shadow/production fail configuration validation
  unless cap and input/output pricing are positive. Remote-query and deadline
  budgets remain tracked separately under the parent requirement.
- [ ] `LLM-012` `P0` Add a post-generation grounding validator independent of
  the generating prompt. Critical claims require citations and compatible
  evidence types.
- [x] `LLM-012a` Interpretation has an independent deterministic
  `claim-grounding/v1` gate with focused hallucinated-ID, causal-overstatement,
  confidence-cap, unsafe-action and non-JSON tests.
- [ ] `LLM-013` `P0` Add prompt-injection and tool-abuse tests for logs, commit
  messages, annotations, retrieved memory, and reviewer feedback.
- [x] `LLM-013a` Untrusted reviewer-text injection is delimited and tested;
  equivalent corpus coverage for every source and tool remains open.
- [ ] `LLM-014` `P1` Define approved model/provider configurations by data
  classification, region, retention policy, context limit, quality, and cost.
- [ ] `LLM-015` `P1` Support controlled fallback between approved models without
  changing the safety or output schema contract.
- [ ] `LLM-016` `P1` Run the gold evaluation suite before prompt/model/rule
  promotion and automatically block statistically or safety-significant
  regressions.
- [ ] `LLM-017` `P1` Record semantic cache keys using evidence revision, prompt
  version, and model version. Cached answers must never cross incidents or data
  access boundaries incorrectly.
- [ ] `LLM-018` `P2` Use tiered model routing: deterministic-only when enough,
  lower-cost model for summarization, and stronger reasoning only when expected
  decision value justifies it.

## 7. Incident Memory And Knowledge Memory

- [x] `MEM-001` LangGraph checkpoints retain local workflow state and allow a
  thread to resume after a single-process restart.
- [x] `MEM-002` Normalized/redacted incident logs are stored separately from the
  compact working evidence pack.
- [x] `MEM-003a` The target versioned incident/revision record boundary is
  documented in `MEMORY_AND_REVIEW_CONTRACT.md`; durable implementation remains open.
- [x] `MEM-004a` The required append-only observation and supersession invariants
  are documented before a persistence backend is selected.
- [ ] `MEM-003` `P0` Replace the implicit state dictionary as the long-term
  contract with versioned incident, observation, evidence, analysis-revision,
  review-decision, and publication schemas.
- [x] `MEM-003b` MySQL stores compact immutable analysis-revision snapshots with
  evidence IDs, candidates, quality and run context; knowledge/publication
  schemas remain separate work.
- [ ] `MEM-004` `P0` Store an append-only timeline of new observations and
  analysis revisions. Each revision records its input evidence set and the
  previous revision it supersedes.
- [x] `MEM-004b` Each durable analysis snapshot records predecessor revision and
  input evidence identifiers; append-only event/revision tests pass.
- [ ] `MEM-005` `P0` Define retention, legal hold, deletion, export, backup, and
  restoration behavior for raw evidence, normalized evidence, checkpoints,
  review records, traces, reports, and model metadata.
- [ ] `MEM-006` `P0` Enforce service/environment/tenant authorization on every
  memory read, write, retrieval, report, and model-context build.
- [ ] `MEM-007` `P1` Create curated knowledge records only from human-approved
  postmortems, reviewed runbooks, service metadata, and tested failure rules.
  Unapproved model output must never become durable knowledge automatically.
- [x] `MEM-007a` Curated knowledge accepts only explicit approved source types
  with approval identity/reference and never implicitly stores model output.
- [ ] `MEM-008` `P1` Tag knowledge with provenance, approval identity,
  created/updated time, service, environment, incident type, validity period,
  security class, schema version, and source link.
- [x] `MEM-008a` Knowledge records store source link/type, approval identity,
  service/environment/type, security class, timestamps and validity period.
- [ ] `MEM-009` `P1` Implement filter-first retrieval by authorization, service,
  environment, incident type, and freshness before optional semantic ranking.
- [x] `MEM-009a` Retrieval filters tenant, allowed security classes, service,
  environment, incident type and validity before bounded lexical ranking.
- [ ] `MEM-010` `P1` Return a small bounded number of knowledge hits with source
  citations and relevance reasons. A retrieval miss must not block incident
  analysis.
- [x] `MEM-010a` Local retrieval returns at most ten cited hits with relevance
  reasons and treats an empty result as a normal non-blocking miss.
- [ ] `MEM-011` `P1` Evaluate retrieval precision, recall, stale-result rate,
  cross-service contamination, and effect on root-cause quality against a
  labeled dataset.
- [ ] `MEM-012` `P1` Protect against memory poisoning. Updates require trusted
  provenance and approval; retrieved text is still treated as untrusted input.
- [x] `MEM-012a` Knowledge creation rejects unapproved provenance and raw
  evidence/prompt fields; retrieved text retains the untrusted-data boundary.
- [ ] `MEM-013` `P1` Support correction, supersession, expiry, and deletion so a
  disproven root cause or retired runbook is no longer recommended.
- [x] `MEM-013a` Knowledge records support supersession, validity expiry and
  attributed soft deletion; filter-first retrieval excludes inactive records.
- [ ] `MEM-014` `P1` Keep full raw evidence out of vector/semantic indexes unless
  an explicit data review approves it. Prefer concise approved summaries and
  structured fields.
- [x] `MEM-014a` The POC uses bounded lexical retrieval over concise approved
  summaries only; raw evidence and prompts are rejected from knowledge metadata.
- [ ] `MEM-015` `P2` Measure memory value: quality lift, added latency, added
  cost, retrieval hit rate, and reviewer acceptance versus a no-memory baseline.

## 8. Human Review And Postmortem Workflow

- [x] `REV-001` The graph interrupts before RCA/postmortem processing and
  requires an approve or reject decision.
- [x] `REV-002` Rejection feedback returns to semantic correlation and creates a
  revised interpretation.
- [x] `REV-002a` Request-more-evidence is a distinct graph/API/HTML/MySQL review
  decision, requires concrete feedback, and enters the same bounded evidence
  expansion loop without being relabeled as an approval.
- [x] `REV-003` The review surface shows timeline, hypotheses, evidence coverage,
  source status, and investigation context.
- [x] `REV-004` Reviewer authentication fails closed in production when Basic
  credentials are absent.
- [x] `REV-005` External publishing is disabled by default.
- [x] `REV-007a` Local review submissions and rejected invalid selections have a
  redacted append-only audit baseline; immutable organization audit remains open.
- [x] `REV-008a` An approval is rejected unless its candidate rank exists in the
  saved deterministic candidate set. API and HTML use one shared gate, and the
  UI offers only the intersection of interpreted and saved candidate ranks.
- [ ] `REV-006` `P0` Replace shared Basic credentials with organization SSO or
  another approved identity system and role-based authorization.
- [x] `REV-006a` The application has a provider-neutral OIDC authorization-code
  browser session and validated JWT/JWKS Bearer path. Viewer, decision and
  operator role sets are independent; Basic Auth is rejected by secure-runtime
  validation. Real IdP registration and staging authorization evidence remain.
- [ ] `REV-007` `P0` Persist reviewer identity, incident revision, selected
  hypothesis ID, displayed evidence IDs, decision, feedback/rationale,
  timestamp, and request correlation ID in an immutable audit record.
- [x] `REV-007b` MySQL records idempotent reviewer decisions with local identity,
  analysis/pending revision, selected hypothesis, displayed evidence IDs,
  rationale and request ID; organization identity immutability remains open.
- [ ] `REV-008` `P0` Reject approval of a hypothesis that does not exist in the
  reviewed revision or whose required evidence failed validation.
- [ ] `REV-009` `P0` Prevent stale review decisions with optimistic locking. If
  new evidence produces a newer revision, the reviewer must see and approve the
  diff or explicitly approve the older revision with rationale.
- [x] `REV-009a` The local API rejects missing, unsaved, resolved, or sequentially
  stale pending revisions and the UI fetches the current pending version before
  enabling controls.
- [x] `REV-009b` Review persistence locks the exact MySQL pending-review row and
  atomically enforces one decision winner per pending revision. An identical
  retry is recognized as idempotent; a competing payload is rejected before the
  graph resumes. Organization-wide multi-instance/load evidence remains open
  under `REV-009`.
- [x] `REV-010` `P0` Add a separate `awaiting_publish_review` gate after the
  postmortem draft is generated and edited. Only approval of that exact draft
  version may enable external publication.
- [x] `REV-011` `P0` Never publish automatically merely because analysis
  Hypothesis 1/2/3 was approved. Analysis approval and document-publication
  approval are separate permissions and audit events.
- [ ] `REV-012` `P0` Make external publishing idempotent with an outbox and
  destination idempotency key. Retries cannot create duplicate Slack messages
  or GitHub issues.
- [x] `REV-012a` A durable publication key prevents a completed attempt from
  running twice and blocks automatic retry when delivery is uncertain. Full
  per-destination idempotency/reconciliation remains open under `REV-012` and
  `REV-013`.
- [ ] `REV-013` `P0` Handle partial publication failure. The UI shows each
  destination status and operators can retry only failed destinations safely.
- [ ] `REV-014` `P1` Let reviewers edit or annotate the draft while preserving
  the generated original and a versioned diff.
- [x] `REV-014a` Generated and edited local postmortem drafts retain immutable
  versioned records, covered by `tests/test_memory_review_persistence.py`.
- [ ] `REV-015` `P1` Require postmortems to separate verified facts, inferred
  root cause, contributing factors, impact, detection, response, action items
  and due dates.
- [ ] `REV-016` `P1` Validate that postmortem facts cite the approved evidence
  revision and that unverified 5-Whys steps are clearly labeled hypotheses.
- [ ] `REV-017` `P1` Support correction/retraction of a published analysis with
  an audit trail and destination update policy.
- [ ] `REV-018` `P1` Measure time-to-review, rejection reasons, revision count,
  approval rate, reviewer overrides, and draft edit distance.
- [ ] `REV-019` `P2` Test keyboard navigation, screen-reader labels, color
  contrast, mobile layout, and large-incident rendering.

## 9. Security, Privacy, And Compliance

- [x] `SEC-001` Common secrets, bearer tokens, email addresses, payment-card-like
  values, and sensitive labels have a first-pass redaction mechanism.
- [x] `SEC-002` Production webhook authentication and reviewer authentication
  fail closed when their configured secrets are unavailable.
- [x] `SEC-003` Production CORS has no wildcard default.
- [x] `SEC-004` Compact Phoenix tracing hides model/node inputs and outputs by
  default when tracing is enabled.
- [x] `SEC-005a` Current trust boundaries, data classes and known missing
  controls are documented in `SECURITY_AND_OPERATIONS.md`.
- [x] `SEC-008a` The production readiness baseline rejects the built-in local
  redaction salt, covered by configuration tests.
- [ ] `SEC-005` `P0` Complete a threat model and data-flow diagram covering
  webhook spoofing/replay, prompt injection, data exfiltration, tool abuse,
  cross-incident access, reviewer compromise, report XSS, SSRF, supply chain,
  and publication abuse.
- [ ] `SEC-006` `P0` Classify every field and store; document which classes may
  reach each model/provider, trace backend, report, and external destination.
- [ ] `SEC-007` `P0` Run recursive schema-aware redaction before persistence,
  tracing, model calls, error logging, and publishing. Unit/property tests use a
  representative secret/PII corpus and nested payloads.
- [x] `SEC-007a` Recursive redaction is tested at event, audit, log and HTML
  export sinks with nested payload/message values; full trace/publisher corpus
  coverage remains open.
- [ ] `SEC-008` `P0` Never use a built-in redaction salt in production. Load
  secrets from an approved secret manager, support rotation, and fail startup
  on insecure defaults.
- [ ] `SEC-009` `P0` Encrypt network traffic and all durable incident data at
  rest using approved key management and rotation.
- [ ] `SEC-010` `P0` Enforce RBAC for reviewers, operators and administrative
  actions.
- [x] `SEC-010a` Reviewer HTTP access distinguishes OIDC viewer, decision and
  operator roles and stores a stable pseudonymous issuer/subject identity in
  review audit records. Additional authorization boundaries remain.
- [ ] `SEC-011` `P0` Add CSRF protection or a same-origin token strategy for
  authenticated browser mutations, in addition to restrictive CORS.
- [x] `SEC-011a` Review decisions require a signed, expiring CSRF token bound to
  the exact incident and authenticated reviewer identity. Both HTML review
  surfaces obtain and send it; missing, expired, tampered or cross-identity/
  incident tokens fail before the route executes. Remaining administrative
  browser mutations stay open under the parent requirement.
- [ ] `SEC-012` `P0` Add audit events for authentication failure, evidence
  access, review, reprocessing, configuration change, deletion, and publication.
- [x] `SEC-012a` Redacted MySQL audit records cover authentication failures,
  review, reprocessing and dead-letter replay; evidence access/config/deletion/
  publication coverage remains open.
- [ ] `SEC-013` `P0` Restrict outbound network destinations to approved model,
  telemetry, identity, and publication endpoints. Callers cannot influence
  outbound URLs.
- [ ] `SEC-014` `P0` Validate and safely render all model/evidence text. Security
  tests cover stored/reflected XSS, unsafe Markdown links, path traversal,
  header injection, and oversized rendering.
- [x] `SEC-014a` Reviewer HTML no longer client-renders model Markdown and a
  regression corpus covers malicious hypothesis/Markdown, oversized rendering,
  path/header/open-redirect injection and safe report filenames. Tool traces and
  Slack/GitHub publisher boundaries now apply recursive/final redaction.
- [ ] `SEC-015` `P0` Pin and scan dependencies, generate an SBOM, scan container
  images and secrets, and define remediation SLAs for critical vulnerabilities.
- [x] `SEC-015a` Python 3.11.15 and direct/transitive dependencies are hash
  locked; the locked environment passes `pip check`, generates a valid
  CycloneDX SBOM and had no known findings in the 2026-08-09 `pip-audit` run.
  The repository secret scanner suppresses values and excludes ignored `.env`.
  Container scanning and production remediation SLAs remain open.
- [ ] `SEC-016` `P1` Add automated data-retention/deletion jobs plus proof that
  all derived stores, backups, vectors, reports, and checkpoints follow a
  deletion request.
- [ ] `SEC-017` `P1` Perform an independent security review/penetration test and
  close all critical/high findings before general availability.
- [ ] `SEC-018` `P1` Document model-provider data retention, training use,
  regional processing, subprocessors, and incident-response obligations.

## 10. State, Reliability, And Failure Recovery

- [x] `REL-001` The local SQLite checkpointer survives construction of a new
  saver instance, verified by an automated test.
- [x] `REL-002` Evidence-source failures degrade source status instead of
  immediately terminating collection.
- [x] `REL-005a` Current source and model retries are bounded by explicit retry,
  backoff and circuit policies; full retry classification remains open.
- [x] `REL-009a` `/readyz` now evaluates the supported secure configuration
  baseline separately from minimal `/healthz` liveness.
- [ ] `REL-003` `P0` Use an officially supported production checkpointer/store
  such as MySQL with transactions, connection pooling, migrations, and
  multi-worker semantics.
- [x] `REL-003a` A real local MySQL 8.4-backed checkpointer now persists the
  LangGraph checkpoint tables when `CHECKPOINTER=mysql`; durable migrations,
  pooling and multi-worker semantics remain open.
- [ ] `REL-004` `P0` Complete the durable execution model around the existing
  MySQL queue and worker lease. Work is at-least-once, every node is
  idempotent, and only one active revision writer owns an incident at a time.
- [x] `REL-004a` MySQL jobs are durable, lease-owned and retry/dead-lettered;
  event idempotency and lease behavior are covered by integration tests. Full
  node-level idempotency and independent worker deployment remain open.
- [ ] `REL-005` `P0` Define retryability per failure type. Invalid input and
  authorization errors are terminal; transient source/model/storage errors use
  bounded retries with jitter and a retry budget.
- [x] `REL-005b` Invalid/authorization worker failures are terminal dead letters;
  other worker failures use bounded retry/dead-letter behavior in local tests.
- [ ] `REL-006` `P0` Make every external write transactional through an outbox.
  Crash/restart between draft, approval, Slack, and GitHub cannot lose state or
  duplicate side effects.
- [ ] `REL-007` `P0` Add workflow deadlines, node timeouts, cancellation, and
  stale-job detection. A stuck provider cannot hold an incident indefinitely.
- [ ] `REL-008` `P0` Cap incident state, raw evidence, group count, timeline
  events, revision count, review feedback, tool result, and report sizes.
- [ ] `REL-009` `P0` Add readiness and startup checks for database, queue,
  schema migration, secure configuration, and required credentials. `/healthz`
  remains a minimal liveness check.
- [x] `REL-009b` `/readyz` verifies secure runtime configuration and MySQL schema
  readiness while `/healthz` stays minimal; test coverage is local only.
- [ ] `REL-010` `P0` Prove crash recovery at each workflow boundary, including
  before/after human interrupts and external-write attempts.
- [ ] `REL-011` `P0` Define backup, point-in-time recovery, restore verification,
  RPO, and RTO. Complete a timed restore drill with documented evidence.
- [ ] `REL-012` `P1` Add backpressure and admission control by tenant/severity so
  alert storms do not exhaust workers, source APIs, storage, or model budgets.
- [ ] `REL-013` `P1` Test multi-worker concurrency, duplicate delivery,
  out-of-order updates, process termination, network partitions, database
  failover, and provider throttling.
- [ ] `REL-014` `P1` Store generated reports in durable object/document storage
  rather than worker-local disk, with access control and retention.
- [ ] `REL-015` `P1` Add safe schema migration and rollback procedures tested
  against a recent production-sized copy with sensitive data removed.
- [ ] `REL-016` `P1` Support graceful worker shutdown: stop admission, finish or
  checkpoint leased work, and release the lease before termination.
- [ ] `REL-017` `P2` Run chaos tests and a regional/dependency outage exercise
  demonstrating the documented degraded behavior.

## 11. Observability And Auditability

- [x] `OBS-001` Optional OpenTelemetry/Phoenix tracing can instrument LangGraph
  nodes and model calls locally.
- [x] `OBS-002` Source status, data quality, tool traces, interpretation quality,
  and an execution log have places in incident state.
- [x] `OBS-003a` A versioned redacted JSON application-log schema is implemented
  and unit-tested; it is not yet emitted by every runtime boundary.
- [x] `OBS-005a` Webhook workflow events include the incident correlation ID;
  end-to-end propagation remains open.
- [ ] `OBS-003` `P0` Emit structured application logs with timestamp, severity,
  service version, environment, incident ID, revision ID, node, source, request
  ID, and redacted error category.
- [x] `OBS-003b` Structured redacted logs include service version and correlation
  fields at implemented runtime boundaries; universal emission remains open.
- [ ] `OBS-004` `P0` Export metrics for accepted/rejected/deduplicated/updated
  alerts, queue depth/age, node latency/errors/retries, source health, workflow
  terminal state, review delay, publication, token use, and cost.
- [x] `OBS-004a` `/metrics` exposes bounded-label Prometheus text metrics for
  intake, worker outcome and retry/dead-letter paths; complete operational
  coverage remains open.
- [ ] `OBS-005` `P0` Propagate a correlation context from webhook to queue,
  workflow, source calls, model calls, review, audit, and publication.
- [ ] `OBS-006` `P0` Ensure telemetry never stores raw sensitive evidence by
  default. Add automated trace/log scanning and documented temporary secure
  debug access.
- [ ] `OBS-007` `P0` Build an operational dashboard and alerts for intake loss,
  queue delay, error budget burn, source/model outages, stuck reviews, storage
  capacity, publication failures, and cost anomalies.
- [ ] `OBS-008` `P1` Separate immutable security/audit events from diagnostic
  logs and restrict their access and retention independently.
- [x] `OBS-008a` Redacted audit events persist separately in MySQL from
  diagnostic logs; access/retention controls remain production work.
- [ ] `OBS-009` `P1` Record analysis revision diffs: evidence added/removed,
  hypothesis rank/confidence changes, model/prompt changes, and reviewer action.
- [ ] `OBS-010` `P1` Add a synthetic canary incident that verifies intake,
  queue, deterministic analysis, checkpointing, review staging, and a no-op
  publisher without sending real external messages.
- [ ] `OBS-011` `P1` Define trace sampling and retention so SEV1/failed workflows
  remain diagnosable without collecting every sensitive prompt.
- [ ] `OBS-012` `P1` Dashboard quality signals alongside uptime: citation
  validity, abstention, reviewer rejection, overrides, calibration, and cost.

## 12. Tests, Evaluation, And Quality Gates

- [x] `TST-001` Two hundred seventy-six automated test methods cover the original flow
  tests plus MySQL lifecycle/persistence, webhook/API contracts, authentication,
  replay protection, evidence and hypothesis contracts, connector policy,
  redaction, security/observability, operational configuration, Hadoop,
  HDFS_v1, OpenStack and signal-retention baselines.
- [x] `TST-002` The repository compiles successfully with `compileall`.
- [x] `TST-003` The representative prompt-budget check passes: interpretation
  is 5 064 characters, RCA 4 047, postmortem 3 743, and the evidence pack
  4 192 characters.
- [x] `TST-006a` Local API-adjacent tests cover authentication, signature,
  payload limits and error contracts; rate limits/CSRF/async acknowledgement remain open.
- [x] `TST-010a` Automated tests cover nested annotation/URL/log redaction and
  redacted structured-log output; the complete sink corpus remains open.
- [ ] `TST-004` `P0` Add CI that runs format/lint, type checking, unit tests,
  security scans, dependency checks, migration checks, prompt budgets, and
  deterministic evaluations on every change.
- [x] `TST-004a` A GitHub Actions definition with MySQL 8.4 now installs the
  hash lock, runs the deterministic local quality gate, audits dependencies and
  uploads coverage/SBOM evidence. A first run from an actual clean repository
  checkout and production migration checks remain open under `TST-004`.
- [x] `TST-005` `P0` Establish coverage gates: at least 80% branch coverage for
  core workflow code and 90% for security, idempotency, review, evidence
  grounding, and publication controls.
- [x] `TST-005a` Branch coverage is measured in the shared local/CI command.
  The locked 2026-08-24 run measured 75.4% repository-wide with a 74% ratchet,
  82.2% for the explicitly listed core workflow against an 80% gate, and 95.9%
  for the explicitly listed security controls against a 90% gate.
- [ ] `TST-006` `P0` Add API tests for schema validation, authentication,
  signature replay, body limits, rate limits, CORS/CSRF, error contracts, and
  async acknowledgement.
- [x] `TST-006b` Local API/worker contract tests now cover async event/job ACK,
  replay, rate limits, security headers and error handling; CORS/CSRF remains open.
- [ ] `TST-007` `P0` Add end-to-end tests from alert through both review branches,
  second publish approval, persisted report, and restart recovery.
- [ ] `TST-008` `P0` Add incremental-update tests proving late and out-of-order
  observations merge into one incident and preserve prior reviewed evidence.
- [x] `TST-008a` Local MySQL integration tests cover late evidence append,
  correction supersession, connector-to-review sync, resolve/reopen,
  out-of-order worker completion and concurrent revision allocation. Full API
  E2E against production-shaped connectors remains open.
- [ ] `TST-009` `P0` Add idempotency/concurrency tests for duplicate webhooks,
  duplicate jobs, concurrent workers, concurrent reviewers, and publication
  retries.
- [x] `TST-009a` MySQL integration tests cover duplicate events, stale writers,
  worker leases and review-decision idempotency. Exec-process tests now cover
  shared checkpoints, concurrent workers, SIGKILL recovery, unique job effects
  and completed/uncertain publication retry guards. Real-provider partial
  delivery remains open.
- [ ] `TST-010` `P0` Add redaction and data-leak tests for nested annotations,
  logs, labels, URLs, exceptions, tool results, feedback, memory, traces, and
  generated output.
- [x] `TST-010b` Sink-boundary redaction tests now cover nested events, logs,
  audits, HTML output and knowledge-memory restrictions; traces/tool/publisher
  coverage remains open.
- [ ] `TST-011` `P0` Build a versioned gold dataset with at least 100
  representative incidents across supported services and failure modes,
  including false alerts, ambiguous causes, missing sources, and no-root-cause
  cases.
- [ ] `TST-012` `P0` Label the gold set with incident window, impact, evidence,
  accepted cause(s), alternatives, invalid causal shortcuts, and expected
  abstention, using at least one SRE reviewer and adjudication for disagreements.
- [ ] `TST-013` `P0` Score top-1/top-3 cause quality, citation precision/recall,
  unsupported claims, abstention, calibration, source-gap handling, latency,
  tokens, tool calls, and cost.
- [x] `TST-013a` The label-blind Hadoop typed-review evaluation scores all 55
  applications for exact classification, signal recoverability, honest
  abstention, unsupported predictions, grounding, unknown evidence IDs and
  label/evidence conflict. Model calibration, top-3, latency, token and cost
  gates remain open under `TST-013`.
- [x] `TST-013b` HDFS_v1 and OpenStack run through the same typed impact and
  grounding boundary with labels held out, minimized source identifiers and
  no root-cause accuracy claim. Forty HDFS block cases and sixteen OpenStack
  VM cases pass the contract gate.
- [ ] `TST-014` `P0` Add adversarial prompt-injection, tool-abuse, malicious
  Markdown/HTML, huge payload, malformed timestamp, regex, and decompression
  cases.
- [x] `TST-014a` Local tests cover malicious reviewer text, safe HTML rendering,
  malformed timestamps, bounded input, prompt-boundary injection, tool abuse,
  literal regex handling, secret-like tool arguments, traversal/header/open
  redirects and compressed expansion bombs. Production-scale fuzzing remains
  open under the parent requirement.
- [ ] `TST-015` `P1` Add connector contract tests against production-like
  CloudWatch, deployment, trace, identity, database, queue, Slack, and document
  destinations. AWS-shaped fixture tests exist for CloudWatch, but do not close
  the real-provider requirement.
- [ ] `TST-016` `P1` Add load tests for normal traffic, alert storms, large
  incidents, long reviews, and concurrent incremental updates. Validate SLOs and
  backpressure.
- [ ] `TST-017` `P1` Add soak and failure-injection tests for memory leaks,
  checkpoint growth, provider throttling, partial source outages, database
  reconnect, and worker restarts.
- [ ] `TST-018` `P1` Run blinded reviewer evaluation comparing the agent to the
  existing process. Measure time-to-useful-hypothesis, correctness, reviewer
  effort, false confidence, and missed evidence.
- [ ] `TST-019` `P1` Treat quality, security, cost, and latency thresholds as
  blocking release gates with an approved exception process.
- [ ] `TST-020` `P2` Add mutation/property tests for evidence grouping,
  timestamps, schema normalization, scoring invariants, and redaction.

## 13. Performance And Cost Control

- [x] `PERF-001` Initial log samples, targeted queries, scope services, tool
  calls, and generation lengths have configurable bounds.
- [x] `PERF-002` Strong deterministic evidence can skip semantic remote-tool
  expansion.
- [x] `PERF-003` Tool results are cached within an investigation budget.
- [x] `PERF-005a` Current remote evidence-unit limits are enforced and rendered
  in the review context; provider token/currency/time budgets remain open.
- [x] `PERF-005b` Targeted expansion additionally enforces depth-one scope,
  maximum services, incident window, rounds, retained result bytes and elapsed
  expansion time. The A→B integration and failure-limit matrix are covered by
  `tests/test_investigation_loop.py`.
- [x] `PERF-005c` `incident-analysis-deadline/v1` prevents new pre-review model
  or targeted-tool calls after the shared deadline and clips provider timeout
  to remaining time. `model-usage-ledger/v1` records provider-reported tokens,
  request ID, model and optional configured cost estimate in review state.
  Cooperative connector cancellation, ratified token/currency caps and billing
  reconciliation remain open under `PERF-005`.
- [ ] `PERF-004` `P0` Benchmark each workflow node and publish p50/p95/p99
  latency, memory, state size, source calls, tokens, and cost by incident class.
- [ ] `PERF-005` `P0` Enforce the ratified per-incident cost/token/query/time
  budget in code and include remaining budget in every relevant decision.
- [ ] `PERF-006` `P0` Measure real provider token usage rather than character
  estimates, while keeping a fast offline preflight budget check.
- [x] `PERF-007` `P0` Intake commits event/job state before replying `accepted`;
  MySQL workers lease analysis after the response, so source/model latency does
  not hold the webhook open. Covered by the Area 2 MySQL integration suite.
- [ ] `PERF-008` `P1` Add early-exit policies for empty evidence, known strong
  deterministic matches, repeated unchanged revisions, and resolved low-impact
  alerts.
- [ ] `PERF-009` `P1` Cache only safe deterministic/source results with explicit
  keys, authorization boundary, evidence revision, TTL, and invalidation.
- [ ] `PERF-010` `P1` Establish capacity estimates and quotas for alerts/minute,
  active incidents, event volume, source QPS, worker concurrency, database
  growth, model rate limits, and monthly spend.
- [ ] `PERF-011` `P1` Load-test the ratified capacity with 30% headroom while
  meeting intake and analysis SLOs.
- [ ] `PERF-012` `P2` Review cost/quality by model route monthly and remove model
  calls that do not measurably improve incident decisions.

## 14. Packaging, Deployment, And Operations

- [x] `DEP-001` Environment variables separate the local model endpoint,
  evidence sources, budgets, auth, storage, tracing, and publishing switch.
- [x] `DEP-002` A local launcher starts the UI and optional Phoenix tracing.
- [x] `DEP-006a` Production runtime configuration has a testable fail-closed
  baseline for local storage/default salt/origins/auth/model URL/publishing.
- [ ] `DEP-003` `P0` Add a reproducible build with pinned direct/transitive
  dependencies and a documented supported Python/runtime version.
- [x] `DEP-003a` `.python-version` fixes Python 3.11.15 and
  `requirements.lock` pins all declared runtime/dev transitive dependencies
  with hashes. A synchronized local environment passes `pip check`, audit and
  the full quality gate; clean Linux CI evidence remains open under `DEP-003`.
- [ ] `DEP-004` `P0` Build a minimal non-root container image with read-only
  filesystem where practical, health endpoints, signal handling, image scan,
  and immutable version label.
- [ ] `DEP-005` `P0` Add environment-specific deployment/IaC definitions for
  API, workers, queue, database, object storage, secrets, network policy,
  autoscaling, and monitoring.
- [ ] `DEP-006` `P0` Validate configuration at startup. Production refuses local
  model keys/default salts, wildcard origins, memory/SQLite checkpointers,
  missing auth, insecure HTTP endpoints, and external publishing without a
  configured approval/audit system.
- [x] `DEP-006b` Production configuration requires the MySQL checkpointer,
  explicit origins, non-local redaction salt, reviewer credentials, webhook
  secret, HTTPS model URL and disabled external publishing; covered by
  `tests/test_operational_baselines.py`.
- [ ] `DEP-007` `P0` Separate development, test, staging, shadow, and production
  data/credentials/destinations. Tests cannot publish to real incident channels.
- [ ] `DEP-008` `P0` Add CI/CD with build provenance, signed artifact, migration
  step, automated gates, staged rollout and smoke test.
- [ ] `DEP-009` `P0` Document and test kill switches for LLM use, source
  expansion, memory retrieval, reviewer UI, and each publication destination.
- [x] `DEP-009a` Current POC LLM, source-tool, reviewer-UI and publication
  switches are documented in `OPERATOR_RUNBOOKS.md`. Memory retrieval does not
  exist yet; activation tests remain open.
- [ ] `DEP-010` `P1` Use canary/progressive delivery and compare quality,
  latency, errors, and cost before full promotion.
- [x] `DEP-011` `P1` Write operator runbooks for queue backlog, stuck workflow,
  database/storage pressure, model outage, source outage, auth failure,
  compromised secret, bad model/prompt/rule release, and duplicate publication.
- [ ] `DEP-012` `P1` Provide dashboards, paging rules and support hours for the
  agent itself.
- [ ] `DEP-013` `P1` Define maintenance, dependency upgrade, key rotation,
  retention cleanup, knowledge review, rule review, and restore-drill schedules.
- [ ] `DEP-014` `P1` Complete a production-readiness review covering product,
  SRE, security, privacy, data and platform concerns.

## 15. Documentation And Governance

- [x] `DOC-001` `PROJECT.md` records purpose, principles, memory layers, model
  strategy, priorities, scope limits, and key decisions.
- [x] `DOC-002a` `ARCHITECTURE.md` documents the current event flow, trust
  boundaries, review gate and production target.
- [x] `DOC-003a` Current evidence and hypothesis schemas plus target memory and
  review invariants are linked from the project compass.
- [x] `DOC-005a` Current local/runtime safety configuration is documented without
  real secrets in `.env.example` and `SECURITY_AND_OPERATIONS.md`.
- [ ] `DOC-002` `P0` Add an architecture document showing trust boundaries,
  event flow, state transitions, queues/stores, model calls, human gates, and
  external side effects.
- [x] `DOC-002b` `ARCHITECTURE.md` diagrams durable intake/worker flow, trust
  boundaries, stores, model stages, human gate and disabled side effects.
- [ ] `DOC-003` `P0` Document canonical schemas and invariants for incidents,
  observations, evidence, hypotheses, analysis revisions, reviews, knowledge,
  and publications.
- [x] `DOC-003b` `CANONICAL_SCHEMAS.md` documents implemented records and
  invariants; unimplemented knowledge/publication records are explicit.
- [ ] `DOC-004` `P0` Create ADRs for production storage/checkpointer, queue,
  identity/RBAC, model/provider, knowledge retrieval, object storage, retention,
  and external publication.
- [x] `DOC-004a` ADR 0001 records the accepted MySQL store/checkpointer/queue
  decision; other production decisions remain open.
- [ ] `DOC-005` `P0` Document local, test, staging, shadow, and production setup
  without putting real secrets or customer data in examples.
- [x] `DOC-005b` `SETUP_GUIDE.md` documents safe local/test setup and required
  boundaries for future staging, shadow and production environments.
- [ ] `DOC-006` `P1` Publish reviewer guidance explaining confidence,
  contradiction, data gaps, stale revisions, approval boundaries, and how
  to report a bad analysis.
- [x] `DOC-006a` `REVIEWER_GUIDE.md` documents evidence, uncertainty,
  contradiction, stale revision and feedback expectations for the POC.
- [ ] `DOC-007` `P1` Publish model/prompt/rule evaluation reports and a release
  change log with known limitations.
- [ ] `DOC-008` `P1` Define review/expiry dates for service metadata, detection
  rules, suppression rules, runbooks, and curated knowledge.
- [ ] `DOC-009` `P1` Maintain a data inventory with classification, purpose,
  store, region, access, retention, deletion, and downstream processors.
- [x] `DOC-009a` `DATA_INVENTORY.md` identifies current POC stores, purpose,
  access and explicitly missing retention/deletion/processor controls.
- [ ] `DOC-010` `P1` Link every production release to its DoD evidence: test
  report, eval report, security scans, migration result, restore drill, load
  result and dashboards.
- [x] `DOC-010a` `RELEASE_EVIDENCE.md` defines required immutable release
  evidence; no production release has been asserted.

## Future Milestone DoD: Shadow-Ready v0.1

This is not the active Local-Safe v0.1 finish line. It remains the required
gate before the system may read approved production telemetry. Shadow mode may
not notify responders, create external tickets, publish documents, or perform
remediation. See `SAFE_COMPLETION_PLAN.md` for the current local closure gate
and the dependency order for resuming this work.

- [ ] A versioned input/event schema and durable event-before-ack queue exist
  (`ING-005`, `ING-008`).
- [ ] New and out-of-order observations update an existing incident through
  versioned analysis revisions (`ING-009` through `ING-014`).
- [ ] Production MySQL checkpointer, queue leasing, idempotent nodes, and
  crash recovery are verified (`REL-003` through `REL-010`).
- [ ] Full recursive redaction, data classification, secure secrets, TLS,
  encryption, RBAC, audit, and prompt-injection controls are implemented
  (`EVD-009`, `EVD-013`, `SEC-005` through `SEC-014`).
- [ ] Each connector passes its contract suite and records source provenance
  (`SRC-006` through `SRC-011`).
- [ ] Hypotheses use a typed schema, support abstention, cite stable evidence,
  and pass the independent grounding gate (`EVD-010` through `EVD-012`,
  `COR-007` through `COR-011`).
- [ ] Every LLM call has timeouts, bounded retries, structured output, metadata,
  usage/cost accounting, hard budgets, and deterministic degraded behavior
  (`LLM-007` through `LLM-013`).
- [ ] Structured logs, metrics, traces, redaction checks, dashboards, and alerts
  cover the entire intake-to-analysis path (`OBS-003` through `OBS-007`).
- [ ] CI, API/E2E/update/idempotency/security tests, and the labeled evaluation
  suite enforce agreed quality gates (`TST-004` through `TST-014`).
- [ ] A reproducible non-root build, staging/shadow environment, validated
  production configuration, and tested kill switches exist (`DEP-003` through
  `DEP-009`).
- [ ] Shadow publishing is technically blocked at both application and
  destination-credential levels.
- [ ] At least 50 representative incidents over at least 14 days have been
  evaluated in shadow mode, with no critical data leak or external side effect.
- [ ] Citation validity, unsupported-claim rate, top-3 usefulness, abstention,
  latency, failure, and cost meet the ratified thresholds.
- [ ] A reviewer game day shows that the decision brief is understandable,
  traceable, and faster than the baseline.

## Controlled Pilot DoD

- [ ] Every Shadow-Ready criterion remains green under production telemetry.
- [ ] SSO/RBAC and immutable reviewer audit records are active.
- [ ] Stale-review protection and analysis revision diffs are active.
- [ ] Draft postmortems remain internal and have a separate publish approval
  gate (`REV-006` through `REV-011`).
- [ ] Outbox/idempotency and partial-failure recovery are tested against sandbox
  Slack/GitHub/document destinations (`REV-012`, `REV-013`, `REL-006`).
- [ ] Approved knowledge memory is available with filter-first retrieval,
  citations, poisoning controls, retention, and measured retrieval quality
  (`MEM-007` through `MEM-014`).
- [ ] Pilot access is limited to named services and reviewers; kill switches are
  visible in the UI/runbook.
- [ ] No critical/high security findings remain open.

## General Availability Release Gate

A release is production-ready only when all conditions below are true:

- [ ] No `P0` criterion in this document is open.
- [ ] Every `P1` criterion is complete or has a documented, time-bounded risk
  acceptance.
- [ ] CI, security, migration, connector contract, end-to-end, evaluation, load,
  soak, and recovery suites pass on the exact release artifact.
- [ ] The latest gold-set and shadow/pilot results meet all ratified quality,
  calibration, safety, latency, reliability, and cost thresholds.
- [ ] A backup restore, worker crash, model outage, source outage, alert storm,
  stale review, and duplicate-publication drill have succeeded.
- [ ] Dashboards, alerts, error budgets, runbooks, capacity, and monthly cost
  controls are active.
- [ ] Release evidence includes security/privacy, SRE/platform,
  incident-management and reviewer results.
- [ ] Kill switches were tested during the release rehearsal.
- [ ] External publication cannot occur without authentication, authorization,
  exact-draft approval, audit record, and idempotent outbox delivery.
- [ ] Automatic remediation remains absent or disabled; adding it requires a
  separate safety design and production-readiness review.

## Recommended Implementation Order

1. **Correct incident lifecycle:** schemas, durable queue, event append,
   idempotency, revisions, resolved events, and concurrency control.
2. **Trustworthy evidence:** recursive redaction, provenance, stable IDs,
   append-only storage, data quality, and prompt-injection boundaries.
3. **Production persistence:** MySQL checkpointer, migrations, object storage,
   retention, deletion, backup, and restore.
4. **Reliable structured reasoning:** typed hypotheses, abstention, independent
   grounding, model timeout/fallback, call metadata, and hard budgets.
5. **Evaluation before memory:** build the gold dataset and quality gates so the
   effect of each later feature can be measured.
6. **Curated knowledge memory:** approved records, filter-first retrieval,
   citations, access control, expiry, and retrieval evaluation.
7. **Safe human and publication flow:** SSO/RBAC, revision-aware review, exact
   draft approval, immutable audit, outbox, and destination idempotency.
8. **Operational production layer:** observability, CI/CD, packaging, IaC,
   capacity, load/chaos testing, runbooks, game days, and staged rollout.

## Definition Of Done For Any Checklist Item

An individual item may be checked only when:

- implementation and configuration are committed;
- automated positive, negative, boundary, and failure-path tests pass;
- telemetry makes success and failure observable;
- security/privacy implications are reviewed;
- documentation and operator/reviewer behavior are updated;
- backward compatibility is addressed where needed; and
- the change is evaluated against quality, latency, and cost baselines.
