# Incident Agent - Project Compass

> This document is the shared reference for the project. Update it whenever we
> make a decision that changes the purpose, architecture, priority, or scope.

The detailed production Definition of Done and current readiness audit live in
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md). The matching verification
plan for areas 1-15 lives in [`TEST_STRATEGY.md`](TEST_STRATEGY.md).
The deduplicated execution order and project-wide progress view live in
[`PROJECT_MASTER_CHECKLIST.md`](PROJECT_MASTER_CHECKLIST.md); use it as the
working queue and keep the readiness file as the authoritative acceptance list.
All deliberately postponed work and its exact resume conditions are collected
in [`DEFERRED_WORK_CHECKLIST.md`](DEFERRED_WORK_CHECKLIST.md); it is a parking
register, not a competing work queue.
The prioritized hardening sequence and Railway migration gates live in
[`PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md`](PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md).
The dated blind OpenAI portfolio, full pre-review E2E evidence, token usage and
Railway cost-control finding live in
[`OPENAI_LIVE_EVALUATION_2026-08-09.md`](OPENAI_LIVE_EVALUATION_2026-08-09.md).
The current verified local runtime result and production-shadow go/no-go are in
[`SHADOW_READINESS_AUDIT_2026-08-14.md`](SHADOW_READINESS_AUDIT_2026-08-14.md).
The local canonical-evidence completion and required real-log revalidation for
the Arcvial shadow scope are in
[`ARCVIAL_SHADOW_PACKAGE_3_2026-08-14.md`](ARCVIAL_SHADOW_PACKAGE_3_2026-08-14.md).
The independent API/worker boundary, leases, heartbeats, backpressure and
direct crash-recovery evidence are in
[`ARCVIAL_SHADOW_PACKAGE_4_2026-08-14.md`](ARCVIAL_SHADOW_PACKAGE_4_2026-08-14.md).
The verified LogHub 2.0 intake, full raw-format audit, and parser findings live
in [`LOGHUB_2_EVALUATION_2026-08-09.md`](LOGHUB_2_EVALUATION_2026-08-09.md).
The bounded local-POC closure plan, explicit production deferrals, and
Railway-excluded scope are in [`SAFE_COMPLETION_PLAN.md`](SAFE_COMPLETION_PLAN.md).
The current support boundary and safety/change policy live in
[`OPERATING_CONTRACT.md`](OPERATING_CONTRACT.md).
The versioned webhook alert contract and current limits live in
[`ALERT_INPUT_CONTRACT.md`](ALERT_INPUT_CONTRACT.md).
The connector boundary and per-source request-policy contract live in
[`CONNECTOR_CONTRACT.md`](CONNECTOR_CONTRACT.md).
The evidence boundary, current schema, and redaction scope live in
[`EVIDENCE_CONTRACT.md`](EVIDENCE_CONTRACT.md).
The deterministic hypothesis candidate boundary lives in
[`HYPOTHESIS_CONTRACT.md`](HYPOTHESIS_CONTRACT.md).
The current memory/review boundary lives in
[`MEMORY_AND_REVIEW_CONTRACT.md`](MEMORY_AND_REVIEW_CONTRACT.md).
The implemented curated-memory boundary lives in
[`KNOWLEDGE_MEMORY.md`](KNOWLEDGE_MEMORY.md), and canonical durable-record
invariants in [`CANONICAL_SCHEMAS.md`](CANONICAL_SCHEMAS.md).
The current security and operations baseline lives in
[`SECURITY_AND_OPERATIONS.md`](SECURITY_AND_OPERATIONS.md).
The current and target architecture live in
[`ARCHITECTURE.md`](ARCHITECTURE.md), and release governance in
[`GOVERNANCE_AND_QUALITY.md`](GOVERNANCE_AND_QUALITY.md).
The complete visual system flow is [`SYSTEM_FLOW.svg`](SYSTEM_FLOW.svg).
Local setup and safe operating procedures live in
[`SETUP_GUIDE.md`](SETUP_GUIDE.md) and
[`OPERATOR_RUNBOOKS.md`](OPERATOR_RUNBOOKS.md).
Dataset selection must follow the actual workload environment rather than
public-corpus availability; the current decision gate and priority order are in
[`TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md`](TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md).

## Agreed POC Decisions

- The durable relational store is **MySQL**. `CHECKPOINTER=mysql` uses the
  real local MySQL 8+ saver; no SQLite or simulated runtime mode is supported.
- The intended POC trigger is an error alert from **Amazon CloudWatch**. The
  currently implemented Grafana/Alertmanager webhook remains the local input
  adapter until a CloudWatch adapter is built.
- POC reports are written only to the configured local `output/` folder. No
  Slack, GitHub, GitLab, ticket, or other external publishing is in scope.
- Named ownership and formal SLO governance are not POC scope. They may be
  restored for a later operated production service.
- The active completion target is **Local-Safe v0.1**: fixture/replay-only,
  no real production telemetry, no hosted deployment, and no external effects.
  Shadow-Ready remains a separate future gate; Railway work is explicitly
  deferred. See `SAFE_COMPLETION_PLAN.md`.

## Purpose

Incident Agent should help an incident handler quickly and safely understand
**what most likely went wrong in a system**. The agent receives an alert and
collects relevant logs, metrics, and deployment information around the right
time window. It reduces and structures the evidence, finds relationships, and
presents evidence-based hypotheses about the root cause.

The agent is decision support for humans. It is not an unattended replacement
for incident management.

## Desired Main Flow

```text
Alert
  -> constrain the incident and time window
  -> collect logs, metrics, and deploys
  -> normalize, group, filter, and correlate
  -> build a small evidence pack and use memory when needed
  -> AI suggests an explanation/root cause with evidence and uncertainty
  -> human review
  -> approved: create a postmortem draft/document
```

New observations can arrive during the incident. They should be attached to the
same incident and timeline, then update or strengthen the hypotheses. They
should not make the agent forget previously verified evidence.

## Implementation Principles

1. **Evidence before claims.** A conclusion must be traceable to timestamped
   logs, metrics, deploys, configuration, or another clear source. The agent
   must say when something is a hypothesis, not a fact.
2. **Compress before the LLM.** Raw data should not be sent directly to the
   model. Normalize, deduplicate, group, count frequency, narrow the time
   window, and build a bounded evidence pack first.
3. **Time is a first-class signal.** Correlation should weigh time, service,
   environment, labels, and dependencies. A deploy after a symptom is not a
   cause by itself, only additional context.
4. **Use deterministic logic where it is enough.** Rules, thresholds, and
   scoring should handle known patterns and selection. The LLM should be used
   when semantic interpretation, synthesis, and clear communication create real
   value.
5. **Humans approve publishing.** No postmortem or external publishing happens
   without explicit human review and approval.
6. **Security and privacy.** Secrets and personal data must be redacted before
   they reach models, durable memory, or reports.
7. **Cost and latency are requirements.** Every LLM call needs a clear purpose,
   bounded input, and a token/tool budget.

## Memory: What The Agent Needs To Remember

We separate memory into three levels so it stays useful without becoming
expensive or polluted by raw data.

| Level | Content | Lifetime | Use |
| --- | --- | --- | --- |
| Incident memory | Timeline, evidence, hypotheses, decisions, and review feedback for one incident id | During/after the incident according to retention | Resume and update the same investigation |
| Knowledge memory | Approved postmortems, known failure patterns, runbooks, and service dependencies | Long-term, curated | Retrieve a few relevant similar cases as context |
| Working memory | The small evidence pack for one model call | Only the call | Let the model reason efficiently |

**Memory rules**

- Store summaries and structured evidence, not unlimited raw logs.
- Tag every memory item with source, time range, service/environment,
  incident id, and security classification.
- Only human-approved conclusions may become long-term knowledge memory.
- Retrieval should be filter-first (service, environment, time, error type),
  then semantic, with a small number of hits and source references.
- Define retention, deletion, and retesting before memory is used in
  production.

## Model Strategy

The project currently defaults to a local OpenAI-compatible endpoint
(`http://127.0.0.1:1234/v1`). The design should remain portable to OpenAI
through configuration of `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and
`OPENAI_MODEL`.

When OpenAI is used, we should keep the same guardrails: sensitive data
redaction, small evidence packs, token budgets, traceable prompt/versioning, and
fixture-based evaluation before changing models or prompts.

## Current Code Foundation

- A LangGraph workflow takes the incident from alert, collection, and
  correlation to interpretation, human review, RCA, postmortem draft, and
  publishing steps.
- Inputs include logs, metrics, and deployment information.
- The code includes normalization, grouping, detection rules, scoring, evidence
  packs, semantic correlation, and PII redaction.
- The MySQL checkpointer makes it possible to resume workflow state locally.
- External publishing is disabled by default (`PUBLISH_EXTERNAL=false`).

This is a good foundation, but a MySQL checkpointer is mainly durable
**workflow state**. It is not, by itself, a finished curated and searchable
knowledge memory across incidents.

## Prioritized Development Direction

1. Make every incident timeline and evidence chain correct, traceable, and easy
   to review.
2. Ensure data compression and selection work before adding more LLM features.
3. Add curated knowledge memory for approved postmortems, rules, and service
   context, with retrieval, retention, and tests.
4. Make hypotheses comparable: likely cause, alternatives, supporting and
   contradicting evidence, uncertainty, and the next best investigation step.
5. Finish a reviewable postmortem flow where human approval is required before
   final document creation or publishing.
6. Harden operations: authentication, authorization, secrets, observability,
   error handling, evaluation, and a production checkpointer/database.

## Current Scope Limits

The project should not:

- automatically make production changes or remediation actions;
- present speculation as a verified root cause;
- send full log streams or sensitive data to a model;
- create or publish a final postmortem without human review;
- expand into a generic chatbot without an incident connection.

## Definition Of A Good Incident Analysis

An analysis is ready for review when it includes:

- the incident impact, affected services, and time window;
- an ordered timeline with relevant signals;
- one or more ranked hypotheses;
- clear evidence and sources for each hypothesis;
- uncertainties, counterevidence, and any data gaps;
- recommended next steps, without claiming they have already been performed.

A postmortem starts from the approved analysis and must clearly separate facts,
decisions, root cause, contributing factors, impact, and follow-up actions.

## Decision Log

| Date | Decision | Status/comment |
| --- | --- | --- |
| 2026-07-21 | A local model is used during development, but the integration surface should remain OpenAI-compatible. | Active |
| 2026-07-21 | Human review is required before a postmortem becomes final or is published. | Active |
| 2026-07-21 | Memory is split into incident memory, knowledge memory, and temporary working memory. | Target for continued design |
| 2026-08-01 | Public system datasets are evaluation corpora, not an implied support matrix. Further Spark-specific work is parked until Spark is part of the ratified target environment. | Active |

## When To Update This Document

Update `PROJECT.md` when we change the target shape, choose the memory solution,
decide retention/security levels, change the approval flow, or add a major data
source. Smaller implementation details belong near the code or in a technical
ADR.
