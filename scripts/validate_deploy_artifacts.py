#!/usr/bin/env python3
"""Static fail-closed validation for versioned deploy artifacts."""

import json
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    _require(
        "python:3.11.15-slim-bookworm" in dockerfile,
        "Python image is not version-pinned",
    )
    _require("--require-hashes" in dockerfile, "Docker dependencies are not hash-locked")
    _require("USER 10001:10001" in dockerfile, "runtime image is not non-root")
    _require(
        'CMD ["python", "scripts/start_api.py"]' in dockerfile,
        "API command is not exec-form",
    )
    api_entrypoint = (ROOT / "scripts" / "start_api.py").read_text(encoding="utf-8")
    _require(
        "validate_runtime_config(settings)" in api_entrypoint,
        "API startup does not fail closed on unsafe runtime configuration",
    )

    api_railway = (ROOT / "railway.toml").read_text(encoding="utf-8")
    worker_railway = (ROOT / "railway.worker.toml").read_text(encoding="utf-8")
    _require("scripts/start_api.py" in api_railway, "Railway API command is missing")
    _require("scripts/run_worker.py" in worker_railway, "Railway worker command is missing")

    dashboard = json.loads(
        (ROOT / "config" / "incident_agent_dashboard.json").read_text(encoding="utf-8")
    )
    alerts = yaml.safe_load(
        (ROOT / "config" / "incident_agent_alerts.yml").read_text(encoding="utf-8")
    )
    _require(len(dashboard.get("panels", [])) >= 6, "runtime dashboard is incomplete")
    _require(
        len(alerts.get("groups", [])[0].get("rules", [])) >= 5,
        "runtime alert rules are incomplete",
    )

    security_workflow_path = ROOT / ".github" / "workflows" / "dependency-security.yml"
    security_workflow = yaml.safe_load(
        security_workflow_path.read_text(encoding="utf-8")
    )
    permissions = security_workflow.get("permissions", {})
    _require(
        permissions.get("contents") == "read",
        "dependency security workflow needs read-only repository contents",
    )
    security_workflow_source = security_workflow_path.read_text(encoding="utf-8")
    _require(
        "pip-audit -r requirements.lock --require-hashes" in security_workflow_source,
        "dependency security workflow must audit the hash-locked requirements",
    )
    _require(
        "github/codeql-action" not in security_workflow_source,
        "private repositories without GHAS must not run CodeQL Action",
    )

    gitlab_path = ROOT / ".gitlab-ci.yml"
    gitlab = yaml.safe_load(gitlab_path.read_text(encoding="utf-8"))
    _require(
        gitlab.get("stages") == ["verify", "security", "container"],
        "GitLab CI stages are incomplete",
    )
    for job_name in ("python-quality", "dependency-security", "compose-e2e"):
        _require(job_name in gitlab, f"GitLab CI job is missing: {job_name}")
    _require(
        gitlab["compose-e2e"].get("tags") == ["docker-dind"],
        "GitLab Compose E2E must target the dedicated Docker-in-Docker runner",
    )

    shadow = (ROOT / "config" / "shadow.env.example").read_text(encoding="utf-8")
    for required in (
        "PROCESS_ROLE=api",
        "RUNTIME_SCHEMA_DDL_ENABLED=false",
        "API_DRAIN_JOBS=false",
        "PUBLISH_EXTERNAL=false",
        "MYSQL_SSL_ENABLED=true",
        "OIDC_TENANT_CLAIM=tenant_id",
        "MYSQL_MIGRATOR_USER=",
    ):
        _require(required in shadow, f"shadow baseline lacks {required}")
    migration_entrypoint = ROOT / "scripts" / "migrate_database.py"
    _require(migration_entrypoint.exists(), "database migration entrypoint is missing")
    migration_source = migration_entrypoint.read_text(encoding="utf-8")
    _require(
        "PROCESS_ROLE=migrator" in migration_source,
        "database migration entrypoint does not require the migrator role",
    )
    print("deploy artifact validation passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"deploy artifact validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
