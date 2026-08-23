#!/usr/bin/env python3
"""Fail closed until one deployed environment satisfies runtime release gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from scripts.check_pitr_readiness import check_pitr_readiness
from utils.runtime_config import SECURE_RUNTIME_MODES, validate_runtime_config
from webhook.incident_store import readiness_check


def run_preflight():
    if settings.ENVIRONMENT not in SECURE_RUNTIME_MODES:
        raise RuntimeError("production preflight requires shadow or production")
    validate_runtime_config(settings)
    dependencies = readiness_check(
        require_worker=True,
        worker_max_age_seconds=settings.WORKER_HEARTBEAT_STALE_SECONDS,
        minimum_workers=settings.MIN_ACTIVE_WORKERS,
    )
    if (
        dependencies["database"] != "ready"
        or dependencies["queue"] != "ready"
        or dependencies["schema"] != "ready"
        or dependencies["worker"]["status"] != "ready"
    ):
        raise RuntimeError("runtime dependencies are not release-ready")
    pitr = check_pitr_readiness(86400)
    if pitr["status"] != "passed":
        raise RuntimeError("MySQL PITR prerequisites are not release-ready")
    return {
        "schema_version": "production-preflight/v1",
        "environment": settings.ENVIRONMENT,
        "configuration": "passed",
        "dependencies": dependencies,
        "pitr": pitr,
    }


def main():
    print(json.dumps(run_preflight(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
