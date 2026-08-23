#!/usr/bin/env python3
"""Apply versioned MySQL schema releases before API and worker startup.

Run this command once per release using a DDL-capable ``migrator`` database
identity. Runtime API and worker identities must keep
``RUNTIME_SCHEMA_DDL_ENABLED=false``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from graph.checkpointer import MySQLSaver
from utils import audit
from utils.mysql import connection as mysql_connection
from webhook import knowledge_store, rate_limit, registry, replay
from webhook import incident_store


INITIAL_MIGRATION = "20260823_01_initial_runtime_schema"
MIGRATION_LOCK_NAME = "incident-agent-schema-migration"


def _validate_invocation():
    if settings.PROCESS_ROLE != "migrator":
        raise RuntimeError("PROCESS_ROLE=migrator is required for database migrations")
    if settings.RUNTIME_SCHEMA_DDL_ENABLED:
        raise RuntimeError(
            "RUNTIME_SCHEMA_DDL_ENABLED must remain false; only the migrator may run DDL"
        )
    if (
        settings.ENVIRONMENT in {"shadow", "production"}
        and not settings.MYSQL_MIGRATOR_USER
    ):
        raise RuntimeError("MYSQL_MIGRATOR_USER is required in secure environments")


def _ensure_ledger(conn):
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "migration_id VARCHAR(128) PRIMARY KEY, applied_at DATETIME(6) NOT NULL, "
            "applied_by VARCHAR(128) NOT NULL)"
        )
    conn.commit()


def _is_applied(conn, migration_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_id=%s",
            (migration_id,),
        )
        return bool(cur.fetchone())


def _apply_initial_schema():
    incident_store.ensure_schema(allow_ddl=True)
    registry.ensure_schema(allow_ddl=True)
    knowledge_store.ensure_schema(allow_ddl=True)
    rate_limit.ensure_schema(allow_ddl=True)
    replay.ensure_schema(allow_ddl=True)
    audit.ensure_schema(allow_ddl=True)
    with mysql_connection() as conn, conn.cursor() as cur:
        MySQLSaver._create_schema(cur, settings.MYSQL_TABLE)
        conn.commit()


def apply_migrations():
    """Apply pending schema migrations under a database advisory lock."""
    _validate_invocation()
    with mysql_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT GET_LOCK(%s, 60)", (MIGRATION_LOCK_NAME,))
        locked = cur.fetchone()
        if not locked or not locked[0]:
            raise RuntimeError("timed out waiting for the database migration lock")
        try:
            _ensure_ledger(conn)
            if _is_applied(conn, INITIAL_MIGRATION):
                return {"applied": [], "already_applied": [INITIAL_MIGRATION]}
            _apply_initial_schema()
            cur.execute(
                "INSERT INTO schema_migrations (migration_id,applied_at,applied_by) "
                "VALUES (%s,UTC_TIMESTAMP(6),%s)",
                (INITIAL_MIGRATION, settings.PROCESS_ROLE),
            )
            conn.commit()
            return {"applied": [INITIAL_MIGRATION], "already_applied": []}
        finally:
            cur.execute("SELECT RELEASE_LOCK(%s)", (MIGRATION_LOCK_NAME,))
            conn.commit()


def check_migrations():
    """Return a non-zero result until the current release schema is applied."""
    _validate_invocation()
    with mysql_connection() as conn:
        _ensure_ledger(conn)
        if not _is_applied(conn, INITIAL_MIGRATION):
            raise RuntimeError(f"missing required database migration: {INITIAL_MIGRATION}")
    return {"applied": [INITIAL_MIGRATION]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("apply", "check"))
    args = parser.parse_args(argv)
    result = apply_migrations() if args.command == "apply" else check_migrations()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
