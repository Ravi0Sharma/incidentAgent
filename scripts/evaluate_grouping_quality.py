"""Evaluate grouping and thinning against source labels held out until scoring."""

import argparse
import json
import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.grouping_quality import (
    evaluate_controlled_grouping,
    evaluate_hdfs_2k_grouping,
    evaluate_hdfs_v3_grouping,
    evaluate_spark_2k_grouping,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        choices=[
            "all",
            "hdfs_2k",
            "hdfs_v3",
            "spark_2k",
            "controlled",
        ],
        default="all",
    )
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument("--hdfs-2k-path")
    parser.add_argument("--hdfs-v3-path")
    parser.add_argument(
        "--spark-2k-structured-path"
    )
    parser.add_argument(
        "--spark-2k-raw-path"
    )
    parser.add_argument("--controlled-path")
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT, "output", "grouping-quality-public.json"
        ),
    )
    args = parser.parse_args()
    reports = []
    sample_limit = max(args.sample_limit, 1)
    if args.dataset in {"all", "hdfs_2k"}:
        path = os.path.abspath(
            args.hdfs_2k_path
            or os.path.join(
                _ROOT,
                "data",
                "external",
                "raw",
                "loghub_hdfs_2k",
                "HDFS_2k.log_structured.csv",
            )
        )
        if not os.path.isfile(path):
            parser.error("HDFS 2k structured CSV is missing")
        reports.append(evaluate_hdfs_2k_grouping(path, sample_limit))
    if args.dataset in {"all", "hdfs_v3"}:
        path = os.path.abspath(
            args.hdfs_v3_path
            or os.path.join(_ROOT, "..", "HDFS_v3_TraceBench")
        )
        if not os.path.isdir(path):
            parser.error("HDFS v3 TraceBench directory is missing")
        reports.append(evaluate_hdfs_v3_grouping(path, sample_limit))
    if args.dataset in {"all", "spark_2k"}:
        spark_root = os.path.join(
            _ROOT,
            "data",
            "external",
            "raw",
            "loghub_spark_2k",
        )
        structured_path = os.path.abspath(
            args.spark_2k_structured_path
            or os.path.join(
                spark_root,
                "Spark_2k.log_structured.csv",
            )
        )
        raw_path = os.path.abspath(
            args.spark_2k_raw_path
            or os.path.join(
                spark_root,
                "Spark_2k.log",
            )
        )
        if not os.path.isfile(
            structured_path
        ):
            parser.error(
                "Spark 2k structured CSV is missing"
            )
        if not os.path.isfile(raw_path):
            parser.error(
                "Spark 2k raw log is missing"
            )
        reports.append(
            evaluate_spark_2k_grouping(
                structured_path,
                raw_path,
                sample_limit,
            )
        )
    if args.dataset in {"all", "controlled"}:
        path = os.path.abspath(
            args.controlled_path
            or os.path.join(
                _ROOT, "fixtures", "grouping_contract_cases.json"
            )
        )
        if not os.path.isfile(path):
            parser.error("controlled grouping contract is missing")
        reports.append(evaluate_controlled_grouping(path, sample_limit))
    payload = {
        "suite": "public-grouping-quality/v1",
        "truth_exposed_to_pipeline": False,
        "reports": reports,
        "required_gates_passed": all(
            report["quality_gate_passed"]
            for report in reports
            if report["quality_gate_passed"] is not None
        ),
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(rendered + "\n")
    print(rendered)
    return 0 if payload["required_gates_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
