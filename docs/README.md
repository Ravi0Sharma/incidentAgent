# Incident Agent documentation

The root [`README.md`](../README.md) is the system overview and onboarding
entry point. This index separates current architecture and operating contracts
from planning history and dated evidence.

## Architecture

- [`ARCHITECTURE.md`](architecture/ARCHITECTURE.md) — runtime topology and trust boundaries.
- [`SYSTEM_FLOW.svg`](architecture/SYSTEM_FLOW.svg) — complete visual workflow.
- [`CANONICAL_SCHEMAS.md`](architecture/CANONICAL_SCHEMAS.md) — durable records and invariants.
- [`DATA_INVENTORY.md`](architecture/DATA_INVENTORY.md) — stored data and retention status.
- [`KNOWLEDGE_MEMORY.md`](architecture/KNOWLEDGE_MEMORY.md) — curated knowledge boundary.
- [`TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md`](architecture/TARGET_ENVIRONMENT_AND_DATA_PRIORITY.md) — target environment and evaluation-data priorities.
- [`adr/`](adr/) — architecture decision records.

## Contracts

- [`OPERATING_CONTRACT.md`](contracts/OPERATING_CONTRACT.md) — supported and unsupported behavior.
- [`ALERT_INPUT_CONTRACT.md`](contracts/ALERT_INPUT_CONTRACT.md) — accepted alert formats and validation.
- [`OPENAPI_CONTRACT.md`](contracts/OPENAPI_CONTRACT.md) — HTTP, authentication and error contract.
- [`CONNECTOR_CONTRACT.md`](contracts/CONNECTOR_CONTRACT.md) — telemetry/change connector behavior.
- [`EVIDENCE_CONTRACT.md`](contracts/EVIDENCE_CONTRACT.md) — normalized evidence and provenance.
- [`HYPOTHESIS_CONTRACT.md`](contracts/HYPOTHESIS_CONTRACT.md) — candidate and confidence semantics.
- [`MEMORY_AND_REVIEW_CONTRACT.md`](contracts/MEMORY_AND_REVIEW_CONTRACT.md) — persistence and human-review invariants.

## Operations

- [`LOCAL_DOCKER_COMPOSE.md`](operations/LOCAL_DOCKER_COMPOSE.md) — zero-setup local stack and E2E checklist.
- [`GITLAB_CI.md`](operations/GITLAB_CI.md) — GitLab pipeline and runner prerequisites.
- [`SETUP_GUIDE.md`](operations/SETUP_GUIDE.md) — native Python and environment setup.
- [`OPERATOR_RUNBOOKS.md`](operations/OPERATOR_RUNBOOKS.md) — migrations, recovery, queue and publication incidents.
- [`PRODUCTION_READINESS.md`](operations/PRODUCTION_READINESS.md) — authoritative production Definition of Done.
- [`SECURITY_AND_OPERATIONS.md`](operations/SECURITY_AND_OPERATIONS.md) — controls and operational baseline.
- [`RELEASE_EVIDENCE.md`](operations/RELEASE_EVIDENCE.md) — release evidence template.
- [`REVIEWER_GUIDE.md`](operations/REVIEWER_GUIDE.md) — safe human decision guidance.
- [`RAILWAY_DEVELOPMENT_SETUP.md`](operations/RAILWAY_DEVELOPMENT_SETUP.md) — shared development deployment.
- [`PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md`](operations/PRODUCTION_HARDENING_AND_RAILWAY_PLAN.md) — long-term hardening plan.

## Development and governance

- [`PROJECT.md`](development/PROJECT.md) — project compass and decision links.
- [`PROJECT_MASTER_CHECKLIST.md`](development/PROJECT_MASTER_CHECKLIST.md) — implementation checklist.
- [`TEST_STRATEGY.md`](development/TEST_STRATEGY.md) — verification strategy.
- [`GOVERNANCE_AND_QUALITY.md`](development/GOVERNANCE_AND_QUALITY.md) — quality gates and release policy.
- [`SAFE_COMPLETION_PLAN.md`](development/SAFE_COMPLETION_PLAN.md) — bounded local completion plan.
- [`DEFERRED_WORK_CHECKLIST.md`](development/DEFERRED_WORK_CHECKLIST.md) — explicitly deferred work.
- [`DEFERRED_CONNECTION_FAILURE_TESTS.md`](development/DEFERRED_CONNECTION_FAILURE_TESTS.md) — parked provider-failure scenarios.
- [`IMPLEMENTATION_PLAN_FROM_LINK_FINDINGS.md`](development/IMPLEMENTATION_PLAN_FROM_LINK_FINDINGS.md) and [`LINK_FINDINGS.md`](development/LINK_FINDINGS.md) — research-derived planning.

## Dated reports

The [`reports/`](reports/) directory contains evaluation results, local closure
records and shadow-readiness audits. These are historical evidence. They do
not override current code, contracts or the production-readiness checklist.
