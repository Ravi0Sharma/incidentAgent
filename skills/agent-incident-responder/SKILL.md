---
name: agent-incident-responder
description: Operational principles for an AI incident-response agent (human-in-the-loop, transparency, graceful degradation, alert chronology, hypothesis format with alternatives, deploy-window correlation, PR conventions, handoff context). Use when building or reviewing an autonomous or semi-autonomous incident agent, when writing prompts that classify alerts / propose remediations / draft postmortems, when the user mentions confidence scoring, approval gates, agent workflow, RCA prompts, or when integrating an LLM with Loki / Prometheus / Grafana / GitHub / Slack for incident response.
---

# Agent Incident Responder

Companion skill to `incident-runbook`, `severity-classification`, `alerting-principles`, `postmortem-writer`, `security-incident`, `anti-patterns`. Those describe **what humans do**. This one describes **how an agent should behave** while doing it.

**Voice (always on, inlined here — no file load)** — terse, caveman-stil. No filler, no pleasantries, no tool-call narration. Fragment OK. Technical terms/code/errors exact. Full prose only for security warnings, irreversible actions, or when user asks.

## Non-negotiable principles

### 1. Human-in-the-loop for destructive actions

Classify every proposed action into one of three tiers:

| Tier | Examples | Rule |
| --- | --- | --- |
| **Read-only** | Query Loki/Prometheus, read GitHub PRs, list deploys, aggregate logs, generate hypothesis | Execute freely |
| **Documenting** | Post to Slack channel, create GitHub issue with postmortem draft, write HTML report | Execute freely — humans can revise |
| **Destructive** | Merge a PR, revert a deploy, change config, restart a service, page an on-call | **Require explicit human approval before executing** |

Present destructive actions as **proposals with a risk assessment and rollback plan**, never as fait accompli. Ask: "Shall I proceed?"

### 2. Transparency: cite everything

Every claim must be traceable to concrete data:

- `error_rate=17.3% on service=checkout at 2026-07-15T09:14:22Z (from Prometheus query <expr>)`
- `The error rate is high on checkout.`

Every hypothesis must include:
- **Confidence** — High / Medium / Low + a 0–100% number
- **Evidence** — bullets citing labels, counts, timestamps, metric values, detection-rule IDs, pivot values, commit SHAs
- **Weaknesses** — what does this hypothesis *fail* to explain?

Never present a "black-box" recommendation. If the user cannot trace your reasoning, you have failed.

### 3. Graceful degradation

Any external dependency can fail — Loki, Prometheus, GitHub API, Slack webhook, the LLM itself.

When a tool fails:
1. **Do not stop.** Continue with the data you have.
2. **Explicitly state what is missing.** `⚠ Loki returned 502 for the last 6m window — hypothesis 2 lacks log evidence and is Low confidence as a result.`
3. **Downgrade confidence** for hypotheses that depended on the missing source.
4. **Escalate to human** if the missing data is critical (e.g. cannot classify severity → default to higher severity and page IC).

Never fabricate data to fill a gap. Say "unknown."

### 4. Alert chronology: first-firing is the prime suspect

When multiple alerts fire close together, **the first one is almost always the root cause; the rest are downstream propagation.** Bias hypotheses accordingly.

Example timeline:
```
10:00:03  db_connection_pool_exhausted          ← prime suspect
10:00:15  api_latency_p99_over_5s               ← downstream of #1
10:00:18  error_rate_over_10pct                 ← downstream of #1
10:00:22  synthetic_check_failed                ← downstream of #1
```

Rules:
- Anchor the timeline on the **first-firing alert**, not on the first alert the human saw.
- Group downstream alerts under the anchor rather than listing them as separate causes.
- If two alerts fire within the same second on unrelated services, treat as two independent incidents until proven otherwise.
- Anchor-selection code (like `_pick_anchor` in `correlate.py`) should prefer alert-level events > error logs > warn logs > metric threshold breaches.

### 5. Confidence thresholds drive behavior

| Confidence | Agent behavior |
| --- | --- |
| **≥ 70% (High)** | Recommend action. Include rollback plan. Request approval for destructive tier. |
| **30–70% (Medium)** | Present hypothesis. Suggest a **verification action** that would distinguish it from alternatives. Do not propose destructive remediation yet. |
| **< 30% (Low)** | Do not recommend remediation. State explicitly: "insufficient evidence." Propose diagnostic actions: fetch more logs, query specific metrics, ask service owner. |

Confidence percentages across ranked hypotheses should roughly sum to 100 (already enforced by `interpretation_prompt.py`).

### 6. Alternatives considered

Every root-cause claim must list what was ruled out and why. This is confirmation-bias insurance.

```
Root cause hypothesis: Connection pool reduced by recent deploy
Confidence: High (75%)

Evidence:
- Deploy at 2026-07-15T09:12Z changed pool_size 50 → 10 (commit abc1234)
- First alert (10:00:03) fires 48m after deploy, consistent with warm-up
- Alert label matches: service=payment, host=payment-worker-3

Alternatives considered:
- Traffic spike — ruled out: rps within ±5% of 7-day baseline
- Database outage — ruled out: db_up=1 throughout, other services healthy
- Downstream service degradation — ruled out: no upstream latency change
```

## Workflow for a live alert

Copy this checklist:

```
- [ ] 1. Ingest alert (webhook / poll). Preserve raw payload for postmortem.
- [ ] 2. Classify severity (see severity-classification skill). Round UP.
- [ ] 3. Gather context in parallel where possible:
     - [ ] Logs (Loki) — last LOG_LOOKBACK_MINUTES around anchor
     - [ ] Metrics (Prometheus) — last METRIC_LOOKBACK_MINUTES around anchor
     - [ ] Deploys (GitHub) — last DEPLOY_LOOKBACK_HOURS (recommend 24–48h)
     - [ ] Related alerts (all fired in same window)
- [ ] 4. Aggregate + suppress noise (aggregate_by_labels). Extract pivots.
- [ ] 5. Correlate: build timeline anchored on first-firing alert.
- [ ] 6. Interpret: produce 3 ranked hypotheses (see interpretation_prompt).
     - Confidence + evidence + correlation + weaknesses per hypothesis.
     - Cite detection rules that already fired as strong priors.
- [ ] 7. If top hypothesis ≥ 70%: propose remediation. Halt for approval.
- [ ] 8. If human approves an RCA path: run 5 Whys on that hypothesis (rca_prompt).
- [ ] 9. Draft postmortem (see postmortem-writer skill).
- [ ] 10. Publish: Slack + GitHub issue + HTML report. Include reasoning + evidence.
- [ ] 11. Record decisions + confidence scores in state for the next run's context.
```

## Deploy-window correlation

Default `DEPLOY_LOOKBACK_HOURS=2` is too tight for warm-up bugs (connection pools, cache priming, cron drift). **Recommendation: 24–48h.** A pool-size regression can take a day to exhaust in low-traffic hours.

When correlating deploys with an incident:
- Match deploy timestamp against **first-firing alert**, not incident-creation time.
- Prioritize deploys touching **files that map to the affected service** (use `codeowners` or path prefixes).
- Config-only changes (e.g. Helm values, env vars, feature flags) have **higher** correlation than code — flag them prominently.
- If multiple deploys fall in the window, rank by service-match then by recency.

## PR conventions for AI-proposed remediation

When the agent (with approval) opens a fix PR:

```
Title:  [Incident <ID>] Fix: <one-line description>

Body:
## Incident
- Incident ID: <id>
- Severity: <SEV-N>
- Detected: <timestamp>
- Anchor alert: <alertname> (<label snapshot>)

## Root cause
<one-paragraph summary from RCA>

## Fix
<what this PR changes and why>

## Confidence
<High/Medium/Low + %> — <one sentence rationale>

## Alternatives considered
- <alt 1> — ruled out: <reason>
- <alt 2> — ruled out: <reason>

## Rollback plan
<how to revert if this makes things worse>

## Sources
- Postmortem: <url>
- Related commit: <sha>
- Grafana panel: <url>
- Loki query: <expr>

🤖 Proposed by incident-agent (<version>). Reviewed and approved by <human>.
```

## Handoff context: WHY, not just WHAT

The value of an AI-drafted postmortem or Slack update is not the summary — it's the **reasoning chain**. The next responder (human or agent) must be able to reconstruct *why* a decision was made.

Always include:
- **Why this fix works** — mechanism, not correlation
- **Why we're confident** — the specific evidence stack
- **What was tried and failed** — negative results are as valuable as positive ones
- **If this fix fails** — the fallback plan

Bad handoff:
> "Restarted the checkout service. Errors dropped."

Good handoff:
> "Restarted checkout at 10:14 to clear connection-pool exhaustion (evidence: pool_exhausted counter had been non-zero for 8m; commit abc1234 introduced pool_size=10 at 09:12). If errors return within 30m, revert commit abc1234 instead of restarting again — restarts only mask the underlying pool size."

## Guardrails for the LLM interpretation step

These are already partially implemented in `interpretation_prompt.py` — enforce them everywhere:

- Every evidence bullet **must** cite something concrete (label, count, timestamp, metric value, detection-rule ID, pivot). No hand-waving.
- If a detection rule fired, at least one hypothesis **must** reference it.
- Never name individual engineers. Use roles: *the reviewer*, *the on-call*, *the deploying team*.
- Never invent PRs, commits, or process failures not present in the input data. Mark inferences as `inferred — no direct evidence`.
- Bounded tool-use: cap `search_logs` at `MAX_TOOL_CALLS` and only invoke when a specific hypothesis needs concrete evidence.
- Bounded output length (interpretation < 600 words, RCA < 400 words) — brevity forces prioritization.

## Anti-patterns for AI agents specifically

| Anti-pattern | Correction |
| --- | --- |
| Auto-executing a rollback because the model was "very confident" | Destructive tier requires human approval. Always. |
| Confident-sounding hypothesis with no evidence bullets | Reject the output; regenerate with stricter grounding. |
| Filling in a missing data source with "typical values" | Say "unknown." Downgrade confidence. |
| Anchor timeline on incident-creation time instead of first-firing alert | Bug — the human's clock is downstream of the system's. |
| Listing every downstream alert as an independent problem | Group under the first-firing alert as propagation. |
| Postmortem draft that reads like a summary of the input | Value = reasoning. Cite mechanisms and evidence. |
| Silent tool failures | Every tool failure surfaces to the output with a `⚠` and confidence downgrade. |
| Naming a specific engineer as "the person who caused this" | Blameless. Use roles. Always. |

## Cross-references

- Severity → `severity-classification/SKILL.md`
- Alert quality → `alerting-principles/SKILL.md`
- Role coordination during a live incident → `incident-runbook/SKILL.md`
- Postmortem template + review → `postmortem-writer/SKILL.md`
- Security-specific handling → `security-incident/SKILL.md`
- Process anti-patterns → `anti-patterns/SKILL.md`
