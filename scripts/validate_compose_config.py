#!/usr/bin/env python3
"""Validate the safety and topology invariants of the local Compose stack."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _environment(service):
    value = service.get("environment", {})
    _require(isinstance(value, dict), "service environment must use mapping form")
    return value


def validate():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    _require(
        set(services) == {"mysql", "migrator", "api", "worker-1", "worker-2", "verify", "stress"},
        "Compose services must be MySQL, migrator, API, two workers, verifier and stress probe",
    )
    _require(services["mysql"].get("image") == "mysql:8.4", "MySQL must be pinned to 8.4")
    _require(
        services["mysql"].get("ports") == ["127.0.0.1:3307:3306"],
        "MySQL must only bind its optional host port to loopback",
    )
    _require(
        compose.get("networks", {}).get("incident_backend", {}).get("internal") is True,
        "runtime network must be internal",
    )

    expected_roles = {
        "migrator": "migrator",
        "api": "api",
        "worker-1": "worker",
        "worker-2": "worker",
    }
    for service_name, process_role in expected_roles.items():
        service = services[service_name]
        environment = _environment(service)
        _require(environment.get("PROCESS_ROLE") == process_role, f"{service_name} role is incorrect")
        _require(environment.get("RUNTIME_SCHEMA_DDL_ENABLED") == "false", f"{service_name} may not run runtime DDL")
        _require(environment.get("PUBLISH_EXTERNAL") == "false", f"{service_name} may not publish externally")
        _require(environment.get("MYSQL_HOST") == "mysql", f"{service_name} must use Compose MySQL DNS")
        _require(service.get("read_only") is True, f"{service_name} filesystem must be read-only")
        _require(bool(service.get("healthcheck")) or service_name == "migrator", f"{service_name} needs a healthcheck")

    _require(_environment(services["api"]).get("API_DRAIN_JOBS") == "false", "API may not drain jobs")
    _require(_environment(services["api"]).get("MIN_ACTIVE_WORKERS") == "2", "API readiness must require two workers")
    _require(
        _environment(services["api"]).get("INCIDENT_STORE_PATH", "").startswith("/app/output/"),
        "local raw-log cache must use the shared writable output volume",
    )
    for worker_name in ("worker-1", "worker-2"):
        dependencies = services[worker_name].get("depends_on", {})
        _require(
            dependencies.get("migrator", {}).get("condition") == "service_completed_successfully",
            f"{worker_name} must wait for migrations",
        )

    api_ports = services["api"].get("ports", [])
    _require(api_ports == ["127.0.0.1:8000:8000"], "API must only bind to loopback locally")
    verify_command = services["verify"].get("command", [])
    _require("--local" in verify_command, "Compose verifier must use explicit local mode")
    _require("--expected-min-workers" in verify_command, "Compose verifier must check worker HA")
    stress = services["stress"]
    _require(stress.get("profiles") == ["tools"], "stress probe must be opt-in")
    _require(_environment(stress).get("PROCESS_ROLE") == "worker", "stress probe must use worker identity")
    _require(_environment(stress).get("PUBLISH_EXTERNAL") == "false", "stress probe may not publish externally")
    stress_command = stress.get("command", [])
    _require("scripts/run_resilience_soak.py" in stress_command, "stress probe must use resilience soak")
    _require("--cycles" in stress_command and "--workers" in stress_command, "stress probe must be multi-cycle and multi-worker")
    _require(
        (ROOT / "docker/mysql/init/001-local-runtime-users.sql").exists(),
        "local database role bootstrap is missing",
    )


def main():
    try:
        validate()
    except Exception as exc:
        print(f"Compose validation failed: {exc}", file=sys.stderr)
        return 1
    print("Compose validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
