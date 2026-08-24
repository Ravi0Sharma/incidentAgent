# GitLab CI

The root [`.gitlab-ci.yml`](../../.gitlab-ci.yml) mirrors the repository's
GitHub checks without relying on GitHub Code Scanning or GitHub Advanced
Security. It has three jobs:

| Job | What it proves |
| --- | --- |
| `python-quality` | Locked install, MySQL migrations, full quality gate, multi-worker recovery probes, backup/restore and SBOM |
| `dependency-security` | `pip-audit` against hash-locked dependencies plus a CycloneDX SBOM artifact |
| `compose-e2e` | Compose rendering, image build, MySQL/migrator/API/two-worker startup and signed duplicate-safe canary |

## Required GitLab Runner capability

`python-quality` and `dependency-security` work on an ordinary Linux Docker
runner. `compose-e2e` is deliberately tagged `docker-dind` and requires a
dedicated runner whose Docker executor permits the `docker:27.5.1-dind` service
to run in privileged mode. GitLab documents this as a runner-side requirement;
do not remove the tag merely to schedule the job on an unprivileged shared
runner.

For a self-managed Docker runner, configure `privileged = true` and restrict it
to this project or isolated CI workloads. For GitLab hosted runners, select a
runner class that supports Docker-in-Docker and assign it the `docker-dind` tag.
The job uses an isolated daemon with TLS disabled only inside the ephemeral CI
network; it does not mount a host Docker socket.

The pipeline's artifacts are retained for 30 days. They include coverage,
backup/restore and resilience evidence, the SBOM, the dependency-audit JSON and
Compose logs on success or failure.

