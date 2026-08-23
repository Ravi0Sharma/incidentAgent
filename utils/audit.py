"""Append-only, redacted audit records stored with the durable incident data.

This is deliberately separate from diagnostic stdout logging.  It is a local
baseline, not a claim of immutable/WORM storage or an authorization system.
"""

from datetime import datetime, timezone
import json

from utils.mysql import connection as mysql_connection
from settings import RUNTIME_SCHEMA_DDL_ENABLED
from utils.redaction import redact_data


AUDIT_SCHEMA_VERSION = "incident-audit-event/v1"


def _connection():
    return mysql_connection()


def _ensure_schema(cursor):
    if not RUNTIME_SCHEMA_DDL_ENABLED:
        return
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS audit_events ("
        "event_id BIGINT AUTO_INCREMENT PRIMARY KEY, "
        "created_at DATETIME(6) NOT NULL, event_type VARCHAR(96) NOT NULL, "
        "incident_id VARCHAR(128) NULL, data JSON NOT NULL, "
        "INDEX audit_events_incident (incident_id, event_id), "
        "INDEX audit_events_type_time (event_type, created_at))"
    )


def record_audit_event(event_type, incident_id=None, **data):
    """Write a redacted audit event and return the record used for storage."""
    record = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": str(event_type),
        "incident_id": incident_id,
        "data": redact_data(data),
    }
    with _connection() as conn, conn.cursor() as cur:
        _ensure_schema(cur)
        cur.execute(
            "INSERT INTO audit_events (created_at,event_type,incident_id,data) VALUES (%s,%s,%s,%s)",
            (record["timestamp"], record["event_type"], incident_id,
             json.dumps(record["data"], default=str, separators=(",", ":"))),
        )
        conn.commit()
    return record


def list_audit_events(incident_id=None, limit=100):
    """Read recent audit records for operational inspection (redacted at write)."""
    limit = max(1, min(int(limit), 1_000))
    with _connection() as conn, conn.cursor() as cur:
        _ensure_schema(cur)
        if incident_id:
            cur.execute(
                "SELECT created_at,event_type,incident_id,data FROM audit_events "
                "WHERE incident_id=%s ORDER BY event_id DESC LIMIT %s",
                (incident_id, limit),
            )
        else:
            cur.execute(
                "SELECT created_at,event_type,incident_id,data FROM audit_events "
                "ORDER BY event_id DESC LIMIT %s",
                (limit,),
            )
        rows = cur.fetchall()
        conn.commit()
    return [
        {
            "timestamp": row[0].isoformat(),
            "event_type": row[1],
            "incident_id": row[2],
            "data": row[3] if isinstance(row[3], dict) else json.loads(row[3]),
        }
        for row in rows
    ]
