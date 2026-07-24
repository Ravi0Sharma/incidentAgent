#!/usr/bin/env python3
"""Run a four-case label-blind OpenAI smoke test for distributed impacts."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation.distributed_log_datasets import (
    _case_id,
    load_hdfs_v1_cases,
    load_openstack_cases,
    prepare_distributed_case_state,
)
from evaluation.hadoop_scorecard import (
    summarize_record_signals,
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


_ACKNOWLEDGEMENT_TERMS = {
    "peer_latency_observation": (
        "latency",
        "duration",
        "slow",
        "baseline",
    ),
    "no_direct_observation": (
        "insufficient",
        "no deterministic candidate",
        "no classified signal",
    ),
    "block_io_failure_observation": (
        "block",
        "read",
        "i/o",
        "operation",
    ),
    "storage_metadata_observation": (
        "metadata",
        "inconsistent",
        "blockinfo",
        "volume",
    ),
    "hdfs_no_direct_observation": (
        "insufficient",
        "no deterministic candidate",
        "no classified signal",
    ),
}


_SCENARIO_QUOTAS = {
    "peer_latency_observation": 4,
    "no_direct_observation": 2,
    "block_io_failure_observation": 2,
    "storage_metadata_observation": 2,
    "hdfs_no_direct_observation": 2,
}


def _select_cases(
    openstack,
    hdfs,
):
    selected = []
    counts = {
        scenario: 0
        for scenario in _SCENARIO_QUOTAS
    }
    for identifier, spec in sorted(
        openstack.items(),
        key=lambda item: _case_id(
            "openstack", item[0]
        ),
    ):
        features = [
            row.get("operation_feature")
            for row in spec["records"]
            if row.get("operation_feature")
        ]
        deviates = any(
            feature.get("status")
            == "deviation_observed"
            for feature in features
        )
        scenario = (
            "peer_latency_observation"
            if deviates
            else "no_direct_observation"
        )
        if (
            counts[scenario]
            >= _SCENARIO_QUOTAS[
                scenario
            ]
        ):
            continue
        selected.append({
            "dataset": "openstack",
            "identifier": identifier,
            "scenario": scenario,
            "records": spec["records"],
        })
        counts[scenario] += 1

    for identifier, spec in sorted(
        hdfs.items(),
        key=lambda item: _case_id(
            "hdfs_v1", item[0]
        ),
    ):
        families = (
            summarize_record_signals(
                spec["records"]
            ).get(
                "direct_families", {}
            )
            or {}
        )
        scenario = (
            "block_io_failure_observation"
            if families.get(
                "storage_io"
            )
            else "storage_metadata_observation"
            if families.get(
                "storage_metadata"
            )
            else "hdfs_no_direct_observation"
        )
        if (
            counts[scenario]
            >= _SCENARIO_QUOTAS[
                scenario
            ]
        ):
            continue
        selected.append({
            "dataset": "hdfs_v1",
            "identifier": identifier,
            "scenario": scenario,
            "records": spec["records"],
        })
        counts[scenario] += 1
    missing = [
        (
            scenario
            + ":"
            + str(
                _SCENARIO_QUOTAS[
                    scenario
                ]
                - counts[scenario]
            )
        )
        for scenario
        in _SCENARIO_QUOTAS
        if (
            counts[scenario]
            < _SCENARIO_QUOTAS[
                scenario
            ]
        )
    ]
    if missing:
        raise RuntimeError(
            "Missing smoke scenarios: "
            + ", ".join(missing)
        )
    return sorted(
        selected,
        key=lambda item:
        item["scenario"],
    )


def _expected_status(state):
    assessment = (
        state.get(
            "deterministic_assessment",
            {},
        )
        or {}
    )
    return (
        "abstained"
        if (
            assessment.get("abstain")
            or not assessment.get(
                "candidates"
            )
        )
        else "supported"
    )


def _acknowledged(
    scenario,
    payload,
):
    text = json.dumps(
        payload,
        sort_keys=True,
    ).lower()
    return any(
        term in text
        for term in (
            _ACKNOWLEDGEMENT_TERMS[
                scenario
            ]
        )
    )


def _unsupported_numeric_claims(
    payload,
    evidence_text="",
):
    text = json.dumps(
        payload,
        sort_keys=True,
    )
    percentages = sorted(set(
        re.findall(
            r"\b\d+(?:\.\d+)?%",
            text,
        )
    ))
    unsupported = []
    for claim in percentages:
        if claim in evidence_text:
            continue
        fraction = (
            float(claim[:-1])
            / 100.0
        )
        candidates = {
            str(fraction),
            f"{fraction:.4f}",
            f"{fraction:.6f}",
        }
        supported_fraction = any(
            re.search(
                r"sampled_fraction"
                r"[^,\n]{0,30}"
                + re.escape(candidate)
                + r"\b",
                evidence_text,
            )
            for candidate in candidates
        )
        if not supported_fraction:
            unsupported.append(claim)
    return unsupported


def _mislabels_latency_as_recovered(
    scenario,
    payload,
):
    if (
        scenario
        != "peer_latency_observation"
    ):
        return False
    tldr = str(
        payload.get("tldr", "")
    ).lower()
    return bool(
        re.search(
            r"\brecovered\s+(?:slow|latency)|"
            r"\bslow\s+operation\s+latency"
            r".{0,30}\brecovered\b",
            tldr,
        )
    )


def _successful_but_slow_acknowledged(
    scenario,
    payload,
):
    if (
        scenario
        != "peer_latency_observation"
    ):
        return None
    text = json.dumps(
        payload,
        sort_keys=True,
    ).lower()
    return (
        any(
            term in text
            for term in (
                "successful",
                "succeeded",
                "completion",
            )
        )
        and any(
            term in text
            for term in (
                "slow",
                "latency",
                "duration",
            )
        )
        and not _mislabels_latency_as_recovered(
            scenario,
            payload,
        )
    )


def _render_index(report):
    rows = []
    for case in report["cases"]:
        model_output = (
            case.get("model_output", {})
            or {}
        )
        review = html.escape(
            str(case.get("review_file", ""))
        )
        case_id = html.escape(
            str(case["case_id"])
        )
        link = (
            f'<a href="{review}">{case_id}</a>'
            if review
            else case_id
        )
        rows.append(
            "<tr>"
            f"<td>{link}</td>"
            f"<td>{html.escape(case['scenario'])}</td>"
            f"<td>{html.escape(str(case.get('provider_status')))}</td>"
            f"<td>{html.escape(str(case.get('raw_model_status')))}</td>"
            f"<td>{html.escape(str(case.get('grounded_status')))}</td>"
            f"<td>{html.escape(str(case.get('boundary_match')))}</td>"
            f"<td>{html.escape(str(case.get('observation_acknowledged')))}</td>"
            f"<td>{html.escape(str(case.get('successful_but_slow_acknowledged')))}</td>"
            f"<td>{html.escape(str(case.get('mislabels_latency_as_recovered')))}</td>"
            f"<td>{html.escape(str(case.get('non_read_only_steps')))}</td>"
            f"<td>{html.escape(str(case.get('unknown_evidence_ids')))}</td>"
            f"<td>{int((case.get('usage') or {}).get('total_tokens', 0))}</td>"
            f"<td>{html.escape(str(model_output.get('tldr', '')))}</td>"
            "</tr>"
        )
    summary = "".join(
        "<li><strong>"
        + html.escape(str(key))
        + ":</strong> "
        + html.escape(str(value))
        + "</li>"
        for key, value
        in report["summary"].items()
    )
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Distributed OpenAI smoke test</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:2rem;background:#f6f8fa;color:#17202a}}
main{{max-width:1500px;margin:auto;background:white;padding:2rem;border-radius:14px}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}}
th,td{{border:1px solid #d8dee4;padding:.5rem;text-align:left;vertical-align:top}}
th{{background:#eef3f7}}li{{margin:.3rem 0}}
</style></head><body><main>
<h1>Label-blind distributed OpenAI smoke test</h1>
<p>Dataset truth was absent from every model request and joined only after
grounding for report context.</p>
<ul>{summary}</ul>
<table><thead><tr><th>Case</th><th>Scenario</th><th>Provider</th>
<th>Raw</th><th>Grounded</th><th>Boundary</th><th>Observation</th>
<th>Successful but slow</th><th>Recovery wording defect</th>
<th>Unsafe steps</th><th>Unknown IDs</th><th>Tokens</th><th>Model TL;DR</th>
</tr></thead><tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openstack-path",
        type=Path,
        default=REPO_ROOT.parent
        / "OpenStack",
    )
    parser.add_argument(
        "--hdfs-path",
        type=Path,
        default=REPO_ROOT.parent
        / "HDFS_v1",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "output"
        / "distributed-openai-eval-12.json",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=REPO_ROOT
        / "output"
        / "distributed-openai-eval-12",
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
        default=1200,
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
    openstack, _ = load_openstack_cases(
        str(args.openstack_path),
        normal_limit=12,
    )
    hdfs, _ = load_hdfs_v1_cases(
        str(args.hdfs_path),
        per_label=20,
    )
    selected = _select_cases(
        openstack, hdfs
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
                    args.sample_limit,
                    1,
                ),
            )
        )
        prepared.append({
            **item,
            "state": state,
        })

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "model": OPENAI_MODEL,
            "official_openai_endpoint":
            _official_openai_endpoint(
                OPENAI_BASE_URL
            ),
            "truth_exposed_to_model":
            False,
            "cases": [
                {
                    "case_id":
                    item["state"][
                        "incident_id"
                    ],
                    "scenario":
                    item["scenario"],
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
        }, indent=2))
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
                    structured,
                    state,
                )
            )
            state[
                "interpretation_quality"
            ] = {
                "passed": grounding.get(
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
            non_read_only = sum(
                step.get("action_type")
                != "read_only"
                for step
                in raw.get(
                    "suggested_next_steps",
                    [],
                )
            )
            result.update({
                "provider_status": "ok",
                "response_id":
                getattr(
                    response, "id", None
                ),
                "raw_model_status":
                raw.get("status"),
                "grounded_status":
                structured.get("status"),
                "schema_parse_passed":
                True,
                "grounding_passed":
                bool(
                    grounding.get(
                        "passed"
                    )
                ),
                "boundary_match":
                structured.get("status")
                == expected,
                "raw_boundary_match":
                raw.get("status")
                == expected,
                "raw_hypothesis_count":
                len(
                    raw.get(
                        "hypotheses", []
                    )
                ),
                "non_read_only_steps":
                non_read_only,
                "unknown_evidence_ids":
                unknown_ids,
                "unsupported_numeric_claims":
                _unsupported_numeric_claims(
                    raw
                ),
                "observation_acknowledged":
                _acknowledged(
                    item["scenario"],
                    raw,
                ),
                "successful_but_slow_acknowledged":
                _successful_but_slow_acknowledged(
                    item["scenario"],
                    raw,
                ),
                "mislabels_latency_as_recovered":
                _mislabels_latency_as_recovered(
                    item["scenario"],
                    raw,
                ),
                "usage":
                _usage_dict(response),
                "review_file":
                review_file,
                "model_output": raw,
                "grounded_output":
                structured,
            })
        except Exception as exc:
            result.update({
                "error_type":
                type(exc).__name__,
                "error": str(exc)[:1000],
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            })
        result["latency_ms"] = round(
            (
                time.perf_counter()
                - started
            )
            * 1000
        )
        # Held-out truth is joined only after model output and grounding.
        source = (
            openstack
            if item["dataset"]
            == "openstack"
            else hdfs
        )
        result["truth"] = source[
            item["identifier"]
        ]["truth"]
        results.append(result)
        print(
            result["case_id"],
            result["scenario"],
            result["provider_status"],
            result.get(
                "grounded_status", "-"
            ),
            str(result["latency_ms"])
            + "ms",
        )

    completed = [
        item
        for item in results
        if item["provider_status"]
        == "ok"
    ]
    summary = {
        "requested_cases":
        len(results),
        "provider_successes":
        len(completed),
        "schema_parse_passes":
        sum(
            item.get(
                "schema_parse_passed",
                False,
            )
            for item in results
        ),
        "grounding_passes":
        sum(
            item.get(
                "grounding_passed",
                False,
            )
            for item in results
        ),
        "boundary_matches":
        sum(
            item.get(
                "boundary_match", False
            )
            for item in results
        ),
        "raw_boundary_matches":
        sum(
            item.get(
                "raw_boundary_match",
                False,
            )
            for item in results
        ),
        "observation_acknowledged":
        sum(
            item.get(
                "observation_acknowledged",
                False,
            )
            for item in results
        ),
        "successful_but_slow_acknowledged":
        sum(
            item.get(
                "successful_but_slow_acknowledged"
            )
            is True
            for item in results
        ),
        "latency_recovery_wording_defects":
        sum(
            item.get(
                "mislabels_latency_as_recovered",
                False,
            )
            for item in results
        ),
        "raw_hypotheses":
        sum(
            item.get(
                "raw_hypothesis_count",
                0,
            )
            for item in results
        ),
        "non_read_only_steps":
        sum(
            item.get(
                "non_read_only_steps",
                0,
            )
            for item in results
        ),
        "unknown_evidence_ids":
        sum(
            len(
                item.get(
                    "unknown_evidence_ids",
                    [],
                )
            )
            for item in results
        ),
        "total_tokens":
        sum(
            (
                item.get("usage", {})
                or {}
            ).get(
                "total_tokens", 0
            )
            for item in results
        ),
    }
    report = {
        "schema_version":
        "distributed-openai-evaluation/v2",
        "model": OPENAI_MODEL,
        "base_url_host":
        urlparse(
            OPENAI_BASE_URL
        ).hostname,
        "official_openai_endpoint":
        _official_openai_endpoint(
            OPENAI_BASE_URL
        ),
        "truth_exposed_to_model":
        False,
        "selection_note": (
            "Twelve pipeline-selected boundary "
            "scenarios. Dataset truth was joined "
            "only after model output and grounding."
        ),
        "request_limits": {
            "case_count": len(results),
            "reasoning_effort": "low",
            "store": False,
            "max_output_tokens_per_case":
            args.max_output_tokens,
            "timeout_seconds":
            args.timeout_seconds,
        },
        "summary": summary,
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
    print("JSON:", args.output)
    print(
        "HTML:",
        args.html_dir / "index.html",
    )
    return (
        0
        if (
            len(completed)
            == len(results)
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
