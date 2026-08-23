# Memory and review contract (v0)

This document makes the current local implementation explicit. It is a bridge
to the production schemas in `PRODUCTION_READINESS.md`, not evidence that the
P0 production memory system is finished. The implemented MySQL record details
and remaining boundary are in `KNOWLEDGE_MEMORY.md`.

## Incident memory

The current incident identity is `incident_id`. Its local LangGraph checkpoint
is the resumable workflow state; redacted normalized logs and the compact
evidence pack are deliberately separate. MySQL now persists append-only event
records, incident revisions, compact analysis-revision snapshots, reviewer
decisions, and draft versions. It does not yet replace every workflow-state
field with a production-owned schema or provide retention/authorization policy.

Every future analysis revision must contain: `revision_id`, `incident_id`,
`previous_revision_id`, `created_at`, the exact evidence IDs considered, the
candidate IDs/ranks, model/prompt metadata, and why it supersedes the prior
revision. Observations must be append-only; correction must create a new
revision rather than rewrite prior evidence.

Knowledge is outside the v0 runtime. Only an explicitly human-approved
postmortem, reviewed runbook, service record, or tested rule may become
knowledge. Retrieval must filter by authorization, tenant, service,
environment, security class and expiry before ranking; a miss or outage must
not block investigation.

## Review

The workflow stops before RCA and postmortem generation. The current API
accepts only `approved` or `rejected`; an approval must select a candidate rank
that exists in the saved deterministic candidate set. Invalid selections are
rejected and recorded as a redacted MySQL append-only audit event. Feedback is bounded
to 2,000 characters and starts a revised interpretation.

The audit baseline records a timestamp, incident ID, decision, selected
rank and redacted feedback. MySQL also retains the pending/analysis revision,
candidate/evidence snapshot, locally available reviewer identity and request
correlation ID. It is not an immutable organization audit ledger: verified SSO
identity, separate document approval and transactional publication remain P0
work.

## Retention and authorization decisions still required

Before production, nominate owners for retention/legal hold/export/deletion,
define RPO/RTO, encrypt every durable store, and enforce authorization at every
read/write/context boundary. These requirements map to `MEM-003`–`MEM-012` and
`REV-006`–`REV-015`; test methods are `A07-T01`–`A07-T10` and
`A08-T01`–`A08-T12` in `TEST_STRATEGY.md`.
