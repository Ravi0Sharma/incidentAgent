"""Stable correlation of direct observations for review and LLM context."""

import hashlib
import json


OBSERVATION_PATTERN_SCHEMA_VERSION = "observation-pattern/v1"
_MAX_REFERENCES = 20
_MAX_REPRESENTATIVES = 3
_MAX_ENTITY_SAMPLES = 5


def _unique_sorted(values):
    return sorted({
        str(value)
        for value in values
        if value not in (None, "")
    })


def _pattern_id(key):
    encoded = json.dumps(
        key,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        "observation-pattern-"
        + hashlib.sha256(encoded).hexdigest()[:16]
    )


def _impact_status(observation):
    return (
        observation.get("impact_assessment", {})
        or {}
    ).get(
        "impact_status",
        observation.get(
            "impact_status",
            "not_established",
        ),
    )


def _group_service(group):
    return str(
        (
            group.get("labels", {})
            or {}
        ).get("service")
        or "unknown"
    )


def _time_quality(groups):
    qualities = []
    scopes = []
    datasets = []
    for group in groups:
        quality = group.get(
            "time_quality", {}
        ) or {}
        qualities.extend(
            quality.get(
                "source_timestamp_qualities",
                [],
            )
            or quality.get(
                "clock_qualities",
                [],
            )
        )
        scopes.extend(
            quality.get(
                "ordering_scopes", []
            )
        )
        datasets.extend(
            quality.get(
                "source_datasets", []
            )
        )
    return {
        "source_timestamp_qualities":
        _unique_sorted(qualities),
        "ordering_scopes":
        _unique_sorted(scopes),
        "source_datasets":
        _unique_sorted(datasets),
    }


def _time_span_status(time_quality):
    scopes = set(
        time_quality.get(
            "ordering_scopes", []
        )
        or ["global"]
    )
    if scopes & {
        "trace_only",
        "not_comparable",
        "unknown",
    }:
        return "not_comparable"
    if (
        "source_relative" in scopes
        and len(
            time_quality.get(
                "source_datasets", []
            )
        )
        != 1
    ):
        return "not_comparable"
    return "comparable"


def _entity_summary(observations):
    values = {}
    for observation in observations:
        for name, items in (
            observation.get("entities", {})
            or {}
        ).items():
            values.setdefault(
                str(name), set()
            ).update(
                str(item)
                for item in items or []
                if item not in (None, "")
            )
    return {
        name: {
            "unique": len(items),
            "sample": sorted(items)[
                :_MAX_ENTITY_SAMPLES
            ],
        }
        for name, items in sorted(
            values.items()
        )
    }


def _representative(group):
    labels = group.get("labels", {}) or {}
    return {
        "event_id": group.get("event_id"),
        "count": group.get("count", 0),
        "first_seen": group.get("first_seen"),
        "last_seen": group.get("last_seen"),
        "level": labels.get("level"),
        "event_name": (
            labels.get("event_name")
            or labels.get("error_type")
            or labels.get("event_signature")
        ),
        "example_message": (
            group.get(
                "example_message_decoded"
            )
            or group.get("example_message")
        ),
    }


def build_observation_patterns(
    observations,
    groups,
):
    """Compress equivalent observations without inferring cause or impact."""
    observations = observations or []
    group_by_event = {
        group.get("event_id"): group
        for group in groups or []
        if group.get("event_id")
    }
    buckets = {}
    for observation in observations:
        event_id = observation.get(
            "event_id"
        )
        group = group_by_event.get(
            event_id, {}
        )
        key = (
            _group_service(group),
            str(
                observation.get(
                    "signal_family"
                )
                or "unknown"
            ),
            str(
                observation.get("status")
                or "unknown"
            ),
            str(
                observation.get("scope")
                or "unknown"
            ),
            str(_impact_status(observation)),
            bool(
                observation.get(
                    "cause_candidate_eligible",
                    False,
                )
            ),
        )
        buckets.setdefault(
            key, []
        ).append(observation)

    patterns = []
    for key, bucket in buckets.items():
        (
            service,
            family,
            status,
            scope,
            impact_status,
            candidate_eligible,
        ) = key
        event_ids = _unique_sorted(
            item.get("event_id")
            for item in bucket
        )
        observation_ids = _unique_sorted(
            item.get("observation_id")
            for item in bucket
        )
        pattern_groups = [
            group_by_event[event_id]
            for event_id in event_ids
            if event_id in group_by_event
        ]
        group_counts = {
            str(group.get("event_id")):
            int(group.get("count", 0) or 0)
            for group in pattern_groups
        }
        representatives = sorted(
            pattern_groups,
            key=lambda group: (
                -int(
                    group.get(
                        "count", 0
                    )
                    or 0
                ),
                str(
                    group.get(
                        "event_id", ""
                    )
                ),
            ),
        )[:_MAX_REPRESENTATIVES]
        first_seen = _unique_sorted(
            item.get("first_seen")
            for item in bucket
        )
        last_seen = _unique_sorted(
            item.get("last_seen")
            for item in bucket
        )
        time_quality = _time_quality(
            pattern_groups
        )
        time_span_status = (
            _time_span_status(time_quality)
        )
        patterns.append({
            "schema_version":
            OBSERVATION_PATTERN_SCHEMA_VERSION,
            "pattern_id": _pattern_id(
                key
            ),
            "service": service,
            "signal_family": family,
            "status": status,
            "scope": scope,
            "impact_status": impact_status,
            "cause_candidate_eligible":
            candidate_eligible,
            "causal_status":
            "not_established",
            "correlation_method":
            "same_incident_service_family_status_scope_impact",
            "event_group_count":
            len(event_ids),
            "occurrence_count": sum(
                group_counts.values()
            ),
            "first_seen": (
                first_seen[0]
                if (
                    first_seen
                    and time_span_status
                    == "comparable"
                )
                else None
            ),
            "last_seen": (
                last_seen[-1]
                if (
                    last_seen
                    and time_span_status
                    == "comparable"
                )
                else None
            ),
            "time_span_status":
            time_span_status,
            "event_ids":
            event_ids[:_MAX_REFERENCES],
            "omitted_event_group_count":
            max(
                0,
                len(event_ids)
                - _MAX_REFERENCES,
            ),
            "observation_ids":
            observation_ids[
                :_MAX_REFERENCES
            ],
            "omitted_observation_count":
            max(
                0,
                len(observation_ids)
                - _MAX_REFERENCES,
            ),
            "entities":
            _entity_summary(bucket),
            "time_quality":
            time_quality,
            "representative_evidence": [
                _representative(group)
                for group in representatives
            ],
        })

    return sorted(
        patterns,
        key=lambda item: (
            not item[
                "cause_candidate_eligible"
            ],
            item["impact_status"]
            != "established",
            item["signal_family"]
            == "unclassified_error",
            -item["occurrence_count"],
            item["pattern_id"],
        ),
    )
