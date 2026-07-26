"""Run the official Spark 2k sample through pre-LLM pipeline boundaries."""

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


from evaluation.distributed_log_datasets import (
    _run_case,
)
from evaluation.grouping_quality import (
    evaluate_spark_2k_grouping,
)
from evaluation.public_log_dataset import (
    load_loghub_spark_csv,
)


def _write_json(path, payload):
    target = os.path.abspath(path)
    os.makedirs(
        os.path.dirname(target),
        exist_ok=True,
    )
    with open(
        target,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            payload,
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return target


def main():
    parser = argparse.ArgumentParser()
    default_root = os.path.join(
        _ROOT,
        "data",
        "external",
        "raw",
        "loghub_spark_2k",
    )
    parser.add_argument(
        "--dataset-root",
        default=default_root,
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
            "spark-pilot.json",
        ),
    )
    parser.add_argument(
        "--html-dir",
        default=os.path.join(
            _ROOT,
            "output",
            "spark-pilot",
            "reviews",
        ),
    )
    args = parser.parse_args()

    dataset_root = os.path.abspath(
        args.dataset_root
    )
    structured_path = os.path.join(
        dataset_root,
        "Spark_2k.log_structured.csv",
    )
    raw_path = os.path.join(
        dataset_root,
        "Spark_2k.log",
    )
    for path in (
        structured_path,
        raw_path,
    ):
        if not os.path.isfile(path):
            parser.error(
                "required Spark input is missing: "
                + path
            )

    sample_limit = max(
        args.sample_limit, 1
    )
    grouping = evaluate_spark_2k_grouping(
        structured_path,
        raw_path,
        sample_limit,
    )
    records, source_rows = (
        load_loghub_spark_csv(
            structured_path
        )
    )
    case = _run_case(
        dataset="spark",
        identifier="spark-2k",
        truth=(
            "unlabeled_info_only_sample"
        ),
        records=records,
        sample_limit=sample_limit,
        html_dir=os.path.abspath(
            args.html_dir
        ),
        case_metadata={
            "source_dataset":
            "loghub_spark_2k",
            "source_event_labels":
            len({
                item["event_id"]
                for item in source_rows
            }),
            "source_labels_used_only_after_pipeline":
            True,
        },
    )

    abstention_checks = {
        "review_abstained":
        case["review_status"]
        == "abstained",
        "no_deterministic_candidates":
        not case[
            "candidate_categories"
        ],
        "no_observed_incident_signals":
        case[
            "observed_signal_count"
        ]
        == 0,
        "no_observation_patterns":
        case[
            "observation_pattern_count"
        ]
        == 0,
        "grounding_passed":
        case["grounding_passed"],
        "no_unknown_evidence_ids":
        case[
            "unknown_evidence_ids"
        ]
        == 0,
        "impact_contract_valid":
        case[
            "impact_contract_valid"
        ],
        "source_identifier_not_leaked":
        not case[
            "raw_identifier_leaked"
        ],
    }
    adapter_and_abstention_gate = (
        grouping[
            "quality_gate_passed"
        ]
        and all(
            abstention_checks.values()
        )
    )
    payload = {
        "suite":
        "spark-pre-llm-pilot/v1",
        "model_called": False,
        "truth_exposed_to_pipeline":
        False,
        "grouping": grouping,
        "deterministic_case": case,
        "abstention_checks":
        abstention_checks,
        "adapter_and_abstention_gate_passed":
        adapter_and_abstention_gate,
        "failure_detection_validated":
        False,
        "ready_for_spark_failure_llm_test":
        False,
        "next_data_requirement": (
            "A Spark case with executor loss, fetch failure, job or stage "
            "failure, or another reviewed incident outcome. It must retain "
            "enough ordered context to score signal, impact, and abstention."
        ),
        "limitations": [
            (
                "All 2,000 source rows are INFO; this sample cannot "
                "measure fault recall or root-cause accuracy."
            ),
            (
                "EventId is template truth only and was joined after "
                "inference for grouping evaluation."
            ),
            (
                "The source declares no timezone; UTC is assumed only "
                "for source-relative ordering."
            ),
            (
                "Passing this pilot authorizes a failure-rich Spark data "
                "test, not an OpenAI or production-readiness claim."
            ),
        ],
    }
    target = _write_json(
        args.output,
        payload,
    )
    summary = {
        "output": target,
        "review_html": os.path.join(
            os.path.abspath(
                args.html_dir
            ),
            case["review_html"],
        ),
        "source_rows":
        grouping["source_rows"],
        "raw_parser_coverage":
        grouping[
            "raw_parser_coverage"
        ],
        "event_label_coverage":
        grouping[
            "event_label_coverage"
        ],
        "pairwise":
        grouping["pairwise"],
        "review_pair_accuracy":
        grouping[
            "review_pair_sample"
        ]["accuracy"],
        "review_status":
        case["review_status"],
        "observed_signal_count":
        case[
            "observed_signal_count"
        ],
        "adapter_and_abstention_gate_passed":
        adapter_and_abstention_gate,
        "failure_detection_validated":
        False,
        "model_called": False,
    }
    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )
    return (
        0
        if adapter_and_abstention_gate
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
