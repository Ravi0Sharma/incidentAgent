---
id: db-connection-pool-exhausted
title: Database connection pool exhausted
level: high
category: resource_exhaustion
tags:
  - db
  - capacity
selection:
  message_regex: "connection pool exhausted|too many connections|pool timeout|acquire connection timeout"
  level: [error, warn]
condition: selection
runbook: https://runbooks.example.com/db-pool
---

# Database connection pool exhausted

Check pool_size / max_connections config in the most recent deploy of the
affected service. Compare current active connections against the pool limit.
