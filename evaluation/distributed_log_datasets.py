"""Label-held-out adapters for local HDFS_v1 and OpenStack corpora."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import heapq
import os
import re

from clients.loki_client import representative_sample
from evaluation.hadoop_dataset import _pipeline_state
from evaluation.impact_contract import assess_impact_contract
from evaluation.hadoop_scorecard import summarize_record_signals
from evaluation.public_log_dataset import sanitize_public_message
from utils.evidence_pack import build_evidence_pack
from utils.html_report import render_review
from utils.interpretation_contract import (
    deterministic_payload,
    render_grounded_interpretation,
    validate_and_ground,
)
from utils.operation_duration import (
    build_peer_duration_features,
)
from utils.redaction import redact_message


_HDFS_LINE = re.compile(
    r"^(?P<date>\d{6}) (?P<time>\d{6}) "
    r"(?P<pid>\d+) (?P<level>[A-Za-z]+) "
    r"(?P<component>[^:]+): (?P<body>.*)$"
)
_BLOCK_ID = re.compile(r"\bblk_-?\d+\b")
_OPENSTACK_LINE = re.compile(
    r"^(?P<source>\S+) "
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2}\.\d+) "
    r"(?P<pid>\d+) (?P<level>[A-Za-z]+) "
    r"(?P<component>\S+) (?P<body>.*)$"
)
_INSTANCE_ID = re.compile(
    r"\[instance:\s*"
    r"(?P<id>[0-9a-fA-F-]{36})\]"
)
_UUID = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}(?![0-9a-fA-F])"
)
_HEX_ID = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}"
    r"(?![0-9a-fA-F])"
)
_ZOOKEEPER_LINE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2},\d{3}) - "
    r"(?P<level>[A-Za-z]+)\s+"
    # Thread names can contain nested brackets and colons, for example
    # QuorumPeer[myid=1]/0:0:0:0:0:0:0:0:2181. Greedy matching stops at
    # the final component@line suffix instead of treating the event as a
    # continuation of the previous row.
    r"\[(?P<thread>.*):"
    r"(?P<component>[^:@\]]+)@\d+\] - "
    r"(?P<body>.*)$"
)
_BGL_LINE = re.compile(
    r"^(?P<truth>\S+)\s+"
    r"(?P<epoch>\d+)\s+"
    r"(?P<date>\d{4}\.\d{2}\.\d{2})\s+"
    r"(?P<node>\S+)\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}-"
    r"\d{2}\.\d{2}\.\d{2}\.\d+)\s+"
    r"(?P<node_repeat>\S+)\s+"
    r"(?P<source>\S+)\s+"
    r"(?P<component>\S+)\s+"
    r"(?P<level>\S+)\s*"
    r"(?P<body>.*)$"
)
_SELECTION_SIGNAL = re.compile(
    r"(?i)(?:error|exception|fatal|panic|"
    r"timeout|timed\s*out|failed|failure|"
    r"lost|unreachable|disconnect|refused|"
    r"corrupt|checksum|no\s+space|"
    r"read-only|killed)"
)
_TRACEBENCH_FAILURE_SIGNAL = re.compile(
    r"(?i)(?:ioexception|socketexception|"
    r"checksum\s+error|connection\s+"
    r"(?:reset|refused)|broken\s+pipe|"
    r"could\s+not|no\s+live\s+nodes|"
    r"\b(?:error|failed|failure)\b)"
)


def _scoped_id(prefix, value):
    digest = hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:16]
    return prefix + "-" + digest


def _case_id(dataset, value):
    digest = hashlib.sha256(
        (dataset + "|" + str(value)).encode("utf-8")
    ).hexdigest()[:12]
    return dataset.upper().replace("_", "-") + "-" + digest


def _select_lowest_hash(rows, per_label):
    heaps = defaultdict(list)
    for identifier, label in rows:
        score = int(
            hashlib.sha256(
                (str(label) + "|" + identifier).encode("utf-8")
            ).hexdigest(),
            16,
        )
        heap = heaps[label]
        item = (-score, identifier)
        if len(heap) < per_label:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heapreplace(heap, item)
    return {
        identifier: label
        for label, heap in heaps.items()
        for _, identifier in heap
    }


def _hdfs_timestamp(date_value, time_value):
    parsed = datetime.strptime(
        str(date_value) + str(time_value),
        "%y%m%d%H%M%S",
    )
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _sanitize_hdfs(value):
    return redact_message(
        sanitize_public_message(value)
    )


def load_hdfs_v1_cases(root, per_label=8):
    label_path = os.path.join(
        root, "preprocessed", "anomaly_label.csv"
    )
    with open(
        label_path,
        newline="",
        encoding="utf-8",
    ) as handle:
        selected = _select_lowest_hash(
            (
                (
                    str(row.get("BlockId", "")).strip(),
                    (
                        "anomaly"
                        if str(row.get("Label", "")).strip().lower()
                        == "anomaly"
                        else "normal"
                    ),
                )
                for row in csv.DictReader(handle)
                if row.get("BlockId")
            ),
            per_label,
        )
    records = defaultdict(list)
    stats = Counter()
    with open(
        os.path.join(root, "HDFS.log"),
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for raw_line in handle:
            stats["source_lines"] += 1
            identifiers = {
                value
                for value in _BLOCK_ID.findall(raw_line)
                if value in selected
            }
            if not identifiers:
                continue
            match = _HDFS_LINE.match(
                raw_line.rstrip("\n")
            )
            if not match:
                stats["selected_unparsed_lines"] += 1
                continue
            message = _sanitize_hdfs(
                match.group("body")
            )
            for identifier in identifiers:
                scoped = _scoped_id(
                    "block", identifier
                )
                records[identifier].append({
                    "timestamp": _hdfs_timestamp(
                        match.group("date"),
                        match.group("time"),
                    ),
                    "message": message,
                    "labels": {
                        "service": "hdfs",
                        "level": match.group("level").lower(),
                        "source_component": match.group("component"),
                        "workload_id": scoped,
                        "execution_id": scoped,
                        "source_dataset": "hdfs_v1",
                    },
                })
                stats["selected_records"] += 1
    return {
        identifier: {
            "truth": selected[identifier],
            "records": rows,
        }
        for identifier, rows in records.items()
    }, dict(stats)


def _sanitize_openstack(value):
    text = sanitize_public_message(value)
    text = _UUID.sub("[UUID]", text)
    text = _HEX_ID.sub("[HEX_ID]", text)
    return redact_message(text)


def _openstack_timestamp(value):
    parsed = datetime.strptime(
        value,
        "%Y-%m-%d %H:%M:%S.%f",
    )
    return parsed.replace(
        tzinfo=timezone.utc
    ).isoformat()


def _openstack_instance_ids(path):
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line in handle:
            match = _INSTANCE_ID.search(line)
            if match:
                yield match.group("id").lower()


def _load_openstack_operation_features(root):
    """Build spawn-duration features before any anomaly label is read."""
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
    traces = {}
    source_lines = 0
    for path in paths:
        source_scope = os.path.basename(
            path
        )
        with open(
            path,
            encoding="utf-8",
            errors="replace",
        ) as handle:
            for raw_line in handle:
                source_lines += 1
                instance = _INSTANCE_ID.search(
                    raw_line
                )
                match = _OPENSTACK_LINE.match(
                    raw_line.rstrip("\n")
                )
                if not instance or not match:
                    continue
                identifier = (
                    instance.group("id").lower()
                )
                timestamp = _openstack_timestamp(
                    match.group("timestamp")
                )
                trace = traces.setdefault(
                    (
                        source_scope,
                        identifier,
                    ),
                    {
                        "operation_id":
                        identifier,
                        "source_scope":
                        source_scope,
                        "started_at": None,
                        "completed_at": None,
                    },
                )
                lowered = match.group(
                    "body"
                ).lower()
                if (
                    trace["started_at"]
                    is None
                    and "attempting claim"
                    in lowered
                ):
                    trace[
                        "started_at"
                    ] = timestamp
                if (
                    "instance spawned successfully"
                    in lowered
                    and (
                        trace["completed_at"]
                        is None
                        or timestamp
                        < trace[
                            "completed_at"
                        ]
                    )
                ):
                    trace[
                        "completed_at"
                    ] = timestamp

    operations = []
    for trace in traces.values():
        if (
            trace["started_at"] is None
            or trace["completed_at"] is None
            or trace["completed_at"]
            < trace["started_at"]
        ):
            continue
        start_hour = (
            datetime.fromisoformat(
                trace[
                    "started_at"
                ].replace(
                    "Z", "+00:00"
                )
            )
            .strftime(
                "%Y-%m-%dT%H:00Z"
            )
        )
        source_scope = trace[
            "source_scope"
        ]
        operations.append({
            "operation_id":
            trace["operation_id"],
            "operation_name":
            "instance_spawn",
            "started_at":
            trace["started_at"],
            "completed_at":
            trace["completed_at"],
            "cohort_key": (
                "openstack",
                "instance_spawn",
                source_scope,
                start_hour,
            ),
            "cohort_dimensions": {
                "service": "openstack",
                "operation":
                "instance_spawn",
                "source_scope":
                source_scope,
                "start_hour":
                start_hour,
            },
            "source_provenance": {
                "source_dataset":
                "openstack",
                "source_schema_id":
                "openstack-spawn-operation/v1",
                "source_scope":
                source_scope,
            },
        })
    features = build_peer_duration_features(
        operations
    )
    return features, {
        "baseline_source_lines":
        source_lines,
        "complete_spawn_operations":
        len(operations),
        "duration_features":
        len(features),
        "latency_deviations": sum(
            feature.get("status")
            == "deviation_observed"
            for feature in features.values()
        ),
        "baseline_labels_used": False,
    }


def load_openstack_cases(root, normal_limit=8):
    operation_features, feature_stats = (
        _load_openstack_operation_features(
            root
        )
    )
    # Dataset truth is deliberately loaded after operation features exist.
    with open(
        os.path.join(root, "anomaly_labels.txt"),
        encoding="utf-8",
    ) as handle:
        anomaly_ids = {
            match.group(0).lower()
            for line in handle
            for match in [_UUID.search(line)]
            if match
        }
    normal_files = [
        os.path.join(root, "openstack_normal1.log"),
        os.path.join(root, "openstack_normal2.log"),
    ]
    normal_identifiers = {
        identifier
        for path in normal_files
        for identifier in _openstack_instance_ids(path)
        if identifier not in anomaly_ids
    }
    normal_selected = _select_lowest_hash(
        (
            (identifier, "normal")
            for identifier in normal_identifiers
        ),
        normal_limit,
    )
    selected = {
        **{identifier: "anomaly" for identifier in anomaly_ids},
        **normal_selected,
    }
    records = defaultdict(list)
    stats = Counter(feature_stats)
    file_specs = [
        (
            os.path.join(root, "openstack_abnormal.log"),
            anomaly_ids,
        ),
        *(
            (path, set(normal_selected))
            for path in normal_files
        ),
    ]
    for path, allowed_ids in file_specs:
        with open(
            path,
            encoding="utf-8",
            errors="replace",
        ) as handle:
            for raw_line in handle:
                stats["source_lines"] += 1
                instance = _INSTANCE_ID.search(raw_line)
                if not instance:
                    continue
                identifier = instance.group("id").lower()
                if identifier not in allowed_ids:
                    continue
                match = _OPENSTACK_LINE.match(
                    raw_line.rstrip("\n")
                )
                if not match:
                    stats["selected_unparsed_lines"] += 1
                    continue
                scoped = _scoped_id(
                    "instance", identifier
                )
                record = {
                    "timestamp": _openstack_timestamp(
                        match.group("timestamp")
                    ),
                    "message": _sanitize_openstack(
                        match.group("body")
                    ),
                    "labels": {
                        "service": "openstack",
                        "level": match.group("level").lower(),
                        "source_component": match.group("component"),
                        "workload_id": scoped,
                        "execution_id": scoped,
                        "source_dataset": "openstack",
                    },
                }
                feature = operation_features.get(
                    identifier
                )
                if (
                    feature
                    and (
                        "instance spawned successfully"
                        in match.group(
                            "body"
                        ).lower()
                    )
                ):
                    record[
                        "operation_feature"
                    ] = feature
                records[identifier].append(
                    record
                )
                stats["selected_records"] += 1
    return {
        identifier: {
            "truth": selected[identifier],
            "records": rows,
        }
        for identifier, rows in records.items()
    }, dict(stats)


def _dataset_file(root, filename):
    return (
        root
        if os.path.isfile(root)
        else os.path.join(root, filename)
    )


def _naive_utc(value, pattern):
    """Normalize source-local times to UTC for relative-order tests only."""
    return datetime.strptime(
        value, pattern
    ).replace(
        tzinfo=timezone.utc
    )


def _window_key(timestamp, minutes):
    minute = (
        timestamp.minute
        // minutes
        * minutes
    )
    return timestamp.replace(
        minute=minute,
        second=0,
        microsecond=0,
    ).isoformat()


def _zookeeper_records(path):
    records = []
    stats = Counter()
    current = None

    def finish():
        nonlocal current
        if current is None:
            return
        current["message"] = redact_message(
            sanitize_public_message(
                current["message"]
            )
        )[:2000]
        records.append(current)
        current = None

    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(
            handle, 1
        ):
            stats["physical_lines"] += 1
            match = _ZOOKEEPER_LINE.match(
                raw_line.rstrip("\r\n")
            )
            if match is None:
                if current is not None:
                    current["message"] += (
                        "\n"
                        + raw_line.rstrip(
                            "\r\n"
                        )
                    )
                    stats[
                        "continuation_lines"
                    ] += 1
                else:
                    stats[
                        "orphan_unparsed_lines"
                    ] += 1
                continue
            finish()
            timestamp = _naive_utc(
                match.group("timestamp"),
                "%Y-%m-%d %H:%M:%S,%f",
            )
            current = {
                "timestamp":
                timestamp.isoformat(),
                "message":
                match.group("body"),
                "labels": {
                    "service": "zookeeper",
                    "level":
                    match.group(
                        "level"
                    ).lower(),
                    "source_component":
                    match.group(
                        "component"
                    ),
                    "event_name":
                    match.group(
                        "component"
                    ),
                    "source_dataset":
                    "loghub_zookeeper",
                },
                "connector_metadata": {
                    "source":
                    "loghub_zookeeper",
                    "source_dataset":
                    "loghub_zookeeper",
                    "source_line_id":
                    line_number,
                    "timestamp_assumption":
                    "source timezone undeclared; "
                    "UTC used for relative ordering",
                    "timestamp_quality":
                    "timezone_assumed_utc",
                    "timestamp_ordering_scope":
                    "source_relative",
                },
            }
            stats["parsed_events"] += 1
    finish()
    return records, stats


def load_zookeeper_cases(
    root,
    per_cohort=8,
    window_minutes=10,
):
    """Select label-free signal-bearing and quiet ZooKeeper windows."""
    path = _dataset_file(
        root, "Zookeeper.log"
    )
    records, stats = _zookeeper_records(
        path
    )
    windows = defaultdict(list)
    cohorts = {}
    for record in records:
        timestamp = datetime.fromisoformat(
            record["timestamp"]
        )
        window = _window_key(
            timestamp, window_minutes
        )
        windows[window].append(record)
    for window, rows in windows.items():
        cohorts[window] = (
            "signal_bearing"
            if any(
                (
                    str(
                        row.get(
                            "labels", {}
                        ).get(
                            "level", ""
                        )
                    ).lower()
                    in {
                        "error",
                        "fatal",
                        "warn",
                        "warning",
                    }
                    or _SELECTION_SIGNAL.search(
                        str(
                            row.get(
                                "message", ""
                            )
                        )
                    )
                )
                for row in rows
            )
            else "quiet"
        )
    selected = _select_lowest_hash(
        (
            (window, cohort)
            for window, cohort
            in cohorts.items()
        ),
        per_cohort,
    )
    stats["windows"] = len(windows)
    stats["selected_windows"] = len(
        selected
    )
    stats["selected_records"] = sum(
        len(windows[window])
        for window in selected
    )
    stats[
        "source_truth_available"
    ] = 0
    return {
        cohort + "|" + window: {
            "truth": "unlabeled",
            "selection_cohort": cohort,
            "records": windows[window],
        }
        for window, cohort
        in selected.items()
    }, dict(stats)


def _parse_bgl_line(raw_line):
    match = _BGL_LINE.match(
        raw_line.rstrip("\r\n")
    )
    if match is None:
        return None
    try:
        timestamp = _naive_utc(
            match.group("timestamp"),
            "%Y-%m-%d-%H.%M.%S.%f",
        )
    except ValueError:
        return None
    return match, timestamp


def load_bgl_cases(
    root,
    per_label=8,
    window_minutes=5,
):
    """Load BGL windows while keeping alert tags out of pipeline records."""
    path = _dataset_file(
        root, "BGL.log"
    )
    stats = Counter()
    window_truth = {}
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for raw_line in handle:
            stats["source_lines"] += 1
            parsed = _parse_bgl_line(
                raw_line
            )
            if parsed is None:
                stats["unparsed_lines"] += 1
                continue
            match, timestamp = parsed
            window = _window_key(
                timestamp, window_minutes
            )
            label = (
                "non_alert"
                if match.group("truth")
                == "-"
                else "alert"
            )
            if (
                label == "alert"
                or window
                not in window_truth
            ):
                window_truth[window] = label
            stats["parsed_lines"] += 1
    selected = _select_lowest_hash(
        window_truth.items(),
        per_label,
    )
    records = defaultdict(list)
    with open(
        path,
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, raw_line in enumerate(
            handle, 1
        ):
            parsed = _parse_bgl_line(
                raw_line
            )
            if parsed is None:
                continue
            match, timestamp = parsed
            window = _window_key(
                timestamp, window_minutes
            )
            if window not in selected:
                continue
            scoped_node = _scoped_id(
                "node",
                match.group("node"),
            )
            records[window].append({
                "timestamp":
                timestamp.isoformat(),
                "message":
                redact_message(
                    sanitize_public_message(
                        match.group("body")
                    )
                )[:2000],
                "labels": {
                    "service": "bgl",
                    "level":
                    match.group(
                        "level"
                    ).lower(),
                    "source_component":
                    match.group(
                        "component"
                    ),
                    "event_name":
                    match.group(
                        "source"
                    ),
                    "workload_id":
                    scoped_node,
                    "execution_id":
                    scoped_node,
                    "source_dataset":
                    "loghub_bgl",
                },
                "connector_metadata": {
                    "source": "loghub_bgl",
                    "source_dataset":
                    "loghub_bgl",
                    "source_line_id":
                    line_number,
                    "timestamp_assumption":
                    "source timezone undeclared; "
                    "UTC used for relative ordering",
                    "timestamp_quality":
                    "timezone_assumed_utc",
                    "timestamp_ordering_scope":
                    "source_relative",
                },
            })
            stats["selected_records"] += 1
    stats["windows"] = len(
        window_truth
    )
    stats["selected_windows"] = len(
        selected
    )
    stats.setdefault("unparsed_lines", 0)
    return {
        window: {
            "truth": selected[window],
            "records": rows,
        }
        for window, rows in records.items()
    }, dict(stats)


def _tracebench_scenario(directory):
    name = os.path.basename(directory)
    cohort = (
        "fault_injected"
        if name.startswith("AN_")
        else "normal"
    )
    value = re.sub(
        r"^(?:AN|NM)_", "", name
    )
    if cohort == "fault_injected":
        value = re.split(
            r"_(?:r|w|rpc)_",
            value,
            maxsplit=1,
        )[0]
    else:
        value = value.split("_", 2)[0]
    return cohort, value


def _tracebench_directories(
    root,
    per_cohort,
):
    trace_root = os.path.join(
        root, "tracebench"
    )
    anomaly_by_scenario = defaultdict(list)
    normal = []
    for name in sorted(
        os.listdir(trace_root)
    ):
        path = os.path.join(
            trace_root, name
        )
        if not os.path.isdir(path):
            continue
        cohort, scenario = (
            _tracebench_scenario(path)
        )
        if cohort == "fault_injected":
            anomaly_by_scenario[
                scenario
            ].append(path)
        elif name.startswith("NM_"):
            normal.append(path)
    anomaly = []
    for scenario in sorted(
        anomaly_by_scenario
    ):
        anomaly.extend(sorted(
            anomaly_by_scenario[
                scenario
            ],
            key=lambda value:
            hashlib.sha256(
                os.path.basename(
                    value
                ).encode("utf-8")
            ).hexdigest(),
        ))
    selected_normal = sorted(
        normal,
        key=lambda value: hashlib.sha256(
            os.path.basename(
                value
            ).encode("utf-8")
        ).hexdigest(),
    )[:per_cohort]
    return anomaly + selected_normal


def _tracebench_trace(
    path,
    allowed_task_ids=None,
):
    chosen = None
    chosen_score = None
    with open(
        os.path.join(path, "trace.csv"),
        newline="",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for row in csv.DictReader(handle):
            task_id = str(
                row.get("TaskID", "")
            ).strip()
            if not task_id:
                continue
            if (
                allowed_task_ids is not None
                and task_id
                not in allowed_task_ids
            ):
                continue
            score = hashlib.sha256(
                task_id.encode("utf-8")
            ).hexdigest()
            if (
                chosen_score is None
                or score < chosen_score
            ):
                chosen = row
                chosen_score = score
    return chosen


def _tracebench_description(row):
    values = [
        str(row.get("Description", ""))
    ]
    values.extend(
        str(value)
        for value in (
            row.get(None, []) or []
        )
    )
    return ",".join(values)


def _tracebench_failed_tasks(
    path,
    stats,
):
    """Reproduce the corpus task label without returning it in records."""
    failed = set()
    with open(
        os.path.join(path, "event.csv"),
        newline="",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for row in csv.DictReader(handle):
            stats[
                "label_scan_event_rows"
            ] += 1
            task_id = str(
                row.get("TaskID", "")
            ).strip()
            description = (
                _tracebench_description(
                    row
                ).lower()
            )
            if (
                task_id
                and "success:"
                not in description
                and "a user task"
                not in description
            ):
                failed.add(task_id)
    return failed


def load_hdfs_v3_cases(
    root,
    per_cohort=8,
):
    """Load TraceBench cases without exposing directory fault metadata."""
    cases = {}
    stats = Counter()
    selected_fault_scenarios = set()
    directories = _tracebench_directories(
        root, per_cohort
    )
    for directory in directories:
        cohort, scenario = (
            _tracebench_scenario(
                directory
            )
        )
        if (
            cohort == "fault_injected"
            and (
                len(
                    selected_fault_scenarios
                )
                >= per_cohort
                or scenario
                in selected_fault_scenarios
            )
        ):
            continue
        failed_tasks = (
            _tracebench_failed_tasks(
                directory, stats
            )
            if cohort
            == "fault_injected"
            else None
        )
        trace = _tracebench_trace(
            directory,
            allowed_task_ids=failed_tasks,
        )
        if not trace:
            stats["directories_without_trace"] += 1
            continue
        task_id = str(trace["TaskID"])
        try:
            trace_time = _naive_utc(
                str(trace["FirstSeen"]),
                "%Y-%m-%d %H:%M:%S",
            ).isoformat()
        except ValueError:
            stats[
                "traces_with_invalid_time"
            ] += 1
            continue
        scoped = _scoped_id(
            "trace", task_id
        )
        records = []
        with open(
            os.path.join(
                directory, "event.csv"
            ),
            newline="",
            encoding="utf-8",
            errors="replace",
        ) as handle:
            for line_number, row in enumerate(
                csv.DictReader(handle), 2
            ):
                stats["event_rows_scanned"] += 1
                if str(
                    row.get("TaskID", "")
                ) != task_id:
                    continue
                description = (
                    _tracebench_description(
                        row
                    )
                )
                message = (
                    str(
                        row.get(
                            "OpName", ""
                        )
                    )
                    + ": "
                    + description
                )
                level = (
                    "error"
                    if _TRACEBENCH_FAILURE_SIGNAL.search(
                        message
                    )
                    else "info"
                )
                records.append({
                    "timestamp":
                    trace_time,
                    "message":
                    _sanitize_hdfs(
                        message
                    )[:2000],
                    "labels": {
                        "service": "hdfs",
                        "level": level,
                        "source_component":
                        row.get(
                            "Agent", ""
                        ),
                        "event_name":
                        row.get(
                            "OpName", ""
                        ),
                        "workload_id":
                        scoped,
                        "execution_id":
                        scoped,
                        "source_dataset":
                        "hdfs_v3_tracebench",
                    },
                    "connector_metadata": {
                        "source":
                        "hdfs_v3_tracebench",
                        "source_dataset":
                        "hdfs_v3_tracebench",
                        "source_line_id":
                        line_number,
                        "timestamp_quality":
                        "coarse_trace_first_seen",
                        "timestamp_ordering_scope":
                        "trace_only",
                        "timestamp_limitation":
                        "host-local event clocks are "
                        "not treated as globally comparable",
                    },
                })
                stats["selected_records"] += 1
        if not records:
            stats[
                "selected_traces_without_events"
            ] += 1
            continue
        cases[
            os.path.basename(
                directory
            )
            + "|"
            + task_id
        ] = {
            "truth": (
                "failure"
                if cohort
                == "fault_injected"
                else "normal"
            ),
            "fault_family": (
                scenario
                if cohort
                == "fault_injected"
                else None
            ),
            "timestamp_quality":
            "coarse_trace_first_seen",
            "records": records,
        }
        if cohort == "fault_injected":
            selected_fault_scenarios.add(
                scenario
            )
        stats["selected_traces"] += 1
    stats["selected_directories"] = len(
        cases
    )
    stats[
        "selected_fault_scenarios"
    ] = len(
        selected_fault_scenarios
    )
    stats["fault_metadata_exposed"] = 0
    stats[
        "globally_comparable_event_clock"
    ] = 0
    return cases, dict(stats)


def _merge_counts(cases, field):
    return dict(
        sum(
            (
                Counter(case.get(field, {}))
                for case in cases
            ),
            Counter(),
        )
    )


def _span_seconds(records):
    timestamps = sorted(
        datetime.fromisoformat(
            str(record["timestamp"]).replace(
                "Z", "+00:00"
            )
        )
        for record in records
        if record.get("timestamp")
    )
    if len(timestamps) < 2:
        return 0.0
    return round(
        (
            timestamps[-1]
            - timestamps[0]
        ).total_seconds(),
        3,
    )


def _openstack_spawn_duration(records):
    start = None
    end = None
    for record in records:
        message = str(
            record.get("message", "")
        ).lower()
        timestamp = datetime.fromisoformat(
            str(record["timestamp"]).replace(
                "Z", "+00:00"
            )
        )
        if (
            start is None
            and "attempting claim" in message
        ):
            start = timestamp
        if (
            "instance spawned successfully"
            in message
        ):
            end = timestamp
            break
    if start is None or end is None or end < start:
        return None
    return round(
        (end - start).total_seconds(),
        3,
    )


def _duration_summary(cases, field):
    by_label = defaultdict(list)
    for case in cases:
        value = case.get(field)
        if isinstance(value, (int, float)):
            by_label[case["truth"]].append(
                float(value)
            )
    output = {}
    for label, values in by_label.items():
        ordered = sorted(values)
        output[label] = {
            "count": len(ordered),
            "min": ordered[0],
            "median": ordered[
                len(ordered) // 2
            ],
            "max": ordered[-1],
        }
    return output


def _run_case(
    *,
    dataset,
    identifier,
    truth,
    records,
    sample_limit,
    html_dir,
    case_metadata=None,
):
    state = prepare_distributed_case_state(
        dataset=dataset,
        identifier=identifier,
        records=records,
        sample_limit=sample_limit,
    )
    structured, grounding = validate_and_ground(
        deterministic_payload(
            state,
            limitation=(
                dataset
                + " generalization evaluation uses no dataset label "
                "inside the pipeline."
            ),
        ),
        state,
    )
    state["interpretation_structured"] = structured
    state["claim_grounding"] = grounding
    state["interpretation"] = (
        render_grounded_interpretation(
            structured, state
        )
    )
    state["interpretation_quality"] = {
        "passed": grounding.get("passed", False),
        "abstained": grounding.get("abstained", False),
        "warnings": grounding.get("warnings", []),
    }
    review_file = None
    if html_dir:
        os.makedirs(html_dir, exist_ok=True)
        review_file = state["incident_id"] + ".html"
        with open(
            os.path.join(html_dir, review_file),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(render_review(state))

    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    observations = assessment.get(
        "observed_signals", []
    ) or []
    observation_patterns = assessment.get(
        "observation_patterns", []
    ) or []
    impact_quality = assess_impact_contract(
        state, observations
    )
    raw_signals = summarize_record_signals(
        records
    )
    raw_identifier_leaked = (
        identifier in state["evidence_pack"]
    )
    operation_features = [
        record["operation_feature"]
        for record in records
        if record.get(
            "operation_feature"
        )
    ]
    latency_features = [
        feature
        for feature in operation_features
        if feature.get("feature_name")
        == "operation_latency_deviation"
    ]
    unsafe_baseline_features = [
        feature
        for feature in latency_features
        if (
            (
                feature.get(
                    "baseline", {}
                )
                or {}
            ).get("labels_used")
            is not False
            or (
                feature.get(
                    "decision_policy",
                    {},
                )
                or {}
            ).get(
                "fixed_seconds_threshold"
            )
            is not None
        )
    ]
    # Truth joins only after state, grounding, and review are complete.
    return {
        "case_id": state["incident_id"],
        "truth": truth,
        "truth_exposed_to_pipeline": False,
        "case_metadata": dict(
            case_metadata or {}
        ),
        "source_records": len(records),
        "sampled_records": int(
            state.get(
                "_evaluation_sampled_record_count",
                0,
            )
        ),
        "source_span_seconds": _span_seconds(
            records
        ),
        "spawn_duration_seconds": (
            _openstack_spawn_duration(records)
            if dataset == "openstack"
            else None
        ),
        "operation_duration_feature":
        (
            latency_features[0]
            if latency_features
            else None
        ),
        "latency_deviation_observed":
        any(
            feature.get("status")
            == "deviation_observed"
            for feature in latency_features
        ),
        "unsafe_baseline_feature_count":
        len(unsafe_baseline_features),
        "raw_identifier_leaked": raw_identifier_leaked,
        "raw_signal_families": raw_signals.get(
            "direct_families", {}
        ),
        "review_status": structured.get("status"),
        "grounding_passed": grounding.get("passed", False),
        "unknown_evidence_ids": sum(
            len(item.get("unknown_evidence_ids", []) or [])
            for item in grounding.get("claims", []) or []
        ),
        "candidate_categories": [
            item.get("category")
            for item in assessment.get("candidates", []) or []
        ],
        "abstain_reasons": assessment.get(
            "abstain_reasons", []
        ),
        "observed_signal_count": len(observations),
        "observed_signal_families": dict(
            Counter(
                item.get("signal_family")
                for item in observations
            )
        ),
        "observation_pattern_count":
        len(observation_patterns),
        "observation_pattern_families": dict(
            Counter(
                item.get("signal_family")
                for item in observation_patterns
            )
        ),
        "impact_contract_valid": impact_quality["valid"],
        "impact_contract_invalid_records": impact_quality[
            "invalid_records"
        ],
        "impact_role_unknown_evidence_ids": impact_quality[
            "unknown_role_evidence_ids"
        ],
        "entity_mismatch_candidates": impact_quality[
            "entity_mismatch_candidates"
        ],
        "pre_signal_outcome_candidates": impact_quality[
            "pre_signal_outcome_candidates"
        ],
        "impact_status_counts": impact_quality[
            "status_counts"
        ],
        "impact_entity_match_counts": impact_quality[
            "entity_match_counts"
        ],
        "impact_time_relation_counts": impact_quality[
            "time_relation_counts"
        ],
        "evidence_pack_chars": len(
            state["evidence_pack"]
        ),
        "review_html": review_file,
    }


def prepare_distributed_case_state(
    *,
    dataset,
    identifier,
    records,
    sample_limit,
):
    """Build one label-free pipeline state for deterministic or model review."""
    sampled = representative_sample(
        records, sample_limit
    )
    state = _pipeline_state(
        sampled,
        len(records),
        service={
            "hdfs_v1": "hdfs",
            "hdfs_v3": "hdfs",
            "openstack": "openstack",
            "bgl": "bgl",
            "zookeeper": "zookeeper",
        }.get(dataset, dataset),
        environment="public-offline-generalization",
    )
    state["incident_id"] = _case_id(
        dataset, identifier
    )
    state["evidence_pack"] = build_evidence_pack(state)
    state[
        "_evaluation_sampled_record_count"
    ] = len(sampled)
    return state


def evaluate_distributed_dataset(
    *,
    dataset,
    root,
    sample_limit=200,
    cases_per_label=8,
    html_dir=None,
):
    if dataset == "hdfs_v1":
        loaded, source_stats = load_hdfs_v1_cases(
            root, per_label=cases_per_label
        )
    elif dataset == "openstack":
        loaded, source_stats = load_openstack_cases(
            root, normal_limit=cases_per_label
        )
    elif dataset == "hdfs_v3":
        loaded, source_stats = load_hdfs_v3_cases(
            root,
            per_cohort=cases_per_label,
        )
    elif dataset == "bgl":
        loaded, source_stats = load_bgl_cases(
            root,
            per_label=cases_per_label,
        )
    elif dataset == "zookeeper":
        loaded, source_stats = load_zookeeper_cases(
            root,
            per_cohort=cases_per_label,
        )
    else:
        raise ValueError(
            "dataset must be hdfs_v1, hdfs_v3, "
            "openstack, bgl, or zookeeper"
        )
    cases = [
        _run_case(
            dataset=dataset,
            identifier=identifier,
            truth=spec["truth"],
            records=spec["records"],
            sample_limit=sample_limit,
            html_dir=html_dir,
            case_metadata={
                key: value
                for key, value in spec.items()
                if key not in {
                    "truth",
                    "records",
                }
            },
        )
        for identifier, spec in sorted(
            loaded.items(),
            key=lambda item: _case_id(
                dataset, item[0]
            ),
        )
        if spec["records"]
    ]
    label_counts = Counter(
        case["truth"] for case in cases
    )
    supported_by_label = Counter(
        case["truth"]
        for case in cases
        if case["review_status"] == "supported"
    )
    direct_cases_by_label = Counter(
        case["truth"]
        for case in cases
        if case["observed_signal_count"]
    )
    catalog_cases_by_label = Counter(
        case["truth"]
        for case in cases
        if case["raw_signal_families"]
    )
    metrics = {
        "cases": len(cases),
        "label_counts": dict(label_counts),
        "supported_by_label": dict(supported_by_label),
        "cases_with_catalog_signals_by_label": dict(
            catalog_cases_by_label
        ),
        "cases_with_direct_observations_by_label": dict(
            direct_cases_by_label
        ),
        "grounding_pass_rate": (
            round(
                sum(
                    case["grounding_passed"]
                    for case in cases
                )
                / len(cases),
                4,
            )
            if cases
            else 0.0
        ),
        "impact_contract_pass_rate": (
            round(
                sum(
                    case["impact_contract_valid"]
                    for case in cases
                )
                / len(cases),
                4,
            )
            if cases
            else 0.0
        ),
        "cases_with_direct_observations": sum(
            bool(case["observed_signal_count"])
            for case in cases
        ),
        "observed_signals_total": sum(
            case["observed_signal_count"]
            for case in cases
        ),
        "observed_signal_families": _merge_counts(
            cases, "observed_signal_families"
        ),
        "observation_patterns_total": sum(
            case["observation_pattern_count"]
            for case in cases
        ),
        "observation_pattern_families":
        _merge_counts(
            cases,
            "observation_pattern_families",
        ),
        "raw_signal_families": _merge_counts(
            cases, "raw_signal_families"
        ),
        "impact_status_counts": _merge_counts(
            cases, "impact_status_counts"
        ),
        "impact_entity_match_counts": _merge_counts(
            cases, "impact_entity_match_counts"
        ),
        "impact_time_relation_counts": _merge_counts(
            cases, "impact_time_relation_counts"
        ),
        "unknown_evidence_ids": sum(
            case["unknown_evidence_ids"]
            for case in cases
        ),
        "impact_role_unknown_evidence_ids": sum(
            len(case["impact_role_unknown_evidence_ids"])
            for case in cases
        ),
        "entity_mismatch_candidates": sum(
            case["entity_mismatch_candidates"]
            for case in cases
        ),
        "pre_signal_outcome_candidates": sum(
            case["pre_signal_outcome_candidates"]
            for case in cases
        ),
        "raw_identifier_leaks": sum(
            case["raw_identifier_leaked"]
            for case in cases
        ),
        "latency_deviations_by_label":
        dict(
            Counter(
                case["truth"]
                for case in cases
                if case[
                    "latency_deviation_observed"
                ]
            )
        ),
        "unsafe_baseline_features": sum(
            case[
                "unsafe_baseline_feature_count"
            ]
            for case in cases
        ),
        "max_evidence_pack_chars": max(
            (
                case["evidence_pack_chars"]
                for case in cases
            ),
            default=0,
        ),
        "source_span_seconds_by_label":
        _duration_summary(
            cases, "source_span_seconds"
        ),
        "spawn_duration_seconds_by_label":
        _duration_summary(
            cases, "spawn_duration_seconds"
        ),
    }
    gate = bool(cases) and all(
        case["grounding_passed"]
        and case["impact_contract_valid"]
        and not case["unknown_evidence_ids"]
        and not case["impact_role_unknown_evidence_ids"]
        and not case["entity_mismatch_candidates"]
        and not case["pre_signal_outcome_candidates"]
        and not case["raw_identifier_leaked"]
        and not case["truth_exposed_to_pipeline"]
        and not case[
            "unsafe_baseline_feature_count"
        ]
        for case in cases
    )
    return {
        "evaluation": (
            "distributed-impact-generalization/v2"
        ),
        "dataset": dataset,
        "truth_scope": {
            "hdfs_v1":
            "normal/anomaly only; no root-cause class",
            "openstack":
            "normal/anomaly only; no root-cause class",
            "hdfs_v3":
            "task failure/normal from TraceBench preprocessing; "
            "fault family held out; no root-cause class",
            "bgl":
            "window contains source alert tag or not; "
            "not incident root-cause truth",
            "zookeeper":
            "unlabeled; selection cohort is observable-only",
        }.get(
            dataset,
            "dataset-specific labels held out",
        ),
        "truth_exposed_to_pipeline": False,
        "source_stats": source_stats,
        "metrics": metrics,
        "cases": cases,
        "contract_gate_passed": gate,
    }
