#!/usr/bin/env python3
"""Create, restore, migrate-check, compare, and remove an isolated MySQL backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from graph.checkpointer import MySQLSaver
from langgraph.checkpoint.base import empty_checkpoint
from utils.mysql import connection as mysql_connection
from webhook.incident_store import record_event_and_enqueue


IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
VERIFIED_TABLES = (
    "schema_migrations",
    "incident_events",
    "incident_jobs",
    "incident_revisions",
    "langgraph_checkpoints",
)


def _credentials_environment():
    environment = os.environ.copy()
    password = settings.MYSQL_MIGRATOR_PASSWORD or settings.MYSQL_PASSWORD
    if password:
        environment["MYSQL_PWD"] = password
    return environment


def _client_arguments(executable):
    user = settings.MYSQL_MIGRATOR_USER or settings.MYSQL_USER
    return [
        executable,
        "--protocol=tcp",
        "-h",
        settings.MYSQL_HOST,
        "-P",
        str(settings.MYSQL_PORT),
        "-u",
        user,
    ]


def _mysql(*arguments, input_file=None, capture_output=True):
    command = [*_client_arguments("mysql"), *map(str, arguments)]
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=_credentials_environment(),
        stdin=input_file,
        check=True,
        capture_output=capture_output,
        text=False,
        timeout=120,
    )


def _table_counts(database):
    statements = " ".join(
        f"SELECT '{table}',COUNT(*) FROM `{table}`;" for table in VERIFIED_TABLES
    )
    output = _mysql("-N", database, "-e", statements).stdout.decode("utf-8")
    counts = {}
    for line in output.splitlines():
        table, count = line.split("\t", 1)
        counts[table] = int(count)
    return counts


def _seed_canary():
    suffix = uuid.uuid4().hex
    incident_id = "INC-BACKUP-CANARY-" + suffix[:16]
    checkpoint_thread = "checkpoint-backup-canary-" + suffix
    record_event_and_enqueue(
        incident_id,
        hashlib.sha256(incident_id.encode("utf-8")).hexdigest(),
        "firing",
        {"alertname": "BackupRestoreCanary", "service": "runtime-verifier"},
    )
    checkpoint = empty_checkpoint()
    version = "00000000000000000000000000000001.0000000000000000"
    checkpoint["channel_values"] = {"backup_canary": incident_id}
    checkpoint["channel_versions"] = {"backup_canary": version}
    MySQLSaver().put(
        {
            "configurable": {
                "thread_id": checkpoint_thread,
                "checkpoint_ns": "",
            }
        },
        checkpoint,
        {"source": "backup-restore-canary"},
        {"backup_canary": version},
    )
    return incident_id, checkpoint_thread


def _cleanup_canary(incident_id, checkpoint_thread):
    MySQLSaver().delete_thread(checkpoint_thread)
    with mysql_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM incident_job_locks WHERE incident_id=%s",
            (incident_id,),
        )
        cursor.execute(
            "DELETE FROM incident_jobs WHERE incident_id=%s",
            (incident_id,),
        )
        cursor.execute(
            "DELETE FROM incident_events WHERE incident_id=%s",
            (incident_id,),
        )
        connection.commit()


def run_rehearsal(source_database=None):
    if settings.ENVIRONMENT not in {"local", "development"}:
        raise RuntimeError("backup/restore rehearsal may only run locally")
    source = source_database or settings.MYSQL_DATABASE
    if not IDENTIFIER.fullmatch(source):
        raise ValueError("source database name is not a safe MySQL identifier")
    if source != settings.MYSQL_DATABASE:
        raise ValueError(
            "source database must match MYSQL_DATABASE so the recovery canary "
            "cannot be written to a different database"
        )
    target = f"{source}_restore_{uuid.uuid4().hex[:10]}"
    if not IDENTIFIER.fullmatch(target):
        raise ValueError("restore database name is not a safe MySQL identifier")

    exists = _mysql(
        "-N",
        "-e",
        "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA "
        f"WHERE SCHEMA_NAME='{target}'",
    ).stdout.strip()
    if exists != b"0":
        raise RuntimeError("generated restore database already exists")

    created = False
    canary = _seed_canary()
    with tempfile.TemporaryDirectory(prefix="incident-agent-backup-") as directory:
        dump_path = Path(directory) / "incident-agent.sql"
        try:
            _mysql(
                "-e",
                f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
            )
            created = True
            with dump_path.open("wb") as output:
                subprocess.run(
                    [
                        *_client_arguments("mysqldump"),
                        "--single-transaction",
                        "--routines",
                        "--events",
                        "--triggers",
                        "--hex-blob",
                        source,
                    ],
                    cwd=PROJECT_ROOT,
                    env=_credentials_environment(),
                    stdout=output,
                    check=True,
                    timeout=120,
                )
            dump_size = dump_path.stat().st_size
            if dump_size <= 0:
                raise RuntimeError("mysqldump produced an empty backup")
            dump_sha256 = hashlib.sha256(dump_path.read_bytes()).hexdigest()
            with dump_path.open("rb") as backup:
                _mysql(target, input_file=backup, capture_output=True)

            migration_environment = os.environ.copy()
            migration_environment.update(
                {
                    "PROCESS_ROLE": "migrator",
                    "RUNTIME_SCHEMA_DDL_ENABLED": "false",
                    "MYSQL_DATABASE": target,
                }
            )
            subprocess.run(
                [sys.executable, "scripts/migrate_database.py", "check"],
                cwd=PROJECT_ROOT,
                env=migration_environment,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            source_counts = _table_counts(source)
            restored_counts = _table_counts(target)
            if source_counts != restored_counts:
                raise RuntimeError("restored table counts differ from the source backup")
            restored_canary = _mysql(
                "-N",
                target,
                "-e",
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.alertname')) "
                "FROM incident_events "
                f"WHERE incident_id='{canary[0]}'; "
                f"SELECT COUNT(*) FROM `{settings.MYSQL_TABLE}` "
                f"WHERE thread_id='{canary[1]}';",
            ).stdout.decode("utf-8").splitlines()
            if restored_canary != ["BackupRestoreCanary", "1"]:
                raise RuntimeError("restored canary event or checkpoint is unreadable")
            return {
                "schema_version": "backup-restore-rehearsal/v1",
                "source_database": source,
                "restore_database": target,
                "dump_bytes": dump_size,
                "dump_sha256": dump_sha256,
                "migration_check": "passed",
                "canary_event_and_checkpoint": "readable",
                "verified_table_counts": restored_counts,
                "restore_removed": True,
            }
        finally:
            if created:
                _mysql("-e", f"DROP DATABASE `{target}`")
            _cleanup_canary(*canary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", default="")
    args = parser.parse_args(argv)
    report = run_rehearsal(args.source_database or None)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
