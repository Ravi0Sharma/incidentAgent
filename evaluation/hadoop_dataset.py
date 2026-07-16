"""Offline Hadoop evaluation with failure labels held out from the pipeline."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import os
import re

from clients.loki_client import (
    representative_sample,
)
from evaluation.public_log_dataset import (
    sanitize_public_message,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.apply_detection_rules import (
    apply_detection_rules,
)
from graph.nodes.correlate import correlate
from graph.nodes.enrich_groups import (
    enrich_groups,
)
from graph.nodes.normalize_logs import (
    normalize_logs,
)
from utils.candidate_scoring import (
    score_candidates,
)
from utils.incident_features import (
    build_features,
)
from utils.incident_window import (
    build_incident_window,
)
from utils.redaction import redact_message


_LOG_PREFIX = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}),"
    r"(?P<millis>\d{3}) "
    r"(?P<level>[A-Za-z]+) "
    r"(?:\[(?P<thread>[^\]]*)\] )?"
    r"(?P<body>.*)$"
)
_DYNAMIC_ID = re.compile(
    r"\b(application|container|job|"
    r"attempt|task)_\d+(?:_\d+)+\b",
    re.IGNORECASE,
)
_GLUED_JOB_ID = re.compile(
    r"\bjob_\d+(?:_\d+)+(?=Job\b)",
    re.IGNORECASE,
)
_HADOOP_TMP_USER = re.compile(
    r"/tmp/hadoop-[^/\s,:]+",
    re.IGNORECASE,
)
_LAB_HOST = re.compile(
    r"\bmsra-sa-\d+\b",
    re.IGNORECASE,
)
_ERROR_TYPE = re.compile(
    r"\b([A-Za-z_$][\w.$]*"
    r"(?:Exception|Error))\b"
)
_HIGH_SIGNAL = re.compile(
    r"(?i)(error|exception|fatal|panic|"
    r"timeout|failed|failure|lost|"
    r"unreachable|no space left|"
    r"disk full|connection reset|"
    r"exit code|killed)"
)


def sanitize_hadoop_message(value):
    """Minimize public lab identifiers and volatile execution IDs."""
    text = sanitize_public_message(
        value
    )
    text = _HADOOP_TMP_USER.sub(
        "/tmp/hadoop-[USER]",
        text,
    )
    text = _LAB_HOST.sub(
        "[HOST]",
        text,
    )
    text = _DYNAMIC_ID.sub(
        lambda match: (
            match.group(1).lower()
            + "_[ID]"
        ),
        text,
    )
    text = _GLUED_JOB_ID.sub(
        "job_[ID]",
        text,
    )
    return redact_message(text)


def load_hadoop_labels(root):
    """Return application truth without exposing it to log records."""
    path = os.path.join(
        root,
        "abnormal_label.txt",
    )
    labels = {}
    workload = None
    outcome = None
    outcomes = {
        "Normal": "normal",
        "Machine down": "machine_down",
        "Network disconnection":
        "network_disconnection",
        "Disk full": "disk_full",
    }
    with open(
        path,
        encoding="utf-8",
    ) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line.startswith("### "):
                workload = line[4:].strip()
                outcome = None
            elif (
                line.endswith(":")
                and line[:-1] in outcomes
            ):
                outcome = outcomes[
                    line[:-1]
                ]
            elif line.startswith("+ "):
                application_id = (
                    line[2:].strip()
                )
                if workload and outcome:
                    labels[
                        application_id
                    ] = {
                        "workload":
                        workload,
                        "outcome":
                        outcome,
                    }
    return labels


def _timestamp(match):
    parsed = datetime.strptime(
        (
            match.group("date")
            + " "
            + match.group("time")
            + ","
            + match.group("millis")
        ),
        "%Y-%m-%d %H:%M:%S,%f",
    )
    # The upstream corpus does not declare a timezone. UTC is an explicit
    # normalization assumption for relative-order evaluation only.
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _scoped_identifier(kind, value):
    """Return a stable incident-local identifier without exposing source IDs."""
    digest = hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:12]
    return f"{kind}-{digest}"


def _finalize(record):
    if not record:
        return None
    record["message"] = (
        sanitize_hadoop_message(
            record["message"]
        )[:2000]
    )
    error = _ERROR_TYPE.search(
        record["message"]
    )
    if error:
        record["labels"][
            "error_type"
        ] = error.group(1)
    return record


def parse_hadoop_log_file(
    path,
    application_id,
    stats=None,
):
    """Parse timestamped events and attach Java continuation lines."""
    stats = stats if stats is not None else Counter()
    records = []
    current = None
    container_id = os.path.splitext(
        os.path.basename(path)
    )[0]
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for raw_line in handle:
            stats["physical_lines"] += 1
            line = raw_line.rstrip(
                "\r\n"
            )
            match = _LOG_PREFIX.match(
                line
            )
            if not match:
                stats[
                    "continuation_lines"
                ] += 1
                if current and line:
                    if len(
                        current["message"]
                    ) < 2000:
                        current[
                            "message"
                        ] += "\n" + line
                elif line:
                    stats[
                        "orphan_lines"
                    ] += 1
                continue
            finalized = _finalize(
                current
            )
            if finalized:
                records.append(
                    finalized
                )
            body = match.group("body")
            if ": " in body:
                component, message = (
                    body.split(": ", 1)
                )
            else:
                component = "unknown"
                message = body
            current = {
                "timestamp": _timestamp(
                    match
                ),
                "message": message,
                "labels": {
                    "service": "hadoop",
                    "level": match.group(
                        "level"
                    ).lower(),
                    "source_component":
                    component,
                    "application_id":
                    application_id,
                    "container_id":
                    container_id,
                    "workload_id":
                    _scoped_identifier(
                        "workload",
                        application_id,
                    ),
                    "execution_id":
                    _scoped_identifier(
                        "execution",
                        container_id,
                    ),
                },
                "connector_metadata": {
                    "source_dataset":
                    "loghub_hadoop",
                    "application_id":
                    application_id,
                    "container_id":
                    container_id,
                    "timestamp_timezone":
                    "assumed_utc",
                },
            }
            stats["parsed_events"] += 1
    finalized = _finalize(current)
    if finalized:
        records.append(finalized)
    return records


def load_hadoop_application(
    root,
    application_id,
):
    stats = Counter()
    records = []
    directory = os.path.join(
        root,
        application_id,
    )
    files = sorted(
        os.path.join(directory, name)
        for name in os.listdir(
            directory
        )
        if name.endswith(".log")
    )
    for path in files:
        records.extend(
            parse_hadoop_log_file(
                path,
                application_id,
                stats,
            )
        )
    stats["log_files"] = len(files)
    return records, stats


def _has_high_signal(record):
    level = str(
        record.get(
            "labels", {}
        ).get("level", "")
    ).lower()
    return (
        level in {
            "warn",
            "error",
            "fatal",
            "critical",
        }
        or bool(
            _HIGH_SIGNAL.search(
                record.get(
                    "message", ""
                )
            )
        )
    )


def _pipeline_state(
    records,
    total_count,
    service="hadoop",
    environment="public-offline-eval",
):
    last_timestamp = max(
        record["timestamp"]
        for record in records
    )
    alert = {
        "service": service,
        "started_at": last_timestamp,
        "received_at": last_timestamp,
        "labels": {
            "service": service,
            "environment":
            environment,
        },
        "annotations": {
            "summary": (
                "Offline public-log "
                "evaluation boundary"
            )
        },
    }
    state = {
        "alert": alert,
        "incident_window":
        build_incident_window(alert),
        "logs": records,
        "log_query": {
            "total_count":
            total_count,
            "count_is_exact": True,
            "fetched_count":
            len(records),
            "sample_limit":
            len(records),
            "possibly_truncated": (
                len(records)
                < total_count
            ),
            "sampling_strategy": (
                "per_application_"
                "time_stratified_"
                "with_high_signal"
            ),
        },
        "metrics": [],
        "deploys": [],
    }
    state.update(normalize_logs(state))
    state.update(
        aggregate_by_labels(state)
    )
    state.update(
        apply_detection_rules(state)
    )
    state.update(enrich_groups(state))
    state["incident_features"] = (
        build_features(state)
    )
    state.update(correlate(state))
    state[
        "deterministic_assessment"
    ] = score_candidates(state)
    return state


def _ratio(numerator, denominator):
    if not denominator:
        return 0.0
    return round(
        numerator / denominator,
        4,
    )


def evaluate_hadoop(
    root,
    sample_limit=200,
):
    truth = load_hadoop_labels(root)
    application_ids = sorted(
        name
        for name in os.listdir(root)
        if name.startswith("application_")
        and os.path.isdir(
            os.path.join(root, name)
        )
    )
    totals = Counter()
    truth_counts = Counter()
    source_levels = Counter()
    sampled_levels = Counter()
    detections_by_truth = {}
    abstentions_by_truth = Counter()
    order_invariant = 0
    apps_with_source_signal = 0
    apps_retaining_signal = 0
    predicted_abnormal = {}
    group_counts = []

    for application_id in (
        application_ids
    ):
        records, stats = (
            load_hadoop_application(
                root,
                application_id,
            )
        )
        totals.update(stats)
        totals[
            "source_events"
        ] += len(records)
        label = truth.get(
            application_id, {}
        ).get("outcome", "missing")
        truth_counts[label] += 1
        for record in records:
            source_levels[
                record["labels"][
                    "level"
                ]
            ] += 1
        source_signal = sum(
            1
            for record in records
            if _has_high_signal(record)
        )
        if source_signal:
            apps_with_source_signal += 1

        sampled = (
            representative_sample(
                records,
                sample_limit,
            )
            if records
            else []
        )
        totals["sampled_events"] += (
            len(sampled)
        )
        for record in sampled:
            sampled_levels[
                record["labels"][
                    "level"
                ]
            ] += 1
        sampled_signal = sum(
            1
            for record in sampled
            if _has_high_signal(record)
        )
        if source_signal and sampled_signal:
            apps_retaining_signal += 1
        predicted_abnormal[
            application_id
        ] = sampled_signal > 0
        if not sampled:
            continue

        forward = _pipeline_state(
            sampled,
            len(records),
        )
        reverse = _pipeline_state(
            list(reversed(sampled)),
            len(records),
        )
        forward_signature = sorted(
            (
                group.get(
                    "event_id"
                ),
                group.get("count"),
                group.get("first_seen"),
                group.get("last_seen"),
            )
            for group in forward.get(
                "log_groups", []
            )
        )
        reverse_signature = sorted(
            (
                group.get(
                    "event_id"
                ),
                group.get("count"),
                group.get("first_seen"),
                group.get("last_seen"),
            )
            for group in reverse.get(
                "log_groups", []
            )
        )
        if (
            forward_signature
            == reverse_signature
        ):
            order_invariant += 1
        group_counts.append(
            len(
                forward.get(
                    "log_groups", []
                )
            )
        )
        detection_ids = sorted({
            item.get("id")
            for item in forward.get(
                "detections", []
            )
            if item.get("id")
        })
        bucket = detections_by_truth.setdefault(
            label,
            Counter(),
        )
        bucket.update(detection_ids)
        assessment = forward.get(
            "deterministic_assessment",
            {},
        )
        if assessment.get("abstain"):
            abstentions_by_truth[
                label
            ] += 1

    missing_labels = (
        set(application_ids)
        - set(truth)
    )
    truth_without_directory = (
        set(truth)
        - set(application_ids)
    )
    tp = fp = tn = fn = 0
    for application_id in (
        application_ids
    ):
        actual_abnormal = (
            truth.get(
                application_id, {}
            ).get("outcome")
            not in {"normal", None}
        )
        predicted = (
            predicted_abnormal.get(
                application_id,
                False,
            )
        )
        if actual_abnormal and predicted:
            tp += 1
        elif actual_abnormal:
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1

    parse_rate = _ratio(
        totals["parsed_events"],
        (
            totals["parsed_events"]
            + totals["orphan_lines"]
        ),
    )
    quality_gate = (
        not missing_labels
        and not truth_without_directory
        and parse_rate >= 0.999
        and order_invariant
        == len(application_ids)
        and apps_retaining_signal
        == apps_with_source_signal
    )
    return {
        "dataset": "loghub_hadoop",
        "dataset_root":
        os.path.abspath(root),
        "applications_total":
        len(application_ids),
        "truth_counts": dict(
            sorted(truth_counts.items())
        ),
        "log_files":
        totals["log_files"],
        "physical_lines":
        totals["physical_lines"],
        "source_events":
        totals["source_events"],
        "continuation_lines":
        totals["continuation_lines"],
        "orphan_lines":
        totals["orphan_lines"],
        "event_parse_rate":
        parse_rate,
        "sample_limit_per_application":
        sample_limit,
        "sampled_events":
        totals["sampled_events"],
        "source_level_counts": dict(
            sorted(source_levels.items())
        ),
        "sample_level_counts": dict(
            sorted(sampled_levels.items())
        ),
        "applications_with_high_signal":
        apps_with_source_signal,
        "applications_retaining_high_signal":
        apps_retaining_signal,
        "order_invariant_applications":
        order_invariant,
        "missing_truth_labels": sorted(
            missing_labels
        ),
        "truth_without_directory": sorted(
            truth_without_directory
        ),
        "mean_groups_per_application": (
            round(
                sum(group_counts)
                / len(group_counts),
                2,
            )
            if group_counts
            else 0.0
        ),
        "detections_by_truth": {
            label: dict(
                sorted(counts.items())
            )
            for label, counts in sorted(
                detections_by_truth.items()
            )
        },
        "abstentions_by_truth": dict(
            sorted(
                abstentions_by_truth.items()
            )
        ),
        "high_signal_only_baseline": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
            "precision": _ratio(
                tp, tp + fp
            ),
            "recall": _ratio(
                tp, tp + fn
            ),
        },
        "truth_exposed_to_pipeline":
        False,
        "timestamp_timezone_policy":
        "assumed_utc_for_relative_order_only",
        "quality_gate_passed":
        quality_gate,
        "quality_gate_scope": (
            "parser, label coverage, "
            "sampling retention, and "
            "order invariance; not "
            "failure-classification accuracy"
        ),
    }
