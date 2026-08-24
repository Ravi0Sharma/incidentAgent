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
IDEMPOTENT_JOB_EFFECTS_MIGRATION = "20260824_02_idempotent_job_effects"
PUBLICATION_GUARD_MIGRATION = incident_store.PUBLICATION_GUARD_MIGRATION
BUCKET_ADMISSION_MIGRATION = incident_store.REQUIRED_RUNTIME_MIGRATION
REQUIRED_MIGRATIONS = (
    INITIAL_MIGRATION,
    IDEMPOTENT_JOB_EFFECTS_MIGRATION,
    PUBLICATION_GUARD_MIGRATION,
    BUCKET_ADMISSION_MIGRATION,
)
MIGRATION_LOCK_NAME = "incident-agent-schema-migration"


def _expected_tables():
    prefix = settings.MYSQL_TABLE
    return {
        "schema_migrations",
        "incident_events",
        "incident_id_sequence",
        "incident_id_map",
        "incident_revisions",
        "incident_revision_heads",
        "incident_analysis_revisions",
        "incident_evidence_records",
        "incident_analysis_evidence",
        "incident_review_decisions",
        "incident_postmortem_drafts",
        "incident_jobs",
        "incident_admission_locks",
        "incident_job_locks",
        "incident_queue_control",
        "incident_workers",
        "incident_dead_letters",
        "incident_publications",
        "pending_reviews",
        "incident_lifecycle",
        "curated_knowledge",
        "webhook_rate_limits",
        "webhook_nonces",
        "audit_events",
        prefix,
        f"{prefix}_writes",
        f"{prefix}_blobs",
    }


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


def _missing_runtime_tables(conn):
    expected = _expected_tables()
    placeholders = ",".join("%s" for _ in expected)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            f"WHERE table_schema=%s AND table_name IN ({placeholders})",
            (settings.MYSQL_DATABASE, *sorted(expected)),
        )
        actual = {row[0] for row in cur.fetchall()}
    return sorted(expected - actual)


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


def _apply_idempotent_job_effects_schema():
    # ``ensure_schema`` is deliberately DDL-enabled only in this migrator
    # process. It adds the job-to-revision idempotency key and durable result
    # fields without mutating existing records.
    incident_store.ensure_schema(allow_ddl=True)


def _apply_publication_guard_schema():
    incident_store.ensure_schema(allow_ddl=True)


def _apply_bucket_admission_schema():
    incident_store.ensure_schema(allow_ddl=True)


def _record_migration(cur, migration_id):
    cur.execute(
        "INSERT INTO schema_migrations (migration_id,applied_at,applied_by) "
        "VALUES (%s,UTC_TIMESTAMP(6),%s)",
        (migration_id, settings.PROCESS_ROLE),
    )


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
            applied = []
            already_applied = []
            if _is_applied(conn, INITIAL_MIGRATION):
                already_applied.append(INITIAL_MIGRATION)
            else:
                _apply_initial_schema()
                _record_migration(cur, INITIAL_MIGRATION)
                conn.commit()
                applied.append(INITIAL_MIGRATION)

            if _is_applied(conn, IDEMPOTENT_JOB_EFFECTS_MIGRATION):
                already_applied.append(IDEMPOTENT_JOB_EFFECTS_MIGRATION)
            else:
                _apply_idempotent_job_effects_schema()
                _record_migration(cur, IDEMPOTENT_JOB_EFFECTS_MIGRATION)
                conn.commit()
                applied.append(IDEMPOTENT_JOB_EFFECTS_MIGRATION)

            if _is_applied(conn, PUBLICATION_GUARD_MIGRATION):
                already_applied.append(PUBLICATION_GUARD_MIGRATION)
            else:
                _apply_publication_guard_schema()
                _record_migration(cur, PUBLICATION_GUARD_MIGRATION)
                conn.commit()
                applied.append(PUBLICATION_GUARD_MIGRATION)

            if _is_applied(conn, BUCKET_ADMISSION_MIGRATION):
                already_applied.append(BUCKET_ADMISSION_MIGRATION)
            else:
                _apply_bucket_admission_schema()
                _record_migration(cur, BUCKET_ADMISSION_MIGRATION)
                conn.commit()
                applied.append(BUCKET_ADMISSION_MIGRATION)

            missing = _missing_runtime_tables(conn)
            if missing:
                raise RuntimeError(
                    "migration did not create required runtime tables: "
                    + ", ".join(missing)
                )
            return {"applied": applied, "already_applied": already_applied}
        finally:
            cur.execute("SELECT RELEASE_LOCK(%s)", (MIGRATION_LOCK_NAME,))
            conn.commit()


def check_migrations():
    """Return a non-zero result until the current release schema is applied."""
    _validate_invocation()
    with mysql_connection() as conn:
        _ensure_ledger(conn)
        missing_migrations = [
            migration
            for migration in REQUIRED_MIGRATIONS
            if not _is_applied(conn, migration)
        ]
        if missing_migrations:
            raise RuntimeError(
                "missing required database migration: "
                + ", ".join(missing_migrations)
            )
        missing = _missing_runtime_tables(conn)
        if missing:
            raise RuntimeError(
                "migration ledger exists but runtime schema is incomplete: "
                + ", ".join(missing)
            )
    return {"applied": list(REQUIRED_MIGRATIONS)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("apply", "check"))
    args = parser.parse_args(argv)
    result = apply_migrations() if args.command == "apply" else check_migrations()
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
