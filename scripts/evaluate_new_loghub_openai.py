#!/usr/bin/env python3
"""Bounded label-last OpenAI evaluation for new Loghub corpora."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation.distributed_log_datasets import (
    load_bgl_cases,
    load_hdfs_v3_cases,
    load_zookeeper_cases,
    prepare_distributed_case_state,
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


def _has_catalog_signal(spec):
    from evaluation.hadoop_scorecard import (
        summarize_record_signals,
    )

    return bool(
        summarize_record_signals(
            spec["records"]
        ).get("direct_families")
    )


def _pick(
    loaded,
    *,
    truth=None,
    has_signal=None,
    signal_family=None,
    excludes_signal_family=None,
):
    for identifier, spec in sorted(
        loaded.items()
    ):
        if (
            truth is not None
            and spec["truth"] != truth
        ):
            continue
        if (
            has_signal is not None
            and _has_catalog_signal(spec)
            is not has_signal
        ):
            continue
        from evaluation.hadoop_scorecard import (
            summarize_record_signals,
        )
        families = (
            summarize_record_signals(
                spec["records"]
            ).get(
                "direct_families", {}
            )
            or {}
        )
        if (
            signal_family is not None
            and not families.get(
                signal_family
            )
        ):
            continue
        if (
            excludes_signal_family
            is not None
            and families.get(
                excludes_signal_family
            )
        ):
            continue
        return identifier, spec
    raise RuntimeError(
        "No case matched selection: "
        f"truth={truth!r}, "
        f"has_signal={has_signal!r}, "
        f"signal_family={signal_family!r}, "
        "excludes_signal_family="
        f"{excludes_signal_family!r}"
    )


def _select_cases(
    hdfs,
    bgl,
    zookeeper,
):
    selections = [
        (
            "hdfs_v3",
            "failure_with_catalog_signal",
            _pick(
                hdfs,
                truth="failure",
                signal_family=
                "network_transport",
            ),
        ),
        (
            "hdfs_v3",
            "storage_observation_only",
            _pick(
                hdfs,
                truth="failure",
                excludes_signal_family=
                "network_transport",
            ),
        ),
        (
            "hdfs_v3",
            "normal_control",
            _pick(
                hdfs,
                truth="normal",
            ),
        ),
        (
            "bgl",
            "alert_with_catalog_signal",
            _pick(
                bgl,
                truth="alert",
                signal_family=
                "network_transport",
            ),
        ),
        (
            "bgl",
            "alert_observation_only",
            _pick(
                bgl,
                truth="alert",
                excludes_signal_family=
                "network_transport",
            ),
        ),
        (
            "bgl",
            "non_alert_observation_control",
            _pick(
                bgl,
                truth="non_alert",
                has_signal=True,
            ),
        ),
        (
            "zookeeper",
            "unlabeled_warning_window",
            _pick(
                zookeeper,
                truth="unlabeled",
            ),
        ),
    ]
    return [
        {
            "dataset": dataset,
            "scenario": scenario,
            "identifier": selected[0],
            "truth": selected[1]["truth"],
            "case_metadata": {
                key: value
                for key, value
                in selected[1].items()
                if key not in {
                    "records",
                    "truth",
                }
            },
            "records": selected[1]["records"],
        }
        for dataset, scenario, selected
        in selections
    ]


def _render_index(report):
    rows = []
    for case in report["cases"]:
        review_file = html.escape(
            str(
                case.get(
                    "review_file", ""
                )
            )
        )
        case_id = html.escape(
            str(case["case_id"])
        )
        case_link = (
            f'<a href="{review_file}">'
            f"{case_id}</a>"
            if review_file
            else case_id
        )
        rows.append(
            "<tr>"
            f"<td>{case_link}</td>"
            f"<td>{html.escape(case['dataset'])}</td>"
            f"<td>{html.escape(case['scenario'])}</td>"
            f"<td>{html.escape(case['truth'])}</td>"
            f"<td>{html.escape(str(case['expected_status']))}</td>"
            f"<td>{html.escape(str(case.get('raw_model_status')))}</td>"
            f"<td>{html.escape(str(case['provider_status']))}</td>"
            f"<td>{html.escape(str(case.get('grounding_passed')))}</td>"
            f"<td>{html.escape(str(case.get('duration_seconds')))}</td>"
            "</tr>"
        )
    metrics = "".join(
        "<li><strong>"
        + html.escape(str(key))
        + ":</strong> "
        + html.escape(str(value))
        + "</li>"
        for key, value in report[
            "metrics"
        ].items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Loghub OpenAI evaluation</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:2rem;background:#f6f8fa;color:#17202a}}
main{{max-width:1400px;margin:auto;background:#fff;padding:2rem;border-radius:14px}}
table{{border-collapse:collapse;width:100%;font-size:.88rem}}
th,td{{border:1px solid #d8dee4;padding:.55rem;text-align:left}}
th{{background:#eef3f7}}li{{margin:.25rem 0}}
</style></head><body><main>
<h1>New Loghub OpenAI evaluation</h1>
<p>Dataset truth and selection metadata were joined after the model boundary.
The model received only the grounded evidence pack.</p>
<ul>{metrics}</ul>
<table><thead><tr><th>Case</th><th>Dataset</th><th>Scenario</th>
<th>Held-out truth</th><th>Expected</th><th>Raw model</th>
<th>Provider</th><th>Grounding</th><th>Seconds</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hdfs-v3-path",
        type=Path,
        default=REPO_ROOT.parent
        / "HDFS_v3_TraceBench",
    )
    parser.add_argument(
        "--bgl-path",
        type=Path,
        default=REPO_ROOT.parent
        / "BGL",
    )
    parser.add_argument(
        "--zookeeper-path",
        type=Path,
        default=REPO_ROOT.parent
        / "Zookeeper.log",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "output"
        / "new-loghub-openai-eval.json",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=REPO_ROOT
        / "output"
        / "new-loghub-openai-eval",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=200,
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60,
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    args = parser.parse_args()

    if not _valid_api_key(
        OPENAI_API_KEY
    ):
        raise SystemExit(
            "OPENAI_API_KEY is missing "
            "or is a placeholder"
        )

    hdfs, _ = load_hdfs_v3_cases(
        str(args.hdfs_v3_path),
        per_cohort=8,
    )
    bgl, _ = load_bgl_cases(
        str(args.bgl_path),
        per_label=8,
    )
    zookeeper, _ = (
        load_zookeeper_cases(
            str(args.zookeeper_path),
            per_cohort=6,
        )
    )
    selected = _select_cases(
        hdfs, bgl, zookeeper
    )
    prepared = []
    for item in selected:
        state = (
            prepare_distributed_case_state(
                dataset=item["dataset"],
                identifier=item[
                    "identifier"
                ],
                records=item["records"],
                sample_limit=max(
                    args.sample_limit, 1
                ),
            )
        )
        prepared.append({
            **item,
            "state": state,
        })

    dry_payload = {
        "dry_run": True,
        "model": OPENAI_MODEL,
        "official_openai_endpoint":
        _official_openai_endpoint(
            OPENAI_BASE_URL
        ),
        "truth_exposed_to_model": False,
        "cases": [
            {
                "case_id":
                item["state"][
                    "incident_id"
                ],
                "dataset": item["dataset"],
                "scenario": item["scenario"],
                "expected_status":
                _expected_status(
                    item["state"]
                ),
                "evidence_pack_chars":
                len(
                    item["state"][
                        "evidence_pack"
                    ]
                ),
            }
            for item in prepared
        ],
    }
    if args.dry_run:
        print(json.dumps(
            dry_payload,
            indent=2,
        ))
        return 0

    from openai import OpenAI

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        timeout=args.timeout_seconds,
        max_retries=1,
    )
    args.html_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    results = []
    for item in prepared:
        state = item["state"]
        expected = _expected_status(
            state
        )
        started = time.perf_counter()
        result: dict[str, Any] = {
            "case_id":
            state["incident_id"],
            "dataset": item["dataset"],
            "scenario": item["scenario"],
            "truth": item["truth"],
            "case_metadata":
            item["case_metadata"],
            "provider_status": "error",
            "expected_status": expected,
            "truth_exposed_to_model":
            False,
            "evidence_pack_chars":
            len(state["evidence_pack"]),
        }
        try:
            response = (
                client.responses.parse(
                    model=OPENAI_MODEL,
                    instructions=INSTRUCTIONS,
                    input=state[
                        "evidence_pack"
                    ],
                    text_format=
                    ModelInterpretationPayload,
                    reasoning={
                        "effort": "low"
                    },
                    max_output_tokens=
                    args.max_output_tokens,
                    store=False,
                )
            )
            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError(
                    "OpenAI returned no "
                    "parsed output"
                )
            raw = parsed.model_dump(
                mode="json"
            )
            structured, grounding = (
                validate_and_ground(
                    raw, state
                )
            )
            state[
                "model_interpretation_raw"
            ] = raw
            state[
                "interpretation_structured"
            ] = structured
            state[
                "claim_grounding"
            ] = grounding
            state["interpretation"] = (
                render_grounded_interpretation(
                    structured, state
                )
            )
            state[
                "interpretation_quality"
            ] = {
                "passed":
                grounding.get(
                    "passed", False
                ),
                "abstained":
                grounding.get(
                    "abstained", False
                ),
                "warnings":
                grounding.get(
                    "warnings", []
                ),
            }
            review_file = (
                state["incident_id"]
                + ".html"
            )
            (
                args.html_dir
                / review_file
            ).write_text(
                render_review(state),
                encoding="utf-8",
            )
            unknown_ids = sorted({
                evidence_id
                for claim
                in grounding.get(
                    "claims", []
                )
                or []
                for evidence_id
                in claim.get(
                    "unknown_evidence_ids",
                    [],
                )
                or []
            })
            result.update({
                "provider_status":
                "success",
                "response_id":
                getattr(
                    response, "id", None
                ),
                "raw_model_status":
                raw.get("status"),
                "final_status":
                structured.get(
                    "status"
                ),
                "status_boundary_passed":
                raw.get("status")
                == expected,
                "grounding_passed":
                bool(
                    grounding.get(
                        "passed"
                    )
                ),
                "unknown_evidence_ids":
                unknown_ids,
                "unsupported_percentages":
                _unsupported_numeric_claims(
                    raw,
                    state[
                        "evidence_pack"
                    ],
                ),
                "hypothesis_count":
                len(
                    raw.get(
                        "hypotheses", []
                    )
                    or []
                ),
                "usage":
                _usage_dict(
                    response
                ),
                "review_file":
                review_file,
                "model_output": raw,
            })
        except Exception as exc:
            result["error"] = (
                type(exc).__name__
                + ": "
                + str(exc)
            )
        result["duration_seconds"] = round(
            time.perf_counter()
            - started,
            3,
        )
        results.append(result)
        print(
            result["case_id"]
            + " "
            + result["provider_status"]
            + " "
            + str(
                result.get(
                    "duration_seconds"
                )
            )
            + "s",
            flush=True,
        )

    usage = {
        key: sum(
            int(
                case.get(
                    "usage", {}
                ).get(key, 0)
                or 0
            )
            for case in results
        )
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
    }
    metrics = {
        "cases": len(results),
        "provider_successes": sum(
            case["provider_status"]
            == "success"
            for case in results
        ),
        "status_boundary_passes": sum(
            bool(
                case.get(
                    "status_boundary_passed"
                )
            )
            for case in results
        ),
        "grounding_passes": sum(
            bool(
                case.get(
                    "grounding_passed"
                )
            )
            for case in results
        ),
        "unknown_evidence_ids": sum(
            len(
                case.get(
                    "unknown_evidence_ids",
                    [],
                )
            )
            for case in results
        ),
        "unsupported_percentages": sum(
            len(
                case.get(
                    "unsupported_percentages",
                    [],
                )
            )
            for case in results
        ),
        "elapsed_seconds": round(
            sum(
                case["duration_seconds"]
                for case in results
            ),
            3,
        ),
        **usage,
    }
    report = {
        "evaluation":
        "new-loghub-openai-label-last/v1",
        "model": OPENAI_MODEL,
        "official_openai_endpoint":
        _official_openai_endpoint(
            OPENAI_BASE_URL
        ),
        "truth_exposed_to_model": False,
        "metrics": metrics,
        "cases": results,
    }
    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    args.output.write_text(
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (
        args.html_dir / "index.html"
    ).write_text(
        _render_index(report),
        encoding="utf-8",
    )
    print(json.dumps(
        metrics,
        indent=2,
    ))
    return (
        0
        if (
            metrics[
                "provider_successes"
            ]
            == len(results)
            and metrics[
                "status_boundary_passes"
            ]
            == len(results)
            and metrics[
                "grounding_passes"
            ]
            == len(results)
            and not metrics[
                "unknown_evidence_ids"
            ]
            and not metrics[
                "unsupported_percentages"
            ]
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
