"""Evaluate production grouping against curated real-log pair annotations."""

from __future__ import annotations

from collections import Counter
import json
import re

from evaluation.grouping_quality import _inferred_key


_UUID = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?![0-9a-f])"
)


def _ratio(numerator, denominator):
    if not denominator:
        return 1.0
    return round(numerator / denominator, 6)


def _current_key(side):
    return _inferred_key({
        "message": side.get("message", ""),
        "labels": side.get("labels", {}),
    })


def evaluate_real_log_pairs(candidates_path, annotations_path):
    with open(candidates_path, encoding="utf-8") as handle:
        candidates_payload = json.load(handle)
    with open(annotations_path, encoding="utf-8") as handle:
        annotations_payload = json.load(handle)
    candidates = {
        item["pair_id"]: item
        for item in candidates_payload.get("candidates", [])
    }
    annotations = annotations_payload.get("annotations", [])
    seen = set()
    duplicate_annotations = []
    missing_candidates = []
    confusion = Counter()
    dataset_confusion = {}
    mismatches = []
    for annotation in annotations:
        pair_id = str(annotation.get("pair_id", ""))
        if pair_id in seen:
            duplicate_annotations.append(pair_id)
            continue
        seen.add(pair_id)
        candidate = candidates.get(pair_id)
        if candidate is None:
            missing_candidates.append(pair_id)
            continue
        expected_same = (
            annotation.get("expected_relation")
            == "same_event_shape"
        )
        predicted_same = (
            _current_key(candidate["left"])
            == _current_key(candidate["right"])
        )
        if expected_same and predicted_same:
            outcome = "true_positive"
        elif not expected_same and predicted_same:
            outcome = "false_positive"
        elif expected_same and not predicted_same:
            outcome = "false_negative"
        else:
            outcome = "true_negative"
        confusion[outcome] += 1
        dataset = str(candidate.get("dataset", "unknown"))
        dataset_confusion.setdefault(dataset, Counter())[outcome] += 1
        if expected_same != predicted_same:
            mismatches.append({
                "pair_id": pair_id,
                "dataset": dataset,
                "expected_relation": annotation.get(
                    "expected_relation"
                ),
                "predicted_relation": (
                    "same_event_shape"
                    if predicted_same
                    else "different_event_shape"
                ),
                "reason": annotation.get("reason"),
                "left_message": candidate["left"].get("message"),
                "right_message": candidate["right"].get("message"),
                "left_group": dict(zip(
                    (
                        "service",
                        "level",
                        "error_type",
                        "event_name",
                        "status_code",
                        "event_signature",
                    ),
                    _current_key(candidate["left"]),
                )),
                "right_group": dict(zip(
                    (
                        "service",
                        "level",
                        "error_type",
                        "event_name",
                        "status_code",
                        "event_signature",
                    ),
                    _current_key(candidate["right"]),
                )),
            })
    tp = confusion["true_positive"]
    fp = confusion["false_positive"]
    fn = confusion["false_negative"]
    tn = confusion["true_negative"]
    evaluated = tp + fp + fn + tn
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    accuracy = _ratio(tp + tn, evaluated)
    serialized_candidates = json.dumps(
        candidates_payload, sort_keys=True
    )
    raw_uuid_matches = sorted(set(_UUID.findall(serialized_candidates)))
    report = {
        "suite": "real-log-pair-benchmark/v1",
        "annotation_schema_version": annotations_payload.get(
            "schema_version"
        ),
        "candidate_schema_version": candidates_payload.get(
            "schema_version"
        ),
        "review_provenance": annotations_payload.get(
            "review_provenance", {}
        ),
        "truth_exposed_to_grouping": False,
        "selection_limitations": (
            "Pairs are deliberately concentrated around volatile variants "
            "and near-neighbor boundaries. Metrics are contract accuracy on "
            "the reviewed pairs, not corpus prevalence."
        ),
        "candidate_pairs": len(candidates),
        "annotated_pairs": len(annotations),
        "evaluated_pairs": evaluated,
        "unlabelled_candidates": max(
            len(candidates) - len(seen), 0
        ),
        "missing_candidate_ids": sorted(missing_candidates),
        "duplicate_annotation_ids": sorted(duplicate_annotations),
        "raw_uuid_matches": raw_uuid_matches,
        "confusion": {
            "true_positive_same": tp,
            "false_positive_overmerge": fp,
            "false_negative_fragmentation": fn,
            "true_negative_different": tn,
        },
        "metrics": {
            "pair_precision": precision,
            "pair_recall": recall,
            "different_pair_specificity": specificity,
            "accuracy": accuracy,
        },
        "dataset_confusion": {
            dataset: {
                "true_positive_same": counts["true_positive"],
                "false_positive_overmerge": counts["false_positive"],
                "false_negative_fragmentation": counts["false_negative"],
                "true_negative_different": counts["true_negative"],
            }
            for dataset, counts in sorted(dataset_confusion.items())
        },
        "mismatches": mismatches,
    }
    report["quality_gate_passed"] = (
        evaluated == len(annotations)
        and not missing_candidates
        and not duplicate_annotations
        and not raw_uuid_matches
        and precision == 1.0
        and recall == 1.0
        and specificity == 1.0
    )
    return report

