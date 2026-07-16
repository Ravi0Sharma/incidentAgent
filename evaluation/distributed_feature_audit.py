"""Label-last feature and confounder audits for OpenStack and HDFS_v1."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import os
import re
from statistics import median


_INSTANCE_ID = re.compile(
    r"\[instance:\s*"
    r"(?P<id>[0-9a-fA-F-]{36})\]"
)
_OPENSTACK_TIME = re.compile(
    r"^\S+\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} "
    r"\d{2}:\d{2}:\d{2}\.\d+)"
)
_EVENT_ID = re.compile(r"E\d+")
_HDFS_FAILURE_EVENTS = {
    "E4",
    "E7",
    "E8",
    "E10",
    "E12",
    "E14",
    "E17",
    "E20",
    "E24",
    "E28",
    "E29",
}
_HDFS_SUCCESS_EVENTS = {
    "E2",
    "E3",
    "E6",
    "E9",
}
_HDFS_TYPED_STORAGE_EVENTS = {
    "E7": "storage_io",
    "E20": "storage_metadata",
    "E28": "storage_metadata",
}


def _case_id(dataset, value):
    digest = hashlib.sha256(
        (dataset + "|" + str(value)).encode("utf-8")
    ).hexdigest()[:12]
    return dataset.upper().replace("_", "-") + "-" + digest


def _parse_openstack_time(line):
    match = _OPENSTACK_TIME.match(line)
    if not match:
        return None
    parsed = datetime.strptime(
        match.group("timestamp"),
        "%Y-%m-%d %H:%M:%S.%f",
    )
    return parsed.replace(tzinfo=timezone.utc)


def _summary(values):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p90": None,
            "max": None,
            "mad": None,
        }
    center = median(ordered)
    deviations = [
        abs(value - center)
        for value in ordered
    ]
    p90_index = min(
        int(0.9 * (len(ordered) - 1)),
        len(ordered) - 1,
    )
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "median": round(center, 3),
        "p90": round(
            ordered[p90_index], 3
        ),
        "max": round(ordered[-1], 3),
        "mad": round(
            median(deviations), 3
        ),
    }


def _peer_features(value, peers):
    peers = [
        float(peer)
        for peer in peers
    ]
    if not peers:
        return {
            "peer_count": 0,
            "peer_median_seconds": None,
            "peer_mad_seconds": None,
            "duration_ratio": None,
            "percentile_rank": None,
            "robust_z": None,
        }
    center = median(peers)
    deviations = [
        abs(peer - center)
        for peer in peers
    ]
    mad = median(deviations)
    percentile = (
        100.0
        * sum(peer <= value for peer in peers)
        / len(peers)
    )
    return {
        "peer_count": len(peers),
        "peer_median_seconds": round(center, 3),
        "peer_mad_seconds": round(mad, 3),
        "duration_ratio": (
            round(value / center, 4)
            if center > 0
            else None
        ),
        "percentile_rank": round(percentile, 2),
        "robust_z": (
            round(
                0.6745
                * (value - center)
                / mad,
                3,
            )
            if mad > 0
            else None
        ),
    }


def _load_openstack_labels(root):
    with open(
        os.path.join(root, "anomaly_labels.txt"),
        encoding="utf-8",
    ) as handle:
        anomaly_ids = {
            match.group(0).lower()
            for line in handle
            for match in [
                re.search(
                    r"\b[0-9a-fA-F-]{36}\b",
                    line,
                )
            ]
            if match
        }
    return anomaly_ids


def audit_openstack_durations(root):
    """Extract all durations first, then join anomaly/normal labels."""
    paths = [
        os.path.join(root, "openstack_abnormal.log"),
        os.path.join(root, "openstack_normal1.log"),
        os.path.join(root, "openstack_normal2.log"),
    ]
    traces = {}
    source_lines = 0
    for path in paths:
        cohort = os.path.basename(path)
        with open(
            path,
            encoding="utf-8",
            errors="replace",
        ) as handle:
            for line in handle:
                source_lines += 1
                instance = _INSTANCE_ID.search(line)
                if not instance:
                    continue
                timestamp = _parse_openstack_time(line)
                if timestamp is None:
                    continue
                identifier = instance.group("id").lower()
                key = (cohort, identifier)
                trace = traces.setdefault(
                    key,
                    {
                        "source_cohort": cohort,
                        "start": None,
                        "end": None,
                        "first": timestamp,
                        "last": timestamp,
                    },
                )
                trace["first"] = min(
                    trace["first"], timestamp
                )
                trace["last"] = max(
                    trace["last"], timestamp
                )
                lowered = line.lower()
                if (
                    trace["start"] is None
                    and "attempting claim"
                    in lowered
                ):
                    trace["start"] = timestamp
                if (
                    "instance spawned successfully"
                    in lowered
                    and (
                        trace["end"] is None
                        or timestamp < trace["end"]
                    )
                ):
                    trace["end"] = timestamp

    feature_rows = []
    for (cohort, identifier), trace in traces.items():
        if (
            trace["start"] is None
            or trace["end"] is None
            or trace["end"] < trace["start"]
        ):
            continue
        duration = (
            trace["end"]
            - trace["start"]
        ).total_seconds()
        feature_rows.append({
            "_identifier": identifier,
            "case_id": _case_id(
                "openstack-audit",
                cohort + "|" + identifier,
            ),
            "source_cohort": cohort,
            "start_hour": trace["start"].strftime(
                "%Y-%m-%dT%H:00Z"
            ),
            "duration_seconds": round(
                duration, 3
            ),
            "trace_span_seconds": round(
                (
                    trace["last"]
                    - trace["first"]
                ).total_seconds(),
                3,
            ),
        })

    by_cohort = defaultdict(list)
    by_hour = defaultdict(list)
    for row in feature_rows:
        by_cohort[
            row["source_cohort"]
        ].append(row["duration_seconds"])
        by_hour[
            (
                row["source_cohort"],
                row["start_hour"],
            )
        ].append(row["duration_seconds"])

    for row in feature_rows:
        cohort_peers = list(
            by_cohort[row["source_cohort"]]
        )
        cohort_peers.remove(
            row["duration_seconds"]
        )
        hour_peers = list(
            by_hour[
                (
                    row["source_cohort"],
                    row["start_hour"],
                )
            ]
        )
        hour_peers.remove(
            row["duration_seconds"]
        )
        row["cohort_features"] = (
            _peer_features(
                row["duration_seconds"],
                cohort_peers,
            )
        )
        row["hour_features"] = (
            _peer_features(
                row["duration_seconds"],
                hour_peers,
            )
        )

    # Labels are read and joined only after all duration and peer features exist.
    anomaly_ids = _load_openstack_labels(root)
    normal_cohorts = {
        "openstack_normal1.log",
        "openstack_normal2.log",
    }
    evaluated = []
    for row in feature_rows:
        identifier = row.pop("_identifier")
        truth = (
            "anomaly"
            if identifier in anomaly_ids
            else "normal"
            if row["source_cohort"]
            in normal_cohorts
            else "unlabeled"
        )
        evaluated.append({
            **row,
            "truth": truth,
        })

    cohort_summaries = {
        cohort: _summary(values)
        for cohort, values in sorted(
            by_cohort.items()
        )
    }
    labeled = [
        row
        for row in evaluated
        if row["truth"] in {
            "anomaly",
            "normal",
        }
    ]
    truth_summaries = {
        truth: _summary(
            row["duration_seconds"]
            for row in labeled
            if row["truth"] == truth
        )
        for truth in ("anomaly", "normal")
    }
    anomaly_rows = [
        row
        for row in labeled
        if row["truth"] == "anomaly"
    ]
    return {
        "audit": "openstack-duration-confounder/v1",
        "labels_used_during_feature_extraction": False,
        "source_lines": source_lines,
        "instance_traces_seen": len(traces),
        "complete_spawn_traces": len(
            feature_rows
        ),
        "cohort_summaries": cohort_summaries,
        "truth_summaries_post_join": truth_summaries,
        "labeled_anomaly_cases": anomaly_rows,
        "anomaly_peer_findings": {
            "all_above_cohort_median": all(
                (
                    row["cohort_features"][
                        "duration_ratio"
                    ]
                    or 0
                )
                > 1
                for row in anomaly_rows
            ),
            "all_at_or_above_cohort_p90": all(
                row["duration_seconds"]
                >= cohort_summaries[
                    row["source_cohort"]
                ]["p90"]
                for row in anomaly_rows
            ),
            "minimum_cohort_percentile": min(
                (
                    row["cohort_features"][
                        "percentile_rank"
                    ]
                    or 0
                    for row in anomaly_rows
                ),
                default=None,
            ),
            "minimum_duration_ratio": min(
                (
                    row["cohort_features"][
                        "duration_ratio"
                    ]
                    or 0
                    for row in anomaly_rows
                ),
                default=None,
            ),
        },
        "decision_note": (
            "Duration is feature-feasible only if labeled anomalies remain "
            "outliers against label-blind peers in the same source cohort."
        ),
    }


def _has_later_success(events, failure_index):
    return any(
        event in _HDFS_SUCCESS_EVENTS
        for event in events[
            failure_index + 1:
        ]
    )


def audit_hdfs_event_traces(root):
    """Extract event/order features before joining Success/Fail truth."""
    path = os.path.join(
        root,
        "preprocessed",
        "Event_traces.csv",
    )
    totals = Counter()
    event_presence = defaultdict(Counter)
    cross_tabs = {
        field: Counter()
        for field in (
            "has_failure_marker",
            "has_typed_storage_marker",
            "failure_then_success",
            "typed_storage_then_success",
            "typed_marker_terminal",
        )
    }
    typed_followups = defaultdict(Counter)
    latency_values = defaultdict(list)
    trace_count = 0
    with open(
        path,
        newline="",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for row in csv.DictReader(handle):
            events = _EVENT_ID.findall(
                row.get("Features", "")
            )
            failure_positions = [
                position
                for position, event
                in enumerate(events)
                if event in _HDFS_FAILURE_EVENTS
            ]
            typed_positions = [
                position
                for position, event
                in enumerate(events)
                if event
                in _HDFS_TYPED_STORAGE_EVENTS
            ]
            last_typed_position = (
                typed_positions[-1]
                if typed_positions
                else None
            )
            features = {
                "event_count": len(events),
                "present_events": sorted(
                    set(events)
                ),
                "has_failure_marker": bool(
                    failure_positions
                ),
                "has_typed_storage_marker": bool(
                    typed_positions
                ),
                "failure_then_success": any(
                    _has_later_success(
                        events, position
                    )
                    for position
                    in failure_positions
                ),
                "typed_storage_then_success": any(
                    _has_later_success(
                        events, position
                    )
                    for position
                    in typed_positions
                ),
                "last_typed_event": (
                    events[last_typed_position]
                    if last_typed_position
                    is not None
                    else None
                ),
                "next_event_after_typed": (
                    events[
                        last_typed_position + 1
                    ]
                    if last_typed_position
                    is not None
                    and last_typed_position + 1
                    < len(events)
                    else None
                ),
                "typed_marker_terminal": (
                    last_typed_position
                    == len(events) - 1
                    if last_typed_position
                    is not None
                    else False
                ),
                "last_event": (
                    events[-1]
                    if events
                    else None
                ),
                "latency": (
                    float(row["Latency"])
                    if str(
                        row.get("Latency", "")
                    ).strip()
                    else None
                ),
            }
            # The row's truth is joined only after feature extraction.
            truth = (
                "fail"
                if str(
                    row.get("Label", "")
                ).strip().lower()
                == "fail"
                else "success"
            )
            trace_count += 1
            totals[truth] += 1
            for event in features[
                "present_events"
            ]:
                event_presence[event][
                    truth
                ] += 1
            for field, counts in (
                cross_tabs.items()
            ):
                counts[
                    (
                        truth,
                        bool(features[field]),
                    )
                ] += 1
            if (
                features[
                    "last_typed_event"
                ]
                is not None
            ):
                typed_followups[
                    (
                        features[
                            "last_typed_event"
                        ],
                        truth,
                    )
                ][
                    features[
                        "next_event_after_typed"
                    ]
                    or "<terminal>"
                ] += 1
            if features["latency"] is not None:
                latency_values[truth].append(
                    features["latency"]
                )
    associations = []
    for event, counts in event_presence.items():
        present = sum(counts.values())
        fail_count = counts["fail"]
        associations.append({
            "event_id": event,
            "support": present,
            "fail_when_present": fail_count,
            "success_when_present": counts[
                "success"
            ],
            "failure_precision": round(
                fail_count / present,
                4,
            ),
            "failure_recall": round(
                fail_count / totals["fail"],
                4,
            ) if totals["fail"] else 0.0,
            "typed_storage_family":
            _HDFS_TYPED_STORAGE_EVENTS.get(
                event
            ),
        })
    associations.sort(
        key=lambda item: (
            -item["failure_precision"],
            -item["support"],
            item["event_id"],
        )
    )

    def cross(field):
        result = cross_tabs[field]
        return {
            f"{truth}:{str(value).lower()}":
            count
            for (truth, value), count
            in sorted(result.items())
        }

    latency_by_truth = {
        truth: _summary(
            latency_values[truth]
        )
        for truth in ("fail", "success")
    }
    typed_totals = {
        truth: cross_tabs[
            "has_typed_storage_marker"
        ][(truth, True)]
        for truth in ("fail", "success")
    }
    typed_support = sum(
        typed_totals.values()
    )
    typed_followup_summary = []
    for (
        event,
        truth,
    ), followups in sorted(
        typed_followups.items()
    ):
        total = sum(followups.values())
        typed_followup_summary.append({
            "last_typed_event": event,
            "typed_storage_family":
            _HDFS_TYPED_STORAGE_EVENTS[
                event
            ],
            "truth": truth,
            "traces": total,
            "terminal": followups[
                "<terminal>"
            ],
            "top_next_events": [
                {
                    "event_id": next_event,
                    "count": count,
                }
                for next_event, count
                in followups.most_common(8)
                if next_event != "<terminal>"
            ],
        })
    return {
        "audit": "hdfs-event-outcome-feasibility/v2",
        "labels_used_during_feature_extraction": False,
        "traces": trace_count,
        "truth_counts_post_join": dict(totals),
        "feature_cross_tabs": {
            "has_failure_marker":
            cross("has_failure_marker"),
            "has_typed_storage_marker":
            cross("has_typed_storage_marker"),
            "failure_then_success":
            cross("failure_then_success"),
            "typed_storage_then_success":
            cross(
                "typed_storage_then_success"
            ),
            "typed_marker_terminal":
            cross("typed_marker_terminal"),
        },
        "typed_storage_combined_association": {
            "support": typed_support,
            "fail_when_present":
            typed_totals["fail"],
            "success_when_present":
            typed_totals["success"],
            "failure_precision": round(
                typed_totals["fail"]
                / typed_support,
                4,
            ) if typed_support else 0.0,
            "failure_recall": round(
                typed_totals["fail"]
                / totals["fail"],
                4,
            ) if totals["fail"] else 0.0,
        },
        "typed_storage_followups":
        typed_followup_summary,
        "latency_by_truth_post_join":
        latency_by_truth,
        "typed_storage_event_associations": [
            item
            for item in associations
            if item[
                "typed_storage_family"
            ]
        ],
        "top_event_associations": associations[
            :12
        ],
        "decision_note": (
            "A block outcome link is feature-feasible only if ordered "
            "failure/recovery markers distinguish post-joined outcomes "
            "without reading Label or Type during feature extraction."
        ),
    }
