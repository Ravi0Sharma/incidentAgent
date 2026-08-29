# Operator Runbooks

## Database migration release

Run migrations before starting or rolling API/worker instances for a release.
Use a one-off process with `PROCESS_ROLE=migrator`,
`RUNTIME_SCHEMA_DDL_ENABLED=false`, and the dedicated DDL-capable
`MYSQL_MIGRATOR_USER` credentials:

```
python scripts/migrate_database.py apply
python scripts/migrate_database.py check
```

The command holds a MySQL advisory lock and records the applied release in
`schema_migrations`; repeat runs are safe. API and worker roles must not have
DDL grants. Do not run a destructive database downgrade during an incident:
roll back application code first, then use a tested backup/restore procedure
if a schema reversal is unavoidable.

The current migrations are additive: nullable job/revision fields and the
publication-attempt table. The rollback plan is therefore to stop intake,
deploy the previous API/worker image, leave the newer schema in place, and
verify `/readyz`. Do not delete columns or migration-ledger rows. A future
contracting migration requires its own compatibility release and restore point.

## Backup and restore rehearsal

Rehearse recovery against a new, isolated MySQL database before every material
release. Take a consistent logical backup from the designated incident
database, restore it under a new database name, then run the migrator in
`check` mode against the restored database. Verify that a checkpoint and an
incident/job record can be read before considering the rehearsal successful.

Never test restore by overwriting the live database. Keep the backup encrypted
and access-controlled, record its source timestamp and MySQL version, and
delete the isolated restore database after the rehearsal. A code rollback is
the first response to a bad migration; use the tested restore procedure only
when data recovery is required.

Generate local recovery evidence with:

```
python scripts/check_pitr_readiness.py --minimum-retention-seconds 86400
python scripts/verify_backup_restore.py
```

The restore verifier adds temporary canary data, creates a consistent dump,
restores it under a generated database name, verifies migrations, and reads
both an event and a checkpoint. It removes the restore database, dump and
source canaries after the rehearsal. Production must run the equivalent job
with managed backup credentials and retain the machine-readable report.

## Queue backlog or stuck job

Inspect `incident_jobs` by status and lease expiry. Do not delete events.
Expired leases are reclaimable; exhausted jobs appear in `incident_dead_letters`.
Review redacted diagnostics, fix the cause, then use the authenticated replay
endpoint. Escalate if backlog grows faster than it drains.

The API and worker must run independently with `API_DRAIN_JOBS=false`; start
the worker with `python scripts/run_worker.py`. In this mode `/healthz` only
shows that the API process is alive, while `/readyz` also requires a fresh row
in `incident_workers`. A stale/missing worker therefore makes readiness fail.

On `SIGTERM`/`SIGINT`, the worker stops polling, finishes its active job and
records `stopped`. Do not manually release a non-expired lease during normal
restart. If the process crashes, wait for `leased_until` to expire; another
worker then reclaims the same job with a higher `attempt_count`. Alert if
`pending` plus `leased` approaches `MAX_PENDING_JOBS`; API queue-capacity 503s
include `Retry-After` and callers should retry the original signed request.

For a release rehearsal, deliberately kill one worker while it holds a short
lease, wait for expiry, and confirm exactly one replacement worker reclaims
and completes that job. Preserve the job id and attempt count as evidence; do
not use a production incident as the test case.

Run the real process boundary and repeated race probes with:

```
python scripts/verify_distributed_runtime.py --jobs 64 --workers 4
python scripts/run_resilience_soak.py --cycles 5 --jobs-per-cycle 50 --workers 4
```

Start the production topology locally without Docker with:

```
python scripts/start_local_cluster.py --workers 2
```

In the deployed shadow/production environment, run
`python scripts/production_preflight.py` before opening ingress. It fails unless
secure configuration, the current schema, PITR prerequisites and the configured
minimum worker replica count all pass together.

Jobs use at-least-once delivery. Database revisions are keyed by job id, so a
crash/reclaim does not duplicate that durable effect. External providers must
still be handled according to their own idempotency contracts.

## Uncertain external publication

External publishing requires a separate final-draft approval. Before calling
providers, the application commits a unique publication attempt. Completed
attempts are deduplicated. If a process or provider fails after an
acknowledgement may have occurred, the attempt becomes `uncertain` and
automatic retry is blocked. Reconcile Jira, Slack and GitHub manually and
preserve the audit trail. Per-destination retry remains future work;
`PUBLISH_EXTERNAL=false` is the safe kill switch.

## Model or source outage

Set `SKIP_LLM=true` to force safe deterministic/abstaining behavior. Disable
tool calling with `USE_TOOL_CALLING=false` if source expansion is unsafe. Keep
events queued; do not retry by resending webhooks.

## Bad model, prompt, or rule release

Set `SKIP_LLM=true`, revert the versioned configuration, and reprocess only
after review. Generated documents stay local because `PUBLISH_EXTERNAL=false`.

## Database pressure or compromised secret

Stop intake at the load balancer, preserve MySQL data, rotate the affected
secret, validate `/readyz`, then re-enable controlled traffic. Do not expose
raw incident payloads in diagnostics.

## Kill switches

`SKIP_LLM=true` disables LLM calls; `USE_TOOL_CALLING=false` disables semantic
tool expansion; `PUBLISH_EXTERNAL=false` blocks all external publication.
`PUBLISH_JIRA_MCP=false`, `PUBLISH_SLACK=false` and `PUBLISH_GITHUB=false`
disable individual destinations. Reviewer access is disabled by
removing/revoking reviewer credentials or taking the UI route out of service.
