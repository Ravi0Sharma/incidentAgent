# Production Hardening and Railway Migration Plan

Status: long-term hardening reference; Local-Safe closure plan active  
Target: safe local POC closure first; shadow deployment and controlled pilot later  
Last updated: 2026-07-22

This document turns the larger
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md) checklist into a smaller,
prioritized delivery plan. It also describes how to move the incident agent
from a local development setup to Railway without weakening the evidence,
privacy, or human-review boundaries.

The immediate goal is **not unattended incident response**. The first hosted
release should be a read-only shadow system that produces reviewable analyses
without publishing or changing production systems.

## Current Scope Boundary

The active, bounded plan is [`SAFE_COMPLETION_PLAN.md`](SAFE_COMPLETION_PLAN.md).
It covers every non-Railway hardening concern in this document while declaring
the difficult production work as an explicit deferred track. It does **not**
weaken the requirements in this document or the production readiness checklist.

Railway is excluded from the active plan. The sections beginning **Railway
target architecture** and **Railway deployment gates** are retained as future
reference only: do not provision Railway, create a hosted service, or copy
credentials as part of the current work.

## What is already strong

- The agent constrains the incident window before collection.
- Logs are normalized, grouped, reduced, and redacted before model use.
- Deterministic rules and candidate scoring run before semantic reasoning.
- The agent can abstain when evidence is insufficient.
- Model tools are bounded and read-only.
- Human approval exists before a postmortem is produced.
- Webhook authentication, replay protection, input schemas, and size limits
  provide a useful ingestion baseline.
- Incident events and queued jobs are persisted atomically before the webhook
  is acknowledged.
- External publishing is disabled by default.

These are the right foundations. The main production risk is not the number of
features; it is whether every claim can be reproduced from canonical evidence
and whether long-running jobs remain safe under retries, crashes, and multiple
workers.

## Target incident flow

```text
Signed alert
  -> canonical alert event + incident revision
  -> bounded initial collection
       logs: aggregates + representative samples
       metrics: incident window + baseline
       traces: representative failures and dependency paths
       deploy/config/Kubernetes: verified changes
  -> normalize + redact + measure data quality
  -> canonical typed evidence graph
  -> deterministic candidate scoring
  -> evidence sufficient?
       no  -> targeted verification plan
              -> allowlisted collection
              -> append evidence revision
              -> rescore
       yes -> continue
  -> zero to three structured hypotheses, or explicit abstention
  -> independent claim-level grounding check
  -> human review of an exact immutable revision
  -> RCA may remain "unknown"
  -> postmortem draft
  -> separate approval of the exact draft
  -> idempotent outbox publication
```

## Priority 0: required before Railway receives real incident data

### 1. Introduce explicit runtime modes

Use an explicit value such as `APP_ENV=local|shadow|production`. Do not infer
safety policy only from hostnames or the presence of an API key.

- [ ] `local` may use fixture connectors, a local model, the current long local
      model timeout, and opt-in local tracing.
- [ ] `shadow` must use real read-only sources, must never publish externally,
      and must clearly label every result as shadow output.
- [x] `production` must fail startup when required connectors, authentication,
      database, model, redaction, or review configuration is missing.
- [x] Mock Loki, Prometheus, deploy, or model responses must be impossible in
      `shadow` and `production`.
- [x] Phoenix/model tracing inputs and outputs must be forced off outside
      `local`, even if a conflicting environment variable is supplied.
- [x] `PUBLISH_EXTERNAL=false` remains enforced for shadow releases.

Current evidence (2026-07-28): `utils/runtime_config.py` validates both secure
runtime modes before FastAPI starts, `webhook/api.py` requires webhook and
review authentication in both modes, and
`tests/test_operational_baselines.py`/`tests/test_scope_safety.py` cover mock,
publishing, tracing and authentication failures. Explicit shadow labelling in
every rendered result remains open, so the section is not complete.

Acceptance criterion: a CI test proves that each unsafe configuration fails
closed before the server starts accepting traffic.

### 2. Make collection iterative and evidence-driven

The local scope-expansion path now forms a bounded investigation loop. Tool
results become canonical evidence and affect deterministic scores before
another interpretation is generated.

- [x] Collect the alert service first, then expand only from observed
      dependencies, traces, deploys, or an approved service map.
- [x] Append every targeted query and compact result summary to a typed
      investigation revision in checkpointed incident state.
- [x] Normalize, redact, deduplicate, and score newly collected evidence through
      the same pipeline as initial evidence.
- [x] Limit expansion depth, services, time range, calls, bytes, and total
      elapsed time.
- [x] Make reviewer feedback request targeted evidence instead of jumping
      directly back to free-form interpretation.
- [x] Record why the agent stopped: enough evidence, budget exhausted, source
      unavailable, or safe abstention.

Current local evidence (2026-07-28): `investigation-loop/v1` controls at most
two expansion rounds by default and records query/result summaries in
`investigation-revision/v1`. The review HTML exposes rounds, retained bytes,
query IDs and stop reason. `tests/test_investigation_loop.py` covers A→B
evidence changing the candidate ranking, source failure, safe abstention,
scope, round, remote-query, byte and elapsed-time limits. The graph checkpoint
persists these revisions; a separately queryable evidence-revision table is
still future hardening, not required by this local acceptance criterion.

The pre-review path also carries `incident-analysis-deadline/v1` from
collection planning through model/tool calls. `model-usage-ledger/v1` records
provider-reported token usage and optional explicitly configured cost
estimates. This is visible in review and the immutable analysis snapshot.
Already-running initial connector requests remain governed by their individual
timeouts rather than cooperative cancellation.

Local acceptance criterion: the selected clear-evidence, insufficient-evidence
and tied-candidate scenarios produce the expected supported/abstained review
states. Cross-service A→B remains regression coverage, not an active release
gate for the current data-focused pass.

### 3. Improve collection without sending all raw data to the model

More data is not automatically better. Preserve full raw records in their
source systems and create a bounded, reproducible evidence pack.

- [ ] Store full-window aggregate counts and rates.
- [ ] Sample first, peak, last, rare, and representative errors across service,
      pod, region, route, and error type.
- [ ] Include incident-window metrics plus a comparable healthy baseline.
- [ ] Retrieve traces that discriminate between the leading candidates.
- [x] Record sampling rules, query boundaries, counts before/after reduction,
      truncation, and source freshness.
- [x] Allow an operator to follow an evidence reference back to the source
      query without copying unrestricted raw data into the report.

Current local evidence (2026-07-28): `connector-provenance/v2` carries a
sanitized `incident-query/v1` replay specification and stable query ID;
`source-quality/v1` records fetched/reduced/quarantined/duplicate/clock and
freshness fields. Query IDs survive grouping and evidence-graph construction
and are visible in the review UI. Real-backend replay authorization remains a
Shadow gate.

Acceptance criterion: the same fixture input always produces the same bounded
evidence pack and no configured secret or personal-data canary reaches it.

Current pre-review evidence: `scripts/evaluate_pre_review.py` covers eight
deterministic ingest-to-score counterexamples, while the allowlisted public
corpus path in `PRE_REVIEW_EVALUATION.md` measures parser, timestamp, sampling,
collision, and fragmentation behavior without treating log-template IDs as
causal labels.

### 4. Establish canonical evidence and label quality

Heuristic schema detection is acceptable for local fixtures, but production
connectors should identify their source and schema explicitly.

Canonical fields should include, when present:

- tenant, environment, cluster, namespace, service, route, and dependency;
- level, error type, trace ID, request ID, deploy ID, and configuration version;
- event time, ingestion time, timestamp quality, source, schema version, and
  provenance;
- incident ID, evidence ID, revision, content hash, and sensitivity class.

Required changes:

- [x] Give every current evidence connector and targeted log search an explicit
      source and schema ID.
- [ ] Parse structured JSON log bodies before applying label aliases.
- [ ] Quarantine unknown schemas or records missing a usable service or time.
- [ ] Measure unknown-schema rate, missing-field/timestamp rate, freshness, truncation,
      parse failures, clock skew, and duplicates.

  Implemented local subset: `source-quality/v1` measures every listed field
  except true source-vs-ingestion clock skew, which requires a trustworthy
  backend ingestion timestamp. Unknown-schema quarantine for structured JSON
  bodies also remains open.
- [ ] Define typed canonical records for alerts, logs, metrics, traces, deploys,
      configuration, and Kubernetes events.
- [ ] Keep source provenance and revision identity through grouping and
      summarization.

Acceptance criterion: a report claim references stable evidence IDs whose
content and source query can be reconstructed for the reviewed revision.

### 5. Replace Markdown-as-truth with typed hypotheses

Markdown should be a rendering of validated analysis, not the authoritative
model output. Allow zero to three hypotheses; never force three alternatives or
percentages when the evidence cannot support them.

Each hypothesis should contain:

```text
hypothesis_id
claim
claim_type
causal_status
mechanism
supporting_evidence_ids[]
contradicting_evidence_ids[]
assumptions[]
evidence_gaps[]
confidence_band
next_verification
```

- [x] Validate the interpretation response against a strict schema.
- [x] Reject unknown evidence IDs and unsupported causal language.
- [x] Run an independent claim-by-claim grounding check.
- [x] Use qualitative confidence bands until model confidence is calibrated on
      a labelled evaluation set.
- [x] Render pre-review Markdown and UI from the validated structure.
- [ ] Render later RCA and postmortem drafts from the approved typed structure.
- [x] Permit a clean abstention with concrete missing evidence and next steps.

Current local evidence (2026-07-28): the interpretation model must return
`model-interpretation/v1`; free-form Markdown is no longer authoritative.
`claim-grounding/v1` resolves every cited ID against the evidence graph and
matching deterministic candidate, downgrades observed causal claims, requires
a validated cross-event semantic link for mechanisms, caps confidence for
source failure/truncation, and removes risky actions without proposal/approval
markers. Review Markdown is rendered only after this pass. Seven focused tests
cover the contract. RCA/postmortem migration intentionally remains in the
later-work list.

Acceptance criterion: every factual and causal claim is supported, explicitly
marked as an assumption, or blocks approval.

### 6. Keep the local-model fallback honest

The local fallback must not invent generic causes or fixed `70/20/10`
confidence values merely to satisfy formatting.

- [x] Make fallback output a deterministic rendering of actual scored
      candidates and evidence gaps only.
- [x] If no supported candidate exists, return abstention.
- [x] Clearly label degraded/local fallback output in the UI and stored record.
- [x] Prevent degraded RCA or postmortem generation from adding new causal
      claims.
- [x] Keep the long local LLM timeout documented as local-only.
- [ ] In hosted mode use per-call timeouts, a total job deadline, cancellation,
      retry classification, and a token/cost budget.

Acceptance criterion: disabling the LLM cannot create a cause that was absent
from deterministic evidence.

## Priority 1: runtime correctness before scaling

### Durable worker execution

The API should enqueue work and return. A separate continuously running worker
should own analysis jobs.

- [x] Add a dedicated worker entry point; do not rely on the API request to
      drain a limited number of queued jobs.
- [x] Heartbeat or renew the job lease while a model or connector call is
      active.
- [x] Set the lease longer than the maximum non-renewed operation, or cancel
      before the lease expires. Runtime validation keeps heartbeat below half
      the lease and the active worker cancels rather than commits after lease
      loss.
- [ ] Retry only classified transient failures with backoff and jitter.
- [x] Move exhausted jobs to a visible dead-letter state.
- [x] Lock by incident so two workers cannot publish competing revisions.
- [ ] Prevent an older completed job from overwriting a newer incident revision
      in the UI.
- [ ] Make every state transition idempotent.

### Replace process-local durability assumptions

- [ ] Replace the process-local/single-connection MySQL saver behavior with a
      multi-process-safe implementation and connection pooling.
- [ ] Generate incident IDs in MySQL rather than from a local SQLite/file
      counter.
- [ ] Store the exact input event, evidence revision, prompt version, model
      version, and policy version required for reproducible reprocessing.
- [ ] Never select an arbitrary latest event, such as reviewer feedback, as the
      original alert during reprocessing.
- [ ] Run database migrations once as a release step; the runtime database role
      should not require DDL privileges.

Acceptance criterion: killing and restarting API or worker processes during an
incident neither loses work nor produces duplicate final revisions.

## Priority 2: review, security, and safe publication

- [ ] Enforce approval policy on the server, not only in the UI.
- [ ] Bind approval to `incident_id`, hypothesis ID, evidence revision, policy
      version, and content hash.
- [ ] Disable approval for abstained, degraded, stale, or insufficiently
      grounded analyses.
- [ ] Require a separate human approval for the exact postmortem draft.
- [ ] Publish through an idempotent transactional outbox.
- [ ] Add SSO, role-based authorization, CSRF protection, audit events, and
      tenant/environment isolation before a production pilot.
- [ ] Define encryption, secrets rotation, retention, deletion, backup,
      restore, and egress policies.
- [ ] Keep connector credentials read-only and least-privileged.

Acceptance criterion: a changed draft or evidence revision invalidates prior
approval, and repeating a publish request cannot create duplicate documents.

## Railway target architecture

```text
Internet / alert source
        |
        v
Railway incident-api service  --->  Railway MySQL service
        |                                ^
        | enqueue                         | claim/heartbeat/result
        v                                |
Railway incident-worker service --------+
        |
        +--> read-only observability/deploy connectors
        +--> approved model endpoint
        +--> external trace backend with payload capture disabled
```

Recommended Railway setup:

1. Create isolated `staging` and `production` environments. Use staging as the
   initial shadow environment and do not copy production secrets into preview
   environments.
2. Deploy the API and worker as separate services from the same repository.
3. Attach MySQL through Railway reference variables and map them to the
   existing `MYSQL_*` configuration, or add one validated database-URL parser.
4. Give only the API a public domain. Keep the worker and database private.
5. Use sealed variables for credentials where practical, keep environment
   values separate, and never upload the local `.env` as a production config.
6. Do not use `start-agent.sh` as the Railway command. It is a local convenience
   launcher that also starts local-only components.
7. Start the API on `0.0.0.0:$PORT`, for example:

   ```sh
   uvicorn webhook.api:app --host 0.0.0.0 --port $PORT
   ```

8. Add a dedicated worker command after the continuous worker entry point has
   been implemented.
9. Configure the API deployment health check to use `/readyz`, but first make
   that endpoint a fast, side-effect-free dependency check. Keep `/healthz` as
   liveness. Railway health checks govern deployment traffic switching; they
   are not continuous uptime monitoring, so add an external monitor as well.
10. Do not depend on local `output/`, SQLite counters, or `.phoenix_data` for
    shared durable state. Put records in MySQL and durable reports in approved
    object/document storage.
11. Keep a single API and worker replica until incident locking, leases, the
    checkpointer, and idempotency tests pass. When replicas are enabled, include
    Railway deployment, region, and replica IDs in structured logs.
12. Do not deploy the bundled local Phoenix process initially. Export only
    redacted metadata to an approved backend, or disable export until the data
    classification and retention policy is complete.

Important Railway behavior and configuration references:

- [Variables and sealed secrets](https://docs.railway.com/variables)
- [Isolated persistent and PR environments](https://docs.railway.com/environments)
- [Deployment health checks and `PORT`](https://docs.railway.com/deployments/healthchecks)
- [Replica and deployment reference variables](https://docs.railway.com/variables/reference)
- [Replica behavior and performance guidance](https://docs.railway.com/deployments/optimize-performance)

### Railway deployment gates

Before the first hosted deployment:

- [ ] Build and tests run in CI from a pinned lockfile/runtime version.
- [ ] Database migrations have a tested forward and rollback procedure.
- [ ] API and worker have separate commands and structured logs.
- [ ] Startup configuration fails closed for the selected environment.
- [ ] `/healthz` and `/readyz` are fast and do not modify the database.
- [ ] No raw model input/output tracing is enabled.

Before connecting real production observability data:

- [ ] Shadow mode and read-only connector permissions are verified.
- [ ] Redaction canary tests pass for every connector.
- [ ] Secrets, retention, backups, restore, and incident-response ownership are
      documented and tested.
- [ ] Job heartbeats, incident locking, idempotency, and stale revision handling
      pass crash/restart tests.
- [ ] An external uptime alert detects API unavailability independently of the
      application's own telemetry.

Before enabling a controlled pilot:

- [ ] Evaluation thresholds below pass on representative incidents.
- [ ] SSO/RBAC and server-side review authorization are active.
- [ ] Exact-draft approval and transactional outbox publishing are complete.
- [ ] A kill switch can immediately stop model calls, ingestion, workers, and
      publication independently.

## Evaluation and release evidence

Start with a small versioned set and grow it toward at least 100 reviewed
incidents or realistic fixtures. Include easy cases, ambiguous cases, missing
sources, clock skew, misleading deploys, duplicated logs, secret canaries, and
malicious log/prompt content.

Track at minimum:

- top-1 and top-3 hypothesis usefulness;
- supporting-citation precision and recall;
- unsupported factual and causal claim rate;
- correct abstention and harmful non-abstention rate;
- suppression, sampling, and source-unavailability misses;
- reviewer overrides and the reason for each override;
- end-to-end latency, connector/model timeouts, token use, and cost;
- queue delay, retries, lease recovery, stale revisions, and duplicates.

Suggested release progression:

| Stage | Traffic | External action | Minimum exit evidence |
| --- | --- | --- | --- |
| Local fixtures | Synthetic/replayed | None | Deterministic regression and redaction tests pass |
| Railway staging | Synthetic/replayed | None | Restart, migration, timeout, and concurrency tests pass |
| Shadow | Sampled real incidents | None | At least 50 reviewed incidents or 14 stable days, with agreed safety and quality thresholds |
| Controlled pilot | Limited real incidents | Exact approved draft only | SSO/RBAC, audit, outbox, rollback, and on-call ownership proven |
| Broader production | Gradual expansion | Policy-controlled | Error budget and quality metrics remain within agreed thresholds |

Threshold values should be agreed with an SRE/domain reviewer after the first
labelled baseline. A useful production metric must distinguish a correct
abstention from an unsupported confident answer.

## Recommended implementation order

1. Runtime modes and fail-closed production configuration.
2. Dedicated worker, heartbeats, incident locking, and revision ordering.
3. Canonical evidence schema, explicit connector schemas, and quality metrics.
4. Iterative collection and deterministic rescoring.
5. Typed hypotheses plus independent claim grounding.
6. Honest deterministic local fallback.
7. Railway staging deployment with no real data.
8. Evaluation suite and labelled baseline.
9. Read-only Railway shadow period.
10. SSO/RBAC, exact-draft approval, outbox, and controlled pilot.

## Assistance and ownership needed

The project can continue as a single-developer build, but production approval
should include independent help in these areas:

- an SRE or incident responder to label evidence and judge hypothesis utility;
- a security reviewer for identity, secrets, egress, retention, and threat
  modelling;
- an application/database reviewer for queue leases, concurrency, migrations,
  backup, and restore;
- service owners to define correct labels, dependencies, runbooks, and source
  access boundaries;
- a named operator for Railway deployment, alerts, rollback, and the kill
  switch.

The most valuable assistance is not more prompt wording. It is high-quality
labelled incidents, verified service metadata, reproducible evidence, and
independent review of unsupported claims. Prompt improvements should then be
measured against that evidence rather than judged from one demo incident.

## Relationship to the full readiness checklist

An unchecked parent item in [`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md)
can remain correct even when some child checks are complete: local code may
exist while production proof, ownership, monitoring, or failure testing is
still missing. Do not check a parent solely because the happy path works.

The checklist's highest-value incomplete areas are currently:

- queue worker ownership, leases, retries, and crash recovery;
- cross-source canonical evidence and claim-level grounding;
- total deadlines, cancellation, and model usage budgets;
- exact-draft approval and idempotent publication;
- gold-set, adversarial, failure-mode, and shadow evaluation;
- authentication, authorization, secrets, retention, backup, and restore.

Update the readiness audit when implementation changes land so counts and
descriptions do not become stale. This plan sets order; the full checklist
remains the Definition of Done.
