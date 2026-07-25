#!/usr/bin/env python3
"""Run two bounded LogHub 2.0 evidence packs against OpenAI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation.distributed_log_datasets import (
    load_zookeeper_cases,
    prepare_distributed_case_state,
)
from evaluation.loghub2_windows import (
    load_spark_explicit_window,
)
from scripts.evaluate_distributed_openai import (
    _expected_status,
    _unsupported_numeric_claims,
)
from scripts.evaluate_hadoop_entity_impact_openai import (
    INSTRUCTIONS,
    ModelInterpretationPayload,
    _official_openai_endpoint,
    _usage_dict,
    _valid_api_key,
)
from settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from utils.html_report import render_review
from utils.interpretation_contract import (
    render_grounded_interpretation,
    validate_and_ground,
)


def _spark_selection(report_path):
    report = json.loads(
        report_path.read_text(encoding="utf-8")
    )
    cases = report["spark"]["cases"]
    selected = max(
        cases,
        key=lambda case: (
            int(case.get("observed_signal_count", 0)),
            case["case_id"],
        ),
    )
    return selected["case_metadata"]


def _prepare(args):
    spark_root = args.dataset_root / "Spark" / "Spark"
    zookeeper_root = args.dataset_root / "Zookeeper" / "Zookeeper"
    metadata = _spark_selection(args.window_report)
    spark_records, spark_stats = load_spark_explicit_window(
        str(spark_root / "Spark_full.log"),
        start_line=metadata["start_line"],
        end_line=metadata["end_line"],
    )
    zookeeper, zookeeper_stats = load_zookeeper_cases(
        str(zookeeper_root / "Zookeeper_full.log"),
        per_cohort=1,
    )
    zookeeper_id, zookeeper_spec = sorted(
        zookeeper.items()
    )[0]
    cases = [
        {
            "dataset": "spark",
            "scenario": "unclassified_errors_without_impact_link",
            "identifier": f"center-{metadata['center_line']}",
            "truth": "unlabeled",
            "records": spark_records,
            "source_stats": spark_stats,
        },
        {
            "dataset": "zookeeper",
            "scenario": "warnings_without_observed_impact",
            "identifier": zookeeper_id,
            "truth": "unlabeled",
            "records": zookeeper_spec["records"],
            "source_stats": zookeeper_stats,
        },
    ]
    for case in cases:
        case["state"] = prepare_distributed_case_state(
            dataset=case["dataset"],
            identifier=case["identifier"],
            records=case["records"],
            sample_limit=max(args.sample_limit, 1),
        )
    return cases


def _call_model(client, item, args):
    state = item["state"]
    expected = _expected_status(state)
    started = time.perf_counter()
    result = {
        "case_id": state["incident_id"],
        "dataset": item["dataset"],
        "scenario": item["scenario"],
        "truth": item["truth"],
        "truth_exposed_to_model": False,
        "expected_status": expected,
        "provider_status": "error",
        "evidence_pack_chars": len(state["evidence_pack"]),
        "source_stats": item["source_stats"],
    }
    try:
        response = client.responses.parse(
            model=OPENAI_MODEL,
            instructions=INSTRUCTIONS,
            input=state["evidence_pack"],
            text_format=ModelInterpretationPayload,
            reasoning={"effort": "low"},
            max_output_tokens=args.max_output_tokens,
            store=False,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed output")
        raw = parsed.model_dump(mode="json")
        structured, grounding = validate_and_ground(raw, state)
        state["model_interpretation_raw"] = raw
        state["interpretation_structured"] = structured
        state["claim_grounding"] = grounding
        state["interpretation"] = render_grounded_interpretation(
            structured,
            state,
        )
        state["interpretation_quality"] = {
            "passed": grounding.get("passed", False),
            "abstained": grounding.get("abstained", False),
            "warnings": grounding.get("warnings", []),
        }
        review_file = state["incident_id"] + ".html"
        (args.html_dir / review_file).write_text(
            render_review(state),
            encoding="utf-8",
        )
        unknown = sorted({
            evidence_id
            for claim in grounding.get("claims", []) or []
            for evidence_id in claim.get(
                "unknown_evidence_ids", []
            ) or []
        })
        result.update({
            "provider_status": "success",
            "response_id": getattr(response, "id", None),
            "raw_model_status": raw.get("status"),
            "final_status": structured.get("status"),
            "status_boundary_passed": raw.get("status") == expected,
            "grounding_passed": bool(grounding.get("passed")),
            "unknown_evidence_ids": unknown,
            "unsupported_percentages": _unsupported_numeric_claims(
                raw,
                state["evidence_pack"],
            ),
            "hypothesis_count": len(raw.get("hypotheses", []) or []),
            "usage": _usage_dict(response),
            "review_file": review_file,
            "model_output": raw,
        })
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    result["duration_seconds"] = round(
        time.perf_counter() - started,
        3,
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT.parent / "Loghub-2.0" / "extracted",
    )
    parser.add_argument(
        "--window-report",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-windows-2026-08-10.json",
    )
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--max-output-tokens", type=int, default=1000)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-openai-2026-08-10.json",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-openai-2026-08-10",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not _valid_api_key(OPENAI_API_KEY):
        raise SystemExit("OPENAI_API_KEY is missing or is a placeholder")
    cases = _prepare(args)
    dry = {
        "model": OPENAI_MODEL,
        "official_openai_endpoint": _official_openai_endpoint(
            OPENAI_BASE_URL
        ),
        "truth_exposed_to_model": False,
        "cases": [
            {
                "case_id": item["state"]["incident_id"],
                "scenario": item["scenario"],
                "expected_status": _expected_status(item["state"]),
                "evidence_pack_chars": len(
                    item["state"]["evidence_pack"]
                ),
            }
            for item in cases
        ],
    }
    if args.dry_run:
        print(json.dumps(dry, indent=2))
        return 0

    from openai import OpenAI

    args.html_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        timeout=args.timeout_seconds,
        max_retries=1,
    )
    results = []
    for item in cases:
        result = _call_model(client, item, args)
        results.append(result)
        print(
            result["case_id"]
            + " "
            + result["provider_status"]
            + " "
            + str(result["duration_seconds"])
            + "s",
            flush=True,
        )
    metrics = {
        "cases": len(results),
        "provider_successes": sum(
            item["provider_status"] == "success" for item in results
        ),
        "status_boundary_passes": sum(
            bool(item.get("status_boundary_passed")) for item in results
        ),
        "grounding_passes": sum(
            bool(item.get("grounding_passed")) for item in results
        ),
        "unknown_evidence_ids": sum(
            len(item.get("unknown_evidence_ids", [])) for item in results
        ),
        "unsupported_percentages": sum(
            len(item.get("unsupported_percentages", []))
            for item in results
        ),
        "input_tokens": sum(
            int(item.get("usage", {}).get("input_tokens", 0) or 0)
            for item in results
        ),
        "output_tokens": sum(
            int(item.get("usage", {}).get("output_tokens", 0) or 0)
            for item in results
        ),
        "elapsed_seconds": round(sum(
            item["duration_seconds"] for item in results
        ), 3),
    }
    report = {
        "evaluation": "loghub2-openai-abstention/v1",
        **dry,
        "metrics": metrics,
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, indent=2))
    passed = (
        metrics["provider_successes"] == len(results)
        and metrics["status_boundary_passes"] == len(results)
        and metrics["grounding_passes"] == len(results)
        and metrics["unknown_evidence_ids"] == 0
        and metrics["unsupported_percentages"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
