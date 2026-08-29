# Local-Safe v0.1 evidence refresh — 2026-08-24

Status: **Local-Safe evidence refresh complete**

Release scope: local synthetic pipeline and explicit OpenAI smoke

Production claim: none

This record preserves the regression, admission-control and model-provider
evidence for the local-safe boundary. The current consolidated interpretation
is in [`EVALUATION.md`](../EVALUATION.md).

## Decision

- Local-Safe remains complete; it is **not** Shadow-, pilot- or
  production-ready.
- The next implementation work remains the open batches in
  [`PROJECT_MASTER_CHECKLIST.md`](../development/PROJECT_MASTER_CHECKLIST.md).
- The OpenAI result validates synthetic local behaviour. It does not ratify
  production capacity, provider policy, cost, SLOs or a release gate.

## Validation evidence

| Check | Result |
| --- | --- |
| `.venv/bin/python scripts/quality_gate.py` | Passed: 349/349 tests; Ruff, scoped mypy, compileall, prompt budgets, secret scan, dependency audit and SBOM passed. |
| Branch coverage | 75.4% repository-wide (74% ratchet), 82.2% core (80% gate), 95.9% security controls (90% gate). |
| Explicit OpenAI bucket load | 100,000 synthetic signed webhook events through the local API and two workers; 12 durable analysis jobs/revisions, 12 successful provider calls and 0 dead letters. |

Matching alerts were placed in five-minute incident buckets. Every event was
persisted; each bucket retained one pending job and at most one follow-up while
the job ran. After the per-incident 12-call model budget was consumed, 6 later
provider calls were blocked and the deterministic fallback was used. Runtime
telemetry masked token values in the persisted load ledger, so this run is not
token-usage or cost-calibration evidence.

## Confirmed boundary

- The default Compose load workflow keeps the model disabled and makes no
  external calls.
- The real-provider test requires the explicit
  `compose.openai.yaml` override. It receives the credential at runtime
  from the excluded `.env`; the Compose file stores no credential.
- Only synthetic alerts were sent. No production telemetry, connector access,
  external publishing or remediation was exercised.

## What remains open before production

- An approved provider/data-region/retention and billing-reconciliation policy,
  plus production-calibrated budgets and SLOs.
- Real IdP/SSO and RBAC registration, managed secrets/KMS, retention/deletion,
  immutable audit storage and independent security/privacy review.
- Target-environment staging, multi-host recovery and measured RPO/RTO.
- An SRE-adjudicated gold set, shadow evidence and quality ratification.
- CI/CD, IaC, dashboards and alerts in the chosen production environment.
