# Operator Runbooks

## Queue backlog or stuck job

Inspect `incident_jobs` by status and lease expiry. Do not delete events.
Expired leases are reclaimable; exhausted jobs appear in `incident_dead_letters`.
Review redacted diagnostics, fix the cause, then use the authenticated replay
endpoint. Escalate if backlog grows faster than it drains.

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
tool expansion; `PUBLISH_EXTERNAL=false` blocks external publication. Reviewer
access is disabled by removing/revoking reviewer credentials or taking the UI
route out of service.
