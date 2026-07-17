"""Adapters and honest quality metrics for approved public log corpora."""

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import ipaddress
import re

from clients.loki_client import representative_sample
from graph.nodes.aggregate_by_labels import (
    _fingerprint,
    aggregate_by_labels,
)
from graph.nodes.normalize_logs import normalize_logs


_IPV4_CANDIDATE = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"
)
_BLOCK_ID = re.compile(r"\bblk_-?\d+\b")
_USER_PATH = re.compile(r"/user/[^/\s,]+")
_SPARK_LINE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}) "
    r"(?P<level>[A-Za-z]+) "
    r"(?P<component>[^:]+): "
    r"(?P<content>.*)$"
)
_SPARK_UNTIMED_EXCEPTION = re.compile(
    r'^Exception in thread "[^"]+" '
    r"(?:java\.lang\.Error:\s*)?"
    r"(?P<content>.*)$"
)
_SPARK_BARE_UNTIMED_EXCEPTION = re.compile(
    r"^(?:[A-Za-z_][\w$]*\.)*"
    r"[A-Za-z_][\w$]*(?:Exception|Error):\s*"
    r"(?P<content>.*)$"
)
_UUID = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"(?![0-9a-fA-F])"
)
_SPARK_APPLICATION_ID = re.compile(
    r"\bapplication_\d+_\d+\b"
)
_SPARK_HOST = re.compile(
    r"\bmesos-slave-\d+\b",
    re.IGNORECASE,
)
_SPARK_USERCACHE = re.compile(
    r"(?<=/usercache/)[^/\s]+"
)
_SPARK_HDFS_USER_ROOT = re.compile(
    r"(?P<authority>hdfs://(?:\[IP\]|[^/\s:]+)"
    r"(?::\d+)?)/[^/\s]+"
)
_SPARK_ACL_SET = re.compile(
    r"Set\([^)]*\)"
)
_SPARK_ACL_VALUE = re.compile(
    r"(?P<prefix>Changing (?:view|modify) acls to: ).*$",
    re.IGNORECASE,
)


def sanitize_public_message(value):
    """Apply dataset-specific minimization before pipeline processing."""
    text = str(value or "")

    def replace_ip(match):
        candidate = match.group(0)
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return candidate
        return "[IP]"

    text = _IPV4_CANDIDATE.sub(
        replace_ip,
        text,
    )
    text = _BLOCK_ID.sub(
        "blk_[ID]",
        text,
    )
    return _USER_PATH.sub(
        "/user/[USER]",
        text,
    )


def sanitize_spark_message(value):
    """Minimize Spark runtime identifiers before inference or grouping."""
    text = sanitize_public_message(value)
    text = _UUID.sub("[UUID]", text)
    text = _SPARK_APPLICATION_ID.sub(
        "application_[ID]",
        text,
    )
    text = _SPARK_HOST.sub(
        "mesos-slave-[ID]",
        text,
    )
    text = _SPARK_USERCACHE.sub(
        "[USER]",
        text,
    )
    text = _SPARK_HDFS_USER_ROOT.sub(
        lambda match: match.group("authority") + "/[USER]",
        text,
    )
    text = _SPARK_ACL_SET.sub(
        "Set([USER_SET])",
        text,
    )
    return _SPARK_ACL_VALUE.sub(
        lambda match: match.group("prefix") + "[USER_SET]",
        text,
    )


def _hdfs_timestamp(date_value, time_value):
    parsed = datetime.strptime(
        (
            str(date_value).strip()
            + str(time_value).strip().zfill(6)
        ),
        "%y%m%d%H%M%S",
    )
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _spark_timestamp(date_value, time_value):
    parsed = datetime.strptime(
        str(date_value).strip()
        + str(time_value).strip(),
        "%y/%m/%d%H:%M:%S",
    )
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _spark_record(
    *,
    line_id,
    date_value,
    time_value,
    level,
    component,
    content,
    source,
):
    return {
        "timestamp": _spark_timestamp(
            date_value,
            time_value,
        ),
        "message": sanitize_spark_message(
            content
        ),
        "labels": {
            "service": "spark",
            "level": str(
                level or "info"
            ).lower(),
            "source_component": str(
                component or ""
            ),
            "source_dataset":
            "loghub_spark_2k",
        },
        "connector_metadata": {
            "source": source,
            "source_dataset":
            "loghub_spark_2k",
            "source_line_id": str(
                line_id
            ),
            "timestamp_quality":
            "timezone_assumed_utc",
            "timestamp_ordering_scope":
            "source_relative",
        },
    }


def load_loghub_spark_csv(path):
    """Load Spark records while keeping EventId out of pipeline records."""
    records = []
    source_rows = []
    with open(
        path,
        newline="",
        encoding="utf-8",
    ) as handle:
        for row in csv.DictReader(handle):
            record = _spark_record(
                line_id=row.get(
                    "LineId", len(records) + 1
                ),
                date_value=row.get("Date", ""),
                time_value=row.get("Time", ""),
                level=row.get("Level", "INFO"),
                component=row.get(
                    "Component", ""
                ),
                content=row.get("Content", ""),
                source="loghub_structured_csv",
            )
            records.append(record)
            source_rows.append({
                "event_id": str(
                    row.get("EventId", "")
                ).strip(),
                "message": record["message"],
            })
    return records, source_rows


def parse_loghub_spark_raw(path):
    """Parse the raw Spark sample without using structured source labels."""
    records = []
    unparsed = []
    previous_timestamp = None
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(
            handle, 1
        ):
            match = _SPARK_LINE.match(
                raw_line.rstrip("\n")
            )
            if not match:
                exception = _SPARK_UNTIMED_EXCEPTION.match(
                    raw_line.rstrip("\n")
                )
                if exception is None:
                    exception = _SPARK_BARE_UNTIMED_EXCEPTION.match(
                        raw_line.rstrip("\n")
                    )
                if exception and previous_timestamp:
                    records.append({
                        "timestamp": previous_timestamp,
                        "message": sanitize_spark_message(
                            exception.group("content")
                        ),
                        "labels": {
                            "service": "spark",
                            "level": "error",
                            "source_component":
                            "unattributed_exception",
                            "source_dataset":
                            "loghub_spark_2k",
                        },
                        "connector_metadata": {
                            "source": "loghub_raw_text",
                            "source_dataset":
                            "loghub_spark_2k",
                            "source_line_id": str(
                                line_number
                            ),
                            "timestamp_quality":
                            "inferred_from_previous_event",
                            "timestamp_ordering_scope":
                            "source_relative",
                        },
                    })
                    continue
                unparsed.append({
                    "source_line_id": str(
                        line_number
                    ),
                    "text": raw_line.rstrip(
                        "\n"
                    )[:300],
                })
                continue
            record = _spark_record(
                line_id=line_number,
                date_value=match.group("date"),
                time_value=match.group("time"),
                level=match.group("level"),
                component=match.group(
                    "component"
                ),
                content=match.group("content"),
                source="loghub_raw_text",
            )
            records.append(record)
            previous_timestamp = record["timestamp"]
    return records, unparsed


def spark_record_signature(record):
    """Return fields that must agree between raw and structured adapters."""
    labels = record.get("labels", {}) or {}
    return (
        record.get("timestamp"),
        record.get("message"),
        labels.get("level"),
        labels.get("source_component"),
    )


def load_loghub_hdfs_csv(path):
    """Load LogHub HDFS rows without using source templates as model input."""
    records = []
    source_rows = []
    with open(
        path,
        newline="",
        encoding="utf-8",
    ) as handle:
        for row in csv.DictReader(handle):
            content = sanitize_public_message(
                row.get("Content", "")
            )
            event_id = str(
                row.get("EventId", "")
            ).strip()
            record = {
                "timestamp": _hdfs_timestamp(
                    row.get("Date", ""),
                    row.get("Time", ""),
                ),
                "message": content,
                "labels": {
                    "service": "hdfs",
                    "level": str(
                        row.get("Level", "info")
                    ).lower(),
                    # Component is useful provenance, but the current canonical
                    # schema deliberately ignores it during grouping.
                    "source_component": row.get(
                        "Component", ""
                    ),
                    "source_dataset":
                    "loghub_hdfs_2k",
                },
                "connector_metadata": {
                    "source_dataset":
                    "loghub_hdfs_2k",
                    "source_line_id": row.get(
                        "LineId"
                    ),
                },
            }
            records.append(record)
            source_rows.append({
                "event_id": event_id,
                "message": content,
            })
    return records, source_rows


def _grouping_quality(source_rows):
    inferred = defaultdict(Counter)
    fingerprints_by_event = defaultdict(
        set
    )
    for row in source_rows:
        fingerprint = _fingerprint(
            row["message"]
        )
        inferred[fingerprint][
            row["event_id"]
        ] += 1
        fingerprints_by_event[
            row["event_id"]
        ].add(fingerprint)
    total = sum(
        sum(counts.values())
        for counts in inferred.values()
    )
    dominant = sum(
        max(counts.values())
        for counts in inferred.values()
        if counts
    )
    collisions = sum(
        1
        for counts in inferred.values()
        if len(counts) > 1
    )
    fragmentation = sorted(
        len(values)
        for values in (
            fingerprints_by_event.values()
        )
    )
    return {
        "inferred_group_count": len(
            inferred
        ),
        "source_event_id_count": len({
            row["event_id"]
            for row in source_rows
        }),
        "weighted_event_id_purity": (
            round(dominant / total, 4)
            if total
            else 0.0
        ),
        "cross_event_collision_groups":
        collisions,
        "mean_fingerprints_per_source_event":
        (
            round(
                sum(fragmentation)
                / len(fragmentation),
                2,
            )
            if fragmentation
            else 0.0
        ),
        "max_fingerprints_per_source_event":
        (
            max(fragmentation)
            if fragmentation
            else 0
        ),
    }


def _pipeline_groups(records):
    state = {
        "logs": records,
        "log_query": {
            "total_count": len(records),
            "count_is_exact": True,
            "fetched_count": len(records),
            "sample_limit": len(records),
            "possibly_truncated": False,
            "sampling_strategy":
            "complete_public_fixture",
        },
    }
    state.update(normalize_logs(state))
    state.update(aggregate_by_labels(state))
    return state["log_groups"]


def evaluate_loghub_hdfs(
    path,
    sample_limit=200,
):
    records, source_rows = (
        load_loghub_hdfs_csv(path)
    )
    sampled = representative_sample(
        records,
        sample_limit,
    )
    forward_groups = _pipeline_groups(
        sampled
    )
    reverse_groups = _pipeline_groups(
        list(reversed(sampled))
    )

    def signature(groups):
        return sorted(
            (
                group.get(
                    "labels", {}
                ).get(
                    "event_signature", ""
                ),
                group.get("count", 0),
                group.get("first_seen"),
                group.get("last_seen"),
            )
            for group in groups
        )

    timestamps_valid = all(
        record.get("timestamp", "").endswith(
            "+00:00"
        )
        for record in records
    )
    minimized = all(
        not _IPV4_CANDIDATE.search(
            record["message"]
        )
        and not re.search(
            r"\bblk_-?\d+\b",
            record["message"],
        )
        and not re.search(
            r"/user/(?!\[USER\])"
            r"[^/\s,]+",
            record["message"],
        )
        for record in records
    )
    quality = _grouping_quality(
        source_rows
    )
    source_levels = Counter(
        str(
            record.get(
                "labels", {}
            ).get("level", "unknown")
        )
        for record in records
    )
    sampled_levels = Counter(
        str(
            record.get(
                "labels", {}
            ).get("level", "unknown")
        )
        for record in sampled
    )
    thresholds = {
        "minimum_weighted_event_id_purity":
        0.98,
        "maximum_cross_event_collision_groups":
        0,
        "maximum_mean_fingerprints_per_source_event":
        2.0,
    }
    order_invariant = (
        signature(forward_groups)
        == signature(reverse_groups)
    )
    quality_gate = (
        timestamps_valid
        and minimized
        and order_invariant
        and quality[
            "weighted_event_id_purity"
        ] >= thresholds[
            "minimum_weighted_event_id_purity"
        ]
        and quality[
            "cross_event_collision_groups"
        ] <= thresholds[
            "maximum_cross_event_collision_groups"
        ]
        and quality[
            "mean_fingerprints_per_source_event"
        ] <= thresholds[
            "maximum_mean_fingerprints_per_source_event"
        ]
    )
    return {
        "dataset": "loghub_hdfs_2k",
        "source_rows": len(records),
        "sample_limit": sample_limit,
        "sampled_rows": len(sampled),
        "pipeline_group_count": len(
            forward_groups
        ),
        "source_level_counts": dict(
            sorted(source_levels.items())
        ),
        "sample_level_counts": dict(
            sorted(sampled_levels.items())
        ),
        "timestamps_valid_utc": (
            timestamps_valid
        ),
        "dataset_specific_minimization":
        minimized,
        "order_invariant_groups":
        order_invariant,
        **quality,
        "quality_thresholds": thresholds,
        "quality_gate_passed":
        quality_gate,
        "scope": (
            "parser/timestamp/sampling/"
            "aggregation robustness only"
        ),
    }
