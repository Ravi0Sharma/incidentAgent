"""Evaluate Hadoop truth against the current typed, grounded review boundary."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from clients.loki_client import representative_sample
from evaluation.hadoop_dataset import (
    _pipeline_state,
    load_hadoop_application,
    load_hadoop_labels,
)
from evaluation.impact_contract import (
    assess_impact_contract,
)
from evaluation.hadoop_llm import (
    prediction_supported_by_signals,
    select_stratified_cases,
)
from evaluation.hadoop_scorecard import (
    expected_outcome_recoverable,
    summarize_record_signals,
)
from utils.evidence_pack import build_evidence_pack
from utils.html_report import render_review
from utils.interpretation_contract import (
    deterministic_payload,
    render_grounded_interpretation,
    validate_and_ground,
)


def _ratio(value, total):
    return round(value / total, 4) if total else 0.0


def _cause_prediction(state):
    assessment = state.get("deterministic_assessment", {}) or {}
    if assessment.get("abstain"):
        return "insufficient_evidence"
    candidates = assessment.get("candidates", []) or []
    if candidates:
        category = candidates[0].get("category")
        if category in {
            "machine_down",
            "network_disconnection",
            "disk_full",
        }:
            return category
    return "insufficient_evidence"


def _observed_outcome(raw_signals):
    if (
        raw_signals.get("statuses", {})
        .get("job_lifecycle:succeeded", 0)
        > 0
    ):
        return "succeeded"
    return "unknown"


def _classification_prediction(cause_prediction, observed_outcome):
    if cause_prediction != "insufficient_evidence":
        return cause_prediction
    if observed_outcome == "succeeded":
        return "normal"
    return cause_prediction


def _observation_category(observation):
    family = observation.get(
        "signal_family"
    )
    return {
        "machine_availability":
        "machine_down",
        "network_transport":
        "network_disconnection",
        "storage_capacity":
        "disk_full",
    }.get(family)


def _case_id(application_id):
    digest = hashlib.sha256(
        application_id.encode("utf-8")
    ).hexdigest()[:12]
    return "HADOOP-TYPED-" + digest


def _run_case(root, spec, sample_limit, html_dir=None):
    application_id = spec["application_id"]
    records, _ = load_hadoop_application(
        root,
        application_id,
    )
    raw_signals = summarize_record_signals(records)
    sampled = representative_sample(records, sample_limit)

    # Pipeline and review artifacts are complete before held-out truth is read.
    state = _pipeline_state(sampled, len(records))
    state["incident_id"] = _case_id(application_id)
    state["evidence_pack"] = build_evidence_pack(state)
    structured, grounding = validate_and_ground(
        deterministic_payload(
            state,
            limitation=(
                "Hadoop typed-review evaluation uses deterministic "
                "signal candidates; dataset truth is held out."
            ),
        ),
        state,
    )
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
    cause_prediction = _cause_prediction(state)
    observed_outcome = _observed_outcome(raw_signals)
    prediction = _classification_prediction(
        cause_prediction,
        observed_outcome,
    )
    assessment = (
        state.get(
            "deterministic_assessment",
            {},
        )
        or {}
    )
    observations = (
        assessment.get(
            "observed_signals", []
        )
        or []
    )
    observed_categories = sorted({
        category
        for category in (
            _observation_category(
                observation
            )
            for observation in observations
        )
        if category
    })
    impact_categories = {
        category
        for category in (
            _observation_category(
                observation
            )
            for observation in observations
            if observation.get(
                "cause_candidate_eligible",
                False,
            )
        )
        if category
    }
    candidates = (
        assessment.get(
            "candidates", []
        )
        or []
    )

    # Truth joins only here.
    truth = spec["outcome"]
    recoverable = expected_outcome_recoverable(
        truth,
        raw_signals,
    )
    supported = prediction_supported_by_signals(
        prediction,
        raw_signals,
    )
    exact = prediction == truth
    impact_recoverable = (
        observed_outcome == "succeeded"
        if truth == "normal"
        else truth in impact_categories
    )
    competing_signals = bool(
        assessment.get("abstain")
        and assessment.get("candidates")
    )
    honest_abstention = (
        structured.get("status") == "abstained"
        and truth != "normal"
        and (
            not impact_recoverable
            or competing_signals
        )
    )
    label_evidence_conflict = (
        truth != "normal"
        and not recoverable
        and (
            cause_prediction != "insufficient_evidence"
            or observed_outcome == "succeeded"
        )
    )
    unknown_ids = sum(
        len(item.get("unknown_evidence_ids", []) or [])
        for item in grounding.get("claims", []) or []
    )
    html_path = None
    if html_dir:
        os.makedirs(html_dir, exist_ok=True)
        html_path = os.path.join(
            html_dir,
            state["incident_id"] + ".html",
        )
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(render_review(state))
    signal_candidates = [
        candidate
        for candidate in candidates
        if str(
            candidate.get("id", "")
        ).startswith(
            "candidate-signal-"
        )
    ]
    signal_candidate_impact_valid = all(
        candidate.get("observation_ids")
        and candidate.get("impact_links")
        for candidate in signal_candidates
    )
    impact_quality = assess_impact_contract(
        state,
        observations,
    )
    return {
        "case_id": state["incident_id"],
        "truth": truth,
        "prediction": prediction,
        "cause_prediction": cause_prediction,
        "observed_outcome": observed_outcome,
        "exact": exact,
        "recoverable": recoverable,
        "impact_recoverable":
        impact_recoverable,
        "honest_abstention": honest_abstention,
        "competing_signals": competing_signals,
        "label_evidence_conflict": label_evidence_conflict,
        "prediction_supported": supported,
        "review_status": structured.get("status"),
        "grounding_passed": grounding.get("passed"),
        "unknown_evidence_ids": unknown_ids,
        "top_candidate": (
            candidates[0].get("title")
            if candidates
            else None
        ),
        "top_category": (
            candidates[0].get("category")
            if candidates
            else None
        ),
        "observed_fault_categories":
        observed_categories,
        "observed_signal_count":
        len(observations),
        "impact_linked_observation_count":
        sum(
            observation.get(
                "cause_candidate_eligible",
                False,
            )
            for observation in observations
        ),
        "recovery_context_observed":
        any(
            observation.get(
                "recovery_observed",
                False,
            )
            for observation in observations
        ),
        "observation_only": bool(
            observations
            and not signal_candidates
        ),
        "signal_candidate_impact_valid":
        signal_candidate_impact_valid,
        "impact_contract_valid":
        impact_quality["valid"],
        "impact_contract_invalid_records":
        impact_quality["invalid_records"],
        "impact_role_unknown_evidence_ids":
        impact_quality[
            "unknown_role_evidence_ids"
        ],
        "entity_mismatch_candidates":
        impact_quality[
            "entity_mismatch_candidates"
        ],
        "pre_signal_outcome_candidates":
        impact_quality[
            "pre_signal_outcome_candidates"
        ],
        "impact_status_counts":
        impact_quality["status_counts"],
        "impact_entity_match_counts":
        impact_quality[
            "entity_match_counts"
        ],
        "impact_time_relation_counts":
        impact_quality[
            "time_relation_counts"
        ],
        "impact_reason_code_counts":
        impact_quality[
            "reason_code_counts"
        ],
        "supported_label_mismatch": (
            structured.get("status")
            == "supported"
            and prediction != truth
        ),
        "source_events": len(records),
        "sampled_events": len(sampled),
        "truth_exposed_to_pipeline": False,
        "review_html": html_path,
    }


def run(root, case_limit, sample_limit, html_dir=None):
    labels = load_hadoop_labels(root)
    selected = select_stratified_cases(
        labels,
        limit=case_limit,
    )
    cases = [
        _run_case(
            root,
            spec,
            sample_limit,
            html_dir=html_dir,
        )
        for spec in selected
    ]
    total = len(cases)
    exact = sum(item["exact"] for item in cases)
    recoverable = [
        item for item in cases
        if item["recoverable"]
    ]
    recoverable_exact = sum(
        item["exact"] for item in recoverable
    )
    impact_recoverable = [
        item for item in cases
        if item["impact_recoverable"]
    ]
    impact_recoverable_exact = sum(
        item["exact"]
        for item in impact_recoverable
    )
    honest = sum(
        item["exact"] or item["honest_abstention"]
        for item in cases
    )
    unsupported = [
        item for item in cases
        if not item["prediction_supported"]
    ]
    confusion = Counter(
        (item["truth"], item["prediction"])
        for item in cases
    )
    return {
        "evaluation":
        "hadoop-typed-grounded-review/v2",
        "cases": cases,
        "cases_total": total,
        "truth_exposed_to_pipeline": False,
        "metrics": {
            "exact_accuracy": _ratio(exact, total),
            "recoverable_exact_accuracy": _ratio(
                recoverable_exact,
                len(recoverable),
            ),
            "correct_or_honest_abstention": _ratio(
                honest,
                total,
            ),
            "unsupported_prediction_rate": _ratio(
                len(unsupported),
                total,
            ),
            "grounding_pass_rate": _ratio(
                sum(
                    item["grounding_passed"]
                    for item in cases
                ),
                total,
            ),
            "unknown_evidence_ids": sum(
                item["unknown_evidence_ids"]
                for item in cases
            ),
            "recoverable_cases": len(recoverable),
            "impact_recoverable_cases":
            len(impact_recoverable),
            "impact_recoverable_exact_accuracy":
            _ratio(
                impact_recoverable_exact,
                len(impact_recoverable),
            ),
            "honest_abstentions": sum(
                item["honest_abstention"]
                for item in cases
            ),
            "label_evidence_conflicts": sum(
                item["label_evidence_conflict"]
                for item in cases
            ),
            "cases_with_direct_observations":
            sum(
                bool(
                    item[
                        "observed_signal_count"
                    ]
                )
                for item in cases
            ),
            "observed_signals_total": sum(
                item[
                    "observed_signal_count"
                ]
                for item in cases
            ),
            "impact_linked_observations":
            sum(
                item[
                    "impact_linked_observation_count"
                ]
                for item in cases
            ),
            "observation_only_cases": sum(
                item["observation_only"]
                for item in cases
            ),
            "recovery_context_cases": sum(
                item[
                    "recovery_context_observed"
                ]
                for item in cases
            ),
            "supported_label_mismatches":
            sum(
                item[
                    "supported_label_mismatch"
                ]
                for item in cases
            ),
            "signal_candidate_impact_pass_rate":
            _ratio(
                sum(
                    item[
                        "signal_candidate_impact_valid"
                    ]
                    for item in cases
                ),
                total,
            ),
            "impact_contract_pass_rate":
            _ratio(
                sum(
                    item[
                        "impact_contract_valid"
                    ]
                    for item in cases
                ),
                total,
            ),
            "impact_contract_invalid_records":
            sum(
                item[
                    "impact_contract_invalid_records"
                ]
                for item in cases
            ),
            "impact_role_unknown_evidence_ids":
            sum(
                len(
                    item[
                        "impact_role_unknown_evidence_ids"
                    ]
                )
                for item in cases
            ),
            "entity_mismatch_candidates":
            sum(
                item[
                    "entity_mismatch_candidates"
                ]
                for item in cases
            ),
            "pre_signal_outcome_candidates":
            sum(
                item[
                    "pre_signal_outcome_candidates"
                ]
                for item in cases
            ),
            "impact_status_counts": dict(
                sum(
                    (
                        Counter(
                            item[
                                "impact_status_counts"
                            ]
                        )
                        for item in cases
                    ),
                    Counter(),
                )
            ),
            "impact_entity_match_counts": dict(
                sum(
                    (
                        Counter(
                            item[
                                "impact_entity_match_counts"
                            ]
                        )
                        for item in cases
                    ),
                    Counter(),
                )
            ),
            "impact_time_relation_counts": dict(
                sum(
                    (
                        Counter(
                            item[
                                "impact_time_relation_counts"
                            ]
                        )
                        for item in cases
                    ),
                    Counter(),
                )
            ),
            "impact_reason_code_counts": dict(
                sum(
                    (
                        Counter(
                            item[
                                "impact_reason_code_counts"
                            ]
                        )
                        for item in cases
                    ),
                    Counter(),
                )
            ),
        },
        "confusion_matrix": [
            {
                "truth": truth,
                "prediction": prediction,
                "count": count,
            }
            for (truth, prediction), count
            in sorted(confusion.items())
        ],
        "contract_gate_passed": (
            bool(cases)
            and not unsupported
            and all(
                item["grounding_passed"]
                and item["unknown_evidence_ids"] == 0
                and not item["truth_exposed_to_pipeline"]
                and item[
                    "signal_candidate_impact_valid"
                ]
                and item[
                    "impact_contract_valid"
                ]
                and not item[
                    "entity_mismatch_candidates"
                ]
                and not item[
                    "pre_signal_outcome_candidates"
                ]
                and not item[
                    "supported_label_mismatch"
                ]
                for item in cases
            )
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        default=os.path.abspath(
            os.path.join(_ROOT, "..", "Hadoop")
        ),
    )
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT,
            "output",
            "hadoop-typed-review-pilot.json",
        ),
    )
    parser.add_argument("--html-dir")
    args = parser.parse_args()
    report = run(
        args.path,
        max(args.cases, 1),
        max(args.sample_limit, 1),
        html_dir=args.html_dir,
    )
    os.makedirs(
        os.path.dirname(args.output) or ".",
        exist_ok=True,
    )
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    metrics = report["metrics"]
    print(
        f"cases={report['cases_total']} "
        f"exact={metrics['exact_accuracy']:.2%} "
        f"recoverable_exact={metrics['recoverable_exact_accuracy']:.2%} "
        f"correct_or_abstain={metrics['correct_or_honest_abstention']:.2%} "
        f"unsupported={metrics['unsupported_prediction_rate']:.2%} "
        f"grounding={metrics['grounding_pass_rate']:.2%} "
        f"gate={report['contract_gate_passed']}"
    )
    print("output: " + args.output)
    return 0 if report["contract_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
