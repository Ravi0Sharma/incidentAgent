# Alert input contract

`POST /v1/alerts` is the current intake route. `/alerts` is a compatibility
alias.

## Accepted payloads

The HTTP route accepts:

1. one Grafana-style alert object; or
2. an Alertmanager object with a non-empty `alerts` array.

Each alert needs a non-empty identity from `alertname`, `service`,
`labels.alertname`, `labels.service` or `labels.job`. Optional `status` must be
`firing` or `resolved`. Labels and annotations must be string-to-string maps;
timestamps must be ISO 8601.

Services must exist in `config/services.yaml`. Environments must be allowed by
`SUPPORTED_INCIDENT_ENVIRONMENTS`. Only local fixtures may rely on the default
environment.

`webhook/cloudwatch.py` can translate an allowlisted CloudWatch alarm state
change into this contract, but raw EventBridge payloads are not wired into the
HTTP route. See the [CloudWatch guide](../operations/CLOUDWATCH.md).

## Request order

The API:

1. rejects a declared or actual oversized body;
2. verifies the HMAC signature with a constant-time comparison;
3. applies the configured source-address policy;
4. validates and consumes the timestamp/nonce in secure environments;
5. applies shared global and caller rate limits;
6. parses and validates JSON, service and environment boundaries; and
7. commits the redacted event and queue job atomically.

No connector query, model call or worker job starts for a rejected request.

## Signature and replay protection

Secure environments require:

```text
X-Incident-Timestamp: <ISO-8601 time>
X-Incident-Nonce: <unique value>
X-Incident-Signature: sha256=<hex HMAC>
```

The signed bytes are:

```text
timestamp + "." + nonce + "." + raw_request_body
```

The timestamp must be inside `WEBHOOK_REPLAY_WINDOW_SECONDS`. MySQL stores only
a SHA-256 nonce fingerprint until the window expires, so multiple API workers
reject the same captured request consistently.

## Limits

| Setting | Default | Failure |
| --- | ---: | --- |
| `MAX_WEBHOOK_BODY_BYTES` | 262,144 bytes | `413` |
| `MAX_ALERTS_PER_REQUEST` | 50 | `413` |
| `MAX_ALERT_LABELS` | 50 | `400` |
| `MAX_ALERT_ANNOTATIONS` | 50 | `400` |
| `MAX_ALERT_FIELD_LENGTH` | 4,096 characters | `400` |

Global and per-caller limits return `429` with `Retry-After`. The caller is the
direct client address. `X-Forwarded-For` is trusted only when the direct peer
matches `WEBHOOK_TRUSTED_PROXY_CIDRS`. Optional
`WEBHOOK_ALLOWED_SOURCE_CIDRS` is checked against the resolved address.

The reverse proxy remains responsible for TLS termination, volumetric DDoS
controls and trustworthy forwarding headers.

## Event, queue and lifecycle behavior

The endpoint commits each distinct normalized event before acknowledging it.
Exact retries return `duplicate_event`. Matching events share a fixed
incident-time bucket and bounded debounce:

- the first event creates one pending job;
- another event updates that job while it remains pending; and
- an event received during a lease creates at most one pending follow-up.

All events remain available for audit. The worker creates the analysis
revision after leasing the job; webhook latency does not include model work.

Firing alerts start or reopen analysis. Resolved alerts update the matching
incident without starting an unrelated investigation. Lifecycle and pending
review writes use monotonic versions, so stale writers fail.

Jobs that exhaust retries become redacted dead letters. Authorized replay
creates analysis work only; it does not repeat external publication.

## Evidence-query limits

Alert intake cannot supply raw provider queries. Collection uses deployment
configuration and severity-aware limits, bounded by `LOG_QUERY_LIMIT`.
Sampling preserves time boundaries and high-signal/uncommon shapes while
recording matched, fetched, retained and truncated counts in provenance.

The live machine-readable contract is available at `/openapi.json`. Human
endpoint documentation is in [OPENAPI_CONTRACT.md](OPENAPI_CONTRACT.md).
