# HTTP API

The running service publishes the machine-readable contract at
`GET /openapi.json` and interactive documentation at `GET /docs`.

## Authentication

Alert intake uses `X-Incident-Signature`. Secure environments also require
`X-Incident-Timestamp` and `X-Incident-Nonce`; see the
[alert contract](ALERT_INPUT_CONTRACT.md).

Local review uses Basic Auth. Shadow/production configuration requires OIDC
login or validated bearer claims with separate viewer, decision and operator
roles. State-changing browser requests require an incident-bound CSRF token.

## Main endpoints

| Method and path | Purpose |
| --- | --- |
| `POST /v1/alerts` | Validate, persist and enqueue/coalesce alerts |
| `POST /alerts` | Compatibility alias for `/v1/alerts` |
| `GET /` | Pending-review dashboard |
| `GET /incidents/{thread_id}` | Current incident review page |
| `POST /alerts/{thread_id}/review` | Approve, reject or request more evidence for the current analysis revision |
| `GET /alerts/{thread_id}/review/status` | Read pending analysis-review state |
| `POST /alerts/{thread_id}/publish` | Decide publication for the exact draft version |
| `POST /v1/incidents/{thread_id}/reprocess` | Queue a new analysis from stored evidence |
| `POST /v1/dead-letters/{job_id}/replay` | Replay a failed analysis job |
| `GET /v1/canary/jobs/{job_id}` | Read authenticated synthetic-canary status |
| `GET /healthz` | Process liveness only |
| `GET /readyz` | Configuration, database, migration, queue and worker readiness |
| `GET /metrics` | Prometheus-format process metrics |

## Intake responses

`POST /v1/alerts` returns a per-alert status:

- `accepted`: event and new job committed together;
- `coalesced`: distinct event committed and the pending job advanced; or
- `duplicate_event`: exact retry already exists and no job changed.

Common failures are `400` for the payload contract, `401` for
signature/replay, `403` for source policy, `413` for limits, `429` for intake
rate limits and `503` for queue capacity or unavailable required state.

The worker creates the analysis revision asynchronously after leasing the job.
An intake request does not wait for connectors or a model call.

## Concurrency

Jobs use MySQL leases. Lifecycle, pending-review and exact-draft decisions use
monotonic versions. A stale decision receives `409` instead of applying to a
newer analysis or draft.

Dead-letter replay and incident reprocessing create analysis work only. They
do not repeat an external publication attempt.

## Health versus readiness

`/healthz` means the API process is alive. It is not permission to route
traffic. `/readyz` verifies the supported runtime configuration, current
migration, MySQL/queue availability and required worker heartbeats.
