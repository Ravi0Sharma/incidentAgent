"""Durable MySQL registry for pending reviews and incident lifecycle state."""

import json
from datetime import datetime, timezone

import pymysql

from settings import MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER
from webhook.lifecycle import LIFECYCLE_VERSION, validate_transition
from utils.redaction import redact_data


class RevisionConflictError(ValueError):
    """The caller attempted to overwrite a newer incident record."""


def _connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        autocommit=False,
    )


def _now():
    return datetime.now(timezone.utc)


def _decode(value):
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def ensure_schema():
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS pending_reviews ("
            "thread_id VARCHAR(128) PRIMARY KEY, data JSON NOT NULL, "
            "version INT NOT NULL, created_at DATETIME(6) NOT NULL, "
            "updated_at DATETIME(6) NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_lifecycle ("
            "thread_id VARCHAR(128) PRIMARY KEY, status VARCHAR(64) NOT NULL, "
            "version INT NOT NULL, history JSON NOT NULL, "
            "updated_at DATETIME(6) NOT NULL)"
        )
        conn.commit()


def add_pending(thread_id, data, expected_version=None):
    """Create or update a pending review, rejecting stale writers."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT data, version, created_at FROM pending_reviews "
            "WHERE thread_id=%s FOR UPDATE",
            (thread_id,),
        )
        row = cur.fetchone()
        current_version = row[1] if row else 0
        if expected_version is not None and current_version != expected_version:
            conn.rollback()
            raise RevisionConflictError("stale pending-review version")
        existing = _decode(row[0]) if row else {}
        created_at = existing.get("created_at") if existing else None
        record = redact_data(dict(data))
        record.update(
            {
                "thread_id": thread_id,
                "created_at": created_at or now.isoformat(),
                "updated_at": now.isoformat(),
                "pending_revision": current_version + 1,
            }
        )
        cur.execute(
            "INSERT INTO pending_reviews "
            "(thread_id,data,version,created_at,updated_at) VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE data=VALUES(data), version=VALUES(version), "
            "updated_at=VALUES(updated_at)",
            (
                thread_id,
                json.dumps(record, default=str),
                current_version + 1,
                row[2] if row else now,
                now,
            ),
        )
        conn.commit()
    return record


def remove_pending(thread_id, expected_version=None):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        if expected_version is None:
            cur.execute("DELETE FROM pending_reviews WHERE thread_id=%s", (thread_id,))
        else:
            cur.execute(
                "DELETE FROM pending_reviews WHERE thread_id=%s AND version=%s",
                (thread_id, expected_version),
            )
            if not cur.rowcount:
                conn.rollback()
                raise RevisionConflictError("stale pending-review version")
        conn.commit()


def get_pending(thread_id):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT data FROM pending_reviews WHERE thread_id=%s", (thread_id,))
        row = cur.fetchone()
    return _decode(row[0]) if row else None


def list_pending():
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT data FROM pending_reviews ORDER BY updated_at DESC")
        rows = cur.fetchall()
    return [_decode(row[0]) for row in rows]


def transition_lifecycle(thread_id, target, reason=None, expected_version=None):
    """Atomically transition lifecycle state and append a versioned audit entry."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, version, history FROM incident_lifecycle "
            "WHERE thread_id=%s FOR UPDATE",
            (thread_id,),
        )
        row = cur.fetchone()
        current = row[0] if row else None
        current_version = row[1] if row else 0
        if expected_version is not None and current_version != expected_version:
            conn.rollback()
            raise RevisionConflictError("stale lifecycle version")
        validate_transition(current, target)
        history = _decode(row[2]) if row else []
        version = current_version + 1
        history.append(
            {
                "schema_version": LIFECYCLE_VERSION,
                "from": current,
                "to": target,
                "version": version,
                "at": now.isoformat(),
                "reason": reason,
            }
        )
        cur.execute(
            "INSERT INTO incident_lifecycle (thread_id,status,version,history,updated_at) "
            "VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
            "status=VALUES(status),version=VALUES(version),history=VALUES(history),"
            "updated_at=VALUES(updated_at)",
            (thread_id, target, version, json.dumps(history), now),
        )
        conn.commit()
    return {"status": target, "version": version, "history": history}


def get_lifecycle(thread_id):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, version, history, updated_at FROM incident_lifecycle "
            "WHERE thread_id=%s",
            (thread_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"status": row[0], "version": row[1], "history": _decode(row[2]), "updated_at": row[3].isoformat()}


def resolve_incident(thread_id, reason="resolved alert received"):
    current = get_lifecycle(thread_id)
    if not current:
        return {"status": "unknown_incident", "idempotent": False}
    if current["status"] == "resolved":
        return {**current, "idempotent": True}
    result = transition_lifecycle(thread_id, "resolved", reason, current["version"])
    return {**result, "idempotent": False}


def reopen_incident(thread_id, reason="new firing observation after resolution"):
    """Atomically reopen a resolved incident through the intake lifecycle."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status,version,history FROM incident_lifecycle "
            "WHERE thread_id=%s FOR UPDATE",
            (thread_id,),
        )
        row = cur.fetchone()
        if not row or row[0] != "resolved":
            conn.rollback()
            raise RevisionConflictError("only a resolved incident can be reopened")
        current = row[0]
        version = row[1]
        history = _decode(row[2])
        for target in ("received", "collecting", "analyzing"):
            validate_transition(current, target)
            version += 1
            history.append({
                "schema_version": LIFECYCLE_VERSION,
                "from": current,
                "to": target,
                "version": version,
                "at": now.isoformat(),
                "reason": reason,
            })
            current = target
        cur.execute(
            "UPDATE incident_lifecycle SET status=%s,version=%s,history=%s,"
            "updated_at=%s WHERE thread_id=%s",
            (current, version, json.dumps(history), now, thread_id),
        )
        conn.commit()
    return {
        "status": current,
        "version": version,
        "history": history,
        "reopened": True,
    }
