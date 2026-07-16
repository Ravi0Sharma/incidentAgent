"""Re-score stored Hadoop model responses against observable raw evidence."""

from collections import Counter
from copy import deepcopy

from evaluation.hadoop_dataset import (
    load_hadoop_application,
)
from evaluation.hadoop_llm import (
    prediction_supported_by_signals,
)
from evaluation.hadoop_scorecard import (
    expected_outcome_recoverable,
    summarize_record_signals,
)


def _ratio(numerator, denominator):
    if not denominator:
        return 0.0
    return round(
        numerator / denominator,
        4,
    )


def rescore_hadoop_report(
    report,
    root,
):
    """Apply evaluator-only fixes without making another model call."""
    report = deepcopy(report)
    cases = []
    usage = Counter()
    for original in report.get(
        "cases", []
    ) or []:
        case = deepcopy(original)
        records, _ = (
            load_hadoop_application(
                root,
                case["application_id"],
            )
        )
        signals = (
            summarize_record_signals(
                records
            )
        )
        prediction = case[
            "prediction"
        ]
        truth = case["truth"]
        answered = (
            prediction
            != "insufficient_evidence"
        )
        grounded = (
            prediction_supported_by_signals(
                prediction,
                signals,
            )
        )
        raw_recoverable = (
            expected_outcome_recoverable(
                truth,
                signals,
            )
        )
        job_success = (
            signals["statuses"].get(
                "job_lifecycle:succeeded",
                0,
            )
            > 0
        )
        case.update({
            "answered": answered,
            "correct": (
                answered
                and prediction == truth
            ),
            "evaluation_correct":
            grounded,
            "prediction_grounded":
            grounded,
            "raw_recoverable":
            raw_recoverable,
            "job_success_observed":
            job_success,
            "data_ceiling_limited": (
                truth != "normal"
                and not raw_recoverable
            ),
            "label_evidence_conflict": (
                prediction
                not in {
                    truth,
                    "insufficient_evidence",
                }
                and grounded
            ),
        })
        for key, value in (
            case.get("usage", {})
            or {}
        ).items():
            if isinstance(value, int):
                usage[key] += value
        cases.append(case)

    successful = len(cases)
    answered = [
        case
        for case in cases
        if case["answered"]
    ]
    correct = [
        case
        for case in answered
        if case["correct"]
    ]
    grounded = [
        case
        for case in cases
        if case[
            "prediction_grounded"
        ]
    ]
    recoverable = [
        case
        for case in cases
        if case["raw_recoverable"]
    ]
    recoverable_answered = [
        case
        for case in recoverable
        if case["answered"]
    ]
    recoverable_correct = [
        case
        for case in recoverable_answered
        if case["correct"]
    ]
    valid_citations = [
        case
        for case in cases
        if (
            case.get(
                "validation", {}
            )
            or {}
        ).get("citation_valid")
    ]
    valid_claims = [
        case
        for case in cases
        if (
            case.get(
                "validation", {}
            )
            or {}
        ).get(
            "claim_contract_valid"
        )
    ]
    unsupported = [
        case
        for case in cases
        if not case[
            "prediction_grounded"
        ]
    ]
    failures = report.get(
        "provider_failures", []
    ) or []
    requested = int(
        report.get(
            "cases_requested",
            successful + len(failures),
        )
    )
    contract_gate = (
        requested > 0
        and not failures
        and successful == requested
        and len(valid_citations)
        == successful
        and len(valid_claims)
        == successful
    )
    grounded_rate = _ratio(
        len(grounded),
        successful,
    )
    recoverable_coverage = _ratio(
        len(recoverable_answered),
        len(recoverable),
    )
    recoverable_accuracy = _ratio(
        len(recoverable_correct),
        len(recoverable_answered),
    )
    diagnostic_gate = (
        grounded_rate >= 1.0
        and recoverable_coverage
        >= 0.75
        and recoverable_accuracy
        >= 0.75
        and not unsupported
    )
    confusion = Counter(
        (
            case["truth"],
            case["prediction"],
        )
        for case in cases
    )
    report.update({
        "cases": cases,
        "cases_successful":
        successful,
        "provider_failures":
        failures,
        "usage": dict(
            sorted(usage.items())
        ),
        "confusion_matrix": [
            {
                "truth": truth,
                "prediction":
                prediction,
                "count": count,
            }
            for (
                truth,
                prediction,
            ), count in sorted(
                confusion.items()
            )
        ],
        "metrics": {
            "coverage": _ratio(
                len(answered),
                successful,
            ),
            "abstention_rate":
            _ratio(
                successful
                - len(answered),
                successful,
            ),
            "selective_accuracy":
            _ratio(
                len(correct),
                len(answered),
            ),
            "overall_exact_accuracy":
            _ratio(
                len(correct),
                successful,
            ),
            "citation_valid_rate":
            _ratio(
                len(valid_citations),
                successful,
            ),
            "claim_contract_valid_rate":
            _ratio(
                len(valid_claims),
                successful,
            ),
            "grounded_response_rate":
            grounded_rate,
            "correct_or_abstain_accuracy":
            grounded_rate,
            "recoverable_coverage":
            recoverable_coverage,
            "recoverable_selective_accuracy":
            recoverable_accuracy,
            "unsupported_answer_rate":
            _ratio(
                len(unsupported),
                successful,
            ),
            "data_ceiling_limited_cases":
            sum(
                int(
                    case[
                        "data_ceiling_limited"
                    ]
                )
                for case in cases
            ),
            "label_evidence_conflict_cases":
            sum(
                int(
                    case[
                        "label_evidence_conflict"
                    ]
                )
                for case in cases
            ),
        },
        "contract_gate_passed":
        contract_gate,
        "diagnostic_gate_passed":
        diagnostic_gate,
        "ready_for_findings_plan":
        contract_gate,
        "diagnostic_gate_policy": {
            "grounded_response_rate_min":
            1.0,
            "recoverable_coverage_min":
            0.75,
            "recoverable_selective_accuracy_min":
            0.75,
            "unsupported_answer_rate_max":
            0.0,
            "note": (
                "Dataset-exact accuracy is "
                "reported separately from "
                "observable-evidence grounding."
            ),
        },
        "rescored_without_model_call":
        True,
    })
    return report
