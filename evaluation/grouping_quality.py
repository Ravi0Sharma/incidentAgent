"""Label-last grouping and thinning quality against public log corpora."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
import re

from clients.loki_client import representative_sample
from evaluation.distributed_log_datasets import load_hdfs_v3_cases
from evaluation.public_log_dataset import (
    load_loghub_hdfs_csv,
    load_loghub_spark_csv,
    parse_loghub_spark_raw,
    spark_record_signature,
)
from graph.nodes.aggregate_by_labels import AGGREGATION_KEYS, _fingerprint
from graph.nodes.normalize_logs import normalize_logs


_HIGH_SIGNAL = re.compile(
    r"(?i)(?:error|exception|fatal|panic|timeout|timed\s*out|"
    r"failed|failure|lost|unreachable|disconnect|refused|"
    r"corrupt|checksum|no\s+space|read-only|killed)"
)
_TRACEBENCH_DIGIT_PATTERN = re.compile(r"[0-9][^a-z^/]*")


def _comb2(value):
    return value * (value - 1) // 2


def _round_ratio(numerator, denominator):
    if not denominator:
        return 1.0
    return round(numerator / denominator, 6)


def _normalized_records(records):
    return normalize_logs({"logs": records})["logs"]


def _inferred_key(record):
    labels = record.get("labels", {}) or {}
    signature = (
        labels.get("error_fingerprint")
        or _fingerprint(record.get("message"))
    )
    values = {
        "service": labels.get("service", ""),
        "level": labels.get("level", ""),
        "error_type": labels.get("error_type", ""),
        "event_name": labels.get("event_name", ""),
        "status_code": labels.get("status_code", ""),
        "event_signature": signature,
    }
    return tuple(values[key] for key in AGGREGATION_KEYS)


def _is_high_signal(record):
    labels = record.get("labels", {}) or {}
    level = str(labels.get("level", "")).lower()
    return level in {
        "warn", "warning", "error", "fatal", "critical",
    } or bool(_HIGH_SIGNAL.search(str(record.get("message", ""))))


def _example_key(key):
    return {
        name: value
        for name, value in zip(AGGREGATION_KEYS, key)
        if value not in (None, "")
    }


def evaluate_grouping_rows(
    rows,
    *,
    dataset,
    truth_kind,
    sample_limit,
    truth_limitations,
):
    """Measure grouping before joining the held-out source event labels."""
    normalized_by_case = defaultdict(list)
    truth_by_case = defaultdict(list)
    raw_by_case = defaultdict(list)
    for case_id, record, truth_label in rows:
        raw_by_case[case_id].append(record)
        truth_by_case[case_id].append(str(truth_label))
    for case_id, records in raw_by_case.items():
        normalized_by_case[case_id] = _normalized_records(records)

    inferred_rows = []
    for case_id in sorted(normalized_by_case):
        normalized = normalized_by_case[case_id]
        truths = truth_by_case[case_id]
        if len(normalized) != len(truths):
            raise ValueError("normalization changed row cardinality")
        # The inferred key is complete before source truth is joined here.
        inferred_rows.extend(
            (case_id, _inferred_key(record), truth, record)
            for record, truth in zip(normalized, truths)
        )

    inferred_counts = defaultdict(Counter)
    truth_counts = Counter()
    truth_to_groups = defaultdict(Counter)
    example_messages = defaultdict(dict)
    for case_id, inferred, truth, record in inferred_rows:
        group_key = (case_id, inferred)
        truth_key = (case_id, truth)
        inferred_counts[group_key][truth] += 1
        truth_counts[truth_key] += 1
        truth_to_groups[truth_key][inferred] += 1
        example_messages[group_key].setdefault(
            truth,
            str(record.get("message", ""))[:500],
        )

    true_positive_pairs = sum(
        _comb2(count)
        for counts in inferred_counts.values()
        for count in counts.values()
    )
    predicted_pairs = sum(
        _comb2(sum(counts.values()))
        for counts in inferred_counts.values()
    )
    truth_pairs = sum(_comb2(count) for count in truth_counts.values())
    false_positive_pairs = predicted_pairs - true_positive_pairs
    false_negative_pairs = truth_pairs - true_positive_pairs
    pair_precision = _round_ratio(true_positive_pairs, predicted_pairs)
    pair_recall = _round_ratio(true_positive_pairs, truth_pairs)
    pair_f1 = _round_ratio(
        2 * pair_precision * pair_recall,
        pair_precision + pair_recall,
    )
    row_count = len(inferred_rows)
    dominant_rows = sum(
        max(counts.values())
        for counts in inferred_counts.values()
        if counts
    )
    fragmented = sorted(
        (
            len(groups),
            truth_key,
            groups,
        )
        for truth_key, groups in truth_to_groups.items()
    )
    collision_groups = [
        (group_key, counts)
        for group_key, counts in inferred_counts.items()
        if len(counts) > 1
    ]
    collision_groups.sort(
        key=lambda item: (
            -sum(item[1].values()),
            item[0][0],
            str(item[0][1]),
        )
    )
    fragmented.sort(
        key=lambda item: (
            -item[0],
            item[1][0],
            item[1][1],
        )
    )

    source_labels = {truth for _, _, truth, _ in inferred_rows}
    source_label_counts = Counter(
        truth for _, _, truth, _ in inferred_rows
    )
    high_signal_labels = {
        truth
        for _, _, truth, record in inferred_rows
        if _is_high_signal(record)
    }
    sampled_labels = set()
    sampled_high_signal_labels = set()
    sampled_rows = 0
    for case_id in sorted(raw_by_case):
        records = raw_by_case[case_id]
        truths = truth_by_case[case_id]
        truth_by_line = {
            str(
                (record.get("connector_metadata", {}) or {}).get(
                    "source_line_id", index
                )
            ): truth
            for index, (record, truth) in enumerate(zip(records, truths))
        }
        sampled = representative_sample(records, sample_limit)
        sampled_rows += len(sampled)
        for index, record in enumerate(sampled):
            line_id = str(
                (record.get("connector_metadata", {}) or {}).get(
                    "source_line_id", index
                )
            )
            truth = truth_by_line.get(line_id)
            if truth is None:
                continue
            sampled_labels.add(truth)
            if _is_high_signal(record):
                sampled_high_signal_labels.add(truth)

    fragmentation_values = [item[0] for item in fragmented]
    missed_labels = sorted(
        source_labels - sampled_labels,
        key=lambda label: (
            source_label_counts[label],
            label,
        ),
    )
    report = {
        "dataset": dataset,
        "truth_kind": truth_kind,
        "truth_joined_after_inference": True,
        "truth_limitations": truth_limitations,
        "case_count": len(raw_by_case),
        "source_rows": row_count,
        "sample_limit_per_case": sample_limit,
        "sampled_rows": sampled_rows,
        "source_event_labels": len(source_labels),
        "sampled_event_labels": len(sampled_labels),
        "missed_event_labels": [
            {
                "source_label": label,
                "source_rows": source_label_counts[label],
                "high_signal": label in high_signal_labels,
            }
            for label in missed_labels[:25]
        ],
        "event_label_coverage": _round_ratio(
            len(sampled_labels), len(source_labels)
        ),
        "high_signal_event_labels": len(high_signal_labels),
        "sampled_high_signal_event_labels": len(
            sampled_high_signal_labels & high_signal_labels
        ),
        "high_signal_label_coverage": _round_ratio(
            len(sampled_high_signal_labels & high_signal_labels),
            len(high_signal_labels),
        ),
        "rare_event_label_coverage": _round_ratio(
            len({
                label
                for label, count in source_label_counts.items()
                if count <= 10 and label in sampled_labels
            }),
            len({
                label
                for label, count in source_label_counts.items()
                if count <= 10
            }),
        ),
        "inferred_group_count": len(inferred_counts),
        "weighted_source_label_purity": _round_ratio(
            dominant_rows, row_count
        ),
        "collision_group_count": len(collision_groups),
        "fragmented_source_label_count": sum(
            1 for value in fragmentation_values if value > 1
        ),
        "mean_groups_per_source_label": (
            round(
                sum(fragmentation_values) / len(fragmentation_values),
                4,
            )
            if fragmentation_values
            else 0.0
        ),
        "max_groups_per_source_label": max(
            fragmentation_values, default=0
        ),
        "pairwise": {
            "true_positive_pairs": true_positive_pairs,
            "false_positive_pairs": false_positive_pairs,
            "false_negative_pairs": false_negative_pairs,
            "precision": pair_precision,
            "recall": pair_recall,
            "f1": pair_f1,
        },
        "top_collision_examples": [
            {
                "case_id": case_id,
                "inferred_group": _example_key(inferred),
                "source_label_counts": dict(counts.most_common()),
                "message_by_source_label": example_messages[
                    (case_id, inferred)
                ],
            }
            for (case_id, inferred), counts in collision_groups[:5]
        ],
        "top_fragmentation_examples": [
            {
                "case_id": truth_key[0],
                "source_label": truth_key[1],
                "inferred_group_count": group_count,
                "largest_group_sizes": sorted(
                    groups.values(), reverse=True
                )[:10],
                "inferred_groups": [
                    _example_key(key)
                    for key, _ in groups.most_common(5)
                ],
            }
            for group_count, truth_key, groups in fragmented[:5]
        ],
    }
    return report


def evaluate_hdfs_2k_grouping(path, sample_limit=200):
    records, source_rows = load_loghub_hdfs_csv(path)
    rows = [
        ("hdfs-2k", record, source["event_id"])
        for record, source in zip(records, source_rows)
    ]
    report = evaluate_grouping_rows(
        rows,
        dataset="loghub_hdfs_2k",
        truth_kind="upstream_human_template_id",
        sample_limit=sample_limit,
        truth_limitations=(
            "EventId labels log templates, not incident causality or "
            "whether two templates may be operationally equivalent."
        ),
    )
    thresholds = {
        "minimum_pairwise_precision": 0.98,
        "minimum_pairwise_recall": 0.90,
        "minimum_event_label_coverage": 1.0,
        "minimum_high_signal_label_coverage": 1.0,
        "minimum_rare_event_label_coverage": 1.0,
    }
    report["quality_thresholds"] = thresholds
    report["quality_gate_passed"] = (
        report["pairwise"]["precision"]
        >= thresholds["minimum_pairwise_precision"]
        and report["pairwise"]["recall"]
        >= thresholds["minimum_pairwise_recall"]
        and report["event_label_coverage"]
        >= thresholds["minimum_event_label_coverage"]
        and report["high_signal_label_coverage"]
        >= thresholds["minimum_high_signal_label_coverage"]
        and report["rare_event_label_coverage"]
        >= thresholds["minimum_rare_event_label_coverage"]
    )
    return report


def _spark_review_pair_sample(
    records,
    source_rows,
    *,
    same_limit=20,
    different_limit=20,
):
    """Create an inspectable label-last subset of the full pair scoring."""
    normalized = _normalized_records(records)
    inferred = [
        _inferred_key(record)
        for record in normalized
    ]
    by_label = defaultdict(list)
    for index, source in enumerate(
        source_rows
    ):
        by_label[str(source["event_id"])].append(
            index
        )

    same_candidates = []
    for label, indexes in sorted(
        by_label.items()
    ):
        for left, right in zip(
            indexes,
            indexes[1:],
        ):
            same_candidates.append(
                (label, left, right)
            )
    exemplars = [
        (label, indexes[0])
        for label, indexes in sorted(
            by_label.items()
        )
        if indexes
    ]
    different_candidates = []
    for left_position, (
        left_label,
        left,
    ) in enumerate(exemplars):
        for right_label, right in (
            exemplars[left_position + 1:]
        ):
            different_candidates.append((
                left_label
                + "|"
                + right_label,
                left,
                right,
            ))

    def select(candidates, limit, relation):
        ranked = sorted(
            candidates,
            key=lambda item: hashlib.sha256(
                (
                    relation
                    + "|"
                    + str(item[0])
                    + "|"
                    + str(item[1])
                    + "|"
                    + str(item[2])
                ).encode("utf-8")
            ).hexdigest(),
        )
        output = []
        for label, left, right in ranked[
            :limit
        ]:
            actual_same = (
                inferred[left]
                == inferred[right]
            )
            expected_same = (
                relation
                == "same_source_template"
            )
            output.append({
                "pair_id": hashlib.sha256(
                    (
                        relation
                        + "|"
                        + str(left)
                        + "|"
                        + str(right)
                    ).encode("utf-8")
                ).hexdigest()[:12],
                "expected_relation":
                relation,
                "actual_relation": (
                    "same_inferred_group"
                    if actual_same
                    else "different_inferred_group"
                ),
                "correct":
                actual_same == expected_same,
                "source_label_scope":
                str(label),
                "left": {
                    "line_id": (
                        records[left].get(
                            "connector_metadata",
                            {},
                        )
                        or {}
                    ).get("source_line_id"),
                    "message":
                    records[left]["message"][
                        :300
                    ],
                },
                "right": {
                    "line_id": (
                        records[right].get(
                            "connector_metadata",
                            {},
                        )
                        or {}
                    ).get("source_line_id"),
                    "message":
                    records[right]["message"][
                        :300
                    ],
                },
            })
        return output

    pairs = (
        select(
            same_candidates,
            same_limit,
            "same_source_template",
        )
        + select(
            different_candidates,
            different_limit,
            "different_source_template",
        )
    )
    return {
        "selection":
        "deterministic_hash_after_label_blind_inference",
        "truth_joined_after_inference": True,
        "requested_same_pairs":
        same_limit,
        "requested_different_pairs":
        different_limit,
        "evaluated_pairs": len(pairs),
        "correct_pairs": sum(
            item["correct"]
            for item in pairs
        ),
        "accuracy": _round_ratio(
            sum(
                item["correct"]
                for item in pairs
            ),
            len(pairs),
        ),
        "pairs": pairs,
    }


def evaluate_spark_2k_grouping(
    structured_path,
    raw_path,
    sample_limit=200,
):
    """Evaluate Spark parsing, thinning, and grouping without source labels."""
    records, source_rows = (
        load_loghub_spark_csv(
            structured_path
        )
    )
    raw_records, unparsed = (
        parse_loghub_spark_raw(
            raw_path
        )
    )
    rows = [
        (
            "spark-2k",
            record,
            source["event_id"],
        )
        for record, source in zip(
            records,
            source_rows,
        )
    ]
    report = evaluate_grouping_rows(
        rows,
        dataset="loghub_spark_2k",
        truth_kind=(
            "upstream_human_template_id"
        ),
        sample_limit=sample_limit,
        truth_limitations=(
            "EventId labels log templates, not failures, incident "
            "causality, or operational equivalence. The official 2k "
            "sample contains only INFO rows."
        ),
    )
    structured_signatures = [
        spark_record_signature(record)
        for record in records
    ]
    raw_signatures = [
        spark_record_signature(record)
        for record in raw_records
    ]
    parser_coverage = _round_ratio(
        len(raw_records),
        len(raw_records) + len(unparsed),
    )
    adapter_equivalent = (
        raw_signatures
        == structured_signatures
    )
    levels = Counter(
        str(
            (
                record.get("labels", {})
                or {}
            ).get("level", "unknown")
        )
        for record in records
    )
    thresholds = {
        "minimum_raw_parser_coverage":
        1.0,
        "require_raw_structured_equivalence":
        True,
        "minimum_pairwise_precision":
        0.98,
        "minimum_pairwise_recall":
        0.90,
        "minimum_event_label_coverage":
        1.0,
        "minimum_rare_event_label_coverage":
        1.0,
    }
    report.update({
        "raw_source_lines":
        len(raw_records) + len(unparsed),
        "raw_parsed_lines":
        len(raw_records),
        "raw_unparsed_lines":
        len(unparsed),
        "raw_unparsed_examples":
        unparsed[:5],
        "raw_parser_coverage":
        parser_coverage,
        "raw_structured_equivalent":
        adapter_equivalent,
        "source_level_counts":
        dict(sorted(levels.items())),
        "review_pair_sample":
        _spark_review_pair_sample(
            records,
            source_rows,
        ),
        "quality_thresholds":
        thresholds,
    })
    report["quality_gate_passed"] = (
        parser_coverage
        >= thresholds[
            "minimum_raw_parser_coverage"
        ]
        and adapter_equivalent
        is thresholds[
            "require_raw_structured_equivalence"
        ]
        and report["pairwise"]["precision"]
        >= thresholds[
            "minimum_pairwise_precision"
        ]
        and report["pairwise"]["recall"]
        >= thresholds[
            "minimum_pairwise_recall"
        ]
        and report["event_label_coverage"]
        >= thresholds[
            "minimum_event_label_coverage"
        ]
        and report[
            "rare_event_label_coverage"
        ]
        >= thresholds[
            "minimum_rare_event_label_coverage"
        ]
    )
    return report


def _tracebench_source_event_label(row):
    description = str(row.get("Description", ""))
    description = _TRACEBENCH_DIGIT_PATTERN.sub("", description.lower())
    return str(row.get("OpName", "")) + "+" + description


def _tracebench_truth_by_line(path, task_id):
    labels = {}
    with open(
        path,
        newline="",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, row in enumerate(csv.DictReader(handle), 2):
            if str(row.get("TaskID", "")) == task_id:
                labels[str(line_number)] = _tracebench_source_event_label(row)
    return labels


def evaluate_hdfs_v3_grouping(root, sample_limit=200, per_cohort=8):
    cases, source_stats = load_hdfs_v3_cases(
        root, per_cohort=per_cohort
    )
    rows = []
    missing_truth_rows = 0
    for case_key, case in sorted(cases.items()):
        directory_name, task_id = case_key.split("|", 1)
        truth_by_line = _tracebench_truth_by_line(
            os.path.join(
                root, "tracebench", directory_name, "event.csv"
            ),
            task_id,
        )
        for record in case["records"]:
            line_id = str(
                (record.get("connector_metadata", {}) or {}).get(
                    "source_line_id", ""
                )
            )
            truth = truth_by_line.get(line_id)
            if truth is None:
                missing_truth_rows += 1
                continue
            rows.append((case_key, record, truth))
    report = evaluate_grouping_rows(
        rows,
        dataset="hdfs_v3_tracebench",
        truth_kind="upstream_preprocessor_event_proxy",
        sample_limit=sample_limit,
        truth_limitations=(
            "The upstream event proxy removes digit-led fragments with a "
            "heuristic regex. It is useful for diagnostics but is not a "
            "human-reviewed grouping gold set."
        ),
    )
    report["adapter_source_stats"] = source_stats
    report["missing_truth_rows"] = missing_truth_rows
    report["quality_gate_passed"] = None
    report["quality_gate_reason"] = (
        "diagnostic_only_because_upstream_event_proxy_is_not_human_reviewed"
    )
    return report


def evaluate_controlled_grouping(path, sample_limit=200):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    rows = []
    for case in payload.get("cases", []):
        case_id = str(case.get("case_id", "controlled"))
        for index, item in enumerate(case.get("records", []), 1):
            record = {
                "timestamp": item.get("timestamp"),
                "message": item.get("message", ""),
                "labels": item.get("labels", {}),
                "connector_metadata": {
                    "source": "controlled_grouping_contract",
                    "source_dataset": "controlled_grouping_contract",
                    "source_line_id": (
                        f"{case_id}:{index}"
                    ),
                },
            }
            rows.append((
                case_id,
                record,
                item.get("source_event_label", ""),
            ))
    report = evaluate_grouping_rows(
        rows,
        dataset="controlled_grouping_contract",
        truth_kind="project_reviewed_operational_event_label",
        sample_limit=sample_limit,
        truth_limitations=(
            "Controlled cases complement missing application-log semantics; "
            "they do not measure public-corpus or production prevalence."
        ),
    )
    thresholds = {
        "minimum_pairwise_precision": 1.0,
        "minimum_pairwise_recall": 1.0,
        "minimum_event_label_coverage": 1.0,
    }
    report["fixture_schema_version"] = payload.get("schema_version")
    report["quality_thresholds"] = thresholds
    report["quality_gate_passed"] = (
        report["pairwise"]["precision"] == 1.0
        and report["pairwise"]["recall"] == 1.0
        and report["event_label_coverage"] == 1.0
    )
    return report
