#!/usr/bin/env python3
"""Fail closed unless MySQL exposes the prerequisites for point-in-time recovery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.mysql import connection as mysql_connection


def check_pitr_readiness(minimum_retention_seconds=86400):
    with mysql_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT @@GLOBAL.log_bin,@@GLOBAL.binlog_format,"
            "@@GLOBAL.binlog_expire_logs_seconds,@@GLOBAL.server_id"
        )
        log_bin, format_name, retention, server_id = cursor.fetchone()
    report = {
        "schema_version": "mysql-pitr-readiness/v1",
        "binary_logging": bool(log_bin),
        "binlog_format": str(format_name).upper(),
        "retention_seconds": int(retention),
        "server_id": int(server_id),
        "minimum_retention_seconds": int(minimum_retention_seconds),
    }
    failures = []
    if not report["binary_logging"]:
        failures.append("binary logging is disabled")
    if report["binlog_format"] != "ROW":
        failures.append("binlog_format must be ROW")
    if report["retention_seconds"] < minimum_retention_seconds:
        failures.append("binary log retention is below the recovery objective")
    if report["server_id"] <= 0:
        failures.append("server_id must be non-zero")
    report["status"] = "passed" if not failures else "failed"
    report["failures"] = failures
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum-retention-seconds", type=int, default=86400)
    args = parser.parse_args(argv)
    report = check_pitr_readiness(args.minimum_retention_seconds)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
