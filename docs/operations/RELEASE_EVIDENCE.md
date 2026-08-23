# Release Evidence Template

Each production candidate must link a immutable record containing:

- artifact/version and source commit;
- full test, evaluation, security scan and dependency/SBOM results;
- MySQL migration and restore-drill result;
- load/soak and queue-recovery results;
- dashboards, alerts and runbook review;
- approvers from product, SRE, security, privacy/data and platform; and
- rollback/kill-switch rehearsal result.

Local release tooling now produces migration, multi-process, SIGKILL,
load/soak, PITR-readiness and backup/restore evidence. A production candidate
must still attach environment-specific results and named approvals; local
evidence alone is never a production release approval.
