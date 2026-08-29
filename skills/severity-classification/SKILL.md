---
name: severity-classification
description: Classify an incident as SEV-1 through SEV-5 using PagerDuty's rubric. Use when triaging an alert, deciding whether to page an Incident Commander, choosing an escalation path, or when the user mentions severity, SEV levels, major incident, or incident classification.
---

# Severity Classification

## Core principle

**Always assume the worst.** If you cannot decide between two levels, pick the higher one. Never litigate severity during an active incident — classify, respond, revisit in the postmortem.

Anything at SEV-2 or above is a **major incident** and must trigger the full incident response process (page an Incident Commander with `!ic page`).

## Severity rubric

| Level | Trigger | Response |
| --- | --- | --- |
| **SEV-1** | Critical: warrants public notification and executive liaison. Large customer impact, SLA breach for extended period, or customer-data-exposing security vulnerability. | Page IC. Notify internal stakeholders. Public status-page post. Postmortem within **3 calendar days**. |
| **SEV-2** | Critical system issue actively impacting many customers. Notification / core pipeline severely impaired. Web app broken for most users. Monitoring of major-incident conditions impaired. | Page IC. Full incident response. Postmortem within **5 business days**. |
| — major incident line — | Everything above requires coordinated response. | |
| **SEV-3** | Stability or minor customer-impacting issues needing immediate service-owner attention. Partial loss of functionality. Loss of redundancy (one more failure = outage). Likely to escalate. | High-urgency page to service team. Top priority. Rollback if related to recent deploy. Escalate to `!ic page` if it grows. |
| **SEV-4** | Minor issues requiring action but no customer impact. Delays, single node down, cron/job failure not on critical path. | Low-urgency page to service team. Handle before normal work. |
| **SEV-5** | Cosmetic bugs, no customer-ability impact. | JIRA ticket to service owner. |

## Deciding: is it an incident at all?

Trigger the response process for **any unplanned disruption or degradation of service** that any employee deems necessary. If unsure — trigger it. The IC decides whether to stand it down.

Ask, in order:
1. Can customers perform all critical product functions across all platforms?
2. Are downstream promises (notifications, events, SLAs) being met?
3. Is a coordinated response between multiple teams needed?

Any "no" → trigger response.

## Classification workflow

Copy this checklist:

```
- [ ] Identify the affected surface (service, pipeline, platform)
- [ ] Quantify impact (% users, % accounts, % requests, dollars)
- [ ] Check SLA/SLO status (breaching now? about to?)
- [ ] Check security dimension (data exposure? auth bypass?)
- [ ] Map to SEV table above, round UP on any tie
- [ ] If SEV-2 or higher → `!ic page`
```

## Examples

**Example 1** — "5xx rate on checkout is 40% for the last 4 minutes."
→ Actively impacting many customers, core revenue path. **SEV-2.** Page IC.

**Example 2** — "SSL cert on `api.example.com` expires in 6 days."
→ No current impact but will cause outage. Human action needed soon, not immediate.
→ **SEV-4** (or Medium-priority alert). Ticket, not page.

**Example 3** — "Analyst reports one customer's dashboard shows wrong logo."
→ Cosmetic, no ability impact. **SEV-5.** JIRA ticket.

**Example 4** — "Auth service latency P99 = 3s, error rate normal. One node of 12 unhealthy."
→ Loss of redundancy, likely to escalate. **SEV-3.** Page the service team.

**Example 5** — "We can't tell if the notification pipeline is delivering."
→ Monitoring of major-incident conditions impaired = **SEV-2** by definition. Page IC.

## Anti-patterns to avoid

- Debating SEV-2 vs SEV-3 on the call — always round up and move on.
- Using SEV-1 for anything short of public-notification-worthy — it dilutes the meaning.
- Waiting for perfect data before classifying — classify with what you have, revise on the fly.
- Downgrading severity to avoid a postmortem — the postmortem is the point.

## Organization-specific tuning

The table above is generic. For production use, replace vague words with metrics:

- "many customers" → `> 5% of accounts` or `> 100k users`
- "severely impaired" → `error rate > X%` or `latency P99 > Y ms`
- "SLA breach" → cite the actual SLA number

Every SEV row should be metric-driven and defensible in a postmortem.
