---
name: security-incident
description: Respond to a security incident (breach, intrusion, credential compromise) using PagerDuty's 14-step checklist. Use when triaging a suspected security event, breach, unauthorized access, data exfiltration, compromised credentials, or when the user mentions security incident, SIRT, forensics, or attack response. Different from normal operational incidents — do not skip these steps.
---

# Security Incident Response

## When in doubt — trigger it

If unsure whether something is a security incident, treat it as one and page the IC (`!ic page`). The IC will decide if it stands down. The cost of a false alarm is a wasted hour. The cost of missing a real intrusion is unbounded.

## Communication rules — read first

- **Do not discuss the incident with anyone outside the response team** until forensics have established the attack is not internal. It could be an insider.
- **Give the incident an innocuous codename** (e.g. `sapphire-unicorn`) and use it in all chats / docs / calendar entries. Never label anything as "security incident" or "breach" in a shared surface.
- **Prefix all emails and chat topics with "Attorney Work Project"** for privilege protection.
- **Prefer voice + Slack.** Avoid email; never SMS the details.
- **Encrypt any email** that includes non-`@yourcompany.com` addresses.

## The 14-step checklist

Work these in parallel where possible — the IC assigns each to a responder.

```
- [  1] Stop the attack in progress
- [  2] Cut off the attack vector
- [  3] Assemble the response team
- [  4] Isolate affected instances
- [  5] Identify the attack timeline
- [  6] Identify compromised data
- [  7] Assess risk to other systems
- [  8] Assess risk of re-attack
- [  9] Apply additional mitigations
- [ 10] Forensic analysis of compromised systems
- [ 11] Internal communication
- [ 12] Involve law enforcement (if warranted)
- [ 13] Reach out to external parties used as vector
- [ 14] External communication
```

## Step details

### 1. Stop the attack (any means necessary)
- Shut down the instance from the provider console — **do not delete or terminate**, forensics need the disk.
- If logged into the host: restore default iptables, `kill -9` suspect sessions, change root password, lock `/etc/shadow` for all other users, `sudo shutdown now`.

### 2. Cut off the attack vector
- Third-party provider compromised? Delete all accounts except your own + others physically present, rotate password + MFA immediately.
- Application-layer vector? Disable that code path or the whole service.

### 3. Assemble the response team
- Page IC via `!ic page`. IC assigns standard roles (Deputy, Scribe, Liaisons).
- Include the security team **always**.
- Include a rep for each affected service.
- Bring in executive stakeholders + legal counsel ASAP — but prioritize operational responders first.
- Start the voice call. Create a Slack room using the codename. Invite responders.

### 4. Isolate affected instances
- Blacklist affected IPs from all other hosts.
- Shut down affected instances (if not already done).
- **Take a read-only disk image** of every disk on affected instances. Ship to off-site cold storage. Read-only, tamper-evident.

### 5. Identify the attack timeline
Use every tool you have. Establish:
- Any reconnaissance before the attack.
- Time of initial access.
- Actions taken by the attacker, in order.
- How long they had access before detection.
- How long between detection and eviction.
- Any DB queries they ran.
- Whether they still have a back-door.

### 6. Identify compromised data
- Was data exfiltrated from any DB?
- What keys / secrets were on the host — assume all are compromised regardless of storage form.
- Did the attacker map out the network?
- Exactly what customer data was touched?

### 7 & 8. Assess risk
- Does the attacker have enough info to find another way in?
- Any credentials that used the initial account elsewhere → rotate everywhere.
- Assess likelihood of a follow-up attack.

### 9. Apply additional mitigations
- Rotate every compromised secret.
- Add alerting for the specific pattern used.
- Block IPs associated with the attack.
- Revoke access for any keys / credentials touched.

### 10. Forensic analysis
Only after systems are secured and monitoring is in place.
- Use the read-only images + access logs.
- Identify exactly what happened, how, and how to prevent it.
- Track every IP involved.
- Monitor for re-entry attempts.

### 11. Internal communication (delegate to VP/Director of Engineering)
Only once forensics confirm the attack was not internal.
- High-level timeline.
- Mitigations taken.
- Don't disclose details that could leak.
- Follow up as more is known.

### 12. Law enforcement (delegate to VP/Director of Engineering)
When warranted:
- Local law enforcement.
- Country-level cyber authority (e.g. FBI in the US).
- Notify operators of any systems used in the attack — they may be compromised too.
- Bring in an external security firm to help assess.
- Contact your cyber insurance provider.

### 13. External-vector outreach
Notify any third parties whose systems were used to reach you — they may not know they are compromised.

### 14. External communication (delegate to Marketing / Comms)
Only after: information is validated, timeline is complete, compromised data is known, and you are confident the attack is closed.

- **Include the date in the announcement title** so it is never confused with a future breach.
- **Do not say "we take security very seriously"** — everyone cringes when they read it.
- Be honest, accept responsibility, present facts, describe prevention.
- Be as detailed as possible on timeline and compromised data.
- If you stored something you shouldn't have — say so. It comes out later otherwise.
- Do not name-and-shame external parties unless they have publicly disclosed themselves (then link).
- Release within a few days of the compromise. Delay makes it worse.
- Ideally, brief customers' security teams before the public notice.

## Differences from operational incidents

| Aspect | Operational | Security |
| --- | --- | --- |
| Codename | Not required | Required (innocuous) |
| Comms channel | Public Slack + call | Private, invite-only |
| Email prefix | Normal | `Attorney Work Project` |
| SMS about it | Fine | Only "join Slack now" |
| Preserve state | Roll back / restart | **Preserve for forensics** — no delete/terminate |
| External comms timing | ASAP | After validated, within days |
| Internal comms timing | Standard exec updates | Only after forensics rule out insider |

## Anti-patterns

- Wiping or reimaging compromised hosts before forensic capture.
- Discussing details on SMS or unencrypted external email.
- Publishing an announcement before you know what was actually taken.
- Naming external parties as attackers before you have proof.
- Skipping the read-only disk image because "we're in a hurry."
