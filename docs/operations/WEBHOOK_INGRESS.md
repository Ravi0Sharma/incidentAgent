# Webhook ingress policy

This document defines the application-side boundary for `POST /v1/alerts`
(`POST /alerts` remains a compatibility alias). It applies equally to a local
test gateway and a deployed reverse proxy.

## Request sequence

The API applies these checks in order:

1. Reject a request larger than `MAX_WEBHOOK_BODY_BYTES` before parsing when a
   too-large `Content-Length` is declared; verify the actual body size again.
2. Verify `X-Incident-Signature` with HMAC-SHA256 and a constant-time compare.
3. If `WEBHOOK_ALLOWED_SOURCE_CIDRS` is set, reject a source address outside
   that list with `403`.
4. In shadow and production, validate and atomically consume the timestamp and
   nonce. A duplicate or expired nonce returns `401`.
5. Apply the shared MySQL global and per-source rate limits. An exceeded limit
   returns `429` with `Retry-After`.
6. Parse the JSON, validate its size/schema/service/environment boundary, then
   persist the event and job atomically.

No source query, model call or worker job begins for a rejected request.

## Signature and replay headers

Shadow and production requests require all three headers:

```text
X-Incident-Timestamp: 2026-08-24T12:00:00Z
X-Incident-Nonce: unique-per-request-value
X-Incident-Signature: sha256=<hex-hmac>
```

The signed byte sequence is:

```text
timestamp + "." + nonce + "." + raw_request_body
```

The nonce itself is never persisted; its SHA-256 fingerprint is stored in
MySQL until `WEBHOOK_REPLAY_WINDOW_SECONDS` expires. This makes replay
protection work across API processes.

## Source address and reverse proxies

The per-source limiter uses the direct TCP client address. It intentionally
does not use `X-Incident-Client-Id`, because a caller can change that header to
evade a per-source limit.

If an approved reverse proxy terminates the connection, configure its network
in `WEBHOOK_TRUSTED_PROXY_CIDRS`. Only then does the API read the first address
in `X-Forwarded-For`. Configure `WEBHOOK_ALLOWED_SOURCE_CIDRS` when an
application-level address filter is desired; it is checked against that
resolved address. Invalid CIDRs make shadow/production startup fail.

```dotenv
WEBHOOK_TRUSTED_PROXY_CIDRS=10.0.0.0/8
WEBHOOK_ALLOWED_SOURCE_CIDRS=198.51.100.0/24
WEBHOOK_GLOBAL_RATE_LIMIT=120
WEBHOOK_CALLER_RATE_LIMIT=60
WEBHOOK_RATE_LIMIT_WINDOW_SECONDS=60
```

The reverse proxy or WAF remains responsible for TLS termination, volumetric
DDoS controls and network routing. It must pass the original source address
only from the configured proxy path; the application does not treat a
client-supplied forwarding header as trustworthy.

## Evidence-query policy

`LOG_QUERY_LIMIT` is a hard source and durable-state cap, not a fixed
“last 1,000 lines” result. The initial plan is severity-aware:

| Severity | Default maximum sampled records |
| --- | ---: |
| SEV1 | `SEV1_LOG_QUERY_LIMIT` = 3,000 |
| SEV2 | `SEV2_LOG_QUERY_LIMIT` = 1,500 |
| SEV3/SEV4 | `INITIAL_LOG_QUERY_LIMIT` = 500 |
| Any severity | `LOG_QUERY_LIMIT` = 5,000 configured hard cap by default |

The Loki path splits the incident window into time slices and reserves query
budget for high-signal shapes such as errors, exceptions, timeouts and
failures. It records the exact/estimated total, fetched count, truncation and
sampling strategy in provenance. Aggregation then preserves bounded
representatives of time boundaries, semantic signals, high-signal shapes and
uncommon general shapes before evidence reaches the model.

CloudWatch uses the same 5,000-record default cap through
`CLOUDWATCH_LOG_QUERY_LIMIT`; its source-map, log-group and metric-page limits
remain independently bounded.

## Verification

- `tests/test_alert_contract.py` covers HMAC/replay, caller limiting and trusted
  proxy/source-CIDR handling.
- `tests/test_production_flow.py` covers the severity-aware collection plan.
- `tests/test_operational_baselines.py` rejects malformed CIDR configuration in
  secure runtimes.
