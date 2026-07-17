"""Label-held-out evaluation helpers for the full LogHub HDFS_v1 corpus."""

from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re

from clients.loki_client import representative_sample
from evaluation.hadoop_scorecard import summarize_record_signals


HDFS_V1_ADAPTER_VERSION = "hdfs-v1-adapter/v1"

_EVENT_ID = re.compile(r"E\d+")


def _stable_key(value):
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:16]


def load_templates(path):
    """Load the small public event-template dictionary."""
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            str(row.get("EventId", "")).strip():
            str(row.get("EventTemplate", "")).strip()
            for row in csv.DictReader(handle)
            if row.get("EventId")
        }


def load_anomaly_labels(path):
    """Load ground truth for evaluator use only."""
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            str(row.get("BlockId", "")).strip():
            str(row.get("Label", "")).strip().lower()
            for row in csv.DictReader(handle)
            if row.get("BlockId")
        }


def parse_event_sequence(value):
    return _EVENT_ID.findall(str(value or ""))


def _trace_artifact(row):
    """Build label-free trace features before any ground-truth join."""
    sequence = parse_event_sequence(
        row.get("Features")
    )
    return {
        "trace_key": _stable_key(
            row.get("BlockId")
        ),
        "source_block_id": str(
            row.get("BlockId", "")
        ).strip(),
        "events": sequence,
        "event_count": len(sequence),
        "unique_event_count": len(
            set(sequence)
        ),
        "first_event":
        sequence[0] if sequence else None,
        "last_event":
        sequence[-1] if sequence else None,
    }


def _trace_records(artifact, templates):
    start = datetime(
        2008, 1, 1, tzinfo=timezone.utc
    )
    records = []
    for index, event_id in enumerate(
        artifact["events"]
    ):
        template = templates.get(
            event_id,
            "Unknown HDFS event",
        )
        records.append({
            "timestamp": (
                start
                + timedelta(seconds=index)
            ).isoformat(),
            "message": (
                template.replace(
                    "[*]", "[VALUE]"
                )
            ),
            "labels": {
                "service": "hdfs",
                "level": (
                    "error"
                    if re.search(
                        r"(?i)(exception|"
                        r"failed|unexpected error|"
                        r"timed out)",
                        template,
                    )
                    else "info"
                ),
                "event_name": event_id,
                "source_dataset":
                "loghub_hdfs_v1",
            },
            "connector_metadata": {
                "source_dataset":
                "loghub_hdfs_v1",
                "trace_key":
                artifact["trace_key"],
                "sequence_offset": index,
            },
        })
    return records


def _selected_insert(selected, truth, artifact, limit):
    bucket = selected.setdefault(
        truth, []
    )
    bucket.append(artifact)
    bucket.sort(
        key=lambda item: item["trace_key"]
    )
    if len(bucket) > limit:
        del bucket[limit:]


def _evaluate_selected(
    selected,
    templates,
    sample_limit,
):
    by_truth = {}
    all_cases = []
    for truth, artifacts in sorted(
        selected.items()
    ):
        summary = Counter()
        type_recall_total = 0.0
        for artifact in artifacts:
            records = _trace_records(
                artifact,
                templates,
            )
            sampled = representative_sample(
                records,
                sample_limit,
            )
            raw_ids = {
                record["labels"]["event_name"]
                for record in records
            }
            sampled_ids = {
                record["labels"]["event_name"]
                for record in sampled
            }
            raw_signals = (
                summarize_record_signals(
                    records
                )
            )
            sample_signals = (
                summarize_record_signals(
                    sampled
                )
            )
            raw_signal_shapes = {
                (
                    match["signal_family"],
                    match["status"],
                )
                for match in raw_signals[
                    "matches"
                ]
            }
            sample_signal_shapes = {
                (
                    match["signal_family"],
                    match["status"],
                )
                for match in sample_signals[
                    "matches"
                ]
            }
            first_retained = (
                not records
                or records[0] in sampled
            )
            last_retained = (
                not records
                or records[-1] in sampled
            )
            signal_shapes_retained = (
                raw_signal_shapes
                <= sample_signal_shapes
            )
            recall = (
                len(
                    raw_ids & sampled_ids
                )
                / len(raw_ids)
                if raw_ids
                else 1.0
            )
            type_recall_total += recall
            summary["cases"] += 1
            summary[
                "source_events"
            ] += len(records)
            summary[
                "sampled_events"
            ] += len(sampled)
            summary[
                "first_event_retained"
            ] += int(first_retained)
            summary[
                "last_event_retained"
            ] += int(last_retained)
            summary[
                "signal_shapes_retained"
            ] += int(
                signal_shapes_retained
            )
            all_cases.append({
                "trace_key":
                artifact["trace_key"],
                "truth": truth,
                "source_events":
                len(records),
                "sampled_events":
                len(sampled),
                "source_event_types":
                len(raw_ids),
                "sampled_event_types":
                len(sampled_ids),
                "event_type_recall":
                round(recall, 4),
                "first_event_retained":
                first_retained,
                "last_event_retained":
                last_retained,
                "raw_signal_shapes":
                sorted(raw_signal_shapes),
                "sample_signal_shapes":
                sorted(
                    sample_signal_shapes
                ),
                "signal_shapes_retained":
                signal_shapes_retained,
                "truth_exposed_to_sampler":
                False,
            })
        count = summary["cases"]
        by_truth[truth] = {
            **dict(summary),
            "mean_event_type_recall":
            round(
                type_recall_total / count,
                4,
            )
            if count
            else 0.0,
        }
    return by_truth, all_cases


def evaluate_hdfs_v1(
    root,
    cases_per_truth=250,
    sample_limit=20,
):
    """Evaluate sequence sampling; join anomaly truth after trace features."""
    preprocessed = os.path.join(
        root, "preprocessed"
    )
    templates = load_templates(
        os.path.join(
            preprocessed,
            "HDFS.log_templates.csv",
        )
    )
    truth_by_block = load_anomaly_labels(
        os.path.join(
            preprocessed,
            "anomaly_label.csv",
        )
    )
    counts = Counter()
    source_outcomes = Counter()
    selected = {}
    missing_truth = 0
    inconsistent_source_outcome = 0
    empty_sequences = 0
    traces_path = os.path.join(
        preprocessed,
        "Event_traces.csv",
    )
    with open(
        traces_path,
        newline="",
        encoding="utf-8",
    ) as handle:
        for row in csv.DictReader(handle):
            artifact = _trace_artifact(
                row
            )
            # The source Label column is never included in the artifact.
            source_outcome = str(
                row.get("Label", "")
            ).strip().lower()
            source_outcomes[
                source_outcome
            ] += 1
            truth = truth_by_block.get(
                artifact["source_block_id"]
            )
            if truth is None:
                missing_truth += 1
                continue
            counts[truth] += 1
            expected_source = (
                "fail"
                if truth == "anomaly"
                else "success"
            )
            if (
                source_outcome
                != expected_source
            ):
                inconsistent_source_outcome += 1
            if not artifact["events"]:
                empty_sequences += 1
            _selected_insert(
                selected,
                truth,
                artifact,
                cases_per_truth,
            )

    by_truth, cases = _evaluate_selected(
        selected,
        templates,
        sample_limit,
    )
    selected_total = len(cases)
    boundary_gate = all(
        case["first_event_retained"]
        and case["last_event_retained"]
        for case in cases
    )
    signal_gate = all(
        case["signal_shapes_retained"]
        for case in cases
    )
    join_gate = (
        missing_truth == 0
        and sum(counts.values())
        == len(truth_by_block)
        and inconsistent_source_outcome
        == 0
    )
    return {
        "evaluation":
        "hdfs_v1_sequence_sampling",
        "adapter_version":
        HDFS_V1_ADAPTER_VERSION,
        "dataset":
        "loghub_hdfs_v1",
        "source_trace_rows":
        sum(source_outcomes.values()),
        "ground_truth_rows":
        len(truth_by_block),
        "truth_counts":
        dict(sorted(counts.items())),
        "source_outcome_counts":
        dict(
            sorted(source_outcomes.items())
        ),
        "template_count": len(templates),
        "empty_sequences":
        empty_sequences,
        "missing_truth_rows":
        missing_truth,
        "inconsistent_source_outcomes":
        inconsistent_source_outcome,
        "evaluation_cases":
        selected_total,
        "cases_per_truth_limit":
        cases_per_truth,
        "sample_limit_per_trace":
        sample_limit,
        "by_truth": by_truth,
        "gates": {
            "truth_join_complete":
            join_gate,
            "boundary_retention":
            boundary_gate,
            "observable_signal_shape_retention":
            signal_gate,
        },
        "quality_gate_passed":
        join_gate
        and boundary_gate
        and signal_gate,
        "truth_isolation": {
            "trace_artifacts_built_before_truth_join":
            True,
            "truth_exposed_to_sampler":
            False,
            "labels_used_only_for_evaluation_selection_and_scoring":
            True,
        },
        "scope": (
            "large-corpus trace parsing and representative-sampling "
            "robustness; anomaly labels do not identify root cause"
        ),
        "cases": cases,
    }
