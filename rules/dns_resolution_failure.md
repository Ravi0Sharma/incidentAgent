---
id: dns-resolution-failure
title: DNS resolution failing
level: high
category: dependency_failure
tags:
  - dns
  - network
selection:
  message_regex: "no such host|dns lookup failed|name resolution|SERVFAIL|NXDOMAIN|EAI_AGAIN"
  level: [error, warn]
condition: selection
runbook: https://runbooks.example.com/dns
---

# DNS resolution failing

DNS is failing. Check cluster CoreDNS pods, upstream resolver, and whether a
service name recently changed (rename, namespace move, missing service manifest).
