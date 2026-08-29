---
name: anti-patterns
description: Recognize and avoid the common incident response anti-patterns PagerDuty learned to reject. Use when reviewing an incident response process, designing on-call procedures, writing runbooks, evaluating a proposed change to incident policy, auditing a postmortem, or when the user asks what NOT to do during an incident.
---

# Incident Response Anti-Patterns

These are things PagerDuty **tried and rejected**. Use this skill to spot the pattern early and steer toward the corrected practice.

## Quick reference

| Anti-pattern | Correction |
| --- | --- |
| Page everyone on every SEV-2 | Only page on-calls for affected services; Internal Liaison mobilizes more if needed. |
| Force everyone to stay on the call | Release responders once their role is done; page them back if needed. |
| Status updates every 5 minutes | Every 20–30 min unless there's real news. |
| Assume silence = no progress | Silence usually means people are fixing; the IC fills silence when needed. |
| Debate severity on the call | Always round up. Litigate in the postmortem. |
| Hesitate to escalate at 3 a.m. | "Never hesitate to escalate." Better to wake one more person than prolong the incident. |
| Debate process changes during the incident | Follow current process; propose changes in the postmortem. |
| Skip the postmortem | Always do one. Even for false alarms. |
| SME tunnel-vision | Follow IC instructions; treat root cause, not symptoms. |
| Reject policy changes | Iterate the process as the org grows. |
| IC also acting as SME | Hand off IC first, then dive in as SME. |
| SME trying to be a hero | Delegate to other experts; focus on one problem at a time. |
| Silent policy changes | Broadcast policy changes ahead of time; never surprise responders mid-incident. |
| Only technical people can be IC | ICs coordinate — they need high-level understanding, not deep expertise. |

## Detailed patterns

### 1. Paging everyone

Paging the entire engineering department at 3 a.m. for a SEV-2 does not speed up response — it costs sleep across the org and puts too many people on the call. **Span of control is ~7 direct reports to the IC.** Beyond that, spin sub-teams.

**Correction:** Page only the on-calls for affected services. The Internal Liaison mobilizes more responders if needed. Nine times out of ten, extra bodies are not needed.

### 2. Forcing responders to stay

"You might be needed later" led to calls full of idle people who could have gone back to sleep and encouraged hero mentality.

**Correction:** Once your part is done, the IC releases you. You can be paged back. Optimize for the 99% case where you won't be needed again.

### 3. Too-frequent status updates

Every-5-minutes updates mean the IC spends the incident writing updates instead of resolving it.

**Correction:** Every 20–30 minutes during a major incident, or more frequently only when there is real news. Executives get an exec-summary update; they do not run the incident.

### 4. Assuming silence means stalled

Silence on a call usually means everyone is working. External observers panic and start talking, which is distracting.

**Correction:** Train the org that silence is OK. The IC will fill silence with a status update when appropriate. Nobody else needs to.

### 5. Litigating severity on the call

Discussing "is this really a SEV-2?" while the incident continues wastes minutes and lets things escalate.

**Correction:** Round up. Assume the higher severity, run the process, revise in the postmortem. Even if it turns out to be lower, treat the response as practice.

### 6. Hesitating to escalate

SMEs at 3 a.m. reluctant to wake a teammate prolong incidents unnecessarily.

**Correction:** **"Never hesitate to escalate."** Don't page everyone (see #1), but if you need one more brain, page them. No shame in either direction.

### 7. Debating process during the incident

Someone dislikes the current policy → the call derails into meta-discussion.

**Correction:** Follow current process now. Bring disagreements to the postmortem or to whoever owns the response process.

### 8. Neglecting the postmortem

Especially tempting when the cause "seems obvious" or the incident was small.

**Correction:** Always do the postmortem — responders' time was spent, and that cost deserves understanding. **Even false alarms get a postmortem** — figure out why response was mobilized and fix that trigger.

### 9. SME tunnel vision

An SME keeps re-raising their pet issue and ignoring IC direction because they can only see the symptom in front of them.

**Correction:** Follow IC instructions. The IC has broader context. Report your findings, then step back and let the IC prioritize.

### 10. Resistance to policy change

"It ain't broke, don't fix it." Response processes that worked at 20 engineers break at 200.

**Correction:** Iterate the process. Introduce sensible changes. Some may slow the short term to win the long term — that trade is usually worth it.

### 11. IC also playing SME

The IC knows the affected system well and starts fixing it → nobody is actually coordinating anymore.

**Correction:** **You cannot be IC and SME at once.** If you're truly the only person who can fix it, hand off IC formally, then dive in. Backup planning is part of the IC role; you can't do it while debugging.

### 12. Hero SME

An SME who takes every request personally instead of delegating burns out and creates single points of failure.

**Correction:** Delegate. Page backup responders if requests pile up. Don't do another SME's task without checking — you'll collide.

### 13. Silent policy updates

Changing the wiki and expecting responders to notice is wishful thinking.

**Correction:** Broadcast policy changes proactively — email, chat announcement, brown-bag. No surprises mid-incident.

### 14. Overly technical IC requirements

Restricting IC to senior engineers artificially shrinks the on-call pool and stalls the rotation.

**Correction:** ICs coordinate — they need to know **where data flows in, how systems use it, where data flows out**. Deep technical work belongs to SMEs. Opening IC to non-engineers spreads on-call empathy across the org and grows the rotation.

## Use during code review / process review

When reviewing a proposed runbook, on-call rotation, or incident process, run each proposal against this list. Flag any that match an anti-pattern with the correction and the reasoning.
