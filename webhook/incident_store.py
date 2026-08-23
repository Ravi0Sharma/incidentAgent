"""MySQL append-only incident event, revision, queue, and dead-letter store."""

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pymysql

from settings import (
    ANALYSIS_CODE_VERSION,
    MYSQL_DATABASE,
    MYSQL_TABLE,
    MAX_PENDING_JOBS,
    OPENAI_MODEL,
    PROMPT_VERSION,
    RUNTIME_SCHEMA_DDL_ENABLED,
)
from utils.mysql import connection as mysql_connection
from utils.redaction import redact_data
from utils.config_versions import config_version_manifest
from utils.evidence import (
    CANONICAL_EVIDENCE_SCHEMA_VERSION,
    canonical_evidence,
    integrity_hash as evidence_integrity_hash,
)


class EvidenceIntegrityError(ValueError):
    """Stored evidence no longer matches the immutable reviewed snapshot."""


class QueueCapacityError(RuntimeError):
    """The durable analysis queue reached its configured admission limit."""


class PublicationStateUncertainError(RuntimeError):
    """An earlier external publication attempt cannot be safely retried."""


REQUIRED_RUNTIME_MIGRATION = "20260824_03_publication_guard"


def _connection():
    return mysql_connection()


def _now():
    return datetime.now(timezone.utc)


def _mysql_datetime(value):
    """Convert accepted ISO-8601 event times to UTC MySQL DATETIME values."""
    if value is None or isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _json(value):
    return json.dumps(redact_data(value), default=str, separators=(",", ":"))


def _decode(value):
    return value if isinstance(value, (dict, list)) else json.loads(value)


def default_run_context():
    return {
        "code_version": ANALYSIS_CODE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model_version": OPENAI_MODEL,
        "pipeline_config": config_version_manifest(),
    }


def complete_run_context(value=None):
    return {
        **default_run_context(),
        **(value or {}),
    }


def _add_column_if_missing(cur, table, column, definition):
    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema=%s "
        "AND table_name=%s AND column_name=%s",
        (MYSQL_DATABASE, table, column),
    )
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _add_index_if_missing(cur, table, index, definition):
    cur.execute(
        "SELECT 1 FROM information_schema.statistics WHERE table_schema=%s "
        "AND table_name=%s AND index_name=%s",
        (MYSQL_DATABASE, table, index),
    )
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table} ADD {definition}")


def ensure_schema(*, allow_ddl=False):
    """Create incident tables only for local development or the release migrator."""
    if not (RUNTIME_SCHEMA_DDL_ENABLED or allow_ddl):
        return
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_events ("
            "event_id BIGINT AUTO_INCREMENT PRIMARY KEY, incident_id VARCHAR(128) NOT NULL, "
            "idempotency_key CHAR(64) NOT NULL UNIQUE, event_type VARCHAR(64) NOT NULL, "
            "event_time DATETIME(6) NULL, source_time DATETIME(6) NULL, "
            "received_at DATETIME(6) NOT NULL, clock_quality VARCHAR(64) NOT NULL, "
            "payload JSON NOT NULL, INDEX incident_events_timeline (incident_id,event_time,event_id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_id_sequence ("
            "sequence_id TINYINT PRIMARY KEY, next_value BIGINT NOT NULL)"
        )
        cur.execute(
            "INSERT INTO incident_id_sequence (sequence_id,next_value) "
            "VALUES (1,100001) ON DUPLICATE KEY UPDATE sequence_id=VALUES(sequence_id)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_id_map ("
            "incident_key CHAR(64) PRIMARY KEY, incident_id VARCHAR(128) NOT NULL UNIQUE, "
            "created_at DATETIME(6) NOT NULL)"
        )
        _add_column_if_missing(
            cur, "incident_events", "clock_quality",
            "clock_quality VARCHAR(64) NOT NULL DEFAULT 'unverified'",
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_revisions ("
            "incident_id VARCHAR(128) NOT NULL, revision INT NOT NULL, "
            "previous_revision INT NULL, job_id BIGINT NULL, "
            "reason VARCHAR(255) NOT NULL, execution_context JSON NULL, created_at DATETIME(6) NOT NULL, "
            "UNIQUE KEY incident_revision_job (job_id), "
            "PRIMARY KEY (incident_id, revision))"
        )
        _add_column_if_missing(
            cur,
            "incident_revisions",
            "job_id",
            "job_id BIGINT NULL",
        )
        _add_index_if_missing(
            cur,
            "incident_revisions",
            "incident_revision_job",
            "UNIQUE KEY incident_revision_job (job_id)",
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_revision_heads ("
            "incident_id VARCHAR(128) PRIMARY KEY, current_revision INT NOT NULL, "
            "updated_at DATETIME(6) NOT NULL)"
        )
        _add_column_if_missing(
            cur, "incident_revisions", "execution_context", "execution_context JSON NULL"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_analysis_revisions ("
            "incident_id VARCHAR(128) NOT NULL, revision INT NOT NULL, "
            "previous_revision INT NULL, event_id BIGINT NULL, "
            "evidence_ids JSON NOT NULL, candidate_snapshot JSON NOT NULL, "
            "state_summary JSON NOT NULL, run_context JSON NULL, "
            "created_at DATETIME(6) NOT NULL, "
            "PRIMARY KEY (incident_id,revision))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_evidence_records ("
            "evidence_record_id BIGINT AUTO_INCREMENT PRIMARY KEY, "
            "incident_id VARCHAR(128) NOT NULL, evidence_id VARCHAR(255) NOT NULL, "
            "evidence_type VARCHAR(64) NOT NULL, version INT NOT NULL, "
            "content_sha256 CHAR(64) NOT NULL, payload JSON NOT NULL, "
            "supersedes_record_id BIGINT NULL, first_analysis_revision INT NOT NULL, "
            "created_at DATETIME(6) NOT NULL, "
            "UNIQUE KEY incident_evidence_version (incident_id,evidence_id,version), "
            "UNIQUE KEY incident_evidence_content (incident_id,evidence_id,content_sha256), "
            "INDEX incident_evidence_lookup (incident_id,evidence_id,evidence_record_id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_analysis_evidence ("
            "incident_id VARCHAR(128) NOT NULL, analysis_revision INT NOT NULL, "
            "evidence_id VARCHAR(255) NOT NULL, evidence_record_id BIGINT NOT NULL, "
            "PRIMARY KEY (incident_id,analysis_revision,evidence_id), "
            "INDEX analysis_evidence_record (evidence_record_id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_review_decisions ("
            "decision_id BIGINT AUTO_INCREMENT PRIMARY KEY, "
            "decision_key CHAR(64) NOT NULL UNIQUE, incident_id VARCHAR(128) NOT NULL, "
            "analysis_revision INT NULL, pending_revision INT NOT NULL, "
            "reviewer_identity VARCHAR(255) NOT NULL, decision VARCHAR(32) NOT NULL, "
            "selected_hypothesis VARCHAR(128) NULL, displayed_evidence_ids JSON NOT NULL, "
            "rationale TEXT NOT NULL, request_id VARCHAR(128) NULL, "
            "created_at DATETIME(6) NOT NULL, "
            "INDEX incident_review_timeline (incident_id,created_at))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_postmortem_drafts ("
            "draft_id BIGINT AUTO_INCREMENT PRIMARY KEY, incident_id VARCHAR(128) NOT NULL, "
            "analysis_revision INT NULL, version INT NOT NULL, content MEDIUMTEXT NOT NULL, "
            "content_sha256 CHAR(64) NOT NULL, source VARCHAR(32) NOT NULL, "
            "editor_identity VARCHAR(255) NULL, supersedes_draft_id BIGINT NULL, "
            "created_at DATETIME(6) NOT NULL, "
            "UNIQUE KEY incident_postmortem_version (incident_id,version))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_jobs ("
            "job_id BIGINT AUTO_INCREMENT PRIMARY KEY, job_key CHAR(64) NOT NULL UNIQUE, "
            "incident_id VARCHAR(128) NOT NULL, event_id BIGINT NOT NULL, kind VARCHAR(32) NOT NULL, "
            "status VARCHAR(32) NOT NULL, attempt_count INT NOT NULL DEFAULT 0, "
            "available_at DATETIME(6) NOT NULL, leased_until DATETIME(6) NULL, worker_id VARCHAR(128) NULL, "
            "payload JSON NOT NULL, run_context JSON NULL, result JSON NULL, "
            "last_error JSON NULL, completed_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL, "
            "updated_at DATETIME(6) NOT NULL, INDEX incident_jobs_claim (status,available_at,leased_until), "
            "INDEX incident_jobs_incident (incident_id,job_id))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_job_locks ("
            "incident_id VARCHAR(128) PRIMARY KEY, job_id BIGINT NOT NULL, "
            "worker_id VARCHAR(128) NOT NULL, leased_until DATETIME(6) NOT NULL, "
            "updated_at DATETIME(6) NOT NULL, "
            "INDEX incident_job_locks_lease (leased_until))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_queue_control ("
            "control_id TINYINT PRIMARY KEY, updated_at DATETIME(6) NOT NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_workers ("
            "worker_id VARCHAR(128) PRIMARY KEY, status VARCHAR(32) NOT NULL, "
            "current_job_id BIGINT NULL, started_at DATETIME(6) NOT NULL, "
            "last_seen DATETIME(6) NOT NULL, "
            "INDEX incident_workers_liveness (status,last_seen))"
        )
        cur.execute(
            "INSERT INTO incident_queue_control (control_id,updated_at) "
            "VALUES (1,%s) ON DUPLICATE KEY UPDATE control_id=VALUES(control_id)",
            (_now(),),
        )
        _add_column_if_missing(cur, "incident_jobs", "run_context", "run_context JSON NULL")
        _add_column_if_missing(cur, "incident_jobs", "result", "result JSON NULL")
        _add_column_if_missing(
            cur,
            "incident_jobs",
            "completed_at",
            "completed_at DATETIME(6) NULL",
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_dead_letters ("
            "dead_letter_id BIGINT AUTO_INCREMENT PRIMARY KEY, job_id BIGINT NOT NULL UNIQUE, "
            "incident_id VARCHAR(128) NOT NULL, event_id BIGINT NOT NULL, kind VARCHAR(32) NOT NULL, "
            "payload JSON NOT NULL, diagnostics JSON NOT NULL, failed_at DATETIME(6) NOT NULL, "
            "replayed_at DATETIME(6) NULL)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS incident_publications ("
            "publication_key CHAR(64) PRIMARY KEY, incident_id VARCHAR(128) NOT NULL, "
            "draft_sha256 CHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, "
            "attempt_token CHAR(32) NOT NULL, issue_url TEXT NULL, diagnostics JSON NULL, "
            "created_at DATETIME(6) NOT NULL, updated_at DATETIME(6) NOT NULL, "
            "completed_at DATETIME(6) NULL, "
            "INDEX incident_publications_incident (incident_id,created_at))"
        )
        conn.commit()


def worker_runtime_status(max_age_seconds=15, minimum_workers=1):
    """Return independently observed worker liveness from durable heartbeats."""
    cutoff = _now() - timedelta(seconds=float(max_age_seconds))
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*),MAX(last_seen) FROM incident_workers "
            "WHERE status='running' AND last_seen>=%s",
            (cutoff,),
        )
        row = cur.fetchone()
        conn.commit()
    return {
        "status": (
            "ready" if int(row[0]) >= int(minimum_workers) else "unavailable"
        ),
        "active_workers": int(row[0]),
        "minimum_workers": int(minimum_workers),
        "last_seen": row[1].isoformat() if row[1] else None,
    }


def record_worker_heartbeat(worker_id, status="running", current_job_id=None):
    """Publish worker process liveness without coupling it to the API process."""
    if status not in {"running", "stopped"}:
        raise ValueError("worker status must be running or stopped")
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO incident_workers "
            "(worker_id,status,current_job_id,started_at,last_seen) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE "
            "started_at=IF(status='stopped',VALUES(started_at),started_at),"
            "status=VALUES(status),"
            "current_job_id=VALUES(current_job_id),last_seen=VALUES(last_seen),"
            "worker_id=VALUES(worker_id)",
            (worker_id, status, current_job_id, now, now),
        )
        conn.commit()
    return now.isoformat()


def readiness_check(
    require_worker=False,
    worker_max_age_seconds=15,
    minimum_workers=1,
):
    """Verify dependencies without creating or changing database state."""
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name IN (%s,%s,%s)),"
                "(SELECT COUNT(*) FROM schema_migrations WHERE migration_id=%s)",
                (
                    MYSQL_DATABASE,
                    "incident_jobs",
                    "incident_publications",
                    MYSQL_TABLE,
                    REQUIRED_RUNTIME_MIGRATION,
                ),
            )
            schema_row = cur.fetchone()
            schema_ready = bool(
                schema_row
                and int(schema_row[0]) == 3
                and int(schema_row[1]) == 1
            )
        if not schema_ready:
            return {
                "database": "ready",
                "queue": "unavailable",
                "schema": "missing",
                "worker": {
                    "status": "not_checked",
                    "active_workers": 0,
                    "last_seen": None,
                },
            }
        worker = (
            worker_runtime_status(worker_max_age_seconds, minimum_workers)
            if require_worker
            else {
                "status": "not_required",
                "active_workers": 0,
                "minimum_workers": int(minimum_workers),
                "last_seen": None,
            }
        )
        return {
            "database": "ready",
            "queue": "ready",
            "schema": "ready",
            "worker": worker,
        }
    except pymysql.MySQLError as exc:
        return {"database": "unavailable", "queue": "unavailable", "schema": "unknown", "error": str(exc)}


def operational_snapshot(worker_max_age_seconds=15):
    """Read shared queue/worker gauges for the API Prometheus scrape surface."""
    cutoff = _now() - timedelta(seconds=float(worker_max_age_seconds))
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT "
            "SUM(status='pending'),SUM(status='leased'),SUM(status='dead_letter'),"
            "COALESCE(TIMESTAMPDIFF(SECOND,MIN(CASE WHEN status='pending' "
            "THEN created_at END),UTC_TIMESTAMP(6)),0) FROM incident_jobs"
        )
        queue_row = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM incident_workers "
            "WHERE status='running' AND last_seen>=%s",
            (cutoff,),
        )
        active_workers = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM incident_job_locks")
        incident_locks = int(cur.fetchone()[0])
        cur.execute(
            "SELECT SUM(status='started'),SUM(status='uncertain'),"
            "COALESCE(TIMESTAMPDIFF(SECOND,MIN(CASE WHEN status='started' "
            "THEN created_at END),UTC_TIMESTAMP(6)),0) FROM incident_publications"
        )
        publication_row = cur.fetchone()
        conn.commit()
    return {
        "queue_pending": int(queue_row[0] or 0),
        "queue_leased": int(queue_row[1] or 0),
        "queue_dead_letter": int(queue_row[2] or 0),
        "queue_oldest_pending_seconds": max(int(queue_row[3] or 0), 0),
        "active_workers": active_workers,
        "publication_started": int(publication_row[0] or 0),
        "publication_uncertain": int(publication_row[1] or 0),
        "publication_oldest_started_seconds": max(
            int(publication_row[2] or 0),
            0,
        ),
        "incident_locks": incident_locks,
    }


def canary_job_status(job_id, incident_id):
    """Return a bounded status view with no incident payload or evidence content."""
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status,attempt_count,created_at,updated_at FROM incident_jobs "
            "WHERE job_id=%s AND incident_id=%s",
            (job_id, incident_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            "SELECT COUNT(*) FROM incident_analysis_revisions WHERE incident_id=%s",
            (incident_id,),
        )
        revisions = int(cur.fetchone()[0])
        conn.commit()
    return {
        "job_id": int(job_id),
        "incident_id": incident_id,
        "status": row[0],
        "attempt_count": int(row[1]),
        "created_at": row[2].isoformat(),
        "updated_at": row[3].isoformat(),
        "analysis_revisions": revisions,
    }


def _insert_event(cur, incident_id, idempotency_key, event_type, payload, event_time, source_time, clock_quality):
    received_at = _now()
    try:
        cur.execute(
            "INSERT INTO incident_events "
            "(incident_id,idempotency_key,event_type,event_time,source_time,received_at,clock_quality,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                incident_id,
                idempotency_key,
                event_type,
                _mysql_datetime(event_time),
                _mysql_datetime(source_time),
                received_at,
                clock_quality,
                _json(payload),
            ),
        )
        return True, cur.lastrowid, received_at
    except pymysql.err.IntegrityError:
        cur.execute("SELECT event_id, received_at FROM incident_events WHERE idempotency_key=%s", (idempotency_key,))
        row = cur.fetchone()
        return False, row[0], row[1]


def get_or_create_incident_id(alert):
    """Allocate retry-stable incident IDs atomically in shared MySQL."""
    alert = alert or {}
    supplied = str(alert.get("incident_id", ""))
    if supplied.startswith("INC-") and supplied[4:].isdigit() and len(supplied) >= 10:
        return supplied
    fingerprint = (
        alert.get("fingerprint")
        or alert.get("upstream_incident_id")
        or alert.get("alertname", "unknown")
    )
    raw_key = "|".join(
        [
            str(fingerprint),
            str(alert.get("service", "unknown")),
            str(alert.get("started_at", "unknown")),
            str(alert.get("tenant_id", "unknown")),
        ]
    )
    incident_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT incident_id FROM incident_id_map WHERE incident_key=%s",
            (incident_key,),
        )
        row = cur.fetchone()
        if row:
            conn.commit()
            return row[0]
        cur.execute(
            "SELECT next_value FROM incident_id_sequence "
            "WHERE sequence_id=1 FOR UPDATE"
        )
        sequence = cur.fetchone()
        if not sequence:
            conn.rollback()
            raise RuntimeError("incident ID sequence is not initialized")
        value = int(sequence[0])
        incident_id = f"INC-{value:06d}"
        cur.execute(
            "UPDATE incident_id_sequence SET next_value=%s WHERE sequence_id=1",
            (value + 1,),
        )
        cur.execute(
            "INSERT INTO incident_id_map (incident_key,incident_id,created_at) "
            "VALUES (%s,%s,%s)",
            (incident_key, incident_id, _now()),
        )
        conn.commit()
    return incident_id


def record_event(incident_id, idempotency_key, event_type, payload, event_time=None, source_time=None, clock_quality="unverified"):
    """Append exactly one redacted normalized event without queueing work."""
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        inserted, event_id, received_at = _insert_event(
            cur, incident_id, idempotency_key, event_type, payload, event_time, source_time, clock_quality
        )
        conn.commit()
    return {"inserted": inserted, "event_id": event_id, "received_at": received_at.isoformat()}


def _job_key(event_id, kind, salt=""):
    return hashlib.sha256(f"{kind}:{event_id}:{salt}".encode("utf-8")).hexdigest()


def _assert_queue_capacity(cur, maximum=None):
    maximum = int(MAX_PENDING_JOBS if maximum is None else maximum)
    if maximum <= 0:
        raise QueueCapacityError("analysis queue admission is disabled")
    cur.execute(
        "SELECT updated_at FROM incident_queue_control "
        "WHERE control_id=1 FOR UPDATE"
    )
    cur.fetchone()
    cur.execute(
        "SELECT COUNT(*) FROM incident_jobs WHERE status IN ('pending','leased')"
    )
    active = int(cur.fetchone()[0])
    if active >= maximum:
        raise QueueCapacityError(
            f"analysis queue capacity reached ({active}/{maximum})"
        )
    cur.execute(
        "UPDATE incident_queue_control SET updated_at=%s WHERE control_id=1",
        (_now(),),
    )


def record_event_and_enqueue(incident_id, idempotency_key, event_type, payload, event_time=None, source_time=None, clock_quality="unverified", run_context=None, max_pending_jobs=None):
    """Atomically append a new event and its durable analysis job before ACK."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        inserted, event_id, received_at = _insert_event(
            cur, incident_id, idempotency_key, event_type, payload, event_time, source_time, clock_quality
        )
        if not inserted:
            conn.commit()
            return {"inserted": False, "event_id": event_id, "queued": False, "received_at": received_at.isoformat()}
        try:
            _assert_queue_capacity(cur, max_pending_jobs)
        except QueueCapacityError:
            conn.rollback()
            raise
        key = _job_key(event_id, "analyze")
        cur.execute(
            "INSERT INTO incident_jobs "
            "(job_key,incident_id,event_id,kind,status,available_at,payload,run_context,created_at,updated_at) "
            "VALUES (%s,%s,%s,'analyze','pending',%s,%s,%s,%s,%s)",
            (key, incident_id, event_id, now, _json(payload), _json(complete_run_context(run_context)), now, now),
        )
        job_id = cur.lastrowid
        conn.commit()
    return {"inserted": True, "event_id": event_id, "job_id": job_id, "queued": True, "received_at": received_at.isoformat()}


def append_event(incident_id, idempotency_key, event_type, payload, event_time=None, source_time=None, clock_quality="unverified"):
    """Append an audit event that intentionally does not schedule analysis."""
    return record_event(
        incident_id,
        idempotency_key,
        event_type,
        payload,
        event_time=event_time,
        source_time=source_time,
        clock_quality=clock_quality,
    )


def _create_revision_once(
    incident_id,
    reason,
    expected_revision=None,
    run_context=None,
    job_id=None,
):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        # Lock one existing head row instead of a moving MAX(revision) range.
        # The latter can deadlock when multiple first revisions race in InnoDB.
        cur.execute(
            "INSERT INTO incident_revision_heads "
            "(incident_id,current_revision,updated_at) "
            "VALUES (%s,0,%s) ON DUPLICATE KEY UPDATE incident_id=VALUES(incident_id)",
            (incident_id, _now()),
        )
        cur.execute(
            "SELECT current_revision FROM incident_revision_heads "
            "WHERE incident_id=%s FOR UPDATE",
            (incident_id,),
        )
        current = cur.fetchone()[0]
        if job_id is not None:
            cur.execute(
                "SELECT incident_id,revision FROM incident_revisions "
                "WHERE job_id=%s",
                (job_id,),
            )
            existing = cur.fetchone()
            if existing:
                if existing[0] != incident_id:
                    conn.rollback()
                    raise ValueError("job revision belongs to another incident")
                conn.commit()
                return int(existing[1])
        # Backfill a head created after older revision rows without taking a
        # range lock. New writers are already serialized by the head row.
        cur.execute(
            "SELECT COALESCE(MAX(revision),0) FROM incident_revisions "
            "WHERE incident_id=%s",
            (incident_id,),
        )
        current = max(current, cur.fetchone()[0])
        if expected_revision is not None and current != expected_revision:
            conn.rollback()
            raise ValueError("stale incident revision")
        revision = current + 1
        cur.execute(
            "INSERT INTO incident_revisions "
            "(incident_id,revision,previous_revision,job_id,reason,execution_context,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                incident_id,
                revision,
                current or None,
                job_id,
                reason,
                _json(complete_run_context(run_context)),
                _now(),
            ),
        )
        cur.execute(
            "UPDATE incident_revision_heads SET current_revision=%s,updated_at=%s "
            "WHERE incident_id=%s",
            (revision, _now(), incident_id),
        )
        conn.commit()
        return revision


def create_revision(
    incident_id,
    reason,
    expected_revision=None,
    run_context=None,
    job_id=None,
):
    """Allocate one revision, retrying transient InnoDB lock conflicts."""
    for attempt in range(3):
        try:
            return _create_revision_once(
                incident_id,
                reason,
                expected_revision=expected_revision,
                run_context=run_context,
                job_id=job_id,
            )
        except pymysql.err.OperationalError as exc:
            error_code = exc.args[0] if exc.args else None
            if error_code not in {1205, 1213} or attempt == 2:
                raise
            time.sleep(0.01 * (attempt + 1))
    raise AssertionError("unreachable revision retry state")


def _canonical_evidence_items(state):
    """Build the exact redacted canonical records reviewed in one revision."""
    timeline = state.get("timeline", []) or []
    if not timeline:
        timeline = (state.get("evidence_graph", {}) or {}).get("nodes", []) or []
    items = []
    seen = {}
    for value in timeline:
        if not isinstance(value, dict) or not value.get("event_id"):
            continue
        evidence_id = str(value["event_id"])
        evidence_type = str(
            value.get("type") or value.get("evidence_type") or "observation"
        )[:64]
        connector_metadata = value.get("connector_metadata", {}) or {}
        lineage = value.get("lineage", {}) or value.get("source_lineage", {}) or {}
        sources = {
            str(source)
            for source in (lineage.get("sources", []) or [])
            if source
        }
        for source in (value.get("source"), connector_metadata.get("source")):
            if source:
                sources.add(str(source))
        if sources:
            source = sorted(sources)[0] if len(sources) == 1 else "multi_source_derived"
        else:
            source = {
                "alert": "alertmanager",
                "deploy": "deployments",
                "log_group": "log_connector",
                "metric": "metric_connector",
            }.get(evidence_type, "unknown")
        timestamp = (
            value.get("original_timestamp")
            if value.get("original_timestamp") is not None
            else value.get("timestamp")
            or value.get("time")
            or value.get("first_seen")
            or value.get("event_time")
        )
        received_at = (
            value.get("received_at")
            or connector_metadata.get("collected_at")
            or ((state.get("alert", {}) or {}).get("received_at"))
        )
        observation = redact_data({
            key: item
            for key, item in value.items()
            if key not in {
                "_dt",
                "offset",
                "is_anchor",
                "event_id",
                "evidence_id",
                "evidence_schema_version",
                "canonical_evidence_schema_version",
                "event_time",
                "received_at",
                "original_timestamp",
                "original_timezone",
                "clock_quality",
                "classification",
                "integrity_hash",
                "lineage",
                "source_lineage",
                "connector_metadata",
                "collection_revision",
                "supersedes",
            }
        })
        canonical = canonical_evidence(
            evidence_type=evidence_type,
            source=source,
            payload=observation,
            timestamp=timestamp,
            received_at=received_at,
            service=(
                value.get("service")
                or (value.get("labels", {}) or {}).get("service")
            ),
            environment=(
                value.get("environment")
                or (value.get("labels", {}) or {}).get("environment")
                or (value.get("labels", {}) or {}).get("env")
            ),
            classification="confidential",
            lineage=(connector_metadata or lineage),
            collection_revision=(
                connector_metadata.get("collection_revision")
                or value.get("collection_revision")
                or 1
            ),
            supersedes=value.get("supersedes"),
        )
        canonical["evidence_id"] = evidence_id
        if not received_at:
            canonical["received_at"] = None
            canonical["collection_time_quality"] = "missing"
        else:
            canonical["collection_time_quality"] = "recorded"
        payload = {
            **canonical,
            "payload": observation,
        }
        digest = _evidence_content_digest(payload)
        if evidence_id in seen:
            if seen[evidence_id] != digest:
                raise EvidenceIntegrityError(
                    "one analysis revision contains conflicting evidence IDs"
                )
            continue
        seen[evidence_id] = digest
        items.append({
            "evidence_id": evidence_id,
            "evidence_type": evidence_type,
            "content_sha256": digest,
            "payload": payload,
        })
    return sorted(items, key=lambda item: item["evidence_id"])


def _evidence_content_digest(payload):
    return hashlib.sha256(
        json.dumps(
            redact_data(payload),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _append_analysis_evidence(
    cur, incident_id, revision, state, now, evidence_items=None
):
    """Append immutable evidence versions and link the exact analysis snapshot."""
    for item in (
        evidence_items
        if evidence_items is not None
        else _canonical_evidence_items(state)
    ):
        cur.execute(
            "SELECT evidence_record_id,version,content_sha256 "
            "FROM incident_evidence_records WHERE incident_id=%s AND evidence_id=%s "
            "ORDER BY version DESC LIMIT 1 FOR UPDATE",
            (incident_id, item["evidence_id"]),
        )
        previous = cur.fetchone()
        if previous and previous[2] == item["content_sha256"]:
            record_id = previous[0]
        else:
            version = (previous[1] if previous else 0) + 1
            cur.execute(
                "INSERT INTO incident_evidence_records "
                "(incident_id,evidence_id,evidence_type,version,content_sha256,payload,"
                "supersedes_record_id,first_analysis_revision,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    incident_id,
                    item["evidence_id"],
                    item["evidence_type"],
                    version,
                    item["content_sha256"],
                    _json(item["payload"]),
                    previous[0] if previous else None,
                    revision,
                    now,
                ),
            )
            record_id = cur.lastrowid
        cur.execute(
            "INSERT INTO incident_analysis_evidence "
            "(incident_id,analysis_revision,evidence_id,evidence_record_id) "
            "VALUES (%s,%s,%s,%s)",
            (incident_id, revision, item["evidence_id"], record_id),
        )


def record_analysis_revision(incident_id, revision, state, event_id=None, run_context=None):
    """Persist the compact, reviewable input boundary for one analysis revision.

    This intentionally stores evidence identifiers and compact deterministic output,
    not raw logs or a full prompt.  A duplicate call is read back unchanged so a
    retried worker can never rewrite what a reviewer saw for a revision.
    """
    ensure_schema()
    graph = (state.get("evidence_graph", {}) or {})
    graph_evidence_ids = sorted({
        str(node.get("event_id"))
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("event_id")
    })
    evidence_items = _canonical_evidence_items(state)
    evidence_ids = [item["evidence_id"] for item in evidence_items]
    if graph_evidence_ids and graph_evidence_ids != evidence_ids:
        raise EvidenceIntegrityError(
            "evidence graph and canonical revision membership differ"
        )
    candidates = []
    for candidate in ((state.get("deterministic_assessment", {}) or {}).get("candidates", []) or []):
        if not isinstance(candidate, dict):
            continue
        candidates.append({
            "id": candidate.get("id"),
            "rank": candidate.get("rank"),
            "title": candidate.get("title"),
            "confidence_label": candidate.get("confidence_label"),
            "score": candidate.get("score"),
            "event_ids": [str(value) for value in candidate.get("event_ids", []) if value],
        })
    summary = {
        "schema_version": "incident-analysis-revision/v1",
        "incident_window": state.get("incident_window", {}),
        "source_status": state.get("source_status", {}),
        "data_quality": state.get("data_quality", {}),
        "interpretation_quality": state.get("interpretation_quality", {}),
        "interpretation_structured": state.get(
            "interpretation_structured", {}
        ),
        "claim_grounding": state.get("claim_grounding", {}),
        "investigation_loop": state.get("investigation_loop", {}),
        "investigation_revisions": state.get(
            "investigation_revisions", []
        ),
        "analysis_deadline": state.get("analysis_deadline", {}),
        "model_usage_ledger": state.get("model_usage_ledger", {}),
        "evidence_pack_sha256": hashlib.sha256(
            str(state.get("evidence_pack", "")).encode("utf-8")
        ).hexdigest(),
    }
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT revision FROM incident_analysis_revisions WHERE incident_id=%s "
            "AND revision=%s FOR UPDATE",
            (incident_id, revision),
        )
        if cur.fetchone():
            conn.commit()
            return get_analysis_revision(incident_id, revision)
        # The incident-revision chain is allocated before analysis and remains
        # authoritative if a later worker finishes before an earlier one.
        cur.execute(
            "SELECT previous_revision FROM incident_revisions "
            "WHERE incident_id=%s AND revision=%s",
            (incident_id, revision),
        )
        allocated = cur.fetchone()
        if allocated:
            previous_revision = allocated[0]
        else:
            cur.execute(
                "SELECT revision FROM incident_analysis_revisions "
                "WHERE incident_id=%s AND revision<%s "
                "ORDER BY revision DESC LIMIT 1 FOR UPDATE",
                (incident_id, revision),
            )
            previous = cur.fetchone()
            previous_revision = previous[0] if previous else None
        cur.execute(
            "INSERT INTO incident_analysis_revisions "
            "(incident_id,revision,previous_revision,event_id,evidence_ids,candidate_snapshot,state_summary,run_context,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                incident_id, revision, previous_revision, event_id,
                _json(evidence_ids), _json(candidates), _json(summary),
                _json(complete_run_context(run_context)), now,
            ),
        )
        _append_analysis_evidence(
            cur,
            incident_id,
            revision,
            state,
            now,
            evidence_items=evidence_items,
        )
        conn.commit()
    return get_analysis_revision(incident_id, revision)


def get_analysis_revision(incident_id, revision):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT revision,previous_revision,event_id,evidence_ids,candidate_snapshot,state_summary,run_context,created_at "
            "FROM incident_analysis_revisions WHERE incident_id=%s AND revision=%s",
            (incident_id, revision),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "incident_id": incident_id, "revision": row[0], "previous_revision": row[1], "event_id": row[2],
        "evidence_ids": _decode(row[3]), "candidates": _decode(row[4]),
        "state_summary": _decode(row[5]), "run_context": _decode(row[6]) if row[6] else {},
        "created_at": row[7].isoformat(),
    }


def list_evidence_records(incident_id, analysis_revision=None):
    """Read immutable evidence versions, optionally for one analysis revision."""
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        if analysis_revision is None:
            cur.execute(
                "SELECT evidence_record_id,evidence_id,evidence_type,version,content_sha256,"
                "payload,supersedes_record_id,first_analysis_revision,created_at "
                "FROM incident_evidence_records WHERE incident_id=%s "
                "ORDER BY evidence_id,version",
                (incident_id,),
            )
        else:
            cur.execute(
                "SELECT r.evidence_record_id,r.evidence_id,r.evidence_type,r.version,"
                "r.content_sha256,r.payload,r.supersedes_record_id,"
                "r.first_analysis_revision,r.created_at "
                "FROM incident_analysis_evidence m JOIN incident_evidence_records r "
                "ON r.evidence_record_id=m.evidence_record_id "
                "WHERE m.incident_id=%s AND m.analysis_revision=%s "
                "ORDER BY r.evidence_id",
                (incident_id, analysis_revision),
            )
        rows = cur.fetchall()
    records = []
    for row in rows:
        payload = _decode(row[5])
        envelope_valid = (
            isinstance(payload, dict)
            and payload.get("evidence_schema_version")
            == CANONICAL_EVIDENCE_SCHEMA_VERSION
            and payload.get("evidence_id") == row[1]
            and payload.get("evidence_type") == row[2]
            and isinstance(payload.get("payload"), dict)
            and payload.get("integrity_hash")
            == evidence_integrity_hash(payload.get("payload"))
        )
        records.append({
            "evidence_record_id": row[0],
            "evidence_id": row[1],
            "evidence_type": row[2],
            "version": row[3],
            "content_sha256": row[4],
            "payload": payload,
            "supersedes_record_id": row[6],
            "first_analysis_revision": row[7],
            "created_at": row[8].isoformat(),
            "integrity_valid": (
                _evidence_content_digest(payload) == row[4]
                and envelope_valid
            ),
        })
    return records


def validate_analysis_evidence(incident_id, analysis_revision):
    """Fail closed unless the exact revision membership is present and intact."""
    snapshot = get_analysis_revision(incident_id, analysis_revision)
    if not snapshot:
        raise EvidenceIntegrityError("analysis revision was not found")
    records = list_evidence_records(incident_id, analysis_revision)
    expected = set(snapshot.get("evidence_ids", []) or [])
    actual = {item["evidence_id"] for item in records}
    invalid = sorted(
        item["evidence_id"]
        for item in records
        if not item["integrity_valid"]
    )
    if expected != actual or invalid:
        raise EvidenceIntegrityError(
            "analysis evidence integrity validation failed"
        )
    return {
        "schema_version": "analysis-evidence-integrity/v1",
        "incident_id": incident_id,
        "analysis_revision": analysis_revision,
        "evidence_ids": sorted(actual),
        "passed": True,
    }


def get_analysis_revision_diff(incident_id, revision):
    """Explain evidence and candidate changes from the previous revision."""
    current = get_analysis_revision(incident_id, revision)
    if not current:
        return None
    validate_analysis_evidence(incident_id, revision)
    previous_revision = current.get("previous_revision")
    previous = (
        get_analysis_revision(incident_id, previous_revision)
        if previous_revision is not None
        else None
    )
    if previous_revision is not None and previous is not None:
        validate_analysis_evidence(incident_id, previous_revision)
    current_records = {
        item["evidence_id"]: item
        for item in list_evidence_records(incident_id, revision)
    }
    previous_records = {
        item["evidence_id"]: item
        for item in (
            list_evidence_records(incident_id, previous_revision)
            if previous_revision is not None
            else []
        )
    }
    current_ids = set(current_records)
    previous_ids = set(previous_records)
    shared_ids = current_ids & previous_ids
    changed = sorted(
        evidence_id
        for evidence_id in shared_ids
        if current_records[evidence_id]["evidence_record_id"]
        != previous_records[evidence_id]["evidence_record_id"]
    )

    def _candidate_map(snapshot):
        return {
            str(item.get("id") or item.get("rank")): item
            for item in ((snapshot or {}).get("candidates", []) or [])
            if isinstance(item, dict)
        }

    before_candidates = _candidate_map(previous)
    after_candidates = _candidate_map(current)
    candidate_changes = []
    for identifier in sorted(set(before_candidates) | set(after_candidates)):
        before = before_candidates.get(identifier)
        after = after_candidates.get(identifier)
        if before != after:
            candidate_changes.append({
                "candidate_id": identifier,
                "before": before,
                "after": after,
            })
    return {
        "schema_version": "analysis-revision-diff/v1",
        "incident_id": incident_id,
        "revision": revision,
        "previous_revision": previous_revision,
        "evidence": {
            "added": sorted(current_ids - previous_ids),
            "changed": changed,
            "removed": sorted(previous_ids - current_ids),
            "unchanged": sorted(shared_ids - set(changed)),
        },
        "candidate_changes": candidate_changes,
    }


def record_review_decision(
    incident_id,
    pending_revision,
    decision,
    reviewer_identity,
    rationale="",
    request_id=None,
    selected_hypothesis=None,
    analysis_revision=None,
    candidate_snapshot=None,
    displayed_evidence_ids=None,
    enforce_pending=False,
):
    """Append an idempotent review decision with the exact evidence snapshot."""
    if decision not in {
        "approved", "rejected", "request_more_evidence"
    }:
        raise ValueError("invalid review decision")
    if decision == "request_more_evidence" and not str(rationale).strip():
        raise ValueError("request_more_evidence requires rationale")
    snapshot = get_analysis_revision(incident_id, analysis_revision) if analysis_revision else None
    if analysis_revision is not None and decision == "approved":
        validate_analysis_evidence(incident_id, analysis_revision)
    evidence_ids = (snapshot or {}).get("evidence_ids", displayed_evidence_ids or [])
    candidates = (snapshot or {}).get("candidates", candidate_snapshot or [])
    permitted = {str(item.get("rank")) for item in candidates if isinstance(item, dict)}
    selected = str(selected_hypothesis) if selected_hypothesis is not None else None
    if decision == "approved" and (not selected or selected not in permitted):
        raise ValueError("selected hypothesis is not present in the reviewed analysis revision")
    key_material = json.dumps(
        [incident_id, pending_revision, decision, selected, reviewer_identity, rationale, request_id],
        sort_keys=True, separators=(",", ":"), default=str,
    )
    decision_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    now = _now()
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        if enforce_pending:
            cur.execute(
                "SELECT version FROM pending_reviews "
                "WHERE thread_id=%s FOR UPDATE",
                (incident_id,),
            )
            pending_row = cur.fetchone()
            if not pending_row or int(pending_row[0]) != int(pending_revision):
                conn.rollback()
                raise ValueError("stale pending-review version")
            cur.execute(
                "SELECT decision_id,decision_key,created_at "
                "FROM incident_review_decisions "
                "WHERE incident_id=%s AND pending_revision=%s "
                "ORDER BY decision_id LIMIT 1",
                (incident_id, pending_revision),
            )
            prior = cur.fetchone()
            if prior:
                if prior[1] != decision_key:
                    conn.rollback()
                    raise ValueError(
                        "pending review revision was already decided"
                    )
                conn.commit()
                return {
                    "decision_id": prior[0],
                    "incident_id": incident_id,
                    "analysis_revision": analysis_revision,
                    "pending_revision": pending_revision,
                    "decision": decision,
                    "selected_hypothesis": selected,
                    "displayed_evidence_ids": evidence_ids,
                    "created_at": prior[2].isoformat(),
                    "deduplicated": True,
                }
        cur.execute(
            "INSERT INTO incident_review_decisions "
            "(decision_key,incident_id,analysis_revision,pending_revision,reviewer_identity,decision,selected_hypothesis,displayed_evidence_ids,rationale,request_id,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE decision_key=VALUES(decision_key)",
            (decision_key, incident_id, analysis_revision, pending_revision, str(reviewer_identity)[:255], decision,
             selected, _json(evidence_ids), str(rationale)[:2000], str(request_id)[:128] if request_id else None, now),
        )
        cur.execute(
            "SELECT decision_id,created_at FROM incident_review_decisions WHERE decision_key=%s",
            (decision_key,),
        )
        row = cur.fetchone()
        conn.commit()
    return {
        "decision_id": row[0], "incident_id": incident_id, "analysis_revision": analysis_revision,
        "pending_revision": pending_revision, "decision": decision, "selected_hypothesis": selected,
        "displayed_evidence_ids": evidence_ids, "created_at": row[1].isoformat(),
        "deduplicated": False,
    }


def record_postmortem_draft(incident_id, content, analysis_revision=None, source="generated", editor_identity=None):
    """Store immutable generated and edited draft versions before any publisher is enabled."""
    if source not in {"generated", "edited"}:
        raise ValueError("invalid draft source")
    text = str(content or "")
    if not text:
        raise ValueError("postmortem draft must not be empty")
    ensure_schema()
    now = _now()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT draft_id,version,content_sha256 FROM incident_postmortem_drafts WHERE incident_id=%s "
            "ORDER BY version DESC LIMIT 1 FOR UPDATE", (incident_id,)
        )
        previous = cur.fetchone()
        if previous and previous[2] == digest:
            conn.commit()
            return {"draft_id": previous[0], "incident_id": incident_id, "version": previous[1], "deduplicated": True}
        version = (previous[1] if previous else 0) + 1
        cur.execute(
            "INSERT INTO incident_postmortem_drafts "
            "(incident_id,analysis_revision,version,content,content_sha256,source,editor_identity,supersedes_draft_id,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (incident_id, analysis_revision, version, text, digest, source,
             str(editor_identity)[:255] if editor_identity else None, previous[0] if previous else None, now),
        )
        draft_id = cur.lastrowid
        conn.commit()
    return {"draft_id": draft_id, "incident_id": incident_id, "version": version, "deduplicated": False}


def list_postmortem_drafts(incident_id):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT draft_id,analysis_revision,version,content,content_sha256,source,editor_identity,supersedes_draft_id,created_at "
            "FROM incident_postmortem_drafts WHERE incident_id=%s ORDER BY version", (incident_id,)
        )
        rows = cur.fetchall()
    return [
        {"draft_id": row[0], "analysis_revision": row[1], "version": row[2], "content": row[3],
         "content_sha256": row[4], "source": row[5], "editor_identity": row[6],
         "supersedes_draft_id": row[7], "created_at": row[8].isoformat()}
        for row in rows
    ]


def list_events(incident_id):
    """Return the audit timeline sorted by event time while preserving arrival order."""
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT event_id,event_type,event_time,source_time,received_at,clock_quality,payload "
            "FROM incident_events WHERE incident_id=%s "
            "ORDER BY COALESCE(event_time,received_at), event_id",
            (incident_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "event_id": row[0], "event_type": row[1],
            "event_time": row[2].isoformat() if row[2] else None,
            "source_time": row[3].isoformat() if row[3] else None,
            "received_at": row[4].isoformat(), "clock_quality": row[5],
            "payload": _decode(row[6]),
        }
        for row in rows
    ]


def claim_next_job(worker_id, lease_seconds=120):
    """Lease one job and its incident so revisions cannot run concurrently."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT job_id,incident_id,event_id,kind,attempt_count,payload,run_context "
            "FROM incident_jobs WHERE "
            "(status='pending' AND available_at<=%s) OR (status='leased' AND leased_until<%s) "
            "ORDER BY job_id LIMIT 20 FOR UPDATE SKIP LOCKED",
            (now, now),
        )
        candidates = cur.fetchall()
        for row in candidates:
            cur.execute(
                "INSERT INTO incident_job_locks "
                "(incident_id,job_id,worker_id,leased_until,updated_at) "
                "VALUES (%s,0,'unowned',%s,%s) "
                "ON DUPLICATE KEY UPDATE incident_id=VALUES(incident_id)",
                (row[1], datetime(1970, 1, 1), now),
            )
            cur.execute(
                "SELECT leased_until FROM incident_job_locks "
                "WHERE incident_id=%s FOR UPDATE",
                (row[1],),
            )
            lock = cur.fetchone()
            if lock and lock[0] >= _mysql_datetime(now):
                continue
            lease_until = now + timedelta(seconds=lease_seconds)
            cur.execute(
                "UPDATE incident_job_locks SET job_id=%s,worker_id=%s,"
                "leased_until=%s,updated_at=%s WHERE incident_id=%s",
                (row[0], worker_id, lease_until, now, row[1]),
            )
            cur.execute(
                "UPDATE incident_jobs SET status='leased',attempt_count=attempt_count+1,worker_id=%s,"
                "leased_until=%s,updated_at=%s WHERE job_id=%s",
                (worker_id, lease_until, now, row[0]),
            )
            job = list(row)
            job[4] = int(job[4]) + 1
            conn.commit()
            return {
                "job_id": job[0], "incident_id": job[1], "event_id": job[2],
                "kind": job[3], "attempt_count": job[4],
                "payload": _decode(job[5]),
                "run_context": _decode(job[6]) if job[6] else default_run_context(),
            }
        conn.commit()
        return None


def renew_job_lease(job_id, worker_id, lease_seconds=120):
    """Atomically renew both job ownership and the per-incident lock."""
    ensure_schema()
    now = _now()
    lease_until = now + timedelta(seconds=lease_seconds)
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT incident_id FROM incident_jobs WHERE job_id=%s "
            "AND status='leased' AND worker_id=%s FOR UPDATE",
            (job_id, worker_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise ValueError("job lease is not owned by this worker")
        incident_id = row[0]
        cur.execute(
            "UPDATE incident_job_locks SET leased_until=%s,updated_at=%s "
            "WHERE incident_id=%s AND job_id=%s AND worker_id=%s",
            (lease_until, now, incident_id, job_id, worker_id),
        )
        if not cur.rowcount:
            conn.rollback()
            raise ValueError("incident lease is not owned by this worker")
        cur.execute(
            "UPDATE incident_jobs SET leased_until=%s,updated_at=%s "
            "WHERE job_id=%s AND status='leased' AND worker_id=%s",
            (lease_until, now, job_id, worker_id),
        )
        conn.commit()
    return lease_until.isoformat()


def complete_job(job_id, worker_id, result=None):
    ensure_schema()
    completed_at = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incident_jobs SET status='completed',leased_until=NULL,result=%s,"
            "completed_at=%s,updated_at=%s "
            "WHERE job_id=%s AND status='leased' AND worker_id=%s",
            (_json(redact_data(result or {})), completed_at, completed_at, job_id, worker_id),
        )
        if not cur.rowcount:
            conn.rollback()
            raise ValueError("job lease is not owned by this worker")
        cur.execute(
            "DELETE FROM incident_job_locks WHERE job_id=%s AND worker_id=%s",
            (job_id, worker_id),
        )
        conn.commit()


def fail_job(job, worker_id, error, max_attempts=3, retry_delay_seconds=30):
    """Retry transient failures; preserve exhausted jobs in a redacted dead letter."""
    ensure_schema()
    now = _now()
    diagnostics = redact_data({"error": str(error), "attempt": job["attempt_count"]})
    with _connection() as conn, conn.cursor() as cur:
        if job["attempt_count"] >= max_attempts:
            cur.execute(
                "UPDATE incident_jobs SET status='dead_letter',leased_until=NULL,last_error=%s,updated_at=%s "
                "WHERE job_id=%s AND status='leased' AND worker_id=%s",
                (_json(diagnostics), now, job["job_id"], worker_id),
            )
            updated = cur.rowcount
            if not updated:
                conn.rollback()
                raise ValueError("job lease is not owned by this worker")
            cur.execute(
                "INSERT INTO incident_dead_letters "
                "(job_id,incident_id,event_id,kind,payload,diagnostics,failed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE diagnostics=VALUES(diagnostics),failed_at=VALUES(failed_at)",
                (job["job_id"], job["incident_id"], job["event_id"], job["kind"], _json(job["payload"]), _json(diagnostics), now),
            )
            outcome = "dead_letter"
        else:
            cur.execute(
                "UPDATE incident_jobs SET status='pending',worker_id=NULL,leased_until=NULL,"
                "available_at=%s,last_error=%s,updated_at=%s WHERE job_id=%s AND status='leased' AND worker_id=%s",
                (now + timedelta(seconds=retry_delay_seconds), _json(diagnostics), now, job["job_id"], worker_id),
            )
            updated = cur.rowcount
            outcome = "retry"
        if not updated:
            conn.rollback()
            raise ValueError("job lease is not owned by this worker")
        cur.execute(
            "DELETE FROM incident_job_locks WHERE job_id=%s AND worker_id=%s",
            (job["job_id"], worker_id),
        )
        conn.commit()
    return outcome


def list_dead_letters(incident_id=None):
    ensure_schema()
    with _connection() as conn, conn.cursor() as cur:
        if incident_id:
            cur.execute("SELECT job_id,incident_id,event_id,kind,payload,diagnostics,failed_at FROM incident_dead_letters WHERE incident_id=%s", (incident_id,))
        else:
            cur.execute("SELECT job_id,incident_id,event_id,kind,payload,diagnostics,failed_at FROM incident_dead_letters ORDER BY failed_at DESC")
        rows = cur.fetchall()
    return [
        {"job_id": row[0], "incident_id": row[1], "event_id": row[2], "kind": row[3], "payload": _decode(row[4]), "diagnostics": _decode(row[5]), "failed_at": row[6].isoformat()}
        for row in rows
    ]


def replay_dead_letter(job_id, run_context=None, max_pending_jobs=None):
    """Create a new analysis job from dead-letter payload without external side effects."""
    ensure_schema()
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT incident_id,event_id,payload FROM incident_dead_letters WHERE job_id=%s FOR UPDATE", (job_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("dead-letter job not found")
        key = _job_key(row[1], "reprocess", str(job_id))
        cur.execute("SELECT job_id FROM incident_jobs WHERE job_key=%s", (key,))
        existing = cur.fetchone()
        if not existing:
            _assert_queue_capacity(cur, max_pending_jobs)
        cur.execute(
            "INSERT INTO incident_jobs (job_key,incident_id,event_id,kind,status,available_at,payload,run_context,created_at,updated_at) "
            "VALUES (%s,%s,%s,'reprocess','pending',%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at)",
            (key, row[0], row[1], now, row[2], _json(complete_run_context(run_context)), now, now),
        )
        cur.execute("UPDATE incident_dead_letters SET replayed_at=%s WHERE job_id=%s", (now, job_id))
        conn.commit()
    return {"incident_id": row[0], "event_id": row[1], "replayed": True}


def enqueue_reprocessing(incident_id, run_context=None, max_pending_jobs=None):
    """Queue the latest stored normalized event for a versioned analysis-only rerun."""
    ensure_schema()
    context = complete_run_context(run_context)
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT event_id,payload FROM incident_events WHERE incident_id=%s "
            "ORDER BY event_id DESC LIMIT 1",
            (incident_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("incident has no stored event")
        salt = json.dumps(context, sort_keys=True, separators=(",", ":"))
        key = _job_key(row[0], "reprocess", salt)
        cur.execute("SELECT job_id FROM incident_jobs WHERE job_key=%s", (key,))
        existing = cur.fetchone()
        if not existing:
            _assert_queue_capacity(cur, max_pending_jobs)
        cur.execute(
            "INSERT INTO incident_jobs (job_key,incident_id,event_id,kind,status,available_at,payload,run_context,created_at,updated_at) "
            "VALUES (%s,%s,%s,'reprocess','pending',%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE updated_at=VALUES(updated_at)",
            (key, incident_id, row[0], now, row[1], _json(context), now, now),
        )
        job_id = int(existing[0]) if existing else cur.lastrowid
        conn.commit()
    return {"incident_id": incident_id, "event_id": row[0], "job_id": job_id, "run_context": context}


def begin_publication(incident_id, draft):
    """Claim one external publication key without ever auto-retrying ambiguity."""
    ensure_schema()
    draft_sha256 = hashlib.sha256(str(draft).encode("utf-8")).hexdigest()
    publication_key = hashlib.sha256(
        f"{incident_id}:{draft_sha256}".encode("utf-8")
    ).hexdigest()
    attempt_token = uuid.uuid4().hex
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO incident_publications "
            "(publication_key,incident_id,draft_sha256,status,attempt_token,created_at,updated_at) "
            "VALUES (%s,%s,%s,'started',%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE publication_key=publication_key",
            (
                publication_key,
                incident_id,
                draft_sha256,
                attempt_token,
                now,
                now,
            ),
        )
        inserted = cur.rowcount == 1
        if inserted:
            conn.commit()
            return {
                "publication_key": publication_key,
                "attempt_token": attempt_token,
                "status": "started",
                "deduplicated": False,
            }
        cur.execute(
            "SELECT status,issue_url FROM incident_publications "
            "WHERE publication_key=%s FOR UPDATE",
            (publication_key,),
        )
        status, issue_url = cur.fetchone()
        conn.commit()
    if status == "completed":
        return {
            "publication_key": publication_key,
            "attempt_token": None,
            "status": "completed",
            "issue_url": issue_url or "",
            "deduplicated": True,
        }
    raise PublicationStateUncertainError(
        "a previous publication attempt is incomplete or uncertain; "
        "reconcile providers before any manual retry"
    )


def complete_publication(publication_key, attempt_token, issue_url=None):
    now = _now()
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incident_publications SET status='completed',issue_url=%s,"
            "completed_at=%s,updated_at=%s WHERE publication_key=%s "
            "AND status='started' AND attempt_token=%s",
            (issue_url, now, now, publication_key, attempt_token),
        )
        if not cur.rowcount:
            conn.rollback()
            raise PublicationStateUncertainError(
                "publication claim is no longer owned by this attempt"
            )
        conn.commit()


def mark_publication_uncertain(publication_key, attempt_token, error):
    diagnostics = redact_data({"error": str(error)})
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE incident_publications SET status='uncertain',diagnostics=%s,"
            "updated_at=%s WHERE publication_key=%s AND status='started' "
            "AND attempt_token=%s",
            (_json(diagnostics), _now(), publication_key, attempt_token),
        )
        conn.commit()
