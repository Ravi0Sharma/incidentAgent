# Railway development server

This is a shared **development/review** deployment. It is not a Shadow or
production deployment and it must not be connected to real alerts yet.

## Services

Create one Railway project with:

1. an API service from this repository;
2. a private worker service from the same repository and revision;
3. a Railway MySQL service shared by API and worker;
4. an optional Volume mounted at `/app/output` if generated HTML files should
   survive a redeploy.

The API uses `railway.toml` and starts
`uvicorn webhook.api:app --host 0.0.0.0 --port $PORT`. Override the worker
service start command with `python scripts/run_worker.py`; it must not have a
public domain. `/readyz` is healthy only when MySQL is ready and the separate
worker has a fresh durable heartbeat. Do not expose the API URL until the
review credentials below are present.

## Required Railway variables

Set these in the **application** service. Store all values marked secret in
Railway variables; never commit them.

```text
ENVIRONMENT=development
CHECKPOINTER=mysql
MYSQL_HOST=${{MySQL.MYSQLHOST}}
MYSQL_PORT=${{MySQL.MYSQLPORT}}
MYSQL_DATABASE=${{MySQL.MYSQLDATABASE}}
MYSQL_USER=${{MySQL.MYSQLUSER}}
MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}

REVIEW_AUTH_MODE=basic
REVIEW_USERNAME=<your private development username>
REVIEW_PASSWORD=<long unique secret>
REVIEW_CSRF_SECRET=<different random secret, 32+ characters>
REVIEW_SESSION_SECRET=<different random secret, 32+ characters>
REDACTION_SALT=<stable random secret>
WEBHOOK_SHARED_SECRET=<random secret; required before alert intake>

OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.6-luna
OPENAI_API_KEY=<OpenAI project key>
LLM_TIMEOUT_SECONDS=60
LLM_RETRY_ATTEMPTS=1
LLM_MAX_CALLS_PER_INCIDENT=12
LLM_MAX_INPUT_TOKENS_PER_INCIDENT=60000
LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT=12000
LLM_MAX_TOTAL_TOKENS_PER_INCIDENT=72000
LLM_MAX_COST_USD_PER_INCIDENT=0.05
LLM_INPUT_USD_PER_MILLION_TOKENS=0.20
LLM_OUTPUT_USD_PER_MILLION_TOKENS=1.20

PII_REDACTION_ENABLED=true
PUBLISH_EXTERNAL=false
API_DRAIN_JOBS=false
JOB_LEASE_SECONDS=120
JOB_HEARTBEAT_INTERVAL_SECONDS=30
WORKER_POLL_INTERVAL_SECONDS=1
WORKER_HEARTBEAT_STALE_SECONDS=15
MAX_PENDING_JOBS=1000
HTML_OUTPUT_DIR=/app/output
DEFAULT_ALERT_ENVIRONMENT=development
```

Leave `LOG_SOURCE` and `METRIC_SOURCE` at their local mock-compatible defaults
until a real connector is intentionally introduced. Do not copy public LogHub
datasets, local `.env`, or local `output/` files into Railway.

## Access from several computers

After deployment, Railway provides a public HTTPS domain. Use the same Railway
project/database from each computer and authenticate to review endpoints with
the configured Basic Auth credentials. `/healthz` and `/readyz` intentionally
remain unauthenticated for Railway health checks.

Railway does not synchronize source code between computers. Use a private git
remote before editing/deploying from more than one computer; connect it to
Railway for automatic deploys, or use Railway CLI from a checked-out clone.

## Acceptance checks

1. Railway healthcheck reports `/readyz` as healthy only while the worker is
   alive; stopping the worker changes it to 503 after the staleness window.
2. `https://<domain>/healthz` returns `{"status":"ok"}`.
3. A review endpoint without Basic Auth returns 401.
4. The same endpoint with Basic Auth is accessible.
5. A deployment restart leaves MySQL-backed incident history intact.
6. Killing the worker during a staging probe causes takeover only after lease
   expiry, increments the attempt once and creates exactly one analysis
   revision.

Do not set `ENVIRONMENT=shadow` or `production` for this project. Those modes
require real OIDC, authenticated telemetry, explicit CORS, a positive model
budget, and other release gates not being claimed by this development server.
