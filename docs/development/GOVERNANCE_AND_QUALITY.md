# Governance and quality baseline

The local quality gate is `scripts/quality_gate.py`. It runs a value-suppressing
repository secret scan, Ruff, scoped mypy, `compileall`, prompt budgets, the
full MySQL-backed suite and branch coverage with live LLM and external
publishing disabled. GitHub Actions installs `requirements.lock`, runs the same
gate, audits dependencies, builds a CycloneDX SBOM and uploads evidence. It is
not yet a production release gate or a representative evaluation dataset.

The active completion target is `Local-Safe v0.1`, defined in
[`SAFE_COMPLETION_PLAN.md`](SAFE_COMPLETION_PLAN.md). It is a local,
fixture/replay-only POC closure and not a Shadow or production release. The
documented unit suite requires the repository virtual environment and a
disposable MySQL instance; do not describe a historical pass count as a current
verification result without its dated command output. On 2026-08-09 the
hash-synchronized environment passed 291/291 tests, lint, scoped types,
compileall, prompt budgets, secret scan, `pip check`, dependency audit and SBOM
generation. Branch coverage was 74.8% repository-wide against a 74% ratchet,
82.4% for core workflow code against the 80% gate and 97.2% for security/control
code against the 90% gate. Hosted provisioning remains outside the active
scope.

For every production release, retain a manifest with test/evaluation results,
security/dependency/image scans, migration result, restore and load drills,
dashboard links, artifact digest, approvers and known limitations. Any
exception needs scope, owner, expiry and approval.

Owners and review dates are required for service metadata, detection and
suppression rules, runbooks and curated knowledge. The data inventory must
record every field/store: classification, purpose, region, access, retention,
deletion and downstream processors.

Setup must remain separated across local, test, staging, shadow and production;
test credentials and publishers must never reach real incident destinations.
Production needs pinned dependencies, reproducible build/container/IaC, staged
rollout/rollback, kill-switch drills, operator runbooks and an on-call owner.

The exact acceptance methods remain `A12-T01`–`A12-T10`, `A13-T01`–`A13-T10`,
`A14-T01`–`A14-T12`, and `A15-T01`–`A15-T10` in `TEST_STRATEGY.md`.
