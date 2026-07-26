"""Render the stored Hadoop/OpenAI JSON baseline as standalone review HTML."""

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


from utils.hadoop_llm_html import (
    render_hadoop_llm_review,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=os.path.join(
            _ROOT,
            "output",
            "hadoop-openai-baseline.json",
        ),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT,
            "output",
            "hadoop-openai-review.html",
        ),
    )
    args = parser.parse_args()
    with open(
        args.input,
        encoding="utf-8",
    ) as handle:
        report = json.load(handle)
    rendered = (
        render_hadoop_llm_review(
            report
        )
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
    print(output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
