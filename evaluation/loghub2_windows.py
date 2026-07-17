"""Bounded, label-last windows from full LogHub 2.0 corpora."""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from itertools import islice
import re

from evaluation.distributed_log_datasets import (
    load_zookeeper_cases,
)
from evaluation.grouping_quality import (
    evaluate_grouping_rows,
)
from evaluation.public_log_dataset import (
    _SPARK_BARE_UNTIMED_EXCEPTION,
    _SPARK_LINE,
    _SPARK_UNTIMED_EXCEPTION,
    sanitize_spark_message,
    sanitize_public_message,
)
from graph.nodes.aggregate_by_labels import (
    _fingerprint,
)
from utils.redaction import redact_message


_HIGH_SIGNAL = re.compile(
    r"(?i)(?:error|exception|fatal|panic|timeout|timed\s*out|"
    r"failed|failure|lost|unreachable|disconnect|refused|"
    r"corrupt|checksum|no\s+space|read-only|killed)"
)
_LINUX_SYSLOG_LINE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<component>.+?):\s*"
    r"(?P<body>.*)$"
)


def _spark_timestamp(date_value, time_value):
    parsed = datetime.strptime(
        str(date_value) + str(time_value),
        "%y/%m/%d%H:%M:%S",
    )
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _spark_parts(raw_line):
    text = raw_line.rstrip("\r\n")
    match = _SPARK_LINE.match(text)
    if match:
        return {
            "date": match.group("date"),
            "time": match.group("time"),
            "timestamp_quality":
            "timezone_assumed_utc",
            "level": match.group("level").lower(),
            "component": match.group("component"),
            "message": match.group("content"),
            "kind": "timestamped",
        }
    exception = _SPARK_UNTIMED_EXCEPTION.match(text)
    if exception is None:
        exception = _SPARK_BARE_UNTIMED_EXCEPTION.match(text)
    if exception:
        return {
            "date": None,
            "time": None,
            "timestamp_quality":
            "inferred_from_previous_event",
            "level": "error",
            "component": "unattributed_exception",
            "message": exception.group("content"),
            "kind": "untimed_exception",
        }
    return None


def _is_signal(parts):
    return (
        parts["level"]
        in {
            "warn",
            "warning",
            "error",
            "fatal",
            "critical",
        }
        or bool(_HIGH_SIGNAL.search(parts["message"]))
    )


def _select_spark_centers(raw_path, case_limit, radius):
    candidates = {}
    stats = Counter()
    with open(
        raw_path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            stats["physical_lines"] += 1
            parts = _spark_parts(raw_line)
            if parts is None:
                stats["unparsed_lines"] += 1
                continue
            stats[parts["kind"]] += 1
            if not _is_signal(parts):
                continue
            stats["signal_lines"] += 1
            signature = _fingerprint(
                sanitize_spark_message(parts["message"])
            )
            candidate = candidates.get(signature)
            rank = hashlib.sha256(
                (
                    signature
                    + "|"
                    + str(line_number)
                ).encode("utf-8")
            ).hexdigest()
            if candidate is None or rank < candidate[0]:
                candidates[signature] = (
                    rank,
                    line_number,
                    parts["level"],
                    parts["kind"],
                )

    ranked = sorted(
        (
            rank,
            line_number,
            signature,
            level,
            kind,
        )
        for signature, (
            rank,
            line_number,
            level,
            kind,
        ) in candidates.items()
    )
    selected = []
    for rank, line_number, signature, level, kind in ranked:
        if any(
            abs(line_number - item["center_line"])
            <= radius * 2
            for item in selected
        ):
            continue
        selected.append({
            "center_line": line_number,
            "start_line": max(1, line_number - radius),
            "end_line": line_number + radius,
            "selection_fingerprint": signature,
            "selection_level": level,
            "selection_kind": kind,
            "selection_rank": rank,
        })
        if len(selected) >= case_limit:
            break
    stats["signal_fingerprints"] = len(candidates)
    stats["selected_windows"] = len(selected)
    return selected, stats


def load_spark_signal_cases(
    raw_path,
    *,
    case_limit=8,
    radius=40,
):
    """Select bounded Spark windows without consulting template labels."""
    selected, stats = _select_spark_centers(
        raw_path,
        max(int(case_limit), 1),
        max(int(radius), 0),
    )
    cases = {
        f"center-{item['center_line']}": {
            "truth": "unlabeled",
            "selection_cohort": "signal_bearing",
            "records": [],
            **item,
        }
        for item in selected
    }
    ordered_cases = sorted(
        cases.items(),
        key=lambda item: item[1]["start_line"],
    )
    case_index = 0
    previous_timestamp_parts = None
    with open(
        raw_path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            parts = _spark_parts(raw_line)
            if parts is not None and parts["kind"] == "timestamped":
                previous_timestamp_parts = (
                    parts["date"],
                    parts["time"],
                )
            while (
                case_index < len(ordered_cases)
                and line_number
                > ordered_cases[case_index][1]["end_line"]
            ):
                case_index += 1
            if case_index >= len(ordered_cases):
                break
            _, active_case = ordered_cases[case_index]
            if (
                line_number < active_case["start_line"]
                or parts is None
            ):
                continue
            timestamp_parts = (
                (parts["date"], parts["time"])
                if parts["kind"] == "timestamped"
                else previous_timestamp_parts
            )
            if timestamp_parts is None:
                stats["selected_without_timestamp"] += 1
                continue
            timestamp = _spark_timestamp(*timestamp_parts)
            record = {
                "timestamp": timestamp,
                "message": sanitize_spark_message(
                    parts["message"]
                ),
                "labels": {
                    "service": "spark",
                    "level": parts["level"],
                    "source_component": parts["component"],
                    "source_dataset": "loghub2_spark",
                },
                "connector_metadata": {
                    "source": "loghub2_raw_text",
                    "source_dataset": "loghub2_spark",
                    "source_line_id": str(line_number),
                    "timestamp_quality":
                    parts["timestamp_quality"],
                    "timestamp_ordering_scope":
                    "source_relative",
                },
            }
            active_case["records"].append(record)
            stats["selected_records"] += 1
    return cases, dict(stats)


def load_spark_explicit_window(
    raw_path,
    *,
    start_line,
    end_line,
):
    """Load one previously selected line range without rescoring the corpus."""
    start = max(int(start_line), 1)
    end = max(int(end_line), start)
    context_start = max(1, start - 1)
    records = []
    stats = Counter()
    previous_timestamp_parts = None
    with open(
        raw_path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(
            islice(handle, context_start - 1, end),
            context_start,
        ):
            parts = _spark_parts(raw_line)
            if parts is None:
                if line_number >= start:
                    stats["unparsed_lines"] += 1
                continue
            if parts["kind"] == "timestamped":
                previous_timestamp_parts = (
                    parts["date"],
                    parts["time"],
                )
            if line_number < start:
                continue
            stats[parts["kind"]] += 1
            timestamp_parts = (
                (parts["date"], parts["time"])
                if parts["kind"] == "timestamped"
                else previous_timestamp_parts
            )
            if timestamp_parts is None:
                stats["without_timestamp"] += 1
                continue
            records.append({
                "timestamp": _spark_timestamp(*timestamp_parts),
                "message": sanitize_spark_message(
                    parts["message"]
                ),
                "labels": {
                    "service": "spark",
                    "level": parts["level"],
                    "source_component": parts["component"],
                    "source_dataset": "loghub2_spark",
                },
                "connector_metadata": {
                    "source": "loghub2_raw_text",
                    "source_dataset": "loghub2_spark",
                    "source_line_id": str(line_number),
                    "timestamp_quality":
                    parts["timestamp_quality"],
                    "timestamp_ordering_scope":
                    "source_relative",
                },
            })
    stats["records"] = len(records)
    stats["start_line"] = start
    stats["end_line"] = end
    return records, dict(stats)


def _template_truth_for_lines(structured_path, line_ids):
    wanted = {str(value) for value in line_ids}
    truth = {}
    with open(
        structured_path,
        newline="",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for row in csv.DictReader(handle):
            line_id = str(row.get("LineId", ""))
            if line_id in wanted:
                truth[line_id] = str(
                    row.get("EventId", "")
                )
                if len(truth) == len(wanted):
                    break
    return truth


def evaluate_template_grouping(
    cases,
    structured_path,
    *,
    dataset,
    sample_limit=200,
):
    """Join template truth only after label-blind case selection."""
    line_ids = {
        str(
            record["connector_metadata"]["source_line_id"]
        )
        for spec in cases.values()
        for record in spec["records"]
    }
    truth = _template_truth_for_lines(
        structured_path,
        line_ids,
    )
    rows = []
    for identifier, spec in sorted(cases.items()):
        for record in spec["records"]:
            line_id = str(
                record["connector_metadata"]["source_line_id"]
            )
            if line_id in truth:
                rows.append((
                    identifier,
                    record,
                    truth[line_id],
                ))
    report = evaluate_grouping_rows(
        rows,
        dataset=dataset,
        truth_kind="loghub2_template_event_id",
        sample_limit=max(int(sample_limit), 1),
        truth_limitations=(
            "EventId is parser/template truth, not failure, incident, "
            "impact, operational equivalence, or root-cause truth."
        ),
    )
    report.update({
        "selection_used_template_truth": False,
        "template_truth_joined_after_selection": True,
        "selected_line_ids": len(line_ids),
        "matched_template_truth_rows": len(truth),
        "missing_template_truth_rows": len(line_ids) - len(truth),
    })
    return report


def load_loghub2_zookeeper_cases(
    raw_path,
    *,
    per_cohort=4,
    window_minutes=10,
):
    """Expose the existing label-free ZooKeeper window adapter by name."""
    return load_zookeeper_cases(
        raw_path,
        per_cohort=max(int(per_cohort), 1),
        window_minutes=max(int(window_minutes), 1),
    )


def load_linux_syslog_records(raw_path):
    """Parse Linux syslog while preserving its missing-year limitation."""
    records = []
    stats = Counter()
    with open(
        raw_path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(handle, 1):
            stats["physical_lines"] += 1
            match = _LINUX_SYSLOG_LINE.match(
                raw_line.rstrip("\r\n")
            )
            if match is None:
                stats["unparsed_lines"] += 1
                continue
            # LogHub's Linux source omits the year. A fixed leap year only
            # permits canonical schema parsing; not_comparable prevents this
            # evaluation fixture from being used as real incident chronology.
            timestamp = datetime.strptime(
                "2000 "
                + match.group("month")
                + " "
                + match.group("day")
                + " "
                + match.group("time"),
                "%Y %b %d %H:%M:%S",
            ).replace(tzinfo=timezone.utc).isoformat()
            records.append({
                "timestamp": timestamp,
                "message": redact_message(
                    sanitize_public_message(
                        match.group("body")
                    )
                ),
                "labels": {
                    "service": "linux_syslog",
                    "level": "unknown",
                    "source_component": match.group(
                        "component"
                    ),
                    "source_dataset": "loghub2_linux",
                },
                "connector_metadata": {
                    "source": "loghub2_raw_text",
                    "source_dataset": "loghub2_linux",
                    "source_line_id": str(line_number),
                    "timestamp_quality": "year_missing",
                    "timestamp_ordering_scope":
                    "not_comparable",
                },
            })
            stats["parsed_events"] += 1
    return records, dict(stats)
