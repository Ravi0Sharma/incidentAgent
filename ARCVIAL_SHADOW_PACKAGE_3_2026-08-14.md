# Arcvial shadow package 3 evidence — 2026-08-14

## Scope and decision

This closes the **local code and persistence part** of shadow package 3:
canonical evidence/revisions, UTC plus original source time, recursive
redaction before checkpointing, source quality and query provenance.

It does not claim that Arcvial production logs are connected. The same probes
must be repeated against the real read-only Arcvial connector during packages
1–2. Package 4 (independent worker and recovery) may start now without waiting
for that connection.

## Defects found by runtime inspection

The work did not rely on the existing green suite as proof. Direct HTTP and
MySQL inspection found these defects:

1. Alertmanager timestamps containing milliseconds and `Z` caused MySQL error
   1292 and HTTP 500. Accepted ISO-8601 values are now converted to UTC MySQL
   `DATETIME` values.
2. Connector rows were quality-checked using redacted copies, but the original
   row was returned to LangGraph state and could be checkpointed before log
   normalization. Records are now recursively redacted before entering usable
   graph state.
3. Metrics and deploys retained provider timestamp formats and used
   collision-prone presentation IDs. They now retain original time/zone,
   expose normalized UTC event time and use content-derived evidence IDs.
4. Redaction was not idempotent. A sensitive value already pseudonymized at
   intake was pseudonymized again when the canonical integrity hash was built.
   The resulting mismatch correctly failed closed but dead-lettered the job.
   Repeated sink-level redaction is now idempotent.
5. Durable evidence payloads did not all use one cross-source canonical
   envelope. Alert, grouped log, metric and deploy revisions now persist as
   `incident-evidence/v1` with source, lineage, collection revision, UTC and
   original time, receive time quality, service/environment, classification,
   integrity hash and nested redacted observation payload.

## Direct database evidence

Synthetic incident `INC-100051` was submitted over HTTP with exact secret
canaries and a `+02:00` source timestamp. Direct SQL inspection showed:

- queue status `completed`;
- lifecycle `awaiting_analysis_review`;
- analysis revision `1` with seven exact evidence members;
- 7/7 rows use `incident-evidence/v1`;
- 7/7 rows are classified `confidential`;
- zero occurrences of either raw canary in `incident_events`;
- zero occurrences of either raw canary in `incident_evidence_records`;
- alert time normalized from `2026-08-14T15:17:00.000+02:00` to
  `2026-08-14T13:17:00Z` while retaining the original representation;
- `validate_analysis_evidence("INC-100051", 1)` passed with the same seven
  evidence IDs stored in the revision membership.

Synthetic incident `INC-100050` captured the non-idempotent-redaction defect:
the mismatched alert envelope was rejected by integrity validation and the job
went to dead letter instead of becoming reviewable. This is retained as a
negative runtime artifact, not counted as a successful run.

## Secondary regression evidence

After the direct probes, `scripts/quality_gate.py` passed with 286/286 tests,
Ruff, scoped mypy, compileall, prompt budgets and the repository secret scan.
The tests are regression protection only; the SQL and lifecycle observations
above are the acceptance evidence for this local package.

## Revalidation required with real Arcvial logs

Before real Arcvial telemetry is allowed into a shadow environment:

1. run an exact canary through the configured server-log connector;
2. verify zero raw canary hits in checkpoints, events, evidence, review HTML,
   application logs and tracing;
3. inspect at least one normal, multiline/error and malformed record;
4. verify the actual source schema, service attribution, UTC/original time,
   query ID, truncation and freshness fields;
5. correct the parser/allowlist if the real log body is structured JSON or uses
   fields not covered by `config/log_schemas.yaml`;
6. repeat revision membership and integrity validation before enabling review.

Until these six checks pass, the result is local package-3 completion, not
production evidence approval.
