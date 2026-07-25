"""Run the three currently approved synthetic scenarios through review."""

import argparse
import json
import os
import sys
from copy import deepcopy


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.synthetic_scenarios import scenarios
from graph.nodes.build_evidence_pack import build_evidence_pack
from graph.nodes.build_llm_context import build_llm_context
from graph.nodes.integrate_targeted_evidence import (
    integrate_targeted_evidence,
)
from graph.nodes.interpret_incident import interpret_incident
from graph.nodes.scope_expansion import scope_expansion
from graph.nodes.semantic_correlate import semantic_correlate
from scripts.evaluate_pre_review import _run_pipeline
from utils.html_report import render_review
from utils.log_store import put_logs
from utils.model_usage import initialize_deadline
from utils.service_registry import get_service


def _normal_success():
    return {
        "id": "review-clear-evidence",
        "alert": {
            "incident_id": "E2E-CLEAR",
            "alertname": "SyntheticCatalogIncident",
            "service": "catalog",
            "started_at": "2026-07-22T10:08:00Z",
            "received_at": "2026-07-22T10:08:00Z",
            "labels": {
                "service": "catalog",
                "environment": "local",
                "severity": "warning",
            },
            "message": "synthetic review evaluation",
        },
        "logs": [{
            "timestamp": "2026-07-22T10:03:00Z",
            "message": "connection pool exhausted SQLSTATE[53300]",
            "labels": {
                "service": "catalog",
                "level": "error",
                "error_type": "db_timeout",
                "pod": "catalog-1",
            },
        }],
        "metrics": [],
        "deploys": [{
            "event_id": "deploy-catalog",
            "commit": "synthetic-catalog-change",
            "time": "2026-07-22T09:58:00Z",
            "environment": "catalog",
        }],
        "expect": {
            "outcome": "supported_review",
            "top_candidate": "Database connection pool exhausted",
            "stop_reason": "enough_evidence",
        },
    }


def _insufficient():
    scenario = next(
        item
        for item in scenarios()
        if item["id"] == "insufficient-evidence"
    )
    copied = deepcopy(scenario)
    copied["id"] = "review-insufficient-evidence"
    copied["expect"] = {
        "outcome": "abstained_review",
    }
    return copied


def _tied_candidates():
    return {
        "id": "review-tied-candidates",
        "alert": {
            "incident_id": "E2E-TIED",
            "alertname": "SyntheticCatalogIncident",
            "service": "catalog",
            "started_at": "2026-07-22T10:08:00Z",
            "received_at": "2026-07-22T10:08:00Z",
            "labels": {
                "service": "catalog",
                "environment": "local",
                "severity": "warning",
            },
            "message": "synthetic tied-candidate evaluation",
        },
        "logs": [
            {
                "timestamp": "2026-07-22T10:03:00Z",
                "message": "connection pool exhausted SQLSTATE[53300]",
                "labels": {
                    "service": "catalog",
                    "level": "error",
                    "error_type": "db_timeout",
                },
            },
            {
                "timestamp": "2026-07-22T10:03:00Z",
                "message": "dns lookup failed NXDOMAIN",
                "labels": {
                    "service": "catalog",
                    "level": "error",
                    "error_type": "dns_error",
                },
            },
        ],
        "metrics": [],
        "deploys": [],
        "expect": {
            "outcome": "abstained_review",
            "expansion_recommended": True,
        },
    }


def _prepare(scenario):
    state = _run_pipeline(scenario)
    incident_id = scenario["alert"]["incident_id"]
    state["incident_id"] = incident_id
    state["severity"] = "SEV3"
    state["severity_reason"] = "synthetic review evaluation"
    state["business_context"] = {
        "service": scenario["alert"]["service"],
        **get_service(scenario["alert"]["service"]),
    }
    state["analysis_deadline"] = initialize_deadline()
    state.update(scope_expansion(state))
    state.update(build_llm_context(state))
    state.update(build_evidence_pack(state))
    put_logs(incident_id, state.get("logs", []))
    return state


def _run_one(scenario, output_dir):
    state = _prepare(scenario)
    state.update(semantic_correlate(state))
    state.update(integrate_targeted_evidence(state))
    state.update(interpret_incident(state))
    structured = state.get("interpretation_structured", {}) or {}
    grounding = state.get("claim_grounding", {}) or {}
    interpretation_trace = (
        state.get("interpretation_tool_trace", [])
        or []
    )
    semantic_validation = (
        (state.get("semantic_correlation", {}) or {})
        .get("validation", {})
        or {}
    )
    provider_degraded = any(
        isinstance(item, dict)
        and item.get("status") == "degraded"
        for item in interpretation_trace
    ) or any(
        "semantic correlation failed" in str(item)
        for item in (
            state.get("semantic_correlation", {})
            or {}
        ).get("missing_evidence", [])
        or []
    ) or any(
        "failed" in str(item).lower()
        for item in semantic_validation.get("warnings", []) or []
    )
    assessment = state.get("deterministic_assessment", {}) or {}
    candidates = assessment.get("candidates", []) or []
    outcome = (
        "abstained_review"
        if structured.get("status") == "abstained"
        else "supported_review"
    )
    expected = scenario["expect"]
    failures = []
    if outcome != expected.get("outcome"):
        failures.append(
            f"expected outcome {expected.get('outcome')}, got {outcome}"
        )
    if expected.get("top_candidate") and (
        not candidates
        or candidates[0].get("title")
        != expected["top_candidate"]
    ):
        failures.append("unexpected top candidate")
    loop = state.get("investigation_loop", {}) or {}
    if expected.get("stop_reason") and (
        loop.get("stop_reason") != expected["stop_reason"]
    ):
        failures.append("unexpected stop reason")
    if (
        "expansion_recommended" in expected
        and bool(assessment.get("expansion_recommended"))
        != expected["expansion_recommended"]
    ):
        failures.append("unexpected expansion recommendation")
    if any(
        claim.get("unknown_evidence_ids")
        for claim in grounding.get("claims", []) or []
    ):
        failures.append("unknown evidence ID survived grounding")

    os.makedirs(output_dir, exist_ok=True)
    html_path = os.path.join(output_dir, scenario["id"] + ".html")
    review_html = render_review(
        state
    )
    review_approvable = (
        "Approve &amp; continue"
        in review_html
    )
    if (
        outcome == "supported_review"
        and not review_approvable
    ):
        failures.append(
            "supported review is not approvable in HTML"
        )
    if (
        outcome == "abstained_review"
        and review_approvable
    ):
        failures.append(
            "abstained review exposed approval control"
        )
    required_sections = (
        "Incident Timeline",
        "Analysis For Decision",
        "Decision Commands",
        "Technical validation, provenance, and model details",
    )
    for section in required_sections:
        if section not in review_html:
            failures.append(
                "review HTML missing "
                + section
            )
    if (
        review_html.find(
            "Analysis For Decision"
        )
        > review_html.find(
            "Decision Commands"
        )
    ):
        failures.append(
            "review decision controls precede the interpretation"
        )
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(review_html)
    return {
        "scenario": scenario["id"],
        "passed": not failures,
        "failures": failures,
        "outcome": outcome,
        "top_candidate": (
            candidates[0].get("title")
            if candidates
            else None
        ),
        "candidate_gap": assessment.get("top_score_gap"),
        "expansion_recommended": bool(
            assessment.get("expansion_recommended")
        ),
        "stop_reason": loop.get("stop_reason"),
        "grounding_passed": grounding.get("passed"),
        "unknown_evidence_ids": sum(
            len(claim.get("unknown_evidence_ids", []) or [])
            for claim in grounding.get("claims", []) or []
        ),
        "model_calls": (
            state.get("model_usage_ledger", {}) or {}
        ).get("call_count", 0),
        "tokens": (
            state.get("model_usage_ledger", {}) or {}
        ).get("total_tokens", 0),
        "provider_degraded": provider_degraded,
        "review_approvable":
        review_approvable,
        "review_html": html_path,
    }


def run(output_dir):
    results = [
        _run_one(scenario, output_dir)
        for scenario in (
            _normal_success(),
            _insufficient(),
            _tied_candidates(),
        )
    ]
    return {
        "suite": "approved-review-scenarios/v1",
        "scenario_count": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="output/review-scenarios",
    )
    args = parser.parse_args()
    report = run(args.output_dir)
    report_path = os.path.join(args.output_dir, "report.json")
    os.makedirs(args.output_dir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    for result in report["results"]:
        print(
            ("PASS" if result["passed"] else "FAIL")
            + " "
            + result["scenario"]
            + " outcome="
            + result["outcome"]
            + " top="
            + str(result["top_candidate"])
            + " stop="
            + str(result["stop_reason"])
            + " calls="
            + str(result["model_calls"])
            + " tokens="
            + str(result["tokens"])
            + " provider_degraded="
            + str(result["provider_degraded"])
        )
        for failure in result["failures"]:
            print("  - " + failure)
    print(
        f"summary: {report['passed']}/{report['scenario_count']} passed"
    )
    print("report: " + report_path)
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
