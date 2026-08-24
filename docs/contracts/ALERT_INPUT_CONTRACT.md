# Incident Agent - Alert Input Contract

**Version:** `grafana-alertmanager/v1`

CloudWatch Alarm is the selected first production alert source. The local
translator in `webhook/cloudwatch.py` accepts only EventBridge events with
`source=aws.cloudwatch` and `detail-type=CloudWatch Alarm State Change`, then
converts an allowlisted `ALARM`/`OK` transition into this existing contract.
Unknown alarms and `INSUFFICIENT_DATA` fail closed. Service, environment and
severity come from the operator-owned CloudWatch source map, never from an
untrusted event field. Authenticated EventBridge-to-webhook transport remains
an explicit deployment decision.

This is the current intake boundary for `POST /v1/alerts` (with a temporary
`POST /alerts` compatibility alias). It validates alert shape
and resource limits before an investigation can start. Accepted normalized
events, idempotency keys, incident revisions, lifecycle state, and pending
reviews are stored in MySQL. Durable queueing and multi-worker analysis remain
separate requirements in Area 2.

## Accepted Payloads

1. A single Grafana-style alert object.
2. An Alertmanager object containing a non-empty `alerts` array.

Every source alert must have a non-empty identity through one of:

- `alertname`;
- `service`;
- `labels.alertname`;
- `labels.service`; or
- `labels.job`.

Optional `status`, when present, must be `firing` or `resolved`. `labels` and
`annotations` must be string-to-string objects. Optional `startsAt` and
`endsAt` must be ISO-8601 timestamps.

Services must exist in `config/services.yaml`. Environments must be in
`SUPPORTED_INCIDENT_ENVIRONMENTS`; a missing label uses
`DEFAULT_ALERT_ENVIRONMENT` for local fixtures only.

## Production signature and replay baseline

Production requests must include `X-Incident-Timestamp`, `X-Incident-Nonce`,
and `X-Incident-Signature`. The signature is HMAC-SHA256 over
`timestamp + "." + nonce + "." + raw_body`. The timestamp must fall inside
`WEBHOOK_REPLAY_WINDOW_SECONDS` and a nonce may be used once. A SHA-256 nonce
fingerprint is atomically stored in MySQL until the replay window expires, so
all webhook workers using the database reject a captured request consistently.

## Configured Limits

| Setting | Default | Behavior when exceeded |
| --- | --- | --- |
| `MAX_WEBHOOK_BODY_BYTES` | 262,144 bytes | Returns `413`; request body is not parsed when `Content-Length` already exceeds the limit |
| `MAX_ALERTS_PER_REQUEST` | 50 | Returns `413`; no workflow starts |
| `MAX_ALERT_LABELS` | 50 | Returns `400`; no workflow starts |
| `MAX_ALERT_ANNOTATIONS` | 50 | Returns `400`; no workflow starts |
| `MAX_ALERT_FIELD_LENGTH` | 4,096 characters | Returns `400`; no workflow starts |

Rejections are counted in the current process by reason. Production metrics and
durable audit events remain required by `OBS-004`, `OBS-008`, and `SEC-012`.

## Intake rate-limit baseline

The service applies `WEBHOOK_GLOBAL_RATE_LIMIT` and
`WEBHOOK_CALLER_RATE_LIMIT` within `WEBHOOK_RATE_LIMIT_WINDOW_SECONDS`, returning
`429` and `Retry-After` when either limit is exceeded. The caller key is the
direct client address. `X-Forwarded-For` is used only when that direct peer is
listed in `WEBHOOK_TRUSTED_PROXY_CIDRS`; a caller-controlled client-ID header
is never used. When `WEBHOOK_ALLOWED_SOURCE_CIDRS` is configured, only the
resolved address ranges may submit a correctly signed request. Counters are
stored as hashed keys in MySQL and are shared by workers.

See [`WEBHOOK_INGRESS.md`](../operations/WEBHOOK_INGRESS.md) for deployment
and reverse-proxy guidance.

## Lifecycle Boundary

Firing alerts start analysis. A resolved alert locates the existing local
incident by its fingerprint/service/tenant/event-time bucket and transitions an active or
completed lifecycle to `resolved`; an unknown resolution is recorded as such
without creating analysis. Repeated resolved alerts are idempotent. Resolution
does not publish a document or delete the immutable pending-review record, but
the server rejects decisions against it while the incident is resolved. A new
firing observation for the same upstream occurrence reopens atomically through
`received` → `collecting` → `analyzing` and creates a new analysis revision.
Production multi-worker race evidence remains open under `ING-007` through
`ING-016`.

For accepted firing alerts, the MySQL lifecycle record uses
`incident-lifecycle/v1`: `received` → `collecting` → `analyzing` →
`awaiting_analysis_review` → `drafting_postmortem` → `completed`. A rejected
analysis returns to `analyzing`. Illegal transitions are rejected. The current
implementation uses row locks and monotonic versions to reject stale lifecycle
and pending-review writers. The separate exact-draft publish-review state
remains open.

## Queue, revisions, and dead letters

The endpoint commits every distinct redacted normalized event before returning
success. Matching fingerprint/service/tenant observations share a fixed
event-time incident bucket. The first observation creates a pending MySQL job;
later observations update that job to the newest event while it remains
pending and return `coalesced`. The sliding debounce has a hard maximum, so a
continuous alert stream cannot postpone analysis indefinitely. If the worker
has already leased the job, the next event creates one pending follow-up job
without mutating the in-flight analysis. Exact retries reuse the same event and
do nothing.

A worker leases analysis only after the response and creates the revision. The
admission transaction uses a per-incident row lock, yielding at most one leased
and one pending analysis job per incident bucket while independent incidents
remain concurrent. All accepted event rows remain available for audit.
Workers that exhaust retry attempts enter a redacted MySQL dead-letter record;
`POST /v1/dead-letters/{job_id}/replay` queues a safe analysis-only replay.

See [`OPENAPI_CONTRACT.md`](OPENAPI_CONTRACT.md) for HTTP/authentication/error
semantics and the live `/openapi.json` machine contract.

## Test Mapping

- `A02-T01` subset: `tests/test_alert_contract.py`
- `A02-T02` signature/replay subset: `tests/test_alert_contract.py`
- `A02-T03` subset: `tests/test_alert_contract.py`
- `A02-T08` lifecycle-transition subset: `tests/test_lifecycle.py`
- `A02-T09` MySQL idempotency and stale-writer integration coverage:
  `tests/test_mysql_incident_lifecycle.py`
