# Incident Agent - Connector Contract

> This is the common behavioral contract for telemetry and change connectors.
> It documents the current implementation boundary and the target interface for
> Area 3 in `PRODUCTION_READINESS.md`.

## Current Connectors

| Connector | Current read capability | Current bounded behavior | Production gap |
| --- | --- | --- | --- |
| Loki | Log samples, counts, targeted search, service discovery | Time window, query/sample limits, versioned query provenance and record-quality accounting | Real-backend contract suite and pagination |
| Prometheus | Error rate, p95 latency, request rate | Incident window, fixed metric set, versioned query provenance and freshness accounting | Real-backend contract suite and baseline/seasonality |
| GitHub | Recent deployment-like records | Lookback window and result cap | Must prove records are actual production deploys, not only repository metadata |
| Slack | Publish postmortem notification | Request policy only | Publishing approval/outbox/idempotency remains outside Area 3 |
| CloudWatch Logs Insights | Allowlisted service log groups with a fixed, bounded query | Max 50 groups, fixed result cap, bounded polling, explicit terminal failures | Real AWS sandbox, IAM scope and representative log-shape contract |
| CloudWatch GetMetricData | Allowlisted namespaces, names, statistics and dimensions | Max 500 configured queries, bounded pagination and partial-data marking | Real AWS sandbox, IAM scope, freshness and metric semantic validation |

CloudWatch is the selected first production telemetry boundary. Loki and
Prometheus remain useful local/evaluation connectors; enabling CloudWatch is an
operator configuration choice (`LOG_SOURCE`/`METRIC_SOURCE`) and cannot be
controlled by an incoming alarm. `config/cloudwatch_sources.example.yaml`
documents the versioned allowlist. It deliberately contains no credentials.

Mocks are development tools only. A connector is not production-approved until
its `A03-T01` through `A03-T06` tests pass against an approved sandbox or
ephemeral backend.

## Request Policy

Every HTTP connector calls `utils.resilience.request(source, ...)`. The policy
is selected by source name from `SOURCE_REQUEST_POLICIES` in `settings.py`.

| Policy field | Meaning |
| --- | --- |
| `timeout_seconds` | Maximum HTTP request time for that source |
| `retry_attempts` | Total attempts for transient HTTP failures |
| `retry_backoff_seconds` | Linear backoff multiplier between attempts |
| `circuit_open_seconds` | Time the in-process circuit remains open after repeated failed requests |

The global `SOURCE_*` values are defaults. `LOKI_*`, `PROMETHEUS_*`,
`GITHUB_*`, and `SLACK_*` environment variables override them per source.

## Target Result Contract

Every future connector must provide or allow the collector to derive:

- source name and backend/tenant identity;
- requested time window and collection time;
- bounded result count, fetched sample count, and truncation/exactness state;
- typed result status: `ok`, `empty`, `partial`, `stale`, `forbidden`,
  `rate_limited`, `invalid_query`, or `failed`;
- sanitized diagnostic category and source request ID where available; and
- cancellation/deadline behavior that respects the source policy.

The current collectors now emit the target typed result status and a redacted
provenance envelope at the graph boundary. `partial` is used when a bounded
request or one metric query yields incomplete evidence; `empty` means the
connector completed successfully with no matching data. Authentication,
validation and rate-limit HTTP responses are mapped to `forbidden`,
`invalid_query`, and `rate_limited` without persisting a raw URL, query, or
provider response body. Real-provider pagination, freshness measurements and
credential-scoping verification remain open.

## Current Provenance And Quality Envelopes

Each source status contains a `connector-provenance/v2` object with:

- explicit source schema and connector version;
- sanitized backend identity and optional tenant;
- stable `query_id` and fingerprint;
- an `incident-query/v1` replay specification containing operation, service,
  allowlisted filters, window, limits, sampling policy and a query template;
- collection revision/time, matched/fetched/reduced counts, truncation and
  provider request ID when available.

Provider-native raw queries are not copied into model context. Prometheus query
text is removed from metric records after collection; the stable query ID
remains. Backend credentials, URL paths and query strings are removed.

Every collection also exposes `source-quality/v1`: input/usable/quarantined
records, parse/source errors, duplicates, missing fields/timestamps, timestamp
quality, first/latest event and freshness relative to the incident window.
Malformed log/deployment timestamps and missing required fields are
quarantined before normalization. Query IDs and source schemas survive log
grouping, timeline construction and evidence-graph nodes.

## Test Mapping

- `A03-T01` and `A03-T02`: future real-backend connector contract suite.
- `A03-T03`: current log limits plus future pagination suite.
- `A03-T04` subset: `tests/test_connector_policy.py` verifies per-source
  timeout/retry/circuit configuration without making a network request.
- `A03-T05` subset: `tests/test_source_provenance.py` covers sanitized,
  replayable query provenance, malformed/duplicate records, freshness fields
  and lineage through grouping/evidence graph.
- The remaining real-provider access-control, pagination, deploy truth, trace,
  routing and freshness-SLO evidence stays open.
