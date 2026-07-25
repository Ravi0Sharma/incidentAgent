#!/usr/bin/env python3
"""Evaluate bounded LogHub 2.0 windows through grouping and pre-review."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation.distributed_log_datasets import _run_case
from evaluation.loghub2_windows import (
    evaluate_template_grouping,
    load_loghub2_zookeeper_cases,
    load_spark_signal_cases,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_pre_review(
    dataset,
    cases,
    *,
    sample_limit,
    html_dir,
):
    results = []
    for identifier, spec in sorted(cases.items()):
        if not spec["records"]:
            continue
        results.append(_run_case(
            dataset=dataset,
            identifier=identifier,
            truth=spec["truth"],
            records=spec["records"],
            sample_limit=sample_limit,
            html_dir=str(html_dir),
            case_metadata={
                key: value
                for key, value in spec.items()
                if key not in {"truth", "records"}
            },
        ))
    return results


def _pre_review_metrics(cases):
    return {
        "cases": len(cases),
        "review_status_counts": dict(Counter(
            case["review_status"] for case in cases
        )),
        "grounding_passed": sum(
            case["grounding_passed"] for case in cases
        ),
        "unknown_evidence_ids": sum(
            case["unknown_evidence_ids"] for case in cases
        ),
        "cases_with_observed_signals": sum(
            bool(case["observed_signal_count"])
            for case in cases
        ),
        "cases_with_candidates": sum(
            bool(case["candidate_categories"])
            for case in cases
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    default_root = REPO_ROOT.parent / "Loghub-2.0" / "extracted"
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=default_root,
    )
    parser.add_argument("--spark-cases", type=int, default=6)
    parser.add_argument("--spark-radius", type=int, default=40)
    parser.add_argument("--zookeeper-per-cohort", type=int, default=3)
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-windows.json",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-windows" / "reviews",
    )
    args = parser.parse_args()

    spark_root = args.dataset_root / "Spark" / "Spark"
    zookeeper_root = args.dataset_root / "Zookeeper" / "Zookeeper"
    spark_raw = spark_root / "Spark_full.log"
    spark_structured = spark_root / "Spark_full.log_structured.csv"
    zookeeper_raw = zookeeper_root / "Zookeeper_full.log"
    zookeeper_structured = (
        zookeeper_root / "Zookeeper_full.log_structured.csv"
    )
    for path in (
        spark_raw,
        spark_structured,
        zookeeper_raw,
        zookeeper_structured,
    ):
        if not path.is_file():
            parser.error(f"required LogHub 2.0 file missing: {path}")

    spark_cases, spark_stats = load_spark_signal_cases(
        str(spark_raw),
        case_limit=args.spark_cases,
        radius=args.spark_radius,
    )
    zookeeper_cases, zookeeper_stats = (
        load_loghub2_zookeeper_cases(
            str(zookeeper_raw),
            per_cohort=args.zookeeper_per_cohort,
        )
    )
    spark_grouping = evaluate_template_grouping(
        spark_cases,
        str(spark_structured),
        dataset="loghub2_spark_signal_windows",
        sample_limit=args.sample_limit,
    )
    zookeeper_grouping = evaluate_template_grouping(
        zookeeper_cases,
        str(zookeeper_structured),
        dataset="loghub2_zookeeper_windows",
        sample_limit=args.sample_limit,
    )

    args.html_dir.mkdir(parents=True, exist_ok=True)
    spark_reviews = _run_pre_review(
        "spark",
        spark_cases,
        sample_limit=max(args.sample_limit, 1),
        html_dir=args.html_dir / "spark",
    )
    zookeeper_reviews = _run_pre_review(
        "zookeeper",
        zookeeper_cases,
        sample_limit=max(args.sample_limit, 1),
        html_dir=args.html_dir / "zookeeper",
    )

    structural_gate = all((
        spark_stats.get("unparsed_lines", 0) == 0,
        spark_stats.get("selected_without_timestamp", 0) == 0,
        spark_grouping["missing_template_truth_rows"] == 0,
        zookeeper_grouping["missing_template_truth_rows"] == 0,
        all(
            case["grounding_passed"]
            and case["unknown_evidence_ids"] == 0
            for case in spark_reviews + zookeeper_reviews
        ),
    ))
    payload = {
        "suite": "loghub2-bounded-windows/v1",
        "model_called": False,
        "selection_used_template_truth": False,
        "structural_gate_passed": structural_gate,
        "grouping_threshold_gate": None,
        "grouping_threshold_gate_reason": (
            "First full-corpus baseline; review collision and fragmentation "
            "examples before ratcheting thresholds."
        ),
        "spark": {
            "source_stats": spark_stats,
            "grouping": spark_grouping,
            "pre_review_metrics": _pre_review_metrics(spark_reviews),
            "cases": spark_reviews,
        },
        "zookeeper": {
            "source_stats": zookeeper_stats,
            "grouping": zookeeper_grouping,
            "pre_review_metrics": _pre_review_metrics(zookeeper_reviews),
            "cases": zookeeper_reviews,
        },
    }
    _write_json(args.output, payload)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "structural_gate_passed": structural_gate,
        "spark_source_stats": spark_stats,
        "spark_pairwise": spark_grouping["pairwise"],
        "spark_pre_review": payload["spark"]["pre_review_metrics"],
        "zookeeper_source_stats": zookeeper_stats,
        "zookeeper_pairwise": zookeeper_grouping["pairwise"],
        "zookeeper_pre_review": payload[
            "zookeeper"
        ]["pre_review_metrics"],
    }, indent=2, sort_keys=True))
    return 0 if structural_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
