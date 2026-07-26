"""Merge a provider-only retry into a frozen Hadoop holdout report."""

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


from evaluation.hadoop_report import (
    rescore_hadoop_report,
)
from utils.hadoop_llm_html import (
    render_hadoop_llm_review,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        required=True,
    )
    parser.add_argument(
        "--retry",
        required=True,
    )
    parser.add_argument(
        "--dataset",
        default=os.path.abspath(
            os.path.join(
                _ROOT,
                "..",
                "Hadoop",
            )
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    args = parser.parse_args()
    with open(
        args.base,
        encoding="utf-8",
    ) as handle:
        base = json.load(handle)
    with open(
        args.retry,
        encoding="utf-8",
    ) as handle:
        retry = json.load(handle)
    retry_cases = (
        retry.get("cases", [])
        or []
    )
    if (
        len(retry_cases) != 1
        or retry.get(
            "provider_failures"
        )
    ):
        parser.error(
            "retry report must contain "
            "exactly one successful case"
        )
    retry_case = retry_cases[0]
    retry_id = retry_case[
        "case_id"
    ]
    failure_ids = {
        item.get("case_id")
        for item in (
            base.get(
                "provider_failures", []
            )
            or []
        )
    }
    if retry_id not in failure_ids:
        parser.error(
            "retry case does not match "
            "a base provider failure"
        )
    cases = [
        case
        for case in (
            base.get("cases", [])
            or []
        )
        if case.get("case_id")
        != retry_id
    ]
    cases.append(retry_case)
    if len({
        case["application_id"]
        for case in cases
    }) != base[
        "cases_requested"
    ]:
        parser.error(
            "merged report is not a "
            "complete unique holdout"
        )
    merged = {
        **base,
        "cases": cases,
        "provider_failures": [
            item
            for item in (
                base.get(
                    "provider_failures",
                    [],
                )
                or []
            )
            if item.get("case_id")
            != retry_id
        ],
        "provider_retry": {
            "resolved_case_id":
            retry_id,
            "reason":
            "structured JSON exceeded "
            "the original output cap",
            "retry_max_output_tokens":
            1200,
            "retry_versions":
            retry.get("versions", {}),
        },
    }
    merged = rescore_hadoop_report(
        merged,
        os.path.abspath(
            args.dataset
        ),
    )
    rendered = json.dumps(
        merged,
        indent=2,
        sort_keys=True,
    )
    output = os.path.abspath(
        args.output
    )
    os.makedirs(
        os.path.dirname(output),
        exist_ok=True,
    )
    with open(
        output,
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(rendered)
        handle.write("\n")
    with open(
        os.path.splitext(
            output
        )[0]
        + ".html",
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(
            render_hadoop_llm_review(
                merged
            )
        )
    print(
        json.dumps(
            {
                "output": output,
                "cases_successful":
                merged[
                    "cases_successful"
                ],
                "contract_gate_passed":
                merged[
                    "contract_gate_passed"
                ],
                "diagnostic_gate_passed":
                merged[
                    "diagnostic_gate_passed"
                ],
                "metrics":
                merged["metrics"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return (
        0
        if (
            merged[
                "contract_gate_passed"
            ]
            and merged[
                "diagnostic_gate_passed"
            ]
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
