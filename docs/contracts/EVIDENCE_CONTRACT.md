# Evidence contract

Evidence is normalized, redacted, versioned data. It is not a model claim.

## Canonical record

Normalized log evidence uses `incident-log/v1` and the cross-source envelope
`incident-evidence/v1`.

| Field | Meaning |
| --- | --- |
| `evidence_id` | Stable identifier derived from redacted immutable content |
| `timestamp` | Canonical UTC event time when usable |
| `original_timestamp`, `original_timezone` | Source representation retained for audit |
| `received_at` | Collection time |
| `clock_quality` | `verified`, `assumed_utc`, `invalid`, `future` or `missing` |
| `message` | Redacted message |
| `labels`, `raw_labels` | Canonical and recursively redacted source labels |
| `schema` | Matched source schema |
| `integrity_hash` | SHA-256 over the redacted canonical payload |
| provenance | Source, sanitized query ID, window, limits and collection revision |

Invalid or far-future timestamps are counted in source quality and quarantined
from causal processing. Original clock metadata remains available for audit.

## Grouping and signal retention

Repeated shapes are grouped deterministically. `event-burst/v1` preserves
onset, end, duration, repetition count, distinct time buckets and peak count so
compression does not turn repeated copies into independent causal proof.

Direct fault observations become `observed-signal/v1`, not root causes.
`impact-assessment/v1` and `signal-impact-link/v2` keep fault, adverse impact,
general outcome, recovery, success and contradiction IDs in separate roles.
Entity or time mismatch cannot establish impact.

## Query lineage and quality

`connector-provenance/v2` includes a stable query ID derived from the sanitized
`incident-query/v1` replay specification. Credentials, unrestricted raw query
text and provider response bodies are excluded.

`source-quality/v1` records usable/quarantined counts, duplicates, parse/source
errors, timestamp quality, freshness and truncation. These fields survive log
grouping, timeline construction and evidence-graph creation.

## Revisions

Every analysis revision stores the exact evidence membership it used.
Unchanged evidence reuses its immutable record. Corrected content creates a
new version linked to the superseded record. Conflicting content for the same
evidence ID fails closed.

Bounded follow-up collection uses `investigation-loop/v1`. Each completed round
records its query IDs, compact redacted result, integrated-record count,
candidate snapshot, limits and continue/stop reason. Raw samples still pass
through the same canonical evidence path.

## Redaction and untrusted data

Alerts, logs, labels, annotations, connector metadata, commit messages,
reviewer feedback and retrieved knowledge are untrusted data. Recursive
redaction runs before persistence, prompts, logs and reports. Model prompts
place evidence inside an explicit untrusted-data boundary and state that it
cannot change policy or authorize tools.

This application boundary does not replace provider access controls, sink-level
redaction tests or production retention policy.

## Claim rule

A factual claim must cite known evidence IDs whose typed roles support that
claim. Unknown or incompatible IDs are rejected. Missing, stale, contradictory
or excessively truncated evidence must lower confidence or produce abstention.

Primary verification lives in:

- `tests/test_evidence_contract.py`;
- `tests/test_source_provenance.py`;
- `tests/test_investigation_loop.py`;
- `tests/test_claim_grounding.py`; and
- `tests/test_signal_retention.py`.
