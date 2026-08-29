# CloudWatch integration

Incident Agent includes an opt-in, read-only evidence path for CloudWatch Logs
Insights and CloudWatch GetMetricData.

## What is implemented

- `clients/cloudwatch_client.py` builds real boto3 clients.
- Logs use `StartQuery` plus bounded polling of `GetQueryResults`.
- Metrics use bounded `GetMetricData` pagination.
- Queries, log groups, namespaces, statistics and dimensions come from an
  operator-owned source map.
- Incoming alert fields cannot select an AWS region, endpoint, credential,
  log group, namespace or dimension.
- Partial results, truncation, request IDs and sanitized provenance are kept.
- AWS authorization, throttling, invalid-query and provider failures map to
  typed connector errors.

## What the public repository verifies

`tests/test_cloudwatch_connector.py` injects sanitized AWS-shaped fake clients.
It checks:

- fixed allowlisted Logs Insights queries;
- unknown-service rejection before an AWS call;
- bounded polling and terminal query failures;
- bounded metric pagination and partial-data handling;
- provenance without native query identifiers leaking into evidence; and
- translation of allowlisted CloudWatch alarm state changes.

The tests do not call a real AWS account. No AWS credential, account ID, ARN,
private log-group map or raw telemetry is committed.

The alarm translator in `webhook/cloudwatch.py` is currently a standalone
component. Raw EventBridge events are not accepted directly by `/v1/alerts`;
an authenticated gateway must translate them to the documented alert contract,
or the translator must be explicitly wired into a future ingress route.

## Configure a private source map

Copy the public example to the ignored private path:

```bash
cp config/cloudwatch_sources.example.yaml config/cloudwatch_sources.yaml
```

Edit the private copy with approved alarm names, services, log groups and
metrics. Do not commit it. Then configure:

```dotenv
LOG_SOURCE=cloudwatch
METRIC_SOURCE=cloudwatch
CLOUDWATCH_REGION=<approved-region>
CLOUDWATCH_SOURCE_MAP_PATH=config/cloudwatch_sources.yaml
```

Use an AWS runtime role or another approved boto3 credential provider. Do not
put access keys in `.env`, the source map or alert payloads.

Minimum read-only actions depend on the selected path and should be scoped to
the configured resources. The implementation uses:

- `logs:StartQuery`;
- `logs:GetQueryResults`; and
- `cloudwatch:GetMetricData`.

## Local verification

```bash
.venv/bin/python -m unittest -v \
  tests.test_cloudwatch_connector \
  tests.test_config_versions
```

The default Compose stack keeps all external connectors disabled. Enabling the
CloudWatch selectors is an explicit deployment change and requires boto3
credentials at runtime.

## Before claiming real AWS support

Record sanitized evidence for:

- the approved region and IAM role boundary;
- representative Logs Insights and GetMetricData calls;
- throttling, timeout, partial-data and access-denied behavior;
- real log/metric shape compatibility;
- provider latency and query cost; and
- end-to-end alert transport into `/v1/alerts`.

Do not publish account IDs, ARNs, private source-map values, raw telemetry or
request identifiers with that evidence.
