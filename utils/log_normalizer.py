import os

import yaml

from utils.redaction import (
    redact_data,
    redact_message,
)
from utils.evidence import canonical_evidence


CANONICAL_LOG_SCHEMA_VERSION = "incident-log/v1"


_CONFIG_PATH = os.getenv(
    "LOG_SCHEMAS_PATH",
    os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "config",
        "log_schemas.yaml"
    )
)


def _load():

    if not os.path.exists(
        _CONFIG_PATH
    ):
        return {
            "canonical_fields": [],
            "schemas": {},
            "level_synonyms": {}
        }

    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load()


_CANONICAL = _CONFIG.get(
    "canonical_fields", []
) or []


_SCHEMAS = _CONFIG.get(
    "schemas", {}
) or {}


def _level_reverse():

    out = {}

    for canonical, aliases in (
        _CONFIG
        .get("level_synonyms", {})
        or {}
    ).items():
        for alias in aliases:
            out[alias.lower()] = (
                canonical
            )

    return out


_LEVEL_REVERSE = _level_reverse()


def _pick(labels, candidates):

    if not candidates:
        return None

    for c in candidates:

        if c in labels:
            v = labels[c]
            if v is None:
                continue
            if isinstance(v, str) and (
                not v.strip()
            ):
                continue
            return v

    return None


def _normalize_level(value):

    if not value:
        return value

    key = str(value).lower().strip()

    return _LEVEL_REVERSE.get(
        key, key
    )


def _detect_schema(labels):

    for name, schema in (
        _SCHEMAS.items()
    ):

        for _, cands in (
            schema.items()
        ):
            for c in cands:
                if c in labels:
                    return name

    return "loki_default"


def normalize_log(log):

    labels = redact_data(log.get(
        "labels", {}
    ) or {})

    schema_name = _detect_schema(
        labels
    )

    schema = _SCHEMAS.get(
        schema_name, {}
    )

    normalized = {}

    for canonical_field in (
        _CANONICAL
    ):

        candidates = schema.get(
            canonical_field, []
        )

        value = _pick(
            labels, candidates
        )

        if value is not None:
            normalized[
                canonical_field
            ] = value

    if "level" in normalized:
        normalized["level"] = (
            _normalize_level(
                normalized["level"]
            )
        )

    record = {
        "evidence_schema_version":
        CANONICAL_LOG_SCHEMA_VERSION,
        "timestamp":
        log.get("timestamp"),
        "message":
        redact_message(log.get("message", "")),
        "raw_labels": labels,
        "labels": normalized,
        "schema": schema_name
    }
    operation_feature = redact_data(
        log.get("operation_feature")
    )
    if operation_feature:
        record[
            "operation_feature"
        ] = operation_feature
    lineage = log.get(
        "connector_metadata", {}
    ) or {}
    canonical = canonical_evidence(
        evidence_type="log",
        source=lineage.get(
            "source", "loki"
        ),
        payload={
            "timestamp": record["timestamp"],
            "message": record["message"],
            "labels": record["labels"],
            "schema": record["schema"],
            "operation_feature":
            operation_feature,
        },
        timestamp=(
            log.get("original_timestamp")
            if log.get("original_timestamp") is not None
            else record["timestamp"]
        ),
        received_at=log.get("received_at"),
        service=record["labels"].get("service"),
        environment=(
            record["raw_labels"].get("environment")
            or record["raw_labels"].get("env")
        ),
        lineage=lineage,
        collection_revision=lineage.get(
            "collection_revision", 1
        ),
    )
    # All downstream ordering and bucketing use the canonical UTC event time.
    # The original source value remains available in original_timestamp.
    record["timestamp"] = canonical[
        "event_time"
    ]
    # Keep the historical log schema for existing consumers while exposing the
    # canonical evidence identity and timestamp quality for new consumers.
    return {
        **record,
        "canonical_evidence_schema_version": canonical[
            "evidence_schema_version"
        ],
        **{
            key: value
            for key, value in canonical.items()
            if key != "evidence_schema_version"
        },
        "source_timestamp_quality":
        lineage.get(
            "timestamp_quality"
        ),
        "timestamp_ordering_scope":
        lineage.get(
            "timestamp_ordering_scope",
            "global",
        ),
        "source_dataset":
        lineage.get(
            "source_dataset"
        ),
        "timestamp_source_field":
        log.get("timestamp_source_field", "timestamp"),
    }


def normalize_logs(logs):

    return [
        normalize_log(log)
        for log in logs
    ]
