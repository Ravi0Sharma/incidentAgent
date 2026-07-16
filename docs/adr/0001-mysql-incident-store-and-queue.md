# ADR 0001: MySQL Incident Store And Queue

**Status:** Accepted for the POC  
**Date:** 2026-07-22  
**Review:** Before a multi-environment deployment

## Context

Incident intake must survive API restarts, reject duplicate events, preserve
ordered revisions, and avoid doing LLM work in the webhook request.

## Decision

Use MySQL 8 as the POC store for incident events, revisions, lifecycle,
pending reviews, replay nonces, rate-limit counters, LangGraph checkpoints and
lease-based jobs. Intake commits its event and job in one transaction before
returning `accepted`.

## Consequences

This gives one durable source of truth and enables local integration tests.
The current worker is launched by the web process, so independent worker
deployment, backup/PITR, migrations and disaster recovery remain production
work. SQLite and mysql-sim are not supported runtime modes.
