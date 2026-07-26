"""Generate deterministic, unlabelled review candidates from real log corpora."""

from __future__ import annotations

import argparse
from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import json
import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.distributed_log_datasets import (
    load_bgl_cases,
    load_openstack_cases,
)
from evaluation.grouping_quality import _inferred_key, _normalized_records
from graph.nodes.aggregate_by_labels import AGGREGATION_KEYS


def _digest(*values):
    return hashlib.sha256(
        "|".join(str(value) for value in values).encode("utf-8")
    ).hexdigest()[:16]


def _safe_record(dataset, case_key, index, raw, normalized):
    labels = normalized.get("labels", {}) or {}
    raw_labels = raw.get("labels", {}) or {}
    message = str(normalized.get("message", ""))[:1000]
    return {
        "record_id": "record-" + _digest(
            dataset,
            case_key,
            index,
            normalized.get("timestamp"),
            message,
        ),
        "case_ref": "case-" + _digest(dataset, case_key),
        "message": message,
        "labels": {
            key: value
            for key, value in {
                "service": labels.get("service"),
                "level": labels.get("level"),
                "event_name": labels.get("event_name"),
                "source_component": raw_labels.get("source_component"),
            }.items()
            if value not in (None, "")
        },
        "inferred_group": {
            name: value
            for name, value in zip(
                AGGREGATION_KEYS, _inferred_key(normalized)
            )
            if value not in (None, "")
        },
    }


def _load_records(bgl_root, openstack_root):
    datasets = {}
    bgl, bgl_stats = load_bgl_cases(bgl_root, per_label=8)
    openstack, openstack_stats = load_openstack_cases(
        openstack_root, normal_limit=8
    )
    for dataset, cases, stats in (
        ("bgl", bgl, bgl_stats),
        ("openstack", openstack, openstack_stats),
    ):
        rows = []
        for case_key, case in sorted(cases.items()):
            raw_records = case["records"]
            normalized = _normalized_records(raw_records)
            for index, (raw, item) in enumerate(
                zip(raw_records, normalized), 1
            ):
                rows.append(
                    _safe_record(dataset, case_key, index, raw, item)
                )
        datasets[dataset] = {
            "rows": rows,
            "source_stats": stats,
        }
    return datasets


def _group_key(record):
    group = record["inferred_group"]
    return tuple(group.get(name, "") for name in AGGREGATION_KEYS)


def _candidate(pair_type, dataset, left, right):
    ordered = sorted(
        (left, right), key=lambda item: item["record_id"]
    )
    left, right = ordered
    similarity = SequenceMatcher(
        None,
        left["message"].lower(),
        right["message"].lower(),
        autojunk=False,
    ).ratio()
    return {
        "pair_id": "pair-" + _digest(
            dataset, left["record_id"], right["record_id"]
        ),
        "dataset": dataset,
        "candidate_type": pair_type,
        "production_same_group": _group_key(left) == _group_key(right),
        "message_similarity": round(similarity, 6),
        "left": left,
        "right": right,
    }


def _same_group_candidates(dataset, records, limit):
    groups = defaultdict(dict)
    for record in records:
        groups[_group_key(record)].setdefault(
            record["message"], record
        )
    candidates = []
    for _, by_message in sorted(groups.items(), key=lambda item: str(item[0])):
        variants = sorted(
            by_message.values(), key=lambda item: item["record_id"]
        )
        if len(variants) < 2:
            continue
        candidates.append(
            _candidate("same_group_variant", dataset, variants[0], variants[-1])
        )
    candidates.sort(
        key=lambda item: (
            item["message_similarity"],
            item["pair_id"],
        )
    )
    return candidates[:limit]


def _near_group_candidates(dataset, records, limit):
    representatives = {}
    for record in records:
        representatives.setdefault(_group_key(record), record)
    buckets = defaultdict(list)
    for key, record in representatives.items():
        labels = record["labels"]
        buckets[
            (
                labels.get("service", ""),
                labels.get("level", ""),
                labels.get("event_name", ""),
            )
        ].append((key, record))
    candidates = []
    for bucket in buckets.values():
        for index, (left_key, left) in enumerate(bucket):
            scored = []
            for right_key, right in bucket[index + 1:]:
                if left_key == right_key:
                    continue
                similarity = SequenceMatcher(
                    None,
                    left["message"].lower(),
                    right["message"].lower(),
                    autojunk=False,
                ).ratio()
                if similarity >= 0.55:
                    scored.append((similarity, right))
            if scored:
                _, right = max(
                    scored,
                    key=lambda item: (
                        item[0], item[1]["record_id"]
                    ),
                )
                candidates.append(
                    _candidate(
                        "nearby_different_group",
                        dataset,
                        left,
                        right,
                    )
                )
    unique = {}
    for item in candidates:
        unique[item["pair_id"]] = item
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            -item["message_similarity"],
            item["pair_id"],
        ),
    )
    return ordered[:limit]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bgl-path", default=os.path.join(_ROOT, "..", "BGL")
    )
    parser.add_argument(
        "--openstack-path",
        default=os.path.join(_ROOT, "..", "OpenStack"),
    )
    parser.add_argument("--per-type", type=int, default=40)
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT, "output", "real-log-pair-candidates.json"
        ),
    )
    args = parser.parse_args()
    datasets = _load_records(
        os.path.abspath(args.bgl_path),
        os.path.abspath(args.openstack_path),
    )
    candidates = []
    summaries = {}
    for dataset, payload in datasets.items():
        rows = payload["rows"]
        same = _same_group_candidates(
            dataset, rows, max(args.per_type, 1)
        )
        different = _near_group_candidates(
            dataset, rows, max(args.per_type, 1)
        )
        candidates.extend(same)
        candidates.extend(different)
        summaries[dataset] = {
            "selected_records": len(rows),
            "same_group_candidates": len(same),
            "near_group_candidates": len(different),
            "source_stats": payload["source_stats"],
        }
    report = {
        "schema_version": "real-log-pair-candidates/v1",
        "labels_present": False,
        "privacy_boundary": (
            "Only adapter-minimized messages and hashed case/record references "
            "are exported."
        ),
        "datasets": summaries,
        "candidates": sorted(
            candidates,
            key=lambda item: (item["dataset"], item["candidate_type"], item["pair_id"]),
        ),
    }
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "output": output,
        "candidates": len(report["candidates"]),
        "datasets": summaries,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
