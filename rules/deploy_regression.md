---
id: deploy-regression
title: Errors started shortly after a deploy
level: high
category: deploy_regression
tags:
  - deploy
  - correlation
selection:
  level: [error]
  first_seen_within_minutes_after_deploy: 15
condition: selection
runbook: https://runbooks.example.com/rollback
---

# Errors started shortly after a deploy

Errors began within 15 minutes of a deploy for the same service. This is the
strongest regression signal. First action: consider rollback while investigating.
