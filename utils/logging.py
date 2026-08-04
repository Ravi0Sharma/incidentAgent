"""Redacted JSON application log records with a stable minimal schema."""

import json
from datetime import datetime, timezone

from settings import ENVIRONMENT, SERVICE_VERSION
from utils.redaction import redact_data


LOG_SCHEMA_VERSION = "incident-log-event/v1"


def build_log_event(
    event, *, severity="INFO", incident_id=None, revision_id=None,
    node=None, source=None, request_id=None, error_category=None, **details,
):
    return redact_data({
        "schema_version": LOG_SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": severity.upper(),
        "event": event,
        "environment": ENVIRONMENT,
        "service_version": SERVICE_VERSION,
        "incident_id": incident_id,
        "revision_id": revision_id,
        "node": node,
        "source": source,
        "request_id": request_id,
        "error_category": error_category,
        "details": details,
    })


def emit_log_event(event, **kwargs):
    record = build_log_event(event, **kwargs)
    print(json.dumps(record, sort_keys=True, default=str))
    return record
