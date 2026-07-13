# Security and operations baseline (v0)

## Trust boundaries and field handling

Untrusted inputs are Alertmanager payloads, source evidence, model output and
reviewer feedback. Before normal incident state is formed, input shape and
size are validated. Secret/PII-like values are recursively redacted before the
normalized evidence/report path. The model gets a compact evidence context,
not raw logs. External publishing is disabled by default.

Data classes are: **restricted** (secrets, credentials, customer identifiers),
**confidential** (raw incident evidence and reviewer feedback), and
**internal** (redacted metrics, source status and report metadata). Restricted
data must never reach models, traces, logs, HTML reports or publishers. The
remaining provider/region/retention decision is P0 and must be recorded before
an OpenAI provider is enabled.

## Current runtime guardrails

`/healthz` is liveness only. `/readyz` validates the supported production
baseline and verifies MySQL plus the local queue schema: webhook/reviewer
OIDC configuration, separate session/CSRF secrets, non-default redaction salt,
explicit CORS origins, HTTPS model
endpoint, a non-local checkpointer, and no external publishing. Unsafe
combinations return not-ready. Local development may use Basic Auth; shadow and
production require OIDC authorization-code login or a validated Bearer token.
Signed secure sessions expose only issuer, subject, expiry and roles. Viewer,
decision and operator roles are configured separately, and review mutations
require an identity/incident-bound CSRF token.

Every model completion uses a bounded timeout/retry/circuit policy. Source
connectors have their own bounded policies. A model failure falls back to a
deterministic/degraded result; it does not skip human review. Structured JSON
application events include timestamp, severity, environment, incident/revision,
node/source/request context and a redacted error category.

Audit records are separate redacted MySQL records for reviewer decisions,
invalid reviewer requests, failed reviewer authentication, dead-letter replay,
and requested reprocessing. They are append-only at the application layer,
but are not immutable/WORM storage and do not prove operator-level tamper
resistance. `GET /metrics` exposes process-local Prometheus-format counters
and duration summaries; it must be scraped into a shared metrics backend for
multi-worker dashboards and alerts.

## Required production controls

The OIDC/RBAC/CSRF boundary is implemented locally but still requires a real
identity-provider registration and staging security test. Hash-locked Python
dependencies, repository secret scanning, dependency audit and CycloneDX SBOM
generation now run in the local/CI quality definition. The following are not
implemented: at-rest key management, network egress allowlisting, approved
secret manager and rotation, container image scanning, durable queue/lease/outbox,
Postgres migrations, backups/restore drill, dashboards, alert routing and
canary delivery. They remain explicit blockers in `SEC-*`, `REL-*`, `OBS-*`
and `DEP-*` checklist items.

Threat-model coverage and proof are defined by `A09-T01`–`A09-T12`, recovery by
`A10-T01`–`A10-T12`, and observability by `A11-T01`–`A11-T10`.

For the AWS POC, a cloud secret means a credential stored in AWS Secrets
Manager (or Parameter Store) and supplied to the running service through an
approved IAM role, rather than committed to the repository or kept in a local
`.env` file. This integration is not needed for the local POC yet.
