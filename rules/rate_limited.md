---
id: rate-limited
title: Traffic being rate-limited
level: medium
category: capacity
tags:
  - rate-limit
  - traffic
selection:
  message_regex: "HTTP\\s+429|rate limit(ed)?|too many requests"
condition: selection
runbook: https://runbooks.example.com/rate-limit
---

# Traffic being rate-limited

Either legitimate traffic spike outgrew a rate-limit, or a client is misbehaving.
Check top user_id / trace_id pivots and traffic dashboard for anomalies.
