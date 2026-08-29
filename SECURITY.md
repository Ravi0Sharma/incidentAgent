# Security policy

## Reporting a vulnerability

Do not open a public issue containing a vulnerability, credential, private
endpoint, incident payload or customer data.

Use GitHub's private vulnerability reporting for this repository. Include:

- affected version or commit;
- minimal reproduction steps;
- expected impact;
- whether credentials or real incident data may be exposed; and
- a safe way to validate the fix.

Do not test against systems, accounts or data you do not own or have explicit
permission to use.

## Supported version

Only the current `main` branch is maintained. This repository is a local-safe
reference implementation, not a hosted service or production support promise.

## Public disclosure

Allow maintainers time to validate and fix the issue before public disclosure.
Remove secrets, account identifiers, private source maps and raw telemetry from
all reports and proof-of-concept material.
