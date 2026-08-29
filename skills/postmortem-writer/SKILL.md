---
name: postmortem-writer
description: Produce a blameless postmortem for a major incident using PagerDuty's template and effectiveness guidelines. Use when the user asks for a postmortem, RCA, incident review, retrospective, or after-action report, or when finishing an incident and needing to document contributing factors, impact, timeline, and action items.
---

# Postmortem Writer

## Core principles

- **Blameless.** Never name-and-shame. If a human "caused" it, the system allowed them to. Attack the system.
- **Honest.** Do not soften details to look better. Postmortems that lie lose all value.
- **Separate what-happened from how-to-fix.** No "alternate reality" mixed into the timeline — describe reality, then propose fixes.
- **Avoid "human error."** Almost always there are multiple contributing factors — missing rate limits, stale docs, no canary — that let a mistake propagate.
- **Avoid the word "outage"** unless it truly was a full outage. Use *incident* or *service degradation*.

## When a postmortem is required

- **SEV-1** — postmortem meeting within **3 calendar days**.
- **SEV-2** — postmortem meeting within **5 business days**.
- **SEV-3 and below** — usually not required, but worthwhile if response was mobilized.
- **False alarm** — still do one. Why did response trigger unnecessarily? Fix that.

## Status lifecycle

| Status | Meaning |
| --- | --- |
| **Draft** | Content still being written. |
| **In Review** | Content complete, ready to review at the meeting. |
| **Reviewed** | Meeting done, content agreed. External message goes to Customer Support next. |
| **Closed** | All follow-ups tracked in JIRA. Skip straight here if no external message. |

## Owner workflow

Copy this checklist:

```
- [ ] Schedule the postmortem meeting (SEV-1: 3 cal days, SEV-2: 5 biz days) BEFORE filling content
- [ ] Create the postmortem doc from the template
- [ ] Reconstruct timeline from Slack + call recording
- [ ] Populate overview, contributing factors, resolution, impact (with numbers)
- [ ] Draft the external message
- [ ] Post in review channel ~24h before the meeting
- [ ] Run the meeting (IC keeps it on track; owner does most of the talking)
- [ ] Create JIRA tickets for action items (P0/P1 only — don't over-ticket)
- [ ] Send internal email with link to postmortem
- [ ] Hand off external message to Support for status-page publication
```

## The Template

Use exactly this structure. Fill every section; write `N/A` explicitly if a section doesn't apply.

```markdown
# Postmortem: <short incident name>

**Postmortem Owner:** <name>
**Meeting Scheduled:** <date, time, timezone>
**Call Recording:** <link>
**Status:** Draft | In Review | Reviewed | Closed

## Overview
One or two sentences: contributing factors + timeline summary + impact.
Example: "On the morning of August 12, we suffered a 47-minute SEV-1 due to
a runaway migration on the primary DB. Roughly 0.024% of notifications
that started during this window were delivered out of SLA."

## What Happened
Short factual description of the incident. No hypotheticals.

## Contributing Factors
Every condition that contributed. Include any responder actions that made
things worse — the point is to learn, not to blame.

## Resolution
What actually solved the problem. If there is a temporary fix and a
long-term fix, describe both.

## Impact
Specific numbers only. No adjectives.

| Metric | Value |
| --- | --- |
| Time in SEV-1 | ? min |
| Time in SEV-2 | ? min |
| Notifications delivered out of SLA | ??% (?? of ??) |
| Events dropped / not accepted | ??% (?? of ??) |
| Accounts affected | ?? |
| Users affected | ?? |
| Support requests | ?? (links to tickets) |

## Responders
- Incident Commander: <name>
- Scribe: <name>
- SMEs / others: <names>

## Timeline
All times in UTC. Include: (1) contributing factor started, (2) page fired,
(3) status page updated (public), (4) each significant action, (5) SEV-2/1 ended,
(6) link to the tool/log for each timestamp.

| Time (UTC) | Event | Data Link |
| --- | --- | --- |
| 2026-07-15 09:12 | Migration `2026_07_15_locks` began | <link to deploy log> |
| 2026-07-15 09:14 | Error rate on `/api/pages` crossed 5% | <link to Grafana> |
| … | … | … |

## How'd We Do?

### What Went Well
- Bullets. Fine to be empty.

### What Didn't Go So Well
- Bullets. Follow up on every point.

## Action Items
Each item = a JIRA ticket, tagged `sev1_YYYYMMDD` and `sev1` (or sev2 equivalent).
Keep to P0/P1 only. Don't over-ticket.

- [ ] JIRA-1234 — Add rate limit on the migration path
- [ ] JIRA-1235 — Improve monitoring: alert on lock-wait duration > 30s
- [ ] JIRA-1236 — Update runbook: rollback procedure for schema migrations

## Messaging

### Internal Email
Short paragraph for employees. Sent right after the meeting. Links to this page.

### External Message (for status.<company>.com)
- **Summary:** short, plain-language
- **What Happened:** factual, no jargon
- **What Are We Doing About This:** concrete steps, honest apology
```

## Review checklist (use before scheduling the meeting)

- [ ] Timeline reflects reality — cross-checked against Slack + call recording
- [ ] Every timeline row has a data link (graph, log, deploy record)
- [ ] Impact numbers are specific and sourced (query or link)
- [ ] Root causes go beyond the immediate trigger — dig until "the system allowed this"
- [ ] "What Happened" and "How to Fix" are separated
- [ ] Language is blameless — no names attached to blame, no "human error"
- [ ] Action items are scoped enough to be assignable (not "improve monitoring")
- [ ] External message will read well to a customer — not defensive, not vague

## Meeting agenda (15–30 min)

1. Recap the timeline — agree on the facts.
2. Recap unusual items or unknowns.
3. Discuss how it could have been caught earlier (canary? tests? loadtest?).
4. Discuss customer impact — real quotes if you have them.
5. Review action items — add / remove / re-scope.

The IC runs the meeting. The postmortem owner does most of the talking.

## Common failure modes

| Failure | Fix |
| --- | --- |
| Timeline is vague ("morning-ish") | Timestamps to the minute, UTC, with data links. |
| Uses "outage" for a partial degradation | Rewrite as "incident" or "service degradation." |
| Contributing factors = one bullet | Dig deeper: what upstream condition allowed it? |
| Action items are aspirational | Rewrite as specific, ownable JIRA tickets. |
| External message sounds defensive | Rewrite with an honest apology and concrete remediation. |
| No postmortem for a "small" incident | If responders were mobilized, do the postmortem. |
