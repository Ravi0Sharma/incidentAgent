from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import re

from utils.code_map import (
    decode as decode_codes,
    decorate as decorate_msg
)

from utils.suppressions import (
    filter_groups
)

from utils.pivots import (
    extract_all as extract_pivots
)

from utils.log_store import (
    put_logs
)
from utils.signal_catalog import (
    detect_signals,
)


AGGREGATION_KEYS = (
    "service",
    "level",
    "error_type",
    "event_name",
    "status_code",
    "event_signature",
)

DIMENSION_KEYS = (
    "route",
    "dependency",
    "region",
    "pod",
    "host",
    "status_code",
    "workload_id",
    "execution_id",
)


def _fingerprint(message):

    text = str(message or "").lower()
    protected = {}

    def protect(match, label):
        if len(protected) >= 26:
            return match.group(0)
        token = (
            "__semanticcode"
            + chr(ord("a") + len(protected))
            + "__"
        )
        protected[token] = (
            f"{label}={match.group(1)}"
        )
        return token

    semantic_patterns = (
        (
            r"\bsqlstate\s*[\[\(:= ]\s*"
            r"([0-9a-z]{5})\]?",
            "sqlstate",
        ),
        (
            r"\b(?:http(?:\s+status)?|status(?:_code)?)"
            r"[=:\s]+([1-5][0-9]{2})\b",
            "http_status",
        ),
        (
            r"\b(?:errno|error_code)"
            r"[=:\s\[]+([0-9a-z_-]{2,16})\]?",
            "error_code",
        ),
    )
    for pattern, label in semantic_patterns:
        text = re.sub(
            pattern,
            lambda match, name=label: protect(
                match, name
            ),
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(
        r"trace[_-]?id[=:\s\"]+"
        r"[a-z0-9-]+",
        "trace_id=?",
        text
    )
    text = re.sub(
        r"(?:req(?:uest)?[_-]?id|x-request-id)"
        r"[=:\s\"]+[a-z0-9-]+",
        "request_id=?",
        text
    )
    text = re.sub(
        r"user[_-]?id[=:\s\"]+"
        r"[a-z0-9-]+",
        "user_id=?",
        text
    )
    text = re.sub(
        r"^\[(?:req-\[uuid\]|-)[^\]]*\]\s*",
        "[request_context] ",
        text,
    )
    text = re.sub(
        r"\b(peer|host|node|pod|instance|container)"
        r"(?:[_-]?id)?[=:]+[a-z0-9._-]+",
        lambda match: match.group(1) + "=?",
        text,
    )
    text = re.sub(
        r"\b0x[0-9a-f]+\b",
        "<hex>",
        text,
    )
    # Embedded human timestamps are volatile payload values, not event
    # semantics. The outer canonical timestamp remains the evidence time.
    text = re.sub(
        r"\b(?:mon|tue|wed|thu|fri|sat|sun)\s+"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+"
        r"\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4}\b",
        "<timestamp>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?=[0-9a-f]{7,40}\b)"
        r"(?=[0-9a-f]*[a-f])[0-9a-f]+\b",
        "<hex>",
        text
    )
    # A measurement is volatile even when its rendered unit changes with
    # magnitude (for example 900 B versus 5.2 KB). Preserve surrounding
    # semantics while treating the measured value and display unit as one
    # placeholder.
    text = re.sub(
        r"(?<![a-z0-9])[-+]?"
        r"\d+(?:\.\d+)?\s*"
        r"(?:bytes?|[kmgt]?i?b|"
        r"milliseconds?|ms|seconds?|secs?)\b",
        "<measure>",
        text,
    )
    text = re.sub(
        # Volatile numbers often live inside path or task tokens
        # (subdir51, task_000742), where word boundaries do not match.
        # Semantic codes were protected above and are restored afterwards.
        r"[-+]?\d+(?:\.\d+)?",
        "<num>",
        text
    )
    # A variable-length list of already-minimized object IDs should represent
    # one event shape, not one group per list length.
    text = re.sub(
        r"(?:blk_\[(?:id|ID)\]"
        r"(?:\s+|$))+",
        "blk_[id] ",
        text,
    )
    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()
    for token, value in protected.items():
        text = text.replace(
            token, value
        )

    if len(text) <= 180:
        return text
    # Preserve the exception/status tail when a long wrapper or stack prefix
    # would otherwise make materially different failures indistinguishable.
    return text[:120] + " … " + text[-56:]


def _parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace(
                    "Z", "+00:00"
                )
            )
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    return parsed.astimezone(
        timezone.utc
    )


def _timestamp_text(value):
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    return parsed.isoformat().replace(
        "+00:00", "Z"
    )


def _bucket(timestamp):
    parsed = _parse_timestamp(
        timestamp
    )
    if parsed is None:
        return "unknown"
    return parsed.replace(
        second=0,
        microsecond=0,
    ).isoformat().replace(
        "+00:00", "Z"
    )


def _event_id(key):
    raw = "|".join(str(value) for value in key)
    return "log-" + hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:12]


def _dimension_summary(values):
    out = {}
    for name, counts in values.items():
        ordered = sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if ordered:
            out[name] = {
                "unique": len(ordered),
                "top": [
                    {"value": value, "count": count}
                    for value, count in ordered[:5]
                ],
            }
    return out


def _burst_summary(group, peak_bucket):
    first = group.get("_first_seen_dt")
    last = group.get("_last_seen_dt")
    duration = None
    if first is not None and last is not None:
        duration = max(
            (last - first).total_seconds(),
            0.0,
        )
    return {
        "schema_version": "event-burst/v1",
        "onset": group.get("first_seen"),
        "end": group.get("last_seen"),
        "duration_seconds": (
            round(duration, 3)
            if duration is not None
            else None
        ),
        "repetitions": group.get("count", 0),
        "distinct_time_buckets": len(
            group.get("bucket_counts", {})
        ),
        "peak_bucket": peak_bucket,
        "peak_count": (
            group.get(
                "bucket_counts", {}
            ).get(peak_bucket, 0)
            if peak_bucket is not None
            else 0
        ),
        "collapsed_repetition": (
            group.get("count", 0) > 1
        ),
    }


def aggregate_by_labels(state):

    raw_logs = state["logs"]
    put_logs(
        state.get("incident_id"),
        raw_logs
    )

    groups = defaultdict(
        lambda: {
            "count": 0,
            "example_message": None,
            "first_seen": None,
            "last_seen": None,
            "_first_seen_dt": None,
            "_last_seen_dt": None,
            "bucket_counts": defaultdict(int),
            "bucket_examples": {},
            "source_query_ids": set(),
            "source_schema_ids": set(),
            "connector_versions": set(),
            "clock_qualities": set(),
            "source_timestamp_qualities":
            set(),
            "timestamp_ordering_scopes":
            set(),
            "source_datasets": set(),
            "operation_features": [],
            "dimension_values": {
                name: defaultdict(int)
                for name in DIMENSION_KEYS
            },
        }
    )

    for log in raw_logs:

        labels = log.get("labels", {})
        message = log.get("message")

        signature = (
            labels.get("error_fingerprint")
            or _fingerprint(message)
        )
        key_values = {
            "service":
            labels.get("service", ""),
            "level":
            labels.get("level", ""),
            "error_type":
            labels.get("error_type", ""),
            "event_name":
            labels.get("event_name", ""),
            "status_code":
            labels.get("status_code", ""),
            "event_signature": signature,
        }

        key = tuple(
            key_values[k]
            for k in AGGREGATION_KEYS
        )

        g = groups[key]
        g["count"] += 1
        lineage = log.get(
            "lineage", {}
        ) or {}
        if lineage.get("query_id"):
            g[
                "source_query_ids"
            ].add(
                str(
                    lineage["query_id"]
                )
            )
        if lineage.get(
            "source_schema_id"
        ):
            g[
                "source_schema_ids"
            ].add(
                str(
                    lineage[
                        "source_schema_id"
                    ]
                )
            )
        if lineage.get(
            "connector_version"
        ):
            g[
                "connector_versions"
            ].add(
                str(
                    lineage[
                        "connector_version"
                    ]
                )
            )
        if log.get("clock_quality"):
            g["clock_qualities"].add(
                str(
                    log[
                        "clock_quality"
                    ]
                )
            )
        if log.get(
            "source_timestamp_quality"
        ):
            g[
                "source_timestamp_qualities"
            ].add(
                str(
                    log[
                        "source_timestamp_quality"
                    ]
                )
            )
        if log.get(
            "timestamp_ordering_scope"
        ):
            g[
                "timestamp_ordering_scopes"
            ].add(
                str(
                    log[
                        "timestamp_ordering_scope"
                    ]
                )
            )
        if log.get("source_dataset"):
            g["source_datasets"].add(
                str(
                    log[
                        "source_dataset"
                    ]
                )
            )

        ts = _timestamp_text(
            log.get("timestamp")
        )
        ts_dt = _parse_timestamp(ts)

        if (
            ts_dt is not None
            and (
                g["_first_seen_dt"] is None
                or ts_dt
                < g["_first_seen_dt"]
            )
        ):
            g["first_seen"] = ts
            g["_first_seen_dt"] = ts_dt
            g["first_sample"] = {
                "timestamp": ts,
                "message": message,
            }

        if (
            ts_dt is not None
            and (
                g["_last_seen_dt"] is None
                or ts_dt
                > g["_last_seen_dt"]
            )
        ):
            g["last_seen"] = ts
            g["_last_seen_dt"] = ts_dt
            g["last_sample"] = {
                "timestamp": ts,
                "message": message,
            }

        bucket = _bucket(ts)
        g["bucket_counts"][bucket] += 1
        g["bucket_examples"].setdefault(
            bucket,
            {"timestamp": ts, "message": message},
        )

        for dimension in DIMENSION_KEYS:
            value = labels.get(dimension)
            if value not in (None, ""):
                g["dimension_values"][dimension][str(value)] += 1

        if g["example_message"] is None:
            g["example_message"] = (
                message
            )

        samples = g.setdefault(
            "sample_messages", []
        )
        if (
            message
            and message not in samples
            and len(samples) < 3
        ):
            samples.append(message)

        operation_feature = log.get(
            "operation_feature"
        )
        if (
            operation_feature
            and operation_feature
            not in g["operation_features"]
        ):
            g["operation_features"].append(
                operation_feature
            )

    result = []

    for key, g in groups.items():

        msg = g["example_message"]
        code_hits = decode_codes(msg)

        peak_bucket = max(
            g["bucket_counts"],
            key=g["bucket_counts"].get,
            default=None,
        )
        time_buckets = [
            {"bucket": bucket, "count": count}
            for bucket, count in sorted(
                g["bucket_counts"].items()
            )
        ]
        group = {
            "labels": dict(
                zip(
                    AGGREGATION_KEYS,
                    key
                )
            ),
            "count": g["count"],
            "first_seen":
            g["first_seen"],
            "last_seen":
            g["last_seen"],
            "example_message": msg,
            "sample_messages":
            g.get("sample_messages", []),
            "example_message_decoded":
            decorate_msg(msg),
            "decoded_codes":
            code_hits,
            "time_buckets": time_buckets,
            "burst": _burst_summary(
                g,
                peak_bucket,
            ),
            "dimensions": _dimension_summary(
                g["dimension_values"]
            ),
            "lineage": {
                "source_query_ids":
                sorted(
                    g[
                        "source_query_ids"
                    ]
                ),
                "source_schema_ids":
                sorted(
                    g[
                        "source_schema_ids"
                    ]
                ),
                "connector_versions":
                sorted(
                    g[
                        "connector_versions"
                    ]
                ),
            },
            "time_quality": {
                "clock_qualities":
                sorted(
                    g[
                        "clock_qualities"
                    ]
                ),
                "source_timestamp_qualities":
                sorted(
                    g[
                        "source_timestamp_qualities"
                    ]
                ),
                "ordering_scopes":
                sorted(
                    g[
                        "timestamp_ordering_scopes"
                    ]
                    or {"global"}
                ),
                "source_datasets":
                sorted(
                    g[
                        "source_datasets"
                    ]
                ),
                "globally_comparable":
                not bool(
                    g[
                        "timestamp_ordering_scopes"
                    ]
                    & {
                        "trace_only",
                        "source_relative",
                        "not_comparable",
                        "unknown",
                    }
                ),
            },
            "representative_samples": [
                sample
                for sample in (
                    g.get("first_sample"),
                    g["bucket_examples"].get(peak_bucket),
                    g.get("last_sample"),
                )
                if sample
            ],
            "operation_features":
            g["operation_features"],
        }
        group["signals"] = (
            detect_signals(group)
        )
        group["signal_families"] = sorted({
            signal[
                "signal_family"
            ]
            for signal in group["signals"]
        })
        result.append(group)

    result.sort(
        key=lambda x: x["count"],
        reverse=True
    )

    kept, suppressed = (
        filter_groups(result)
    )

    log_query = state.get("log_query", {}) or {}
    loki_status = (
        state.get(
            "source_status", {}
        )
        or {}
    ).get("loki", {}) or {}
    loki_provenance = (
        loki_status.get(
            "provenance", {}
        )
        or {}
    )
    group_counts_exact = not log_query.get(
        "possibly_truncated", False
    )

    for group in kept:
        key = tuple(
            group.get("labels", {}).get(name, "")
            for name in AGGREGATION_KEYS
        )
        group["event_id"] = _event_id(key)
        group["count_is_exact"] = group_counts_exact
        group["count_scope"] = (
            "full_window"
            if group_counts_exact
            else "fetched_log_sample"
        )

    for group in suppressed:
        key = tuple(
            group.get("labels", {}).get(name, "")
            for name in AGGREGATION_KEYS
        )
        group["event_id"] = "suppressed-" + _event_id(key)
        group["count_is_exact"] = group_counts_exact
        group["count_scope"] = (
            "full_window"
            if group_counts_exact
            else "fetched_log_sample"
        )

    pivots = extract_pivots(
        kept, top_n=15
    )
    total_count = log_query.get("total_count")
    sampled_fraction = None
    if total_count:
        sampled_fraction = round(min(len(raw_logs) / total_count, 1), 4)
    services_with_groups = {
        (group.get("labels", {}) or {}).get("service", "unknown")
        for group in kept
    }
    rare_high_signal_ids = [
        group.get("event_id")
        for group in kept
        if (
            (group.get("labels", {}) or {}).get("level")
            in {
                "error",
                "fatal",
                "warn",
                "warning",
            }
            or group.get("detections")
        )
    ]

    return {
        "logs": [],
        "raw_log_count": (
            log_query.get("total_count")
            if log_query.get("total_count") is not None
            else len(raw_logs)
        ),
        "log_groups": kept,
        "suppressed_groups":
        suppressed,
        "pivots": pivots,
        "data_quality": {
            "logs": {
                "total_count": log_query.get("total_count"),
                "count_is_exact": log_query.get(
                    "count_is_exact", False
                ),
                "fetched_count": len(raw_logs),
                "usable_count": len(
                    raw_logs
                ),
                "possibly_truncated": log_query.get(
                    "possibly_truncated", False
                ),
                "group_counts_are_exact": group_counts_exact,
                "sampling_bias": {
                    "sampled_fraction": sampled_fraction,
                    "connector_sampling_strategy": log_query.get(
                        "sampling_strategy",
                        "caller_provided",
                    ),
                    "representative_sample_policy": (
                        "bounded_signal_and_general_shape_coverage_"
                        "then_group_first_peak_last"
                    ),
                    "cross_service_representatives": sorted(services_with_groups),
                    "rare_high_signal_event_ids": rare_high_signal_ids,
                    "suppressed_group_count": len(suppressed),
                    "omitted_group_count": 0,
                },
                "window": state.get("incident_window", {}),
                "source_schema_id":
                loki_provenance.get(
                    "source_schema_id"
                ),
                "source_query_id":
                loki_provenance.get(
                    "query_id"
                ),
                "source_quality":
                loki_status.get(
                    "data_quality",
                    log_query.get(
                        "data_quality",
                        {},
                    ),
                ),
            }
        }
    }
