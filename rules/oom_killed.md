---
id: oom-killed
title: Pod OOMKilled
level: high
category: resource_exhaustion
tags:
  - memory
  - k8s
selection:
  message_regex: "OOMKilled|Out of memory|Memory cgroup out of memory|killed by (the )?kernel"
condition: selection
runbook: https://runbooks.example.com/oom
---

# Pod OOMKilled

Container exceeded its memory limit. Check whether the last deploy changed memory
limits, whether there's a leak (heap growth over hours), or if traffic spiked
beyond capacity.
