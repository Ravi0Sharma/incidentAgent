"""Versioned, source-agnostic record quality accounting."""

from collections import Counter
from datetime import datetime, timezone
import json

from utils.evidence import (
    normalize_timestamp,
)
from utils.redaction import redact_data


SOURCE_QUALITY_VERSION = (
    "source-quality/v1"
)


def empty_quality(
    source_schema_id,
    *,
    source_error_records=0,
):
    return {
        "quality_schema_version":
        SOURCE_QUALITY_VERSION,
        "source_schema_id":
        str(source_schema_id),
        "input_records": 0,
        "usable_records": 0,
        "quarantined_records": 0,
        "parse_failure_records": 0,
        "source_error_records":
        max(
            int(
                source_error_records
                or 0
            ),
            0,
        ),
        "duplicate_records": 0,
        "missing_required_field_records": 0,
        "missing_timestamp_records": 0,
        "invalid_timestamp_records": 0,
        "unknown_schema_records": 0,
        "timestamp_quality": {},
        "first_event_time": None,
        "latest_event_time": None,
        "freshness_seconds": None,
    }


def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).replace(
                "Z", "+00:00"
            )
        )
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    return parsed.astimezone(
        timezone.utc
    )


def _timestamp(
    record,
    fields,
):
    for field in fields:
        value = record.get(field)
        if value not in (
            None, ""
        ):
            return value
    return None


def _identity(record):
    safe = {
        key: value
        for key, value
        in record.items()
        if key
        not in {
            "connector_metadata",
        }
    }
    return json.dumps(
        redact_data(safe),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def assess_records(
    records,
    *,
    source_schema_id,
    timestamp_fields=(
        "timestamp",
        "time",
    ),
    required_fields=(),
    window=None,
    quarantine_invalid_timestamp=False,
    error_field="error",
):
    """Return unique usable records plus bounded quality counters."""
    usable = []
    seen = set()
    counters = Counter()
    clock_quality = Counter()
    event_times = []
    for value in records or []:
        counters[
            "input_records"
        ] += 1
        if not isinstance(
            value, dict
        ):
            counters[
                "parse_failure_records"
            ] += 1
            counters[
                "quarantined_records"
            ] += 1
            continue
        record = dict(value)
        if (
            error_field
            and record.get(
                error_field
            )
        ):
            counters[
                "source_error_records"
            ] += 1
        missing = [
            field
            for field in required_fields
            if record.get(field)
            in (None, "")
        ]
        if missing:
            counters[
                "missing_required_field_records"
            ] += 1
            counters[
                "quarantined_records"
            ] += 1
            continue
        raw_timestamp = _timestamp(
            record,
            timestamp_fields,
        )
        quality = normalize_timestamp(
            raw_timestamp
        )
        clock_quality[
            quality["clock_quality"]
        ] += 1
        if raw_timestamp in (
            None, ""
        ):
            counters[
                "missing_timestamp_records"
            ] += 1
        elif (
            quality["event_time"]
            is None
        ):
            counters[
                "invalid_timestamp_records"
            ] += 1
        else:
            parsed = _parse(
                quality[
                    "event_time"
                ]
            )
            if parsed:
                event_times.append(
                    parsed
                )
        if (
            quarantine_invalid_timestamp
            and quality[
                "event_time"
            ]
            is None
        ):
            counters[
                "quarantined_records"
            ] += 1
            continue
        identity = _identity(
            record
        )
        if identity in seen:
            counters[
                "duplicate_records"
            ] += 1
            continue
        seen.add(identity)
        usable.append(record)
    counters[
        "usable_records"
    ] = len(usable)
    window_end = _parse(
        (window or {}).get("end")
    )
    latest = (
        max(event_times)
        if event_times
        else None
    )
    earliest = (
        min(event_times)
        if event_times
        else None
    )
    freshness = (
        max(
            (
                window_end
                - latest
            ).total_seconds(),
            0.0,
        )
        if (
            window_end
            and latest
        )
        else None
    )
    report = {
        "quality_schema_version":
        SOURCE_QUALITY_VERSION,
        "source_schema_id":
        str(source_schema_id),
        **{
            key: int(
                counters.get(
                    key, 0
                )
            )
            for key in (
                "input_records",
                "usable_records",
                "quarantined_records",
                "parse_failure_records",
                "source_error_records",
                "duplicate_records",
                "missing_required_field_records",
                "missing_timestamp_records",
                "invalid_timestamp_records",
            )
        },
        "unknown_schema_records": 0,
        "timestamp_quality":
        dict(
            sorted(
                clock_quality.items()
            )
        ),
        "first_event_time": (
            earliest.isoformat()
            if earliest
            else None
        ),
        "latest_event_time": (
            latest.isoformat()
            if latest
            else None
        ),
        "freshness_seconds": (
            round(freshness, 3)
            if freshness
            is not None
            else None
        ),
    }
    return usable, report
