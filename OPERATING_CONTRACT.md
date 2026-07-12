# Incident Agent - Operating Contract

> This document records the current support boundary and the target safety
> behavior. It supports Area 1 in `PRODUCTION_READINESS.md`; it is not a claim
> that the project is production-ready.

## Current Support Boundary (v0)

| Capability | Current behavior | Production status |
| --- | --- | --- |
| Alert input | Grafana single-alert payloads and Alertmanager payloads validated by `grafana-alertmanager/v1`; only firing alerts are processed from an Alertmanager batch | Development adapter. The intended POC source is Amazon CloudWatch; its adapter remains to be built |
| Log evidence | Loki when configured; deterministic mock data when Loki is not configured | Mock fallback is development-only |
| Metric evidence | Prometheus when configured; deterministic mock data when it is not configured | Mock fallback is development-only |
| Change evidence | Current GitHub-compatible client or deterministic mock | Not POC scope. A future GitLab connector can replace it when change evidence is needed |
| Trace evidence | Trace/request IDs are extracted from collected logs | No trace-backend connector yet |
| Services | Entries in `config/services.yaml` have explicit tier/owner/dependency metadata; unknown services are rejected at intake | The configured service catalogue must be governed before production |
| Environments | `local`, `development`, `staging`, and `production` are accepted by default; an environment label is preferred and otherwise the configured default is used | Production matrix must be ratified with service owners |
| Model | Local OpenAI-compatible endpoint by default; endpoint/model/key are configurable | Provider policy, model evaluation, and production failure handling are pending |
| Workflow state | Local SQLite checkpoint and log store | Single-process development only |
| Review | Local browser review flow | Production identity, RBAC, audit, and stale-review protection are pending |
| Output | Local HTML report in the configured `output/` folder; external publishing is disabled by default | POC scope is local-folder output only |

The current build must not be described as supporting shadow, pilot, or general
availability production use. Those stages remain gated by
`PRODUCTION_READINESS.md`.

## Current Verified Safety Behavior

| Situation | Current behavior | Verification |
| --- | --- | --- |
| Production webhook secret is absent | Webhook authentication rejects the request | `A01-T03` subset: `test_scope_safety.py` |
| Webhook signature is invalid | Webhook authentication rejects the request | `A01-T03` subset: `test_scope_safety.py` |
| Production reviewer credentials are absent | Reviewer surface rejects the request | `A01-T03` subset: `test_scope_safety.py` |
| Loki, Prometheus, or deployment source fails | That source is explicitly marked `failed`; the workflow can retain other evidence | `A01-T03` subset: `test_scope_safety.py` |
| External publishing is not enabled | Only a local HTML draft is written | Existing default configuration; complete publish safety remains `REV-010` through `REV-013` |

## Target Failure Policy

| Area | Required target behavior | Current status |
| --- | --- | --- |
| Intake authentication, authorization, replay, schema, rate limit | Fail closed; persist no incident state for rejected input; create redacted audit event | Partial |
| Required state, queue, audit, approval, and publisher controls | Fail closed; do not publish or acknowledge work that cannot be durably governed | Not implemented |
| Optional evidence source | Continue as `degraded` with source-specific gap, provenance, and lower confidence | Partial |
| Model/provider | Return a deterministic or explicitly degraded decision brief; retain state; never bypass review or publish | Partial |
| Memory retrieval | Continue without retrieved knowledge; record the gap and never weaken access control | Not implemented |
| Review | Deny unauthenticated/unauthorized/stale decisions; preserve pending state | Partial |
| Publishing | Require authenticated authorization, exact-draft approval, immutable audit event, and idempotent outbox; fail closed otherwise | Not implemented |

## Target Abstention Policy

The agent must return **No supported root cause yet** instead of forcing a
hypothesis when any of the following is true:

- required evidence is unavailable, stale, malformed, or too truncated;
- top causes are materially tied and no causal mechanism distinguishes them;
- supporting and contradicting evidence conflict materially;
- evidence is untrusted or violates data/prompt-injection policy; or
- the incident is a false alert or outside the supported source/service scope.

An abstention response must include the incident window, available evidence,
known gaps, why confidence is insufficient, and the next smallest safe evidence
collection step. It must not claim that a remediation occurred.

The current deterministic scorer enters this mode when no candidate has support,
a required source failed, or leading candidates are materially tied. Runtime
evaluation coverage for stale/untrusted/false alerts remains `SCP-007`,
`COR-010`, `A01-T04`, and `A05-T06`.

## Output Quality Gate (current v0)

Before review, a non-abstention interpretation must have the required sections,
cite known evidence or detection-rule IDs, include an Evidence section, and not
recommend a risky action without approval/risk language. A failed gate is
replaced by the standard **No supported root cause yet** response with the
detected evidence gaps and next verification step. This is a deterministic
safety baseline, not a substitute for the independent grounding evaluator and
gold-set measurement required for production.

## Change Policy

Changes to prompts, models, rules, schemas, source mappings, safety controls,
memory retrieval, or publishing are production-affecting changes.

Before promotion, each change must have:

1. a change record naming the affected readiness criteria and test IDs;
2. a versioned artifact (code, prompt, model, rule, schema, or configuration);
3. required automated test results from `TEST_STRATEGY.md`;
4. a comparison with the current baseline for grounding, abstention, quality,
   latency, and cost where applicable;
5. a rollback or kill-switch path verified in the target environment; and
6. explicit project approval before enabling a production-affecting capability.

Documentation-only changes may use a lighter review, but they cannot alter a
runtime safety decision. The future CI change gate is tracked by `SCP-008` and
`A01-T06`.

## POC Decisions Still Required

The exact CloudWatch event mapping and the production support matrix remain to
be decided when the CloudWatch intake adapter is built (`SCP-003`). Named
ownership and formal SLO governance are intentionally outside the current POC.
