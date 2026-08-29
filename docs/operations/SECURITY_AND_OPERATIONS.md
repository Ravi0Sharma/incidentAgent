# Security and operations

## Trust and data handling

Webhook payloads, connector responses, model output, reviewer feedback and
publisher responses are untrusted.

Input shape and size are validated before incident state is created.
Secret/PII-like values are recursively redacted before persistence, prompts,
logs and reports. The model receives a compact evidence pack, not unrestricted
raw logs. External publishing is disabled by default.

Data classes:

| Class | Examples | Rule |
| --- | --- | --- |
| Restricted | Secrets, credentials, customer identifiers | Must not reach models, traces, reports or publishers |
| Confidential | Raw incident evidence and reviewer feedback | Access-controlled, redacted and retained by deployment policy |
| Internal | Redacted metrics, source state and report metadata | Still treated as untrusted data |

## Runtime guardrails

- `/healthz` reports process liveness only.
- `/readyz` validates secure configuration, current migration, MySQL/queue and
  required worker heartbeats.
- Local development may use Basic Auth; secure modes require OIDC and explicit
  viewer, decision and operator roles.
- Browser mutations require an incident-bound CSRF token.
- Model and connector calls have timeout, retry, circuit and incident budgets.
- Provider/model failure cannot skip human review or enable publication.
- External publication requires separate exact-draft approval and a durable
  attempt guard.
- Ambiguous external acknowledgement blocks automatic retry.

Structured application events include incident/revision, node/source/request
context and a redacted error category. Audit records cover review decisions,
invalid review requests, failed authentication, dead-letter replay and
reprocessing.

Application audit rows are append-only but are not immutable/WORM storage. A
production deployment needs organizational audit retention and operator-level
tamper controls.

## Secrets

Do not commit `.env`, private CloudWatch source maps, provider keys, database
credentials, certificates, dumps or raw incident data. The repository ignores
the common local forms and includes a pattern-based scanner:

```bash
.venv/bin/python scripts/check_repository_secrets.py
```

Use the target platform's secret manager and runtime identity. For AWS, prefer
an IAM role and the standard boto3 credential chain over static access keys.
Rotate a credential immediately if it may have been exposed outside the
ignored local file.

## Production controls still required

- Real identity-provider registration and staging authorization tests.
- Managed secret injection and rotation.
- Encryption at rest with managed keys.
- Retention, deletion, legal hold and tenant-isolation policy.
- Immutable audit storage.
- Container/IaC scanning and independent security review.
- Shared metrics, dashboards and alert routing across processes.
- Target-environment backup, failover and measured RPO/RTO.
- Provider-specific publication reconciliation.
- Approved data-region, retention and model-provider policy.

The complete environment gate is
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
