"""Privacy-minimized parser and honest OpenStack anomaly evaluation."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import os
import re

from clients.loki_client import (
    HIGH_SIGNAL_PATTERN,
    representative_sample,
)
from evaluation.hadoop_scorecard import summarize_record_signals
from graph.nodes.aggregate_by_labels import (
    _fingerprint,
)


OPENSTACK_ADAPTER_VERSION = (
    "openstack-adapter/v1"
)

_LINE = re.compile(
    r"^(?P<source>\S+) "
    r"(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+) "
    r"(?P<pid>\d+) "
    r"(?P<level>TRACE|DEBUG|INFO|AUDIT|WARNING|ERROR|CRITICAL) "
    r"(?P<component>\S+) "
    r"(?P<message>.*)$"
)
_INSTANCE = re.compile(
    r"\[instance: ([0-9a-f-]{36})\]",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\[(req-[0-9a-f-]{36})\b",
    re.IGNORECASE,
)
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_IP = re.compile(
    r"(?<![\d.])(?:\d{1,3}\.){3}"
    r"\d{1,3}(?![\d.])"
)


def _key(prefix, value):
    digest = hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _sanitize_message(value):
    text = _UUID.sub(
        "[UUID]", str(value or "")
    )
    return _IP.sub("[IP]", text)


def load_anomaly_instance_keys(path):
    """Return pseudonymous evaluator truth keys."""
    keys = set()
    with open(
        path, encoding="utf-8"
    ) as handle:
        for line in handle:
            value = line.strip()
            if _UUID.fullmatch(value):
                keys.add(
                    _key("instance", value)
                )
    return keys


def parse_openstack_file(path):
    """Parse primary lines and attach rare continuation lines."""
    records = []
    physical_lines = 0
    primary_lines = 0
    attached_continuations = 0
    orphan_lines = 0
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for raw_line in handle:
            physical_lines += 1
            line = raw_line.rstrip("\n")
            match = _LINE.match(line)
            if not match:
                if records:
                    records[-1]["message"] += (
                        "\n"
                        + _sanitize_message(
                            line
                        )
                    )
                    attached_continuations += 1
                else:
                    orphan_lines += 1
                continue
            primary_lines += 1
            message = match.group(
                "message"
            )
            instance = _INSTANCE.search(
                message
            )
            request = _REQUEST.search(
                message
            )
            timestamp = datetime.fromisoformat(
                match.group("date")
                + "T"
                + match.group("time")
            ).replace(
                tzinfo=timezone.utc
            ).isoformat()
            source = match.group(
                "source"
            )
            service = source.split(
                ".", 1
            )[0]
            instance_key = (
                _key(
                    "instance",
                    instance.group(1),
                )
                if instance
                else None
            )
            request_key = (
                _key(
                    "request",
                    request.group(1),
                )
                if request
                else None
            )
            records.append({
                "timestamp": timestamp,
                "message":
                _sanitize_message(message),
                "labels": {
                    "service": service,
                    "level":
                    match.group(
                        "level"
                    ).lower(),
                    "request_id":
                    request_key,
                    "source_component":
                    match.group(
                        "component"
                    ),
                    "source_dataset":
                    "loghub_openstack",
                },
                "entity_key":
                instance_key,
                "connector_metadata": {
                    "source_dataset":
                    "loghub_openstack",
                    "source_file":
                    os.path.basename(path),
                    "entity_key":
                    instance_key,
                },
            })
    return records, {
        "physical_lines":
        physical_lines,
        "primary_records":
        primary_lines,
        "attached_continuations":
        attached_continuations,
        "orphan_lines": orphan_lines,
    }


def _high_signal_shapes(records):
    return {
        _fingerprint(
            record.get("message")
        )
        for record in records
        if (
            str(
                record.get(
                    "labels", {}
                ).get("level", "")
            ).lower()
            in {
                "warn",
                "warning",
                "error",
                "critical",
                "fatal",
            }
            or re.search(
                HIGH_SIGNAL_PATTERN,
                str(
                    record.get(
                        "message", ""
                    )
                ),
            )
        )
    }


def _file_summary(
    path,
    sample_limit,
):
    records, parsing = (
        parse_openstack_file(path)
    )
    sampled = representative_sample(
        records, sample_limit
    )
    levels = Counter(
        str(
            record["labels"].get(
                "level", "unknown"
            )
        )
        for record in records
    )
    sample_levels = Counter(
        str(
            record["labels"].get(
                "level", "unknown"
            )
        )
        for record in sampled
    )
    raw_shapes = _high_signal_shapes(
        records
    )
    sample_shapes = _high_signal_shapes(
        sampled
    )
    minimized = all(
        not _UUID.search(
            record["message"]
        )
        and not _IP.search(
            record["message"]
        )
        and not any(
            _UUID.search(str(value or ""))
            for value in record[
                "labels"
            ].values()
        )
        for record in records
    )
    critical_retained = (
        levels.get("critical", 0) == 0
        or sample_levels.get(
            "critical", 0
        ) > 0
    )
    error_retained = (
        levels.get("error", 0) == 0
        or sample_levels.get(
            "error", 0
        ) > 0
    )
    return records, {
        "file": os.path.basename(path),
        **parsing,
        "source_records": len(records),
        "sampled_records":
        len(sampled),
        "source_levels":
        dict(sorted(levels.items())),
        "sample_levels":
        dict(
            sorted(sample_levels.items())
        ),
        "entity_count": len({
            record["entity_key"]
            for record in records
            if record["entity_key"]
        }),
        "request_count": len({
            record["labels"].get(
                "request_id"
            )
            for record in records
            if record["labels"].get(
                "request_id"
            )
        }),
        "high_signal_shapes":
        len(raw_shapes),
        "sampled_high_signal_shapes":
        len(sample_shapes),
        "high_signal_shape_recall":
        round(
            len(
                raw_shapes
                & sample_shapes
            )
            / len(raw_shapes),
            4,
        )
        if raw_shapes
        else 1.0,
        "critical_level_retained":
        critical_retained,
        "error_level_retained":
        error_retained,
        "dataset_specific_minimization":
        minimized,
        "all_continuations_accounted_for":
        (
            parsing[
                "primary_records"
            ]
            + parsing[
                "attached_continuations"
            ]
            + parsing["orphan_lines"]
            == parsing["physical_lines"]
        ),
    }


def _entity_sequence_signature(records):
    ordered = sorted(
        records,
        key=lambda record: (
            record.get("timestamp", ""),
            record.get("message", ""),
        ),
    )
    return tuple(
        _fingerprint(
            record.get("message")
        )
        for record in ordered
    )


def evaluate_openstack(
    root,
    file_sample_limit=1000,
    entity_sample_limit=200,
):
    """Evaluate parsing and anomaly evidence without treating labels as RCA."""
    paths = [
        os.path.join(
            root,
            "openstack_abnormal.log",
        ),
        os.path.join(
            root,
            "openstack_normal1.log",
        ),
        os.path.join(
            root,
            "openstack_normal2.log",
        ),
    ]
    records_by_file = {}
    file_reports = []
    for path in paths:
        records, report = _file_summary(
            path,
            file_sample_limit,
        )
        records_by_file[
            os.path.basename(path)
        ] = records
        file_reports.append(report)

    abnormal_records = records_by_file[
        "openstack_abnormal.log"
    ]
    by_entity = defaultdict(list)
    for record in abnormal_records:
        if record["entity_key"]:
            by_entity[
                record["entity_key"]
            ].append(record)

    # Ground truth is joined only after parsing, minimization and grouping.
    truth_keys = (
        load_anomaly_instance_keys(
            os.path.join(
                root,
                "anomaly_labels.txt",
            )
        )
    )
    signature_counts = Counter(
        _entity_sequence_signature(
            records
        )
        for records in by_entity.values()
    )
    anomaly_cases = []
    for entity_key in sorted(
        truth_keys
    ):
        records = by_entity.get(
            entity_key, []
        )
        sampled = representative_sample(
            records,
            entity_sample_limit,
        )
        raw_signals = (
            summarize_record_signals(
                records
            )
        )
        sampled_signals = (
            summarize_record_signals(
                sampled
            )
        )
        raw_shapes = {
            (
                match["signal_family"],
                match["status"],
            )
            for match in raw_signals[
                "matches"
            ]
        }
        sampled_shapes = {
            (
                match["signal_family"],
                match["status"],
            )
            for match in sampled_signals[
                "matches"
            ]
        }
        signature = (
            _entity_sequence_signature(
                records
            )
        )
        anomaly_cases.append({
            "entity_key": entity_key,
            "source_events":
            len(records),
            "sampled_events":
            len(sampled),
            "levels": dict(
                sorted(
                    Counter(
                        record[
                            "labels"
                        ].get(
                            "level",
                            "unknown",
                        )
                        for record
                        in records
                    ).items()
                )
            ),
            "raw_signal_shapes":
            sorted(raw_shapes),
            "sampled_signal_shapes":
            sorted(sampled_shapes),
            "signal_shapes_retained":
            raw_shapes
            <= sampled_shapes,
            "sequence_signature_shared_by_entities":
            signature_counts[
                signature
            ],
            "anomaly_directly_recoverable":
            bool(raw_shapes),
            "truth_exposed_to_parser_or_sampler":
            False,
        })

    parser_gate = all(
        report[
            "all_continuations_accounted_for"
        ]
        and report[
            "dataset_specific_minimization"
        ]
        for report in file_reports
    )
    severity_gate = all(
        report[
            "critical_level_retained"
        ]
        and report[
            "error_level_retained"
        ]
        for report in file_reports
    )
    anomaly_entity_gate = all(
        case["source_events"] > 0
        for case in anomaly_cases
    )
    signal_gate = all(
        case[
            "signal_shapes_retained"
        ]
        for case in anomaly_cases
    )
    directly_recoverable = sum(
        int(
            case[
                "anomaly_directly_recoverable"
            ]
        )
        for case in anomaly_cases
    )
    return {
        "evaluation":
        "openstack_parser_sampling",
        "adapter_version":
        OPENSTACK_ADAPTER_VERSION,
        "dataset":
        "loghub_openstack",
        "file_sample_limit":
        file_sample_limit,
        "entity_sample_limit":
        entity_sample_limit,
        "files": file_reports,
        "anomaly_truth_entities":
        len(truth_keys),
        "anomaly_entities_found":
        sum(
            int(case["source_events"] > 0)
            for case in anomaly_cases
        ),
        "anomaly_entities_with_catalog_signal":
        directly_recoverable,
        "anomaly_observable_coverage":
        round(
            directly_recoverable
            / len(anomaly_cases),
            4,
        )
        if anomaly_cases
        else 0.0,
        "anomaly_cases":
        anomaly_cases,
        "gates": {
            "parser_and_minimization":
            parser_gate,
            "severity_class_retention":
            severity_gate,
            "truth_entities_joined":
            anomaly_entity_gate,
            "observable_signal_shape_retention":
            signal_gate,
        },
        "quality_gate_passed":
        parser_gate
        and severity_gate
        and anomaly_entity_gate
        and signal_gate,
        "truth_isolation": {
            "records_parsed_and_grouped_before_truth_join":
            True,
            "truth_exposed_to_parser_or_sampler":
            False,
        },
        "scope": (
            "raw parser, privacy minimization, entity grouping and "
            "representative-sampling robustness; injected-anomaly labels "
            "do not identify root cause"
        ),
        "data_limit": (
            "A labeled anomalous entity is not automatically observable "
            "as a cataloged failure signal; the evaluator reports this "
            "as limited evidence rather than inventing an explanation."
        ),
    }
