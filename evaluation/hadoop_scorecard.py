"""Stage-by-stage Hadoop signal retention without invoking an LLM."""

from collections import Counter
from datetime import datetime
import os

from clients.loki_client import (
    representative_sample,
)
from evaluation.hadoop_dataset import (
    _pipeline_state,
    load_hadoop_application,
    load_hadoop_labels,
)
from graph.nodes.aggregate_by_labels import (
    _fingerprint,
)
from utils.evidence_pack import (
    build_evidence_pack,
)
from utils.log_normalizer import (
    normalize_logs,
)
from utils.signal_catalog import (
    SIGNAL_CATALOG_VERSION,
    detect_signals,
)


_EXPECTED = {
    "normal": (
        "job_lifecycle",
        {"succeeded"},
    ),
    "machine_down": (
        "machine_availability",
        {"unavailable"},
    ),
    "network_disconnection": (
        "network_transport",
        {
            "unreachable",
            "disconnected",
        },
    ),
    "disk_full": (
        "storage_capacity",
        {"exhausted"},
    ),
}


def _timestamp(value):
    return datetime.fromisoformat(
        str(value).replace(
            "Z", "+00:00"
        )
    )


def _coverage(records):
    timestamps = sorted(
        _timestamp(
            record["timestamp"]
        )
        for record in records
        if record.get("timestamp")
    )
    if not timestamps:
        return {
            "first": None,
            "last": None,
            "span_seconds": 0.0,
        }
    return {
        "first":
        timestamps[0].isoformat(),
        "last":
        timestamps[-1].isoformat(),
        "span_seconds": round(
            (
                timestamps[-1]
                - timestamps[0]
            ).total_seconds(),
            3,
        ),
    }


def _record_signals(records):
    rows = []
    families = Counter()
    direct_families = Counter()
    statuses = Counter()
    evidence_ids = set()
    normalized = normalize_logs(records)
    for record in normalized:
        matches = detect_signals(
            record
        )
        if not matches:
            continue
        evidence_id = record.get(
            "evidence_id"
        )
        if evidence_id:
            evidence_ids.add(
                evidence_id
            )
        for signal in matches:
            family = signal[
                "signal_family"
            ]
            families[family] += 1
            if (
                signal["directness"]
                == "direct"
            ):
                direct_families[
                    family
                ] += 1
            statuses[
                family
                + ":"
                + signal["status"]
            ] += 1
            rows.append({
                **signal,
                "source_evidence_id":
                evidence_id,
                "timestamp":
                record.get("timestamp"),
            })
    return {
        "matched_events":
        len(evidence_ids),
        "families": dict(
            sorted(families.items())
        ),
        "direct_families": dict(
            sorted(
                direct_families.items()
            )
        ),
        "statuses": dict(
            sorted(statuses.items())
        ),
        "evidence_ids": sorted(
            evidence_ids
        ),
        "matches": rows,
    }


def summarize_record_signals(
    records,
):
    """Public label-agnostic signal summary for evaluation callers."""
    return _record_signals(records)


def _group_signals(state, evidence_pack):
    families = Counter()
    direct_families = Counter()
    visible_families = Counter()
    group_ids = set()
    visible_ids = set()
    for group in state.get(
        "log_groups", []
    ) or []:
        group_id = group.get(
            "event_id"
        )
        signals = group.get(
            "signals", []
        ) or []
        if signals and group_id:
            group_ids.add(group_id)
        is_visible = bool(
            group_id
            and group_id
            in evidence_pack
        )
        if is_visible:
            visible_ids.add(
                group_id
            )
        for signal in signals:
            family = signal[
                "signal_family"
            ]
            families[family] += 1
            if (
                signal["directness"]
                == "direct"
            ):
                direct_families[
                    family
                ] += 1
            if is_visible:
                visible_families[
                    family
                ] += 1
    return {
        "group_families": dict(
            sorted(families.items())
        ),
        "direct_group_families":
        dict(
            sorted(
                direct_families.items()
            )
        ),
        "visible_pack_families":
        dict(
            sorted(
                visible_families.items()
            )
        ),
        "signal_group_ids": sorted(
            group_ids
        ),
        "visible_signal_group_ids":
        sorted(visible_ids),
    }


def _recoverable(
    outcome,
    record_summary,
):
    expected = _EXPECTED.get(
        outcome
    )
    if not expected:
        return False
    family, statuses = expected
    return any(
        key
        == family + ":" + status
        and count > 0
        for key, count in (
            record_summary[
                "statuses"
            ].items()
        )
        for status in statuses
    )


def expected_outcome_recoverable(
    outcome,
    record_summary,
):
    """Join a held-out outcome to an already-built observable summary."""
    return _recoverable(
        outcome,
        record_summary,
    )


def _group_recoverable(
    outcome,
    state,
    evidence_pack=None,
):
    expected = _EXPECTED.get(
        outcome
    )
    if not expected:
        return False
    family, statuses = expected
    for group in state.get(
        "log_groups", []
    ) or []:
        if (
            evidence_pack is not None
            and group.get("event_id")
            not in evidence_pack
        ):
            continue
        for signal in group.get(
            "signals", []
        ) or []:
            if (
                signal["signal_family"]
                == family
                and signal["status"]
                in statuses
            ):
                return True
    return False


def evaluate_hadoop_stages(
    root,
    sample_limit=200,
):
    """Join truth only after each case's pipeline artifacts are complete."""
    labels = load_hadoop_labels(root)
    application_ids = sorted(
        application_id
        for application_id
        in labels
        if os.path.isdir(
            os.path.join(
                root,
                application_id,
            )
        )
    )
    cases = []
    by_truth = {}
    contradiction_count = 0
    for application_id in (
        application_ids
    ):
        records, stats = (
            load_hadoop_application(
                root,
                application_id,
            )
        )
        sampled = (
            representative_sample(
                records,
                sample_limit,
            )
        )
        state = _pipeline_state(
            sampled,
            len(records),
        )
        evidence_pack = (
            build_evidence_pack(state)
        )
        raw_signals = (
            _record_signals(records)
        )
        sample_signals = (
            _record_signals(sampled)
        )
        grouped = _group_signals(
            state,
            evidence_pack,
        )

        # Truth joins here, after parsing, sampling, grouping and pack creation.
        metadata = labels[
            application_id
        ]
        outcome = metadata["outcome"]
        raw_recoverable = (
            _recoverable(
                outcome,
                raw_signals,
            )
        )
        sample_recoverable = (
            _recoverable(
                outcome,
                sample_signals,
            )
        )
        group_recoverable = (
            _group_recoverable(
                outcome,
                state,
            )
        )
        pack_recoverable = (
            _group_recoverable(
                outcome,
                state,
                evidence_pack,
            )
        )
        assessment = state.get(
            "deterministic_assessment",
            {},
        ) or {}
        sufficient_without_candidate = (
            not assessment.get(
                "candidates"
            )
            and "sufficient"
            in str(
                assessment.get(
                    "expansion_reason", ""
                )
            ).lower()
        )
        if sufficient_without_candidate:
            contradiction_count += 1
        raw_ids = set(
            raw_signals[
                "evidence_ids"
            ]
        )
        sample_ids = set(
            sample_signals[
                "evidence_ids"
            ]
        )
        raw_time = _coverage(
            records
        )
        sample_time = _coverage(
            sampled
        )
        raw_span = raw_time[
            "span_seconds"
        ]
        temporal_ratio = (
            round(
                min(
                    sample_time[
                        "span_seconds"
                    ]
                    / raw_span,
                    1.0,
                ),
                4,
            )
            if raw_span
            else 1.0
        )
        case = {
            "application_id":
            application_id,
            "workload":
            metadata["workload"],
            "truth": outcome,
            "source_events":
            len(records),
            "sampled_events":
            len(sampled),
            "log_files":
            stats["log_files"],
            "raw_time_coverage":
            raw_time,
            "sample_time_coverage":
            sample_time,
            "temporal_span_retention":
            temporal_ratio,
            "raw_event_families":
            len({
                _fingerprint(
                    record.get(
                        "message"
                    )
                )
                for record in records
            }),
            "sample_event_families":
            len({
                _fingerprint(
                    record.get(
                        "message"
                    )
                )
                for record in sampled
            }),
            "raw_signals": raw_signals,
            "sample_signals":
            sample_signals,
            "signal_events_retained":
            len(raw_ids & sample_ids),
            "signal_events_dropped":
            len(raw_ids - sample_ids),
            "dropped_signal_evidence_ids":
            sorted(raw_ids - sample_ids),
            "group_and_pack_signals":
            grouped,
            "evidence_pack_chars":
            len(evidence_pack),
            "raw_recoverable":
            raw_recoverable,
            "sample_recoverable":
            sample_recoverable,
            "group_recoverable":
            group_recoverable,
            "pack_recoverable":
            pack_recoverable,
            "assessment_contract": {
                "candidate_count":
                len(
                    assessment.get(
                        "candidates", []
                    )
                    or []
                ),
                "abstain":
                assessment.get(
                    "abstain"
                ),
                "expansion_reason":
                assessment.get(
                    "expansion_reason"
                ),
                "sufficient_without_candidate":
                sufficient_without_candidate,
            },
            "truth_exposed_to_pipeline":
            False,
        }
        cases.append(case)
        bucket = by_truth.setdefault(
            outcome,
            Counter(),
        )
        bucket["cases"] += 1
        bucket["raw_recoverable"] += (
            int(raw_recoverable)
        )
        bucket["sample_recoverable"] += (
            int(sample_recoverable)
        )
        bucket["group_recoverable"] += (
            int(group_recoverable)
        )
        bucket["pack_recoverable"] += (
            int(pack_recoverable)
        )

    raw_recoverable_total = sum(
        int(
            case["raw_recoverable"]
        )
        for case in cases
    )
    pack_recoverable_total = sum(
        int(
            case["pack_recoverable"]
        )
        for case in cases
    )
    return {
        "evaluation":
        "hadoop_stage_scorecard_v1",
        "signal_catalog_version":
        SIGNAL_CATALOG_VERSION,
        "applications_total":
        len(cases),
        "sample_limit_per_application":
        sample_limit,
        "truth_exposed_to_pipeline":
        False,
        "summary": {
            "raw_recoverable_cases":
            raw_recoverable_total,
            "sample_recoverable_cases":
            sum(
                int(
                    case[
                        "sample_recoverable"
                    ]
                )
                for case in cases
            ),
            "group_recoverable_cases":
            sum(
                int(
                    case[
                        "group_recoverable"
                    ]
                )
                for case in cases
            ),
            "pack_recoverable_cases":
            pack_recoverable_total,
            "recoverable_pack_retention":
            (
                round(
                    pack_recoverable_total
                    / raw_recoverable_total,
                    4,
                )
                if raw_recoverable_total
                else 0.0
            ),
            "assessment_contradictions":
            contradiction_count,
        },
        "by_truth": {
            truth: dict(counts)
            for truth, counts in sorted(
                by_truth.items()
            )
        },
        "cases": cases,
    }
