# Release Evidence Template

Each production candidate must link a immutable record containing:

- artifact/version and source commit;
- full test, evaluation, security scan and dependency/SBOM results;
- MySQL migration and restore-drill result;
- load/soak and queue-recovery results;
- dashboards, alerts and runbook review;
- approvers from product, SRE, security, privacy/data and platform; and
- rollback/kill-switch rehearsal result.

This POC has no production release process; this file is the required evidence
shape, not evidence that a release has passed.
