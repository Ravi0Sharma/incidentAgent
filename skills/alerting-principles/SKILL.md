---
name: alerting-principles
description: Design and review alerts so every page is human-actionable with clear context and remediation. Use when creating a new alert, reviewing an alert rule (Prometheus, Grafana, Datadog, etc.), auditing on-call noise, deciding whether something should page vs notify, or when the user mentions alerting, paging, on-call noise, or alert fatigue.
---

# Alerting Principles

## Core principle

> **An alert is something that requires a human to perform an action. Everything else is a notification.**

If a page fires at 3 a.m. and there is nothing a human can immediately do about it, the alert is broken. Fix the alert, not the human.

## Priority matrix

| Priority | When it fires | Response expectation |
| --- | --- | --- |
| **High** | 24/7/365 page | Immediate human action |
| **Medium** | Page during business hours only | Human action within 24h |
| **Low** | Low-priority page 24/7 | Human action at some point |
| **Notification** | Suppressed event (log/chatops only) | No response — informational |

**Rule of thumb:** if it wakes someone at 3 a.m., it must be *immediately human-actionable*. If not, downgrade the priority or suppress.

### Priority decision tree

```
Is a human required to act?
├─ No  → Notification (suppress)
└─ Yes → Must they act now (minutes)?
         ├─ Yes → High priority (24/7 page)
         └─ No  → Will it wait until morning?
                  ├─ Yes → Medium (business-hours page)
                  └─ No  → Low (24/7 page, non-urgent tone)
```

## Alert content checklist

Every high-priority alert must have all four:

- [ ] **Descriptive title** — mentions the specific resource
  - Bad: `Something went wrong`
  - Good: `Disk 80% full on prod-web-loadbalancer-af5462ce`
- [ ] **Triggering metric in the body** — the actual query/expression
  - Bad: `Diskspace on a disk is filling`
  - Good: `avg(last_1h):max:system.disk.in_use{env:prod-web-loadbalancer} by {host} > 0.8`
- [ ] **Why it matters** — impact statement
  - Bad: `Disk is full`
  - Good: `Disk at 80% — writes will start failing at 100%, causing service instability`
- [ ] **Remediation** — runbook link or explicit steps
  - Bad: `Fix it by deleting stuff`
  - Good: `See runbook: https://example.com/runbook/disk. Also review log-rotation thresholds.`

An alert without any of these is worthless.

## Priority examples

- **"Production service failing 75% of requests, automation cannot resolve"** → High
- **"Disk full in ~48h, log rotation insufficient"** → Medium
- **"SSL cert expires in 7 days"** → Low
- **"Deployment X succeeded"** → Notification (suppressed)

## Testing alerts

**An untested alert is equivalent to having no alert.** Every new or modified alert must be tested:

- [ ] Threshold is set correctly (fires on real breach, not on noise)
- [ ] "No data" condition alerts (missing data usually means broken pipeline)
- [ ] Auto-resolves when the metric returns to normal
- [ ] Include it in the next Failure Friday / game day if applicable

## Review workflow for an existing alert

When asked to review an alert:

1. Read the alert rule (yaml / expr / UI export).
2. Classify its priority against the matrix above.
3. Score its content against the 4-item checklist. Missing any = fail.
4. Check for these smells:
   - Fires more than 2× per week without action → too noisy, tune or downgrade
   - Never fires and never resolves → probably broken, test it
   - Uses generic title (`error`, `alert`, `warning`) → rewrite
   - No runbook link → add one, or don't page on it
5. Propose specific fixes with the corrected expression / annotations.

## Prometheus / Alertmanager template

When generating a Prometheus alert rule, follow this shape:

```yaml
- alert: DiskSpaceHighProdLoadbalancer
  expr: max by (host) (avg_over_time(node_filesystem_free_bytes{env="prod-web-loadbalancer"}[1h])) / max by (host) (node_filesystem_size_bytes{env="prod-web-loadbalancer"}) < 0.2
  for: 10m
  labels:
    severity: medium
    team: platform
  annotations:
    summary: "Disk {{ $labels.host }} at {{ $value | humanizePercentage }} free"
    description: "Host {{ $labels.host }} has less than 20% free disk. Writes fail at 0%, causing service instability."
    runbook_url: "https://runbooks.example.com/disk-full"
    triggering_query: "avg_over_time(node_filesystem_free_bytes[1h])/node_filesystem_size_bytes < 0.2"
```

Notice: descriptive `summary`, `description` explains impact, `runbook_url` present, `triggering_query` echoed so responders don't have to guess.
