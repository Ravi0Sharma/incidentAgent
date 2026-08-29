# Connector contract

Connectors are bounded, read-only evidence sources. Deployment configuration
selects a connector and its scope; an alert cannot select endpoints,
credentials or unrestricted provider queries.

## Implemented connectors

| Connector | Capability | Main bound | Public verification boundary |
| --- | --- | --- | --- |
| Loki | Log counts, samples and targeted search | Incident window and query/sample caps | Local mock plus contract tests; real-backend suite not included |
| Prometheus | Error rate, p95 latency and request rate | Fixed metrics and incident window | Local mock plus contract tests; real-backend suite not included |
| GitHub-compatible API | Recent deployment-like records | Lookback window and result cap | Mocked unless explicitly configured |
| CloudWatch Logs Insights | Allowlisted service log groups and fixed query | 50 groups, result limit and polling budget | Real boto3 path; AWS-shaped fake clients in tests |
| CloudWatch GetMetricData | Allowlisted metric definitions | 500 queries and bounded pages | Real boto3 path; AWS-shaped fake clients in tests |
| Slack | Separately approved postmortem notification | Exact-draft approval and durable attempt guard | Mocked unless explicitly configured |

The default Compose stack disables all external connectors. Missing local Loki,
Prometheus or GitHub configuration uses deterministic fixture data. Mocks are
development behavior, not evidence that a provider is production-ready.

CloudWatch configuration and its exact test boundary are documented in
[CLOUDWATCH.md](../operations/CLOUDWATCH.md).

## Request policy

Each source has bounded timeouts, retry attempts, backoff and an in-process
circuit-open period. Per-source configuration overrides the global defaults.
An incident-wide deadline and tool budget provide an additional bound.

Connectors must return one of:

- `ok`;
- `empty`;
- `partial`;
- `stale`;
- `forbidden`;
- `rate_limited`;
- `invalid_query`; or
- `failed`.

An optional source failure becomes an explicit evidence gap. It may lower
confidence or force abstention, but it cannot silently become an empty result.

## Provenance

Each collection result includes a `connector-provenance/v2` envelope with:

- source schema and connector version;
- sanitized backend identity;
- stable query ID and fingerprint;
- incident window, operation, service, allowlisted filters and limits;
- collection revision/time;
- matched, fetched and retained counts;
- truncation/partial state; and
- sanitized provider request ID where available.

The replay specification is `incident-query/v1`. It contains enough sanitized
structure to understand the query without exposing credentials, raw provider
URLs or unrestricted query text.

## Source quality

`source-quality/v1` records input, usable, quarantined, duplicate and invalid
counts; missing fields/timestamps; source errors; time range; and freshness.
Malformed required fields and unusable timestamps are quarantined before
normalization. Query and source-schema IDs survive grouping, timeline and
evidence-graph stages.

## Required production proof

Before enabling a connector against a real system, verify:

- least-privilege credentials and tenant isolation;
- allowlisted query construction;
- representative real response shapes;
- pagination, truncation, empty and partial behavior;
- access denied, throttling, timeout and retry behavior;
- freshness and clock semantics;
- provider latency and cost; and
- redaction of diagnostics, request IDs and stored provenance.

No real provider endpoint or source map should be committed to this repository.
