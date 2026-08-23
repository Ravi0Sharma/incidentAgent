# Safe Completion Plan: Local-Safe v0.1

Status: proposed closure plan  
Last updated: 2026-07-22  
Scope: areas 2–7, 10–13, 15, the Shadow-Ready DoD, and the non-Railway
hardening work in `PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md`. The related
review, security, and packaging constraints from areas 8, 9, and 14 are also
included where the hardening plan depends on them.

## Decision This Plan Makes

The repository cannot truthfully be declared **Shadow-Ready** while the hard
production controls remain open. In particular, real connector authorization,
data classification/retention, multi-process recovery, model accounting,
observability, CI, a labelled evaluation set, and operational ownership cannot
be replaced by local code or documentation.

The safe way to finish the current giant task is therefore to close a smaller,
honest milestone first:

> **Local-Safe v0.1** is a fixture/replay-only decision-support prototype. It
> accepts no production telemetry, makes no external writes, has no hosted
> deployment target, and makes no Shadow-Ready or production claim.

Railway work is deliberately excluded from this plan. The Railway sections in
`PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md` remain a future reference only; do
not create a Railway environment, publish a service, or copy credentials as
part of Local-Safe v0.1.

## What “Finish” Means

This milestone finishes the *local POC workstream*, not the whole production
backlog. It leaves the difficult work visible, owned, and non-actionable until
the necessary people, systems, and evidence exist. No unchecked production
criterion is to be marked complete merely because a local fixture succeeds.

The project may stop active feature work after the Local-Safe exit gate below.
It must not be connected to real incident sources or represented as shadow or
production software until the separate Shadow track is completed.

## Local-Safe v0.1 Exit Gate

All items below need dated evidence in a small closure record before this
milestone is declared complete.

1. **Safety boundary is confirmed.** `PUBLISH_EXTERNAL=false`; no production
   connector, publisher, or reviewer credentials are present; there is no
   public webhook endpoint; all demonstrations use fixtures or approved
   synthetic data.
2. **The local validation procedure is reproducible.** Use Python 3.11,
   `.venv/bin/python`, and a disposable MySQL 8.4 database as documented in
   `SETUP_GUIDE.md`. Record the exact command, dependency environment, MySQL
   availability, pass/fail result, and any skipped suite. A historical test
   count is not a current result.
3. **The fixture evidence path remains safe.** Run the existing deterministic
   contract, redaction, evidence-pack, hypothesis, and prompt-budget checks in
   the prepared local environment. Record their output; do not use real
   telemetry to make the command pass.
4. **Documentation has one coherent status.** `PROJECT.md`,
   `PRODUCTION_READINESS.md`, this plan, `TEST_STRATEGY.md`, setup/runbook
   guidance, data inventory, and release-evidence template agree that the
   product is a local POC and that Shadow/production gates are open.
5. **The hand-off is explicit.** Create a dated closure record that links the
   validation evidence, lists the deferred workstreams below, identifies the
   exact restart point, and states that real-data ingestion and publishing are
   forbidden. A named release owner is not required for this local solo-POC;
   Shadow and production promotion still require accountable owners. Do not
   delete existing local incident artifacts until their retention/deletion
   treatment has been decided.

If the prepared local MySQL environment is unavailable, the correct outcome is
**“Local-Safe closure pending validation”**, not a false green result.

## Delivery Sequence

### Phase 0 — Freeze the boundary (first)

- Accept Local-Safe v0.1 as the only active release target.
- Keep `PUBLISH_EXTERNAL=false` and fixture/mock inputs as the only permitted
  operating mode; do not relax this for a demo.
- Capture the current test prerequisite issue and establish the canonical
  `.venv/bin/python` command. Do not use the system `python3` as evidence when
  it lacks project dependencies.
- Make one closure record from the Local-Safe exit gate and record the exact
  checklist item from which later work resumes.

### Phase 1 — Reconcile and preserve the POC (small, bounded work)

- Re-run the documented local suite only in an environment that can reach its
  disposable MySQL instance. Preserve the report rather than editing checklist
  boxes from memory.
- Correct stale status wording and broken internal links. Update the audit date
  and the documented test result only from that report.
- Exercise the fixture workflow and prompt-budget script once. Keep generated
  reports local and redacted.
- Record the known limitations and the exact restart point in the closure
  record.

No redesign, new connector, model migration, hosted deployment, or real-data
collection is permitted in this phase.

### Phase 2 — Stop safely

- Freeze feature work after the exit gate passes.
- Keep the repository and its test fixtures; retain the production checklist as
  the authoritative deferred backlog.
- On resumption, begin with the dependency order in the next section rather
  than selecting isolated UI/model features.

## Deferred Production Track: Dependency Order

These are deliberately left difficult. They are grouped so a future team can
restart safely without reopening the entire checklist at once.

| Track | Readiness areas and hardening-plan coverage | Cannot be closed without |
| --- | --- | --- |
| 1. Canonical incident record | Area 2 (`ING-010`, `ING-015`, `ING-018`), Area 4 (`EVD-009`–`EVD-014`, `EVD-018`–`EVD-020`), Area 10 (`REL-003`–`REL-011`) and hardening priorities 2–4 | append-only cross-source observations, revision-safe worker execution, migrations/backup/restore, real concurrency and crash evidence |
| 2. Trusted source collection | Area 3 (`SRC-006`–`SRC-016`) and hardening priorities 2–4 | approved read-only source identities, representative backend fixtures, source ownership, query provenance, schema/freshness and pagination evidence |
| 3. Grounded analysis | Area 5 (`COR-007`–`COR-017`), Area 6 (`LLM-007`–`LLM-018`), and hardening priorities 1, 4–6 | strict typed output, independent grounding, cancellation/deadlines, real usage and cost ledger, adversarial evaluation, calibrated labels |
| 4. Governed memory, review, and security | Area 7 (`MEM-003`–`MEM-015`), related areas 8/9, and hardening priority 2 | authorization boundary, approved knowledge sources, retention/deletion policy, retrieval evaluation, SSO/RBAC, immutable audit, exact-draft approval, outbox, least-privilege credentials and egress controls |
| 5. Operable service | Area 10 (`REL-012`–`REL-017`), Area 11, Area 13, and non-Railway hardening priority 1/2 | independent worker, backpressure, full logs/metrics/traces, dashboards/alerts, capacity and cost benchmarks, game days |
| 6. Proof, packaging, and release governance | Areas 12, 14, and 15 plus evaluation/release-evidence sections of the hardening plan | CI, reproducible build/container, environment isolation, coverage/security gates, gold set with SRE adjudication, E2E/load/chaos/restore reports, owners and signed release evidence |

Tracks 1–3 are prerequisites for meaningful Shadow evaluation. Track 6 must
establish the measurement system before knowledge-memory or model-routing
claims are promoted. Tracks 4–6 require named owners and organizational
decisions; they are not suitable for a local-only implementation sprint.

## Area-by-Area Resume Map

This map keeps every requested area visible while avoiding duplicate
checklists. IDs refer to `PRODUCTION_READINESS.md`; detailed methods remain in
`TEST_STRATEGY.md`.

| Area | Local-Safe disposition | First production-safe batch when work resumes |
| --- | --- | --- |
| 2. Alert intake and lifecycle | Preserve current contract and event-before-ack local baseline; do not claim late connector observations or distributed fairness are done. | Append connector observations into immutable revisions, run lifecycle/update/concurrency tests, then prove reprocess/dead-letter/rate-limit behavior. |
| 3. Connectors | Keep mocks/local contracts only. No production credential or backend is in scope. | Establish one approved read-only log/metric/deploy source contract end-to-end before adding trace/Kubernetes/flag sources. |
| 4. Evidence/provenance/timeline | Preserve redaction and compact fixture packs; do not infer complete sink redaction or append-only cross-source proof. | Make canonical evidence append-only with source query reconstruction, sink redaction, citation validation, untrusted-data boundaries and quality metrics. |
| 5. Detection/correlation/hypotheses | Retain deterministic candidates and safe abstention as local behavior; scores remain uncalibrated. | Deliver final typed hypotheses, mechanism/contradiction/reranking and independent grounding, then calibrate against labels. |
| 6. LLM boundary | Keep compact contexts and deterministic fallback; no provider or cost guarantee is made. | Add structured output, cancellation/timeouts, call ledger, hard budgets, provider policy/fallback and injection corpus. |
| 7. Memory | Keep local approved-summary boundary only; no cross-tenant or production retrieval claim. | Add retention/authorization, evaluated filter-first retrieval and correction/deletion lifecycle. |
| 10. Reliability | Keep a local MySQL prerequisite for the POC; no multi-process durability or restore claim. | Add migrations/pooling, dedicated worker/heartbeats/deadlines, outbox, caps, crash/restore/failover/backpressure drills. |
| 11. Observability | Keep local redacted log/metric primitives; dashboards and operational alerts are deferred. | Propagate context end-to-end, scan telemetry for leaks, then build dashboard/alert/canary and immutable audit access controls. |
| 12. Tests/evaluation | Preserve existing local tests as a baseline only. | Build CI/coverage gates, E2E/update/concurrency/redaction corpus, 100-case labelled dataset, evaluator, adversarial/load/soak and release gate. |
| 13. Performance/cost | Keep static limits only; no SLO, capacity or provider-cost claim. | Capture real per-node/provider measurements, enforce ratified budgets, then benchmark capacity/caching/early-exit behavior. |
| Related review/security | Keep all external publishing and real-data access out of the POC. | Add server-side authorization, revision-aware and exact-draft approval, audit/outbox, encryption/secrets/egress and adversarial security proof before pilot. |
| Related packaging/operations | Do not package or deploy the POC as a hosted service. | Build provider-neutral reproducible artifact/configuration, environment separation, migrations, kill switches and rollback evidence before selecting any host. |
| 15. Documentation/governance | This plan, the updated compass and readiness annotations are the local closure documentation. | Add ADRs for unresolved architecture decisions, CI doc checks, ownership/expiry, complete data inventory, evaluation reports and signed release manifest. |

## Shadow-Ready v0.1 Remains a Future Gate

The Shadow-Ready DoD in `PRODUCTION_READINESS.md` is intentionally unchanged
as a safety gate. It may be attempted only after Tracks 1–3 and the applicable
security/review prerequisites have evidence. The final 50-incident/14-day
period, ratified quality thresholds, technical publication block, and reviewer
game day cannot be waived or replaced with this closure plan.

## Governance Rules for Resumption

1. Pick one track and one accountable owner; do not run an unbounded
   “production-hardening” sprint.
2. Open with an ADR when a work item selects storage, identity, provider,
   retention, object-store, or publication architecture.
3. Implement schema and tests before enabling a new source, model, memory, or
   external effect.
4. Close a readiness checkbox only with the mapped test/report/operational
   evidence. A child implementation note does not close its parent criterion.
5. Review this plan, data inventory, owners, and expiry dates at every release
   decision. Expired or unknown ownership blocks promotion.

## Required Closure Record Template

Use this as a single dated Markdown record; it is intentionally small.

```text
Local-Safe v0.1 closure date:
Commit/artifact identifier:
Environment: Python version, dependency environment, MySQL version/database:
Validation commands and results:
Fixture/redaction/prompt-budget evidence links:
Confirmed safety settings: PUBLISH_EXTERNAL=false; fixture-only; no public endpoint:
Known limitations and deferred tracks:
Decision: Local-Safe complete | pending validation
Explicit statement: not Shadow-Ready; not production-ready; Railway excluded
```

A named owner is deliberately omitted from this local closure template. Named
operational and release owners remain mandatory for future Shadow, pilot, and
production gates.

`RELEASE_EVIDENCE.md` remains mandatory for any future production candidate;
this local closure record is not a production release manifest.
