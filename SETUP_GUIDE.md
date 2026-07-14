# Setup Guide

## Local

Use Python 3.11 and MySQL 8.4. Create the `incident_agent` database, copy
`.env.example` to `.env`, keep `CHECKPOINTER=mysql`, then install from
`requirements.txt` and run the webhook with Uvicorn. `GET /readyz` confirms
safe runtime configuration; `GET /openapi.json` exposes the API contract.

For the reproducible development/test environment, use the exact bootstrap and
hash-locked dependency set used by CI:

```sh
.venv/bin/python -m pip install pip==26.1.2 setuptools==84.0.0
.venv/bin/python -m pip install --require-hashes -r requirements.lock
```

Run the local verification suite with:

```sh
.venv/bin/python scripts/quality_gate.py
```

The gate forces `SKIP_LLM=true`, disables external publishing and tracing,
and substitutes a non-secret test provider key. It never performs a live model
request. It requires the disposable local MySQL database to be reachable.

## Test

Use a disposable MySQL database with synthetic fixtures only. Set
`PUBLISH_EXTERNAL=false`; tests must not receive production connector,
publisher, or reviewer credentials.

## Staging, shadow, production

These environments are not supplied by this repository. Before creating them,
use separate credentials/databases/destinations, independent workers, TLS,
RBAC, a secret manager, backup/restore, migration, CI/CD and monitored
kill-switch procedures. Shadow mode must prohibit every external side effect.

Reviewer authentication must use `REVIEW_AUTH_MODE=oidc`. Register the HTTPS
`/auth/callback` URL with the identity provider, then configure issuer, metadata,
JWKS, audience, client ID/secret and the viewer/decision/operator role sets shown
in `.env.example`. Generate different random values of at least 32 characters
for `REVIEW_SESSION_SECRET` and `REVIEW_CSRF_SECRET`; supply all secrets through
the environment's secret manager. Basic Auth is local-only and fails production
readiness validation.
