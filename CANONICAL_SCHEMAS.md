# Canonical Schemas And Invariants

This POC stores all durable operational records in MySQL. JSON payloads are
redacted before persistence.

| Record | Durable fields | Invariants |
| --- | --- | --- |
| Incident event | `event_id`, incident ID, idempotency key, event/source/receive times, clock quality, payload | Idempotency key is unique; rows are append-only; reads sort by event time then event ID. |
| Job | job key, incident/event IDs, kind, status, lease, attempts, run context | A job key is unique; only the lease owner can complete/fail it; exhausted jobs become dead letters. |
| Revision | incident ID, monotonic revision, previous revision, reason, model/prompt/code/config context | A locked per-incident head allocates unique monotonic versions without range-lock races; revisions never overwrite prior revisions; pipeline config uses a content-addressed manifest. |
| Evidence revision | incident/evidence IDs, content hash, version, payload, supersedes record, first analysis revision | Unchanged evidence reuses its immutable record; corrected content creates a linked version; every analysis revision has an exact membership snapshot. |
| Lifecycle | incident ID, state, monotonic version, ordered history | Only `incident-lifecycle/v1` transitions are allowed; stale expected versions fail. |
| Pending review | incident ID, review payload, monotonic version | A reviewer must submit the displayed `pending_revision`; stale decisions fail with `409`. |
| Hypothesis/evidence | See `HYPOTHESIS_CONTRACT.md` and `EVIDENCE_CONTRACT.md` | Claims must be grounded or the agent abstains. |
| Observed signal/impact | `observed-signal/v1`, `impact-assessment/v1`, `signal-impact-link/v2`, `event-burst/v1` | Fault, impact, outcome, recovery and contradiction IDs have separate roles; entity/time mismatch cannot establish impact. |
| Connector query | `connector-provenance/v2` plus sanitized `incident-query/v1` | Stable query ID; explicit source schema; no backend credentials or unrestricted raw provider query. |
| Source quality | `source-quality/v1` | Counts input, usable, quarantined, duplicate and invalid records; event range and freshness are explicit. |

Knowledge records and external publication records are not implemented in this
POC. They must not be inferred from mutable workflow state.
