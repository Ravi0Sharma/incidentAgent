# Operating contract

This document defines the current support boundary. It is not a claim that the
repository is ready for production traffic.

## Current behavior

| Capability | Supported behavior | Boundary |
| --- | --- | --- |
| Alert HTTP intake | Grafana-style alerts and Alertmanager batches | Raw EventBridge payloads are not wired into `/v1/alerts` |
| CloudWatch alarm translation | Standalone allowlisted `ALARM`/`OK` translator | Publicly verified with sanitized events only |
| Log evidence | Loki, CloudWatch Logs Insights or deterministic fixtures | External connectors are opt-in and deployment-owned |
| Metric evidence | Prometheus, CloudWatch GetMetricData or deterministic fixtures | Fixed/allowlisted metric definitions only |
| Change evidence | GitHub-compatible deployment records or fixtures | Repository activity is not automatically production-deploy truth |
| Trace evidence | Trace/request IDs extracted from logs | No trace-backend evidence connector |
| Services | Explicit entries in `config/services.yaml` | Unknown services fail intake |
| Model | Configurable OpenAI-compatible structured-output client | Optional, bounded and never an authority |
| Runtime state | MySQL events, queue, revisions, reviews and LangGraph checkpoints | SQLite is limited to bounded local raw-log cache and isolated legacy tests |
| Review | Local browser flow; secure configuration supports OIDC/RBAC | Real IdP registration and staging authorization proof are deployment work |
| Output | Versioned local HTML drafts | External publishing is off by default and needs exact-draft approval |

The default Compose stack uses fixtures, disables external connectors/model
calls and keeps publishing off. The OpenAI override uses redacted synthetic
evidence and still cannot publish.

CloudWatch evidence clients construct real boto3 requests, but the public test
suite injects AWS-shaped fakes. No real AWS account proof, credential or private
source map is included. See [CLOUDWATCH.md](../operations/CLOUDWATCH.md).

## Safety behavior

| Situation | Required response |
| --- | --- |
| Invalid signature, replay, schema, service or limit | Reject before analysis |
| Exact accepted redelivery | Return `duplicate_event`; create no duplicate job |
| Optional source failure | Record a typed gap; lower confidence or abstain |
| Model failure or budget exhaustion | Use deterministic/degraded output or abstain |
| Missing, stale or contradictory evidence | Return `No supported root cause yet` |
| Worker loss | Reclaim after lease expiry without duplicating the durable revision |
| Stale reviewer decision | Reject with a version conflict |
| Analysis approval | Create a versioned local draft; do not imply publication approval |
| Uncertain publisher acknowledgement | Block automatic retry for reconciliation |

No automatic remediation exists.

## Abstention

The system must abstain rather than force a hypothesis when:

- required evidence is unavailable, malformed, stale or excessively
  truncated;
- leading candidates are materially tied;
- supporting and contradicting evidence conflict;
- cited evidence cannot support the typed cause/mechanism/impact claim;
- model output fails its schema or grounding checks; or
- the incident is outside the configured support scope.

An abstention includes the incident window, available evidence, known gaps,
why support is insufficient and the next smallest safe evidence step.

## Change policy

Prompts, models, rules, schemas, source maps, security controls, retrieval and
publishing are behavior-changing artifacts. Before promotion, record:

1. the affected contract and versioned artifact;
2. automated tests and label-last evaluation where relevant;
3. grounding, abstention, latency and cost comparison;
4. rollback or kill-switch behavior; and
5. explicit approval for the target environment.

Documentation cannot weaken a runtime safety control. Current test strategy and
release requirements are in
[TEST_STRATEGY.md](../development/TEST_STRATEGY.md) and
[PRODUCTION_READINESS.md](../operations/PRODUCTION_READINESS.md).
