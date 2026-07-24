#!/usr/bin/env python3
"""Run real Loghub records through the complete production pre-review path."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from clients.loki_client import representative_sample
from evaluation.distributed_log_datasets import (
    _case_id,
    load_hdfs_v3_cases,
)
from evaluation.hadoop_scorecard import (
    summarize_record_signals,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.apply_detection_rules import (
    apply_detection_rules,
)
from graph.nodes.build_evidence_pack import (
    build_evidence_pack,
)
from graph.nodes.build_llm_context import (
    build_llm_context,
)
from graph.nodes.classify_severity import (
    classify_severity,
)
from graph.nodes.correlate import correlate
from graph.nodes.enrich_groups import (
    enrich_groups,
)
from graph.nodes.extract_features import (
    extract_features,
)
from graph.nodes.ingest_alert import (
    ingest_alert,
)
from graph.nodes.integrate_targeted_evidence import (
    integrate_targeted_evidence,
)
from graph.nodes.interpret_incident import (
    interpret_incident,
)
from graph.nodes.normalize_logs import (
    normalize_logs,
)
from graph.nodes.plan_collection import (
    plan_collection,
)
from graph.nodes.reassess_severity import (
    reassess_severity,
)
from graph.nodes.score_candidates import (
    score_candidates,
)
from graph.nodes.semantic_correlate import (
    semantic_correlate,
)
from settings import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from utils.html_report import render_review
from utils.investigation_loop import (
    expansion_router,
)
from utils.service_registry import (
    get_service,
)


def _valid_api_key(value):
    text = str(value or "")
    return (
        bool(text)
        and text != "lm-studio"
        and not text.startswith(
            "replace-"
        )
    )


def _official_endpoint(value):
    return str(value or "").rstrip(
        "/"
    ) in {
        "https://api.openai.com",
        "https://api.openai.com/v1",
    }


def _pick_cases(loaded):
    supported = None
    observation_only = None
    for identifier, spec in sorted(
        loaded.items()
    ):
        families = (
            summarize_record_signals(
                spec["records"]
            ).get(
                "direct_families", {}
            )
            or {}
        )
        if (
            spec["truth"] == "failure"
            and families.get(
                "network_transport"
            )
            and supported is None
        ):
            supported = (
                identifier,
                spec,
                "supported_network",
            )
        if (
            spec["truth"] == "failure"
            and not families.get(
                "network_transport"
            )
            and families.get(
                "storage_io"
            )
            and observation_only
            is None
        ):
            observation_only = (
                identifier,
                spec,
                "storage_observation_only",
            )
    if not supported or not observation_only:
        raise RuntimeError(
            "Could not select both a supported "
            "network case and a storage-only case."
        )
    return [
        supported,
        observation_only,
    ]


def _source_status(
    incident_id,
    source_count,
    sampled_count,
):
    return {
        "offline_loghub": {
            "status": "available",
            "total_count": source_count,
            "records_fetched":
            sampled_count,
            "records_usable":
            sampled_count,
            "provenance": {
                "source_schema_id":
                "loghub-hdfs-v3/v1",
                "query_id":
                "offline-" + incident_id,
                "fetched_count":
                sampled_count,
                "reduced_count":
                sampled_count,
                "truncated":
                sampled_count
                < source_count,
            },
            "data_quality": {
                "input_records":
                sampled_count,
                "usable_records":
                sampled_count,
                "quarantined_records": 0,
            },
        },
        "prometheus": {
            "status": "not_collected",
            "provenance": {
                "source_schema_id":
                "not-collected",
                "query_id": "not-run",
            },
        },
        "deployments": {
            "status": "not_collected",
            "provenance": {
                "source_schema_id":
                "not-collected",
                "query_id": "not-run",
            },
        },
    }


def _scope(state):
    service = (
        state.get("alert", {})
        .get("service", "hdfs")
    )
    config = get_service(service)
    return {
        "scope_expansion": {
            "alert_service": service,
            "services": [service],
            "service_summaries": [{
                "service": service,
                "owner":
                config.get("owner"),
                "tier":
                config.get("tier"),
                "customer_facing":
                config.get(
                    "customer_facing"
                ),
                "runbook":
                config.get("runbook"),
                "dependencies": [],
            }],
            "service_reasons": {
                service:
                "offline dataset source"
            },
            "service_depths": {
                service: 0
            },
            "observed_services": [
                service
            ],
            "configured_dependencies":
            [],
            "configured_related_services":
            [],
            "discovered_services": [{
                "service": service,
                "source":
                "offline dataset adapter",
            }],
            "trace_ids": (
                state.get("pivots", {})
                or {}
            ).get("trace_id", [])[:3],
            "request_ids": (
                state.get("pivots", {})
                or {}
            ).get("request_id", [])[:3],
            "environment_labels": {
                "environment":
                "public-offline-e2e",
            },
            "scope_limit": 1,
            "depth_limit": 0,
            "window":
            state.get(
                "incident_window", {}
            ),
        }
    }


def _apply(
    state,
    name,
    function,
    timings,
):
    started = time.perf_counter()
    result = function(state) or {}
    state.update(result)
    timings[name] = round(
        time.perf_counter()
        - started,
        3,
    )


def _case_summary(
    state,
    *,
    scenario,
    truth,
    source_records,
    sampled_records,
    timings,
    review_file,
):
    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    grounding = state.get(
        "claim_grounding", {}
    ) or {}
    interpretation = state.get(
        "interpretation_structured", {}
    ) or {}
    ledger = state.get(
        "model_usage_ledger", {}
    ) or {}
    return {
        "case_id":
        state["incident_id"],
        "scenario": scenario,
        "held_out_truth": truth,
        "truth_exposed_to_pipeline":
        False,
        "source_records":
        source_records,
        "sampled_records":
        sampled_records,
        "log_group_count":
        len(
            state.get(
                "log_groups", []
            )
        ),
        "observed_signal_count":
        len(
            assessment.get(
                "observed_signals", []
            )
        ),
        "observation_pattern_count":
        len(
            assessment.get(
                "observation_patterns", []
            )
        ),
        "candidate_categories": [
            item.get("category")
            for item in assessment.get(
                "candidates", []
            )
        ],
        "deterministic_abstain":
        assessment.get("abstain"),
        "abstain_reasons":
        assessment.get(
            "abstain_reasons", []
        ),
        "semantic_primary_links":
        len(
            (
                state.get(
                    "semantic_correlation",
                    {},
                )
                or {}
            ).get(
                "primary_chain", []
            )
        ),
        "semantic_tool_calls":
        len(
            state.get(
                "semantic_correlation_tool_trace",
                [],
            )
        ),
        "targeted_evidence":
        state.get(
            "targeted_evidence", {}
        ),
        "investigation_loop":
        state.get(
            "investigation_loop", {}
        ),
        "interpretation_status":
        interpretation.get("status"),
        "hypothesis_count":
        len(
            interpretation.get(
                "hypotheses", []
            )
        ),
        "grounding_passed":
        grounding.get("passed", False),
        "grounding_abstained":
        grounding.get(
            "abstained", False
        ),
        "unknown_evidence_ids":
        sorted({
            evidence_id
            for claim in grounding.get(
                "claims", []
            )
            for evidence_id in claim.get(
                "unknown_evidence_ids",
                [],
            )
        }),
        "evidence_pack_chars":
        len(
            state.get(
                "evidence_pack", ""
            )
        ),
        "model_usage": ledger,
        "stage_seconds": timings,
        "review_file": review_file,
    }


def _run_case(
    *,
    identifier,
    spec,
    scenario,
    sample_limit,
    output_dir,
):
    records = spec["records"]
    sampled = representative_sample(
        records,
        sample_limit,
    )
    incident_id = _case_id(
        "hdfs_v3", identifier
    ) + "-E2E"
    last_timestamp = max(
        str(record["timestamp"])
        for record in sampled
    )
    state = {
        "alert": {
            "incident_id": incident_id,
            "alertname":
            "OfflineHDFSFailureReview",
            "service": "hdfs",
            "severity": "warning",
            "message": (
                "Offline public-log "
                "end-to-end evaluation"
            ),
            "started_at":
            last_timestamp,
            "received_at":
            last_timestamp,
            "labels": {
                "service": "hdfs",
                "severity": "warning",
                "environment":
                "public-offline-e2e",
            },
        },
        "execution_log": [],
    }
    timings = {}
    _apply(
        state,
        "ingest_alert",
        ingest_alert,
        timings,
    )
    _apply(
        state,
        "classify_severity",
        classify_severity,
        timings,
    )
    _apply(
        state,
        "plan_collection",
        plan_collection,
        timings,
    )
    state.update({
        "logs": sampled,
        "raw_log_count":
        len(records),
        "log_query": {
            "total_count":
            len(records),
            "count_is_exact": True,
            "fetched_count":
            len(sampled),
            "sample_limit":
            sample_limit,
            "possibly_truncated":
            len(sampled)
            < len(records),
            "sampling_strategy":
            "representative_sample",
        },
        "metrics": [],
        "deploys": [],
        "source_status":
        _source_status(
            incident_id,
            len(records),
            len(sampled),
        ),
    })
    for name, function in (
        (
            "normalize_logs",
            normalize_logs,
        ),
        (
            "aggregate_by_labels",
            aggregate_by_labels,
        ),
        (
            "apply_detection_rules",
            apply_detection_rules,
        ),
        (
            "enrich_groups",
            enrich_groups,
        ),
        (
            "extract_features",
            extract_features,
        ),
        (
            "correlate",
            correlate,
        ),
        (
            "reassess_severity",
            reassess_severity,
        ),
    ):
        _apply(
            state,
            name,
            function,
            timings,
        )
    state.update(_scope(state))
    for name, function in (
        (
            "score_candidates",
            score_candidates,
        ),
        (
            "build_llm_context",
            build_llm_context,
        ),
        (
            "build_evidence_pack",
            build_evidence_pack,
        ),
    ):
        _apply(
            state,
            name,
            function,
            timings,
        )

    rounds = 0
    while True:
        rounds += 1
        _apply(
            state,
            (
                "semantic_correlate_"
                + str(rounds)
            ),
            semantic_correlate,
            timings,
        )
        _apply(
            state,
            (
                "integrate_targeted_"
                "evidence_"
                + str(rounds)
            ),
            integrate_targeted_evidence,
            timings,
        )
        if (
            expansion_router(state)
            != "semantic_correlate"
            or rounds >= 3
        ):
            break

    _apply(
        state,
        "interpret_incident",
        interpret_incident,
        timings,
    )
    review_file = (
        state["incident_id"]
        + ".html"
    )
    (
        output_dir / review_file
    ).write_text(
        render_review(state),
        encoding="utf-8",
    )
    return _case_summary(
        state,
        scenario=scenario,
        truth=spec["truth"],
        source_records=len(records),
        sampled_records=len(sampled),
        timings=timings,
        review_file=review_file,
    )


def _render_index(report):
    metrics = "".join(
        "<li><strong>"
        + html.escape(str(key))
        + ":</strong> "
        + html.escape(str(value))
        + "</li>"
        for key, value in (
            report.get("metrics", {})
            or {}
        ).items()
    )
    rows = []
    for case in report["cases"]:
        link = (
            '<a href="'
            + html.escape(
                case["review_file"]
            )
            + '">'
            + html.escape(
                case["case_id"]
            )
            + "</a>"
        )
        rows.append(
            "<tr>"
            f"<td>{link}</td>"
            f"<td>{html.escape(case['scenario'])}</td>"
            f"<td>{case['source_records']}</td>"
            f"<td>{case['log_group_count']}</td>"
            f"<td>{case['observed_signal_count']}</td>"
            f"<td>{case['observation_pattern_count']}</td>"
            f"<td>{html.escape(str(case['candidate_categories']))}</td>"
            f"<td>{html.escape(str(case['interpretation_status']))}</td>"
            f"<td>{case['hypothesis_count']}</td>"
            f"<td>{html.escape(str(case['grounding_passed']))}</td>"
            "</tr>"
        )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Full pre-review pipeline evaluation</title>
<style>
body{font-family:Inter,system-ui,sans-serif;margin:2rem;background:#f6f8fa;color:#17202a}
main{max-width:1400px;margin:auto;background:white;padding:2rem;border-radius:14px}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #d8dee4;padding:.55rem;text-align:left}
th{background:#eef3f7}li{margin:.25rem 0}
</style></head><body><main>
<h1>Full production pre-review path</h1>
<p>Real HDFS/TraceBench records passed through production deterministic
nodes, bounded semantic investigation, interpretation, grounding, and review.
Held-out truth was joined only after each review artifact was complete.</p>
<ul>""" + metrics + """</ul>
<table><thead><tr><th>Case</th><th>Scenario</th><th>Source records</th>
<th>Groups</th><th>Observations</th><th>Patterns</th><th>Candidates</th>
<th>Interpretation</th><th>Hypotheses</th><th>Grounding</th></tr></thead>
<tbody>""" + "".join(rows) + """</tbody></table>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hdfs-v3-path",
        type=Path,
        default=(
            REPO_ROOT.parent
            / "HDFS_v3_TraceBench"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPO_ROOT
            / "output"
            / "full-pre-review-e2e.json"
        ),
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=(
            REPO_ROOT
            / "output"
            / "full-pre-review-e2e"
        ),
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=200,
    )
    args = parser.parse_args()

    if not _valid_api_key(
        OPENAI_API_KEY
    ):
        raise SystemExit(
            "OPENAI_API_KEY is missing "
            "or is a placeholder."
        )
    args.html_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    loaded, source_stats = (
        load_hdfs_v3_cases(
            str(args.hdfs_v3_path),
            per_cohort=8,
        )
    )
    started = time.perf_counter()
    cases = []
    for (
        identifier,
        spec,
        scenario,
    ) in _pick_cases(loaded):
        case = _run_case(
            identifier=identifier,
            spec=spec,
            scenario=scenario,
            sample_limit=max(
                args.sample_limit, 1
            ),
            output_dir=args.html_dir,
        )
        cases.append(case)
        print(
            case["case_id"],
            case[
                "interpretation_status"
            ],
            "grounding="
            + str(
                case[
                    "grounding_passed"
                ]
            ),
            "hypotheses="
            + str(
                case[
                    "hypothesis_count"
                ]
            ),
        )
    report = {
        "suite":
        "full-pre-review-e2e/v1",
        "model": OPENAI_MODEL,
        "official_openai_endpoint":
        _official_endpoint(
            OPENAI_BASE_URL
        ),
        "truth_exposed_to_pipeline":
        False,
        "source_stats":
        source_stats,
        "cases": cases,
        "metrics": {
            "cases": len(cases),
            "grounding_passes": sum(
                item[
                    "grounding_passed"
                ]
                for item in cases
            ),
            "status_boundaries": [
                item[
                    "interpretation_status"
                ]
                for item in cases
            ],
            "hypotheses_total": sum(
                item[
                    "hypothesis_count"
                ]
                for item in cases
            ),
            "unknown_evidence_ids":
            sum(
                len(
                    item[
                        "unknown_evidence_ids"
                    ]
                )
                for item in cases
            ),
            "semantic_tool_calls": sum(
                item[
                    "semantic_tool_calls"
                ]
                for item in cases
            ),
            "model_calls": sum(
                (
                    item.get(
                        "model_usage", {}
                    )
                    or {}
                ).get(
                    "call_count", 0
                )
                for item in cases
            ),
            "model_tokens": sum(
                (
                    item.get(
                        "model_usage", {}
                    )
                    or {}
                ).get(
                    "total_tokens", 0
                )
                for item in cases
            ),
            "elapsed_seconds": round(
                time.perf_counter()
                - started,
                3,
            ),
        },
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
        report["metrics"],
        indent=2,
    ))
    return 0 if all(
        item["grounding_passed"]
        for item in cases
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
