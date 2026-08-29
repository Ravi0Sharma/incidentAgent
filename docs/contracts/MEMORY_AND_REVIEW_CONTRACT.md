# Review and memory contract

The system separates immutable incident history, curated knowledge and human
decisions. Model output never becomes durable knowledge or an approved result
by itself.

## Incident memory

MySQL keeps append-only incident events and versioned analysis revisions. Each
analysis revision records its predecessor, triggering event, exact evidence
membership, deterministic candidate snapshot, data-quality state and
code/prompt/model context. A correction creates a new revision instead of
rewriting previous evidence.

Raw logs are not copied into prompts or long-lived knowledge. The analysis
snapshot retains redacted canonical evidence and content hashes needed to
reproduce what the reviewer saw.

## Curated knowledge

Only concise records from an approved source may enter `curated_knowledge`:

- reviewed postmortem;
- reviewed runbook;
- governed service metadata; or
- tested failure rule.

Every record needs source provenance, approval identity/reference, tenant,
security class and expiry metadata. Retrieval filters authorization, tenant,
security class, service, environment, active state and expiry before ranking.
A miss or retrieval failure must not block incident analysis.

Corrections create a new record and supersede the old one. Deletion removes a
record from retrieval but keeps the audit transition. Production retention,
legal hold, encryption and tenant authorization remain deployment gates.

## Analysis review

The graph pauses before RCA and postmortem drafting. The reviewer sees the
analysis revision, evidence, contradictions, ranked candidates, uncertainty
and gaps.

A decision must target the current `pending_revision`. MySQL locks that row and
allows one decision winner. A stale browser or second reviewer receives
`409 stale_incident_revision` instead of applying a decision to newer
evidence.

The reviewer may approve, reject or request more evidence where supported by
the current route. Feedback is bounded and redacted. Approval must select a
candidate that exists in the saved candidate set; an abstained analysis cannot
be approved as a supported root cause.

## Draft and publication review

Analysis approval creates a versioned local postmortem draft. This does not
authorize external publication.

A separate publication decision binds to the exact draft version and SHA-256
digest. Editing the draft invalidates an earlier publication approval. Before
calling a publisher, MySQL records a unique attempt. A completed attempt is
deduplicated; ambiguous provider acknowledgement blocks automatic retry for
operator reconciliation.

`PUBLISH_EXTERNAL=false` keeps all output local even after approval.

## Reviewer checklist

Approve only when the selected explanation:

- cites known compatible evidence;
- states a plausible mechanism without claiming proof;
- exposes contradictory evidence and missing sources;
- distinguishes confidence from causality; and
- proposes only safe verification steps.

Reject or request more evidence when citations are weak, sources failed,
candidates are materially tied, contradictions are unresolved or the page is
stale. Reload after a `409` response.

## Audit boundary

Review decisions record time, incident/revision, selected candidate, displayed
evidence, redacted rationale, reviewer identity and request correlation ID.
These are append-only application records, not immutable/WORM audit storage.
Real identity-provider registration and immutable organizational audit storage
remain production requirements.
