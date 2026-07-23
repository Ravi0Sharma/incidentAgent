---
id: upstream-timeout
title: Upstream dependency timeout
level: medium
category: dependency_failure
tags:
  - upstream
  - latency
selection:
  message_regex: "upstream (timeout|timed out)|gateway timeout|HTTP\\s+504|context deadline exceeded"
  level: [error, warn]
condition: selection
runbook: https://runbooks.example.com/upstream-timeout
---

# Upstream dependency timeout

A downstream call is not returning in time. Identify which upstream (usually in
the log message or trace) and check its own dashboards. If multiple services are
timing out on the same upstream, that upstream is the incident source.
