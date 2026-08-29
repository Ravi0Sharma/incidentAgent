# Architecture

Incident Agent is a durable, human-reviewed incident-analysis pipeline. The
default Docker Compose stack runs an API, a one-shot migrator, MySQL and two
independent workers.

![Complete system flow](SYSTEM_FLOW.svg)

## Runtime flow

1. `POST /v1/alerts` authenticates, bounds and validates Grafana-style or
   Alertmanager payloads.
2. The API normalizes and redacts the alert.
3. MySQL commits the event, idempotency key and queue job atomically.
4. A worker leases the job and resumes the MySQL-checkpointed LangGraph.
5. Bounded connectors collect logs, metrics and deployment evidence.
6. Deterministic stages normalize, group, correlate and rank candidates.
7. Optional model stages interpret only the compact redacted evidence pack.
8. The graph stops for analysis review.
9. Approval creates RCA and a versioned local postmortem draft.
10. A second exact-draft decision is required before external publication.

The CloudWatch evidence path uses real boto3 APIs when explicitly configured.
The public tests use AWS-shaped fake clients, and raw EventBridge intake is not
currently wired into the HTTP route. See the
[CloudWatch guide](../operations/CLOUDWATCH.md).

## Local services

| Service | Responsibility |
| --- | --- |
| `migrator` | Applies versioned schema migrations and exits |
| `api` | Alert intake, review UI, health, readiness and API metrics |
| `worker-1`, `worker-2` | Lease jobs and execute the graph independently |
| `mysql` | Durable operational state and graph checkpoints |
| `verify` | Sends a signed synthetic canary and verifies deduplication |

The API becomes ready only when configuration, schema, MySQL, queue state and
the required worker heartbeats are valid. `/healthz` is process liveness;
`/readyz` is the routing/deployment gate.

## Durable invariants

| Record or boundary | Invariant |
| --- | --- |
| Incident event | Unique content-derived idempotency key; append-only event history |
| Event and job | Written in one transaction before acknowledgement |
| Job | Unique key; only the lease owner may complete/fail it; exhausted retries become a dead letter |
| Checkpoint | Database-direct, multi-process-safe write with immutable conflict detection |
| Analysis revision | Monotonic per incident; previous versions are not overwritten |
| Evidence revision | Exact membership snapshot; corrected content creates a linked version |
| Lifecycle | Versioned legal transitions; stale writes fail |
| Analysis review | Decision binds to the displayed pending revision and reviewer identity |
| Publication review | Decision binds to the exact draft version and SHA-256 digest |
| Publication attempt | Durable at-most-once guard; uncertain acknowledgement blocks automatic retry |

## Stored data

MySQL stores accepted events, jobs and leases, checkpoints, lifecycle,
canonical evidence, analysis revisions, reviews, postmortem drafts, dead
letters, worker heartbeats, audit events and publication attempts.

Compose uses `/app/output` for generated local HTML and the bounded raw-log
cache used during graph continuation. Raw external datasets and generated
evaluation output are ignored by Git. Production retention, deletion,
encryption and object-storage policy remain deployment decisions.

## Why MySQL also backs the queue

The accepted event and its work item must cross one durable boundary. Keeping
both in MySQL makes atomic acknowledgement, idempotency, incident-level
serialization, leases and backup/restore possible without a second message
system in the local topology.

The migrator has DDL permission. API and worker identities receive only the
data-plane grants they need. Runtime schema creation remains disabled outside
the migration job.

## Trust boundaries

Treat all of these as untrusted:

- webhook payloads;
- every evidence connector response;
- model output;
- reviewer feedback and browser requests;
- database/report files; and
- future publisher responses.

The incident/correlation ID crosses every boundary. Input limits, recursive
redaction, typed evidence, output escaping, deployment-owned connector
allowlists and version-bound human decisions keep untrusted content from
becoming authority.

## Explicit non-goals

- No automatic remediation.
- No production claim from local fixtures or public datasets.
- No raw provider query or credential supplied by an alert.
- No implicit publication approval from analysis approval.
- No automatic retry when external delivery may already have succeeded.

Production environment requirements are tracked in
[PRODUCTION_READINESS.md](../operations/PRODUCTION_READINESS.md).
