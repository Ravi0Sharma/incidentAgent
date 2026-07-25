"""Evaluate an already-fetched public corpus without invoking an LLM."""

import argparse
import json
import os
import sys


_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.public_log_dataset import (
    evaluate_loghub_hdfs,
)
from evaluation.hadoop_dataset import (
    evaluate_hadoop,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        choices=[
            "loghub_hdfs_2k",
            "loghub_hadoop",
        ],
        required=True,
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=200,
    )
    parser.add_argument(
        "--path",
        help=(
            "Optional local dataset path. "
            "Defaults to ../Hadoop for "
            "loghub_hadoop."
        ),
    )
    parser.add_argument(
        "--output",
        help=(
            "Optional path for the "
            "machine-readable JSON report."
        ),
    )
    args = parser.parse_args()
    if args.dataset == "loghub_hadoop":
        path = os.path.abspath(
            args.path
            or os.path.join(
                _ROOT,
                "..",
                "Hadoop",
            )
        )
    else:
        path = os.path.join(
            _ROOT,
            "data",
            "external",
            "raw",
            "loghub_hdfs_2k",
            "HDFS_2k.log_structured.csv",
        )
    if not os.path.exists(path):
        parser.error(
            "dataset is not present; run "
            "scripts/fetch_public_logs.py first"
        )
    evaluator = (
        evaluate_hadoop
        if args.dataset
        == "loghub_hadoop"
        else evaluate_loghub_hdfs
    )
    report = evaluator(
        path,
        sample_limit=max(
            args.sample_limit,
            1,
        ),
    )
    rendered = json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if args.output:
        output_path = os.path.abspath(
            args.output
        )
        os.makedirs(
            os.path.dirname(
                output_path
            ),
            exist_ok=True,
        )
        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(rendered)
            handle.write("\n")
    required = report[
        "quality_gate_passed"
    ]
    return 0 if required else 1


if __name__ == "__main__":
    sys.exit(main())
