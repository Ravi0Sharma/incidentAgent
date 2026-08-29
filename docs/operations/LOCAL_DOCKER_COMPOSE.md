# Local Docker Compose runbook and E2E checklist

This runbook is the canonical way to start and share the complete local
Incident Agent topology. It starts MySQL, applies migrations once, starts a
separate API and two independent workers, and keeps every published port bound
to `127.0.0.1`.

The base stack is intentionally safe for local development:

- evidence connectors and the hosted model are disabled;
- fixture-backed deterministic analysis remains available;
- external publication is disabled;
- MySQL TLS is disabled only inside the private local Compose network;
- all credentials in `compose.yaml` and the init SQL are local placeholders;
- the API and MySQL are not exposed to the LAN.

It is not a production deployment template. Production requirements are in
[`PRODUCTION_READINESS.md`](PRODUCTION_READINESS.md).

For a complete local run that includes the real OpenAI model, use the explicit
override below. It reads provider settings from the ignored `.env`, enables the
model, and permits outbound access only for that run. `PUBLISH_EXTERNAL` stays
false.

## Topology

| Service | Responsibility | Host endpoint |
| --- | --- | --- |
| `mysql` | Durable events, queue, revisions, review state and LangGraph checkpoints | `127.0.0.1:3307` |
| `migrator` | Applies versioned schema changes and exits successfully | none |
| `api` | Webhook intake, review UI, health, readiness and metrics | `http://127.0.0.1:8000` |
| `worker-1` | Claims leased jobs and executes the graph | `http://127.0.0.1:9101/metrics` |
| `worker-2` | Independent second consumer for local HA behavior | `http://127.0.0.1:9102/metrics` |
| `verify` | One-shot signed E2E canary and duplicate-delivery check | none |

Application containers use the private hostname `mysql:3306`; port `3307` is
only for optional inspection from the host. MySQL state lives in one named
volume. Generated reports and the bounded local raw-log cache share a second
writable volume, so graph continuation can move between the API and workers
without writing to their read-only image layers. Normal restarts do not erase
either volume.

## Prerequisites checklist

Before the first start, confirm all boxes:

- [ ] Docker Engine or Docker Desktop is installed and running.
- [ ] `docker version` succeeds for both client and server.
- [ ] `docker compose version` reports Compose v2.
- [ ] At least 4 GB of memory and 5 GB of free disk are available to Docker.
- [ ] Host ports `8000`, `3307`, `9101` and `9102` are free.
- [ ] The command is being run from the repository root.
- [ ] No real provider secrets have been copied into `compose.yaml`.
- [ ] `PUBLISH_EXTERNAL` is still `false` in `compose.yaml`.

Render and statically validate the configuration before starting it:

```bash
docker compose config --quiet
python scripts/validate_compose_config.py
```

The Python validator checks the two-worker topology, process/database roles,
migration dependency, read-only application filesystems, loopback ports,
private network and publication kill switch.

## Start everything

The only required startup command is:

```bash
docker compose up --build --wait
```

This is the no-cost topology check: it runs the complete durable workflow with
deterministic interpretation, because `MODEL_ENABLED=false` and
`SKIP_LLM=true` in `compose.yaml` deliberately block provider calls.

### Start the full flow with OpenAI

With a valid `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` in `.env`:

```bash
docker compose -f compose.yaml -f compose.openai.yaml up --build --wait
docker compose -f compose.yaml -f compose.openai.yaml --profile tools run --rm --no-deps verify
```

The second command sends one signed synthetic canary through API, two workers,
MySQL and the OpenAI model. It does not use external telemetry connectors and
cannot publish externally.

### Start with Jira MCP publication to a sandbox

Only after configuring a disposable Jira project and a scoped token in the
ignored `.env`, start the explicit publisher override:

```bash
docker compose -f compose.yaml -f compose.jira-mcp.yaml up --build --wait
```

This keeps fixtures and deterministic analysis but changes the external-effect
boundary: approval of the exact draft can create a Jira issue. Do not run the
normal verifier's review steps unattended against a real destination. Setup,
least-privilege and failure semantics are in [JIRA_MCP.md](JIRA_MCP.md).

On the first run Docker downloads the pinned base images, builds the application
image, initializes the database users, applies every migration, starts both
workers and finally marks the API healthy when `/readyz` sees two current
worker heartbeats. Later runs reuse the image and MySQL volume unless their
inputs changed.

To keep logs attached, omit `--wait`. To run in the background while still
waiting for health:

```bash
docker compose up --build --detach --wait
```

Expected result:

- `mysql`, `api`, `worker-1` and `worker-2` are healthy;
- `migrator` has exited with status `0`;
- `verify` is absent because it is an on-demand tool;
- `GET /readyz` returns HTTP 200 and reports at least two active workers.

Inspect the state:

```bash
docker compose ps
curl --fail --silent http://127.0.0.1:8000/healthz
curl --fail --silent http://127.0.0.1:8000/readyz
curl --fail --silent http://127.0.0.1:8000/metrics
curl --fail --silent http://127.0.0.1:9101/metrics
curl --fail --silent http://127.0.0.1:9102/metrics
```

## Required E2E acceptance check

Run the verifier after every clean build or shared-environment handoff:

```bash
docker compose --profile tools run --rm --no-deps verify
```

The verifier does more than ping the API. It:

1. requires `/readyz` to observe both worker processes;
2. signs and sends a synthetic `payments` alert;
3. sends the identical body again and requires `duplicate_event`;
4. polls the durable canary job record until completion;
5. requires exactly one controlled processing attempt;
6. requires at least one durable analysis revision.

Success prints JSON containing `active_workers: 2`,
`duplicate_status: "duplicate_event"` and a completed job. The generated
incident remains available in the review UI at `http://127.0.0.1:8000/`.

## Manual review check

Open `http://127.0.0.1:8000/`. The local basic-auth credentials are deliberately
non-secret development values:

```text
username: incident-reviewer
password: local-review-only
```

Open the canary incident and confirm that evidence, ranked hypotheses,
uncertainty and the review controls render. Review actions persist to MySQL.
Approval of the analysis creates a postmortem draft and a separate exact-draft
publication decision; `PUBLISH_EXTERNAL=false` prevents external effects.

## Failure and recovery checks

The following checks are safe against synthetic local data.

### Kill one worker

```bash
docker compose kill worker-1
curl --fail --silent http://127.0.0.1:8000/readyz
docker compose up --detach worker-1
```

Readiness is expected to become unavailable once the killed worker heartbeat
ages past the configured threshold, then recover after `worker-1` returns.
`worker-2` continues consuming jobs. A job killed after being leased is
reclaimable only after its lease expires; durable job-id keys prevent duplicate
analysis revisions.

### Restart the API

```bash
docker compose restart api
docker compose ps
curl --fail --silent http://127.0.0.1:8000/readyz
```

Workers and MySQL remain alive while the API restarts. Pending and in-flight
jobs are not stored in API memory.

### Re-run migrations

```bash
docker compose run --rm migrator
```

Migrations are ledgered and repeat-safe. The output should list current
migrations under `already_applied`.

## Logs and diagnosis

Follow all runtime logs:

```bash
docker compose logs --follow --tail=200 api worker-1 worker-2 mysql
```

Inspect a single service:

```bash
docker compose logs --tail=200 migrator
docker compose logs --tail=200 worker-1
```

Common failures:

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Docker daemon connection error | Docker Desktop/Engine is stopped | Start Docker and retry `docker version` |
| Port already allocated | Another local service uses a published port | Stop it or intentionally change only the host side of the mapping |
| `migrator` exits non-zero on an old volume | Schema or local role state is inconsistent | Read migrator/MySQL logs; preserve the volume until the cause is understood |
| `/readyz` returns 503 | MySQL, schema, queue or fewer than two fresh workers | Check `docker compose ps` and worker logs |
| E2E receives `tenant_mismatch` | Canary and Compose tenant values diverged | Keep both values at `local-compose` |
| E2E reports duplicate failure | Intake idempotency regression | Stop and investigate before sharing the stack |
| E2E remains pending | Workers are unhealthy or a lease is stuck | Inspect both worker logs and queue gauges |

## Stop, preserve or reset

Stop containers while preserving the database and reports:

```bash
docker compose down
```

Start again with the same durable state:

```bash
docker compose up --build --wait
```

To permanently erase all local Compose database and report state, use the
following only when the data is disposable:

```bash
docker compose down --volumes
```

That reset is not recoverable unless a separate backup was created. It also
causes the local MySQL users and schema to be initialized again on next start.

## Sharing between local machines

Share the repository at a specific commit, not built containers or the MySQL
volume. The receiving machine runs the same startup and E2E commands. This
ensures that migrations and image construction are reproducible on that host.

For a repeatable handoff, record:

- the Git commit SHA;
- `docker version` and `docker compose version`;
- the output of `docker compose ps`;
- the JSON from the E2E verifier;
- any deliberate changes to host ports or resource limits.

Do not share `.env`, a raw MySQL data directory or real incident payloads.

## Boundary to shadow and production

Do not turn this local file into a public deployment by changing
`ENVIRONMENT`. Shadow/production additionally require managed MySQL with TLS
identity verification and PITR, managed secrets, OIDC, HTTPS ingress, explicit
CORS/egress, real source contracts, metrics authentication and an approved
release record. Use the production preflight and
[`OPERATOR_RUNBOOKS.md`](OPERATOR_RUNBOOKS.md) for that transition.
