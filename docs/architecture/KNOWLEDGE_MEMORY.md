# Curated knowledge memory (v1)

The local MySQL implementation has two deliberately separate stores:

- Incident history: append-only `incident_events`, `incident_revisions`, and
  `incident_analysis_revisions`. An analysis revision contains its predecessor,
  triggering event, exact evidence IDs, deterministic candidate snapshot,
  compact data-quality state, and code/prompt/model run context. It stores an
  evidence-pack digest instead of the full prompt or raw logs.
- Curated knowledge: `curated_knowledge` contains only concise, explicitly
  approved records. It is not an automatic memory of model output.

## Curated knowledge rules

A writer must provide all of these fields: approved source type, source link,
approval identity, approval reference, tenant, security class, and summary.
Only `reviewed_postmortem`, `reviewed_runbook`, `service_metadata`, and
`tested_failure_rule` are accepted source types. Raw logs, raw evidence, and
prompts are rejected as metadata keys.

Retrieval is filter-first: tenant, allowed security classes, service,
environment, incident type, active status, and expiry are evaluated before a
small (maximum 10) lexical ranking. A no-hit result is expected and must not
block incident analysis. Future semantic retrieval must retain the same filters
and return the source link and relevance reason.

Corrections make a new record and mark its predecessor `superseded`; deletion
marks a record `deleted`, removing it from retrieval. Neither operation erases
the audit history. Retention, legal hold, encryption, backup/restore, tenant
identity verification, and evaluation of retrieval quality remain production
work outside this local implementation.

## Review records and drafts

`incident_review_decisions` stores an idempotent decision record with the
incident/pending/analysis revision, locally available reviewer identity,
selected hypothesis, displayed evidence IDs, rationale, request correlation ID
and timestamp. In production the local Basic/no-auth identity must be replaced
by verified SSO/RBAC claims.

`incident_postmortem_drafts` preserves generated drafts and reviewer edits as
immutable versions linked by `supersedes_draft_id`. A separate exact-draft
decision and durable attempt guard govern external publication; ambiguous
delivery still requires operator reconciliation.
