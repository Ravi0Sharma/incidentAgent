# Incident Agent - Evidence Contract

**Current normalized log schema:** `incident-log/v1` with canonical evidence
metadata `incident-evidence/v1`

This document describes the current evidence boundary and the target production
contract for Area 4 in `PRODUCTION_READINESS.md`.

## Current Normalized Log Record

Every normalized log record carries:

| Field | Meaning |
| --- | --- |
| `evidence_schema_version` | Current normalized log schema version |
| `timestamp` | Canonical UTC event timestamp when the source time is usable |
| `message` | Redacted message string |
| `raw_labels` | Recursively redacted source labels |
| `labels` | Canonical labels selected through `config/log_schemas.yaml` |
| `schema` | Matched source schema name |
| `evidence_id` | Stable ID derived from redacted immutable log content |
| `canonical_evidence_schema_version` | Cross-source canonical schema version |
| `event_time` / `received_at` | UTC event and collection time, when the source timestamp is valid |
| `original_timestamp` / `original_timezone` | Preserved source time representation for audit |
| `clock_quality` | `verified`, `assumed_utc`, `invalid`, `future`, or `missing` |
| `integrity_hash` | SHA-256 over the redacted canonical payload |

Canonical labels can additionally carry source-provided `workload_id` and
`execution_id`. The Hadoop adapter derives stable SHA-256-based scoped values
instead of exposing raw application/container IDs. Aggregated groups retain
these values only as bounded dimension summaries for incident-local entity
matching.

Grouping derives a deterministic `event_id` from the aggregation key. The
source record also carries a stable `evidence_id`, canonical source lineage and
an integrity hash. Invalid or more-than-five-minutes-future timestamps are
counted in source quality and quarantined from the log pipeline; canonical
records retain original clock metadata for audit where normalization occurs.

Repeated normalized shapes carry `event-burst/v1`: onset, end, duration,
repetitions, distinct time buckets and peak bucket/count. This preserves
volume and timing while preventing repeated copies from being treated as
independent causal proof.

Direct fault observations also carry `impact-assessment/v1`. It separates
fault-event IDs from impact, adverse-outcome, outcome, recovery and
contradiction IDs. `signal-impact-link/v2` records explicit entity match and
time relation. Success on a matching workload can contradict impact; an
adverse event on a conflicting execution is excluded from impact support.

## Query Lineage And Source Quality

Collection provenance is versioned as `connector-provenance/v2`, with a stable
query ID derived from a sanitized `incident-query/v1` replay specification.
The specification records operation, service, allowlisted filters, window,
limits and sampling policy without backend credentials or unrestricted raw
query text.

`source-quality/v1` records input/usable/quarantined counts, duplicates,
parse/source errors, missing required fields and timestamps, timestamp quality,
event range and freshness. Log groups and evidence-graph nodes retain the
source query IDs and source schema IDs that produced them. Review HTML shows
these fields as compact source cards, with sanitized replay details collapsed.

## Targeted Investigation Revisions

`investigation-loop/v1` is the bounded control record for evidence expansion.
It carries the current and maximum round, service/depth boundary, retained
result-byte and elapsed-time limits, continuation decision and explicit stop
reason.

Every completed targeted round appends an `investigation-revision/v1` record to
checkpointed incident state. The record contains query IDs, redacted compact
tool-result summaries, integrated-record count, the resulting deterministic
candidate snapshot and the continue/stop decision. Raw samples still follow the
canonical evidence path; the revision is audit metadata, not a second raw-log
store. The complete revision list is included in the immutable analysis
snapshot used by review.

## Redaction Boundary

Before alert state is built, labels are redacted/pseudonymized, annotations are
recursively redacted, and message-like values such as `generatorURL` are passed
through message redaction. Structured nested values, lists, and tuples are
handled recursively.

This closes the current raw-annotation path. It does **not** complete `EVD-009`:
review feedback, exceptions, tool results, connector metadata, traces, reports,
memory, and every external publisher still need a unified sink-level redaction
test.

## Target Production Evidence Contract

Every evidence item must eventually include a stable ID, source/backend/tenant,
sanitized query provenance, collection revision, event time, receive time,
service/environment, security classification, integrity hash, and supersession
link where corrected. Claims must cite compatible evidence IDs.

The canonical record now covers stable IDs, lineage, collection revision,
event/receive time, service/environment, classification and integrity hashes
at the normalized log boundary. Connector rows are recursively redacted before
they can enter checkpointed graph state. Metrics and deploys retain original
source time/zone while exposing canonical UTC event time and content-derived
evidence IDs.

Local MySQL analysis snapshots persist alert, grouped-log, metric and deploy
observations inside the same `incident-evidence/v1` envelope. The envelope
contains the redacted observation payload and an independently checked inner
integrity hash. Snapshot creation fails closed if evidence-graph membership
differs from canonical revision membership or if one revision contains the
same evidence ID with conflicting content. Local snapshots also keep an
append-only, queryable evidence membership: unchanged content reuses the same
immutable record and corrected content creates a version with a supersession
link. The stored content hash is verified before revision diffing and review;
missing membership or modified payload blocks the decision. Production
migration/retention/tamper-evident audit proof, cross-source citation validation
and production-wide sink tests remain open.

## Untrusted Evidence Rule

Logs, labels, annotations, commit messages, reviewer feedback, and retrieved
knowledge are data, never instructions. All current model prompt builders
serialize such values inside an explicit `<untrusted-evidence>` boundary after
redaction; prompts state that the enclosed content cannot alter policy or
invoke tools. This is a local guardrail, not a substitute for provider-level
tool authorization.

## Test Mapping

- `A04-T01` subset: `tests/test_evidence_contract.py` validates the schema
  version and canonical normalization.
- `A04-T02` subset: `tests/test_evidence_contract.py` validates recursive alert
  annotation and URL redaction.
- `A04-T03` subset: `tests/test_evidence_contract.py` validates stable IDs,
  hashes, UTC timestamp handling and future/invalid timestamp quarantine.
- `A04-T04` subset: `tests/test_evidence_contract.py` validates prompt
  delimiting for untrusted evidence. Cross-source citations, append-only
  persistence, sampling and revision behavior remain open.
- Query redaction, quality quarantine, stable query IDs and lineage through
  grouping/graph/review are covered by `tests/test_source_provenance.py`.
- Bounded A→B expansion, revision append, rerouting and honest limit/failure
  stop reasons are covered by `tests/test_investigation_loop.py`.
