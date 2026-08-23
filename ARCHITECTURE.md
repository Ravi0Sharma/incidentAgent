# Architecture (current POC and production target)

```text
Alertmanager/CloudWatch adapter (untrusted)
  -> validate + HMAC + nonce replay protection + normalize/redact
  -> MySQL incident_events + idempotency key + incident_jobs (atomic ACK)
  -> lease-based MySQL worker
  -> MySQL LangGraph checkpointed workflow
     -> bounded Loki / Prometheus / deployment evidence
     -> deterministic candidate scoring
     -> bounded OpenAI-compatible semantic/interpretation stages
     -> human review interrupt
     -> RCA + postmortem draft
     -> reviewer revision gate
     -> local HTML draft (external publishing disabled by default)
```

Trust boundaries are the webhook, each configured source connector, the model
provider, the reviewer browser, MySQL/report files and every future
publisher. A correlation/incident ID must cross all of these boundaries. The
event, lifecycle, pending review and checkpoint records are durable MySQL
state. Canonical schemas and invariants are listed in
[`CANONICAL_SCHEMAS.md`](CANONICAL_SCHEMAS.md).

Local development may still drain jobs from the API when `API_DRAIN_JOBS=true`.
Shadow and production reject that setting and require the independent
`scripts/run_worker.py` process. Durable worker heartbeats, renewable job and
incident leases, retry/dead-letter state and bounded queue admission are stored
in MySQL. The remaining production target adds versioned migrations,
connection pooling, object storage, validated multi-host behavior, immutable
audit records and outbox-based external writes. No automatic remediation
exists in either architecture.

## Decisions awaiting ADRs

The current MySQL storage/queue decision is documented in
[`docs/adr/0001-mysql-incident-store-and-queue.md`](docs/adr/0001-mysql-incident-store-and-queue.md).
Before production, create ADRs for identity/RBAC, model providers/data handling,
knowledge retrieval, object storage/retention and publication.
