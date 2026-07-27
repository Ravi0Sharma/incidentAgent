---
name: incident-runbook
description: Coordinate a live major incident using PagerDuty's role hierarchy and per-role playbooks (IC, Deputy, Scribe, SME, Customer Liaison, Internal Liaison). Use when running or joining an incident call, when the user asks for the incident runbook, wants to know what to do during an incident, needs a role checklist, or mentions Incident Commander / IC / SME / Peacetime vs Wartime.
---

# Incident Runbook — During an Incident

## Mentality shift

Incident response is **Wartime**, not Peacetime. Riskier actions are acceptable because the cost of doing nothing is higher than the cost of a wrong action. Don't wait for perfect data — bias toward action, roll back aggressively, and rely on the postmortem to correct course later.

Alternate framings: *Normal vs Emergency*, *OK vs Not OK*. Pick one and use it consistently.

## First 60 seconds — anyone joining

1. Join the incident call **and** Slack channel (both — never just one).
2. Mute mic until you speak. State your name and the system you own when you first speak.
3. If no IC is on the call → type `!ic page` in Slack (or your equivalent).
4. If you're not an SME, filter your input through the SME for your service — don't crowd the call.

## Roles at a glance

Flexible — one person can hold multiple minor roles on small incidents.

| Role | Owns | Notes |
| --- | --- | --- |
| **Incident Commander (IC)** | Coordination, decisions, single source of truth | Never a resolver. Delegates all repair actions. |
| **Deputy** | Backs up IC, watches timers, manages the call | Must be IC-trained (may need to take over). |
| **Scribe** | Documents timeline in Slack | Often the Deputy on small incidents. |
| **Subject Matter Expert (SME)** | Diagnoses and fixes their service | Reports CAN: Condition / Actions / Needs. |
| **Customer Liaison** | External comms, status page | Waits for IC approval before posting. |
| **Internal Liaison** | Notifies internal stakeholders, pages other teams | Sends exec updates every ~30 min. |

## IC playbook

Copy this checklist:

```
- [ ] Announce on call + Slack: "I am the IC. Deputy: <name>. Scribe: <name>."
- [ ] Ask each SME for a CAN report (Condition / Actions / Needs)
- [ ] Identify obvious cause (recent deploy? traffic spike? DC issue?)
- [ ] Delegate investigation & repair — you are NOT a resolver
- [ ] Poll for strong objections before any large/risky action
- [ ] Once decided, the decision is final — even for those who objected
- [ ] Watch span of control (>7 people reporting to you = spin sub-teams)
- [ ] Decide public communication: "If in doubt, post it out."
- [ ] Announce end of incident when actively recovering
- [ ] Assign a postmortem owner before leaving the call
```

**Never**:
- Take on an SME role while acting as IC. Hand over IC first, then dive in.
- Skip severity classification for a "quick fix" — round up if unsure.
- Litigate policy on the call.

## Deputy playbook

- Track timers the IC started. Nudge when they expire.
- Circle back on unanswered items from the roll call.
- Be prepared to remove people from the call (only on IC's instruction).
- Be ready to become IC at any moment.

## Scribe playbook

- Post in Slack: "IC: X, Deputy: Y, Scribe: me."
- Start the status-monitoring bot (e.g. `!status stalk`).
- Log significant actions as they happen — don't wait for the IC to ask.
  - Example: `prod-server-387723 restarted to clear stuck lock`
- Log status updates from the IC verbatim.
- Log key callouts and add `TODO:` for follow-ups.
- Ensure the call is being recorded.

## SME playbook

- Investigate using graphs / logs — announce all findings to the IC.
- Communicate as **CAN**:
  - **C**ondition — current state of your service
  - **A**ctions — what you want to do, or need done
  - **N**eeds — what support you need
- Suggest resolutions to the IC. **Do not act until instructed.**
- If you don't know, say "I don't know, investigating, will report back in N minutes."
- If N minutes pass, report — even if the answer is "still don't know."

## Customer Liaison playbook

- Draft external messages proactively — don't wait to be asked.
- Regularly report to the IC: "X customers have opened tickets about this."
- Post publicly (X, StatusPage) only after IC approves.
- If the incident turns out to be a false alarm and no customer impact — check with IC before removing any ephemeral investigation message.

## Internal Liaison playbook

- Page other on-calls as instructed by the IC.
- Notify Legal / Finance / Marketing when the IC calls for it.
- Post exec summary in `#executive-summary-updates` (or equivalent) every ~30 min. Keep it short: what's broken, what we're doing, ETA.
- Absorb stakeholder questions so the primary call stays clean.

## Complex incidents (sub-teams)

Signs you need sub-teams:
- Multiple uncorrelated symptoms
- The call "feels crowded"
- SMEs all analyzing the same thing

Spin off named sub-teams (Alpha / Bravo / Charlie — avoid Red/Blue, they collide with security terminology). Assign a **team lead** to each; SMEs report to team leads; team leads report to the IC. Each team gets its own Slack room and call bridge.

If you want to switch sub-teams, raise it with your current team lead — **not** with the IC.

## Communication etiquette on the call

- Speak clearly and factually. No filler.
- Bring concerns to the IC — respect timeboxes.
- Use plain English. No new acronyms. Explicit > implicit.
- Radio terms in active use: `Ack` / `Say again` / `Standby` / `Wilco`.
- Silence on the call is fine — it usually means people are working. Do not fill it.
- If you have nothing to do, leave the call. You can be paged back.

## When the incident ends

- IC declares it over on the call.
- Non-time-critical discussion moves to Slack.
- IC groups related PagerDuty incidents, sets final severity, resolves in the tool.
- IC creates the postmortem shell and assigns an owner **before** leaving the call.
- Everyone follows the After-an-Incident checklist for their role.
