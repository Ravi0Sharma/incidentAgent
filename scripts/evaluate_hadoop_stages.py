"""Run the label-held-out Hadoop stage scorecard without an LLM."""

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


from evaluation.hadoop_scorecard import (
    evaluate_hadoop_stages,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        default=os.path.abspath(
            os.path.join(
                _ROOT,
                "..",
                "Hadoop",
            )
        ),
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=200,
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT,
            "output",
            "hadoop-stage-scorecard.json",
        ),
    )
    args = parser.parse_args()
    report = evaluate_hadoop_stages(
        os.path.abspath(args.path),
        sample_limit=max(
            args.sample_limit, 1
        ),
    )
    rendered = json.dumps(
        report,
        indent=2,
        sort_keys=True,
    )
    output_path = os.path.abspath(
        args.output
    )
    os.makedirs(
        os.path.dirname(output_path),
        exist_ok=True,
    )
    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(rendered)
        handle.write("\n")
    print(
        json.dumps(
            {
                "evaluation":
                report["evaluation"],
                "applications_total":
                report[
                    "applications_total"
                ],
                "summary":
                report["summary"],
                "by_truth":
                report["by_truth"],
                "output": output_path,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
