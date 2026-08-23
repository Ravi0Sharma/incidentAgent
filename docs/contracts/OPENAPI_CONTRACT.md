# Incident Agent HTTP API

**API version:** `v1`  
**Machine-readable contract:** `GET /openapi.json` from the running webhook
service.

## Authentication

`POST /v1/alerts` uses `X-Incident-Signature`. In production it must include
`X-Incident-Timestamp` and `X-Incident-Nonce`; the signed value is
`timestamp + "." + nonce + "." + raw_body`. The nonce is stored as a hash in
MySQL for the configured replay window. Reviewer routes use HTTP Basic
authentication when reviewer credentials are configured.

## Endpoints

| Endpoint | Meaning | Success | Important errors |
| --- | --- | --- | --- |
| `POST /v1/alerts` | Validate, persist and enqueue one or more alerts | `200` with `accepted` event/job IDs | `400` malformed contract, `401` signature/replay, `413` limits, `429` intake limit |
| `POST /alerts` | Temporary compatibility alias for `/v1/alerts` | Same as v1 | Same as v1 |
| `POST /alerts/{incident_id}/review` | Submit an approve/reject decision for a saved review revision | `200` | `409` stale/missing review revision |
| `GET /alerts/{incident_id}/review/status` | Read review state | `200` | returns `awaiting_review: false` if absent |
| `POST /v1/dead-letters/{job_id}/replay` | Queue a safe reprocessing run from redacted stored evidence | `200 accepted` | `404` unknown job |
| `POST /v1/incidents/{incident_id}/reprocess` | Queue latest stored evidence with selected code/prompt/model versions | `200 accepted` | `404` unknown incident |
| `GET /healthz` / `GET /readyz` | Liveness / configuration + MySQL queue readiness | `200` | `503` invalid configuration or unavailable store |
| `GET /metrics` | Process-local Prometheus-format diagnostic metrics | `200` | — |

## Intake semantics

The response means the normalized event and its idempotency key were committed
with a MySQL job in the same transaction. The worker creates the analysis
revision after leasing the job; a request never waits for LLM analysis. Exact
retries return `duplicate_event` and do not create a job. A new payload creates
a new event and analysis job for the existing incident ID.

Every event retains `event_time`, `source_time`, `received_at`,
`clock_quality`, and its monotonic database event ID. Timeline reads sort by
event time then ID, preserving arrival order as an audit field.

## Concurrency and failures

Jobs are leased with MySQL row locks. Lifecycle and pending-review writes use
monotonic versions; a client must send `pending_revision` when posting a
review, otherwise the request receives `409 stale_incident_revision`. Failed
jobs retry, then move to `incident_dead_letters` with redacted diagnostics.
Dead-letter replay and incident reprocessing create analysis-only jobs and do
not publish an external side effect. Their payload can specify
`code_version`, `prompt_version`, and `model_version`; these values are stored
with the resulting incident revision for reproducibility.
