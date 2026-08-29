# Incident Agent documentation

The root [README](../README.md) is the main entry point. These documents cover
only current behavior, public evaluation evidence and operating boundaries.

## Start here

| Need | Document |
| --- | --- |
| Understand the runtime | [Architecture](architecture/ARCHITECTURE.md) and [system flow](architecture/SYSTEM_FLOW.svg) |
| Understand the results | [Evaluation](EVALUATION.md) |
| Run the complete local stack | [Docker Compose runbook](operations/LOCAL_DOCKER_COMPOSE.md) |
| Connect CloudWatch safely | [CloudWatch integration](operations/CLOUDWATCH.md) |
| Send an approved draft to Jira | [Jira MCP output](operations/JIRA_MCP.md) |
| Check production blockers | [Production readiness](operations/PRODUCTION_READINESS.md) |

## Contracts

- [Alert input](contracts/ALERT_INPUT_CONTRACT.md)
- [HTTP API](contracts/OPENAPI_CONTRACT.md)
- [Connectors and provenance](contracts/CONNECTOR_CONTRACT.md)
- [Evidence](contracts/EVIDENCE_CONTRACT.md)
- [Hypotheses and grounding](contracts/HYPOTHESIS_CONTRACT.md)
- [Memory and review](contracts/MEMORY_AND_REVIEW_CONTRACT.md)

## Operations

- [Local Docker Compose](operations/LOCAL_DOCKER_COMPOSE.md)
- [Native setup](operations/SETUP_GUIDE.md)
- [Operator runbooks](operations/OPERATOR_RUNBOOKS.md)
- [Security and operations](operations/SECURITY_AND_OPERATIONS.md)
- [Jira MCP output](operations/JIRA_MCP.md)
- [GitLab CI](operations/GITLAB_CI.md)
- [Production readiness](operations/PRODUCTION_READINESS.md)

## Engineering detail

- [Project compass](development/PROJECT.md)
- [Production checklist execution order](development/PROJECT_MASTER_CHECKLIST.md)
- [Test strategy](development/TEST_STRATEGY.md)
- [Research findings](development/LINK_FINDINGS.md)
- [Research-derived implementation plan](development/IMPLEMENTATION_PLAN_FROM_LINK_FINDINGS.md)
- [Deferred work](development/DEFERRED_WORK_CHECKLIST.md)
- [MySQL store and queue ADR](adr/0001-mysql-incident-store-and-queue.md)
- [Canonical schemas](architecture/CANONICAL_SCHEMAS.md)
- [Data inventory](architecture/DATA_INVENTORY.md)
- [Curated knowledge memory](architecture/KNOWLEDGE_MEMORY.md)

## Detailed evidence

- [Pre-review evaluation](reports/PRE_REVIEW_EVALUATION.md)
- [Bounded live-model evaluation](reports/OPENAI_LIVE_EVALUATION_2026-08-09.md)
- [Latest local-safe evidence](reports/LOCAL_SAFE_CLOSURE_2026-08-24.md)

Raw public evaluation datasets and generated reports are intentionally not
committed. Dataset provenance and fetch instructions are in
[data/external/README.md](../data/external/README.md).
