"""Curated incident knowledge with explicit approval and filter-first retrieval.

This is deliberately a small lexical store.  It creates no embeddings and never
accepts raw incident evidence; a semantic retriever can later sit behind the
same authorization filters without changing the safety boundary.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from utils.redaction import redact_data
from utils.mysql import connection as mysql_connection
from settings import RUNTIME_SCHEMA_DDL_ENABLED


APPROVED_SOURCE_TYPES = {
    "reviewed_postmortem",
    "reviewed_runbook",
    "service_metadata",
    "tested_failure_rule",
}


def _connection():
    return mysql_connection()


def _now():
    return datetime.now(timezone.utc)


def _json(value):
    return json.dumps(redact_data(value), default=str, separators=(",", ":"))


def _decode(value):
    return value if isinstance(value, (dict, list)) else json.loads(value)


def ensure_schema(*, allow_ddl=False):
    if not (RUNTIME_SCHEMA_DDL_ENABLED or allow_ddl):
        return
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS curated_knowledge ("
            "knowledge_id CHAR(32) PRIMARY KEY, status VARCHAR(32) NOT NULL, "
            "source_type VARCHAR(64) NOT NULL, source_link VARCHAR(512) NOT NULL, "
            "approval_identity VARCHAR(255) NOT NULL, approval_reference VARCHAR(255) NOT NULL, "
            "tenant VARCHAR(128) NOT NULL, service VARCHAR(128) NULL, environment VARCHAR(64) NULL, "
            "incident_type VARCHAR(128) NULL, security_class VARCHAR(64) NOT NULL, "
            "valid_until DATETIME(6) NULL, supersedes_knowledge_id CHAR(32) NULL, "
            "summary TEXT NOT NULL, metadata JSON NOT NULL, created_at DATETIME(6) NOT NULL, "
            "updated_at DATETIME(6) NOT NULL, "
            "INDEX knowledge_filter (tenant,service,environment,status,valid_until))"
        )
        conn.commit()


def create_knowledge_record(*, source_type, source_link, approval_identity, approval_reference,
                            tenant, summary, security_class, service=None, environment=None,
                            incident_type=None, valid_until=None, metadata=None,
                            supersedes_knowledge_id=None):
    """Create one approved, concise knowledge record; never ingest model output implicitly."""
    if source_type not in APPROVED_SOURCE_TYPES:
        raise ValueError("knowledge source type is not approved")
    if not approval_identity or not approval_reference:
        raise ValueError("knowledge requires approval identity and reference")
    if not tenant or not source_link:
        raise ValueError("knowledge requires tenant and source link")
    text = " ".join(str(summary or "").split())
    if not text or len(text) > 6000:
        raise ValueError("knowledge summary must be between 1 and 6000 characters")
    if metadata and any(key.lower() in {"raw_logs", "raw_evidence", "prompt"} for key in metadata):
        raise ValueError("raw evidence and prompts cannot be indexed as knowledge")
    ensure_schema()
    now = _now()
    identifier = uuid.uuid4().hex
    with _connection() as conn, conn.cursor() as cur:
        if supersedes_knowledge_id:
            cur.execute(
                "SELECT status FROM curated_knowledge WHERE knowledge_id=%s FOR UPDATE",
                (supersedes_knowledge_id,),
            )
            if not cur.fetchone():
                conn.rollback()
                raise ValueError("knowledge record to supersede was not found")
            cur.execute(
                "UPDATE curated_knowledge SET status='superseded',updated_at=%s WHERE knowledge_id=%s",
                (now, supersedes_knowledge_id),
            )
        cur.execute(
            "INSERT INTO curated_knowledge "
            "(knowledge_id,status,source_type,source_link,approval_identity,approval_reference,tenant,service,environment,incident_type,security_class,valid_until,supersedes_knowledge_id,summary,metadata,created_at,updated_at) "
            "VALUES (%s,'active',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (identifier, source_type, str(source_link)[:512], str(approval_identity)[:255],
             str(approval_reference)[:255], str(tenant)[:128], str(service)[:128] if service else None,
             str(environment)[:64] if environment else None, str(incident_type)[:128] if incident_type else None,
             str(security_class)[:64], valid_until, supersedes_knowledge_id, text,
             _json(metadata or {}), now, now),
        )
        conn.commit()
    return get_knowledge_record(identifier)


def get_knowledge_record(knowledge_id):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT knowledge_id,status,source_type,source_link,approval_identity,approval_reference,tenant,service,environment,incident_type,security_class,valid_until,supersedes_knowledge_id,summary,metadata,created_at,updated_at "
            "FROM curated_knowledge WHERE knowledge_id=%s", (knowledge_id,)
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "knowledge_id": row[0], "status": row[1], "source_type": row[2], "source_link": row[3],
        "approval_identity": row[4], "approval_reference": row[5], "tenant": row[6],
        "service": row[7], "environment": row[8], "incident_type": row[9], "security_class": row[10],
        "valid_until": row[11].isoformat() if row[11] else None, "supersedes_knowledge_id": row[12],
        "summary": row[13], "metadata": _decode(row[14]), "created_at": row[15].isoformat(),
        "updated_at": row[16].isoformat(),
    }


def retrieve_knowledge(*, tenant, allowed_security_classes, service=None, environment=None,
                       incident_type=None, query="", limit=5, now=None):
    """Filter by access boundary before bounded lexical ranking; a miss is normal."""
    if not tenant:
        raise ValueError("knowledge retrieval requires tenant")
    allowed = [str(value) for value in (allowed_security_classes or []) if value]
    if not allowed:
        raise ValueError("knowledge retrieval requires allowed security classes")
    bounded = max(1, min(int(limit), 10))
    current = now or _now()
    placeholders = ",".join(["%s"] * len(allowed))
    clauses = [
        "tenant=%s", "status='active'", "security_class IN (" + placeholders + ")",
        "(valid_until IS NULL OR valid_until>%s)",
        "(service IS NULL OR service=%s)", "(environment IS NULL OR environment=%s)",
    ]
    params = [tenant, *allowed, current, service, environment]
    if incident_type:
        clauses.append("(incident_type IS NULL OR incident_type=%s)")
        params.append(incident_type)
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT knowledge_id,source_link,summary,service,environment,incident_type,metadata "
            "FROM curated_knowledge WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT 50",
            tuple(params),
        )
        rows = cur.fetchall()
    terms = {term.lower() for term in re.findall(r"[a-zA-Z0-9_-]{3,}", str(query))}
    scored = []
    for row in rows:
        haystack = (row[2] + " " + json.dumps(_decode(row[6]), default=str)).lower()
        score = sum(term in haystack for term in terms)
        scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "knowledge_id": row[0], "source_link": row[1], "summary": row[2],
            "service": row[3], "environment": row[4], "incident_type": row[5],
            "relevance_reason": "lexical match: " + ", ".join(
                term for term in sorted(terms) if term in (row[2] + " " + json.dumps(_decode(row[6]), default=str)).lower()
            ) if terms else "recent approved record",
        }
        for _score, row in scored[:bounded]
    ]


def delete_knowledge_record(knowledge_id, approval_identity, reason):
    """Soft-delete with attribution so retrieval stops recommending a bad record."""
    if not approval_identity or not str(reason).strip():
        raise ValueError("knowledge deletion requires identity and reason")
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE curated_knowledge SET status='deleted',updated_at=%s WHERE knowledge_id=%s AND status!='deleted'",
            (now, knowledge_id),
        )
        if not cur.rowcount:
            conn.rollback()
            raise ValueError("active knowledge record was not found")
        conn.commit()
    return {"knowledge_id": knowledge_id, "status": "deleted", "deleted_by": str(approval_identity)[:255]}
