"""Versioned canonical evidence records and timestamp quality checks."""

from datetime import datetime, timedelta, timezone
import hashlib
import json

from utils.redaction import redact_data


CANONICAL_EVIDENCE_SCHEMA_VERSION = "incident-evidence/v1"
_FUTURE_TOLERANCE = timedelta(minutes=5)


def _iso_utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_timestamp(value, *, received_at=None):
    """Normalize a source timestamp while retaining provenance and quality.

    Invalid or implausibly future values are retained as original data but are
    not used as canonical event time.  This lets a reviewer see the problem
    without allowing bad clocks to reorder an incident timeline.
    """
    received = received_at or datetime.now(timezone.utc)
    if isinstance(received, str):
        received = datetime.fromisoformat(received.replace("Z", "+00:00"))
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    original = None if value is None else str(value)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        return {
            "event_time": None,
            "original_timestamp": original,
            "original_timezone": None,
            "clock_quality": "invalid" if original else "missing",
        }
    original_timezone = (
        "Z" if original and original.endswith("Z")
        else str(parsed.tzinfo) if parsed.tzinfo else "naive"
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
        quality = "assumed_utc"
    else:
        quality = "verified"
    if parsed > received + _FUTURE_TOLERANCE:
        quality = "future"
        event_time = None
    else:
        event_time = _iso_utc(parsed)
    return {
        "event_time": event_time,
        "original_timestamp": original,
        "original_timezone": original_timezone,
        "clock_quality": quality,
    }


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def integrity_hash(payload):
    return "sha256:" + hashlib.sha256(
        _canonical_json(redact_data(payload)).encode("utf-8")
    ).hexdigest()


def stable_evidence_id(evidence_type, source, payload):
    """Derive an ID from redacted immutable content, never collection time."""
    digest = hashlib.sha256(
        _canonical_json({
            "type": evidence_type,
            "source": source,
            "payload": redact_data(payload),
        }).encode("utf-8")
    ).hexdigest()[:20]
    return f"evd-{evidence_type}-{digest}"


def canonical_evidence(
    *,
    evidence_type,
    source,
    payload,
    timestamp=None,
    received_at=None,
    service=None,
    environment=None,
    classification="operational",
    lineage=None,
    collection_revision=1,
    supersedes=None,
):
    """Build the common evidence record used across alerts and telemetry."""
    received = received_at or datetime.now(timezone.utc)
    if isinstance(received, str):
        received = datetime.fromisoformat(received.replace("Z", "+00:00"))
    if received.tzinfo is None:
        received = received.replace(tzinfo=timezone.utc)
    safe_payload = redact_data(payload)
    timestamp_data = normalize_timestamp(timestamp, received_at=received)
    record = {
        "evidence_schema_version": CANONICAL_EVIDENCE_SCHEMA_VERSION,
        "evidence_id": stable_evidence_id(evidence_type, source, safe_payload),
        "evidence_type": str(evidence_type),
        "source": str(source),
        "lineage": redact_data(lineage or {}),
        "collection_revision": max(int(collection_revision or 1), 1),
        "event_time": timestamp_data["event_time"],
        "received_at": _iso_utc(received),
        "original_timestamp": timestamp_data["original_timestamp"],
        "original_timezone": timestamp_data["original_timezone"],
        "clock_quality": timestamp_data["clock_quality"],
        "service": service or "unknown",
        "environment": environment or "unknown",
        "classification": str(classification),
        "supersedes": supersedes,
        "integrity_hash": integrity_hash(safe_payload),
    }
    return record
