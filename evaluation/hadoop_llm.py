"""Blind Hadoop evidence-pack evaluation against an injected interpreter.

Dataset truth is used for stratified case selection and scoring only. The
callable that invokes a model receives a ModelInput without application ID,
workload, or truth.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import time
from typing import Callable, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from clients.loki_client import (
    representative_sample,
)
from evaluation.hadoop_dataset import (
    _pipeline_state,
    load_hadoop_application,
    load_hadoop_labels,
)
from evaluation.hadoop_scorecard import (
    expected_outcome_recoverable,
    summarize_record_signals,
)
from utils.evidence_pack import (
    EVIDENCE_PACK_VERSION,
    build_evidence_pack,
)
from utils.signal_catalog import (
    SIGNAL_CATALOG_VERSION,
)


FailureClass = Literal[
    "normal",
    "machine_down",
    "network_disconnection",
    "disk_full",
    "insufficient_evidence",
]
Confidence = Literal[
    "low",
    "medium",
    "high",
]


class TimelineObservation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    evidence_id: str = Field(
        min_length=1,
        max_length=128,
    )
    timestamp: str | None = Field(
        default=None,
        max_length=64,
    )
    observation: str = Field(
        min_length=1,
        max_length=500,
    )


class ModelInterpretation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    classification: FailureClass
    confidence: Confidence
    summary: str = Field(
        min_length=1,
        max_length=1000,
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
    )
    contradicting_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    timeline: list[TimelineObservation] = Field(
        default_factory=list,
        max_length=8,
    )


@dataclass(frozen=True)
class ModelInput:
    case_id: str
    evidence_pack: str
    known_evidence_ids: frozenset[str]


@dataclass(frozen=True)
class InterpreterResult:
    interpretation: ModelInterpretation
    model: str
    latency_ms: int
    usage: dict
    response_status: str


Interpreter = Callable[
    [ModelInput],
    InterpreterResult,
]


def _case_id(application_id):
    return (
        "hadoop-"
        + hashlib.sha256(
            application_id.encode(
                "utf-8"
            )
        ).hexdigest()[:12]
    )


def select_stratified_cases(
    labels,
    limit=8,
):
    """Select balanced, reproducible cases with workload variety."""
    limit = max(
        min(int(limit), len(labels)),
        0,
    )
    buckets = defaultdict(list)
    for application_id, metadata in (
        labels.items()
    ):
        buckets[
            metadata["outcome"]
        ].append(
            (
                metadata["workload"],
                application_id,
            )
        )
    for values in buckets.values():
        values.sort()

    outcome_order = [
        "normal",
        "machine_down",
        "network_disconnection",
        "disk_full",
    ]
    selected = []
    selected_ids = set()
    round_index = 0
    while len(selected) < limit:
        added = False
        for outcome in outcome_order:
            values = buckets.get(
                outcome, []
            )
            if round_index >= len(values):
                continue
            workload, application_id = (
                values[round_index]
            )
            if application_id in selected_ids:
                continue
            selected.append({
                "application_id":
                application_id,
                "workload": workload,
                "outcome": outcome,
            })
            selected_ids.add(application_id)
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
        round_index += 1

    if len(selected) < limit:
        remainder = sorted(
            (
                metadata["outcome"],
                metadata["workload"],
                application_id,
            )
            for application_id, metadata
            in labels.items()
            if application_id
            not in selected_ids
        )
        for outcome, workload, application_id in remainder:
            selected.append({
                "application_id":
                application_id,
                "workload": workload,
                "outcome": outcome,
            })
            if len(selected) >= limit:
                break
    return selected


def known_evidence_ids(state):
    ids = set()
    for group in state.get(
        "log_groups", []
    ) or []:
        if group.get("event_id"):
            ids.add(group["event_id"])
    for detection in state.get(
        "detections", []
    ) or []:
        for key in ("id", "event_id"):
            if detection.get(key):
                ids.add(detection[key])
    for node in (
        state.get("evidence_graph", {})
        or {}
    ).get("nodes", []) or []:
        if node.get("event_id"):
            ids.add(node["event_id"])
    anchor = state.get(
        "anchor_event", {}
    ) or {}
    if anchor.get("event_id"):
        ids.add(anchor["event_id"])
    assessment = (
        state.get(
            "deterministic_assessment",
            {},
        )
        or {}
    )
    for pattern in assessment.get(
        "observation_patterns",
        [],
    ) or []:
        if pattern.get("pattern_id"):
            ids.add(pattern["pattern_id"])
    return frozenset(ids)


def validate_interpretation(
    interpretation,
    known_ids,
):
    cited = (
        list(
            interpretation.evidence_ids
        )
        + list(
            interpretation
            .contradicting_evidence_ids
        )
        + [
            item.evidence_id
            for item in (
                interpretation.timeline
            )
        ]
    )
    unsupported = sorted({
        value
        for value in cited
        if value not in known_ids
    })
    warnings = []
    if (
        interpretation.classification
        != "insufficient_evidence"
        and not interpretation.evidence_ids
    ):
        warnings.append(
            "answered classification has no supporting evidence ID"
        )
    if (
        interpretation.classification
        == "insufficient_evidence"
        and not interpretation.missing_evidence
    ):
        warnings.append(
            "abstention does not name missing evidence"
        )
    if unsupported:
        warnings.append(
            "response cites unknown evidence IDs"
        )
    return {
        "citation_valid":
        not unsupported,
        "claim_contract_valid":
        not warnings,
        "unsupported_evidence_ids":
        unsupported,
        "warnings": warnings,
    }


def _ratio(numerator, denominator):
    if not denominator:
        return 0.0
    return round(
        numerator / denominator,
        4,
    )


def prediction_supported_by_signals(
    prediction,
    signal_summary,
):
    """Check the predicted observable class without consulting truth."""
    statuses = signal_summary.get(
        "statuses", {}
    ) or {}
    expected = {
        "normal": {
            "job_lifecycle:succeeded",
        },
        "machine_down": {
            "machine_availability:"
            "unavailable",
        },
        "network_disconnection": {
            "network_transport:"
            "unreachable",
            "network_transport:"
            "disconnected",
        },
        "disk_full": {
            "storage_capacity:"
            "exhausted",
        },
    }
    if (
        prediction
        == "insufficient_evidence"
    ):
        return True
    return any(
        statuses.get(key, 0) > 0
        for key in expected.get(
            prediction, set()
        )
    )


def evaluate_hadoop_llm(
    root,
    interpreter,
    case_limit=8,
    sample_limit=200,
    excluded_application_ids=None,
    included_application_ids=None,
):
    labels = load_hadoop_labels(root)
    excluded_application_ids = set(
        excluded_application_ids or []
    )
    included_application_ids = (
        set(included_application_ids)
        if included_application_ids
        else None
    )
    available_labels = {
        application_id: metadata
        for application_id, metadata
        in labels.items()
        if application_id
        not in excluded_application_ids
        and (
            included_application_ids
            is None
            or application_id
            in included_application_ids
        )
    }
    selected = select_stratified_cases(
        available_labels,
        limit=case_limit,
    )
    case_results = []
    failures = []
    usage = Counter()

    for spec in selected:
        application_id = spec[
            "application_id"
        ]
        records, _ = load_hadoop_application(
            root,
            application_id,
        )
        raw_signal_summary = (
            summarize_record_signals(
                records
            )
        )
        sampled = representative_sample(
            records,
            sample_limit,
        )
        if not sampled:
            failures.append({
                "case_id":
                _case_id(application_id),
                "error_type":
                "empty_application",
            })
            continue
        state = _pipeline_state(
            sampled,
            len(records),
        )
        evidence_pack = build_evidence_pack(
            state
        )
        case_id = _case_id(
            application_id
        )
        if application_id in evidence_pack:
            failures.append({
                "case_id": case_id,
                "error_type":
                "application_id_leak",
            })
            continue
        all_known_ids = (
            known_evidence_ids(state)
        )
        visible_ids = frozenset(
            evidence_id
            for evidence_id
            in all_known_ids
            if evidence_id
            in evidence_pack
        )
        model_input = ModelInput(
            case_id=case_id,
            evidence_pack=evidence_pack,
            known_evidence_ids=visible_ids,
        )
        started = time.monotonic()
        try:
            result = interpreter(
                model_input
            )
        except Exception as exc:
            failures.append({
                "case_id": case_id,
                "error_type":
                type(exc).__name__,
                "error": str(exc)[:500],
            })
            continue
        measured_latency = int(
            (
                time.monotonic()
                - started
            )
            * 1000
        )
        interpretation = (
            result.interpretation
        )
        validation = (
            validate_interpretation(
                interpretation,
                model_input
                .known_evidence_ids,
            )
        )
        predicted = (
            interpretation
            .classification
        )
        answered = (
            predicted
            != "insufficient_evidence"
        )
        correct = (
            answered
            and predicted
            == spec["outcome"]
        )
        raw_recoverable = (
            expected_outcome_recoverable(
                spec["outcome"],
                raw_signal_summary,
            )
        )
        job_success_observed = (
            raw_signal_summary[
                "statuses"
            ].get(
                "job_lifecycle:succeeded",
                0,
            )
            > 0
        )
        data_ceiling_limited = (
            spec["outcome"]
            != "normal"
            and not raw_recoverable
        )
        prediction_grounded = (
            prediction_supported_by_signals(
                predicted,
                raw_signal_summary,
            )
        )
        evaluation_correct = (
            prediction_grounded
        )
        label_evidence_conflict = (
            predicted
            not in {
                spec["outcome"],
                "insufficient_evidence",
            }
            and prediction_grounded
        )
        for key, value in (
            result.usage or {}
        ).items():
            if isinstance(value, int):
                usage[key] += value
        case_results.append({
            "case_id": case_id,
            "application_id":
            application_id,
            "workload":
            spec["workload"],
            "truth":
            spec["outcome"],
            "prediction": predicted,
            "answered": answered,
            "correct": correct,
            "evaluation_correct":
            evaluation_correct,
            "prediction_grounded":
            prediction_grounded,
            "label_evidence_conflict":
            label_evidence_conflict,
            "raw_recoverable":
            raw_recoverable,
            "job_success_observed":
            job_success_observed,
            "data_ceiling_limited":
            data_ceiling_limited,
            "confidence":
            interpretation.confidence,
            "summary":
            interpretation.summary,
            "evidence_ids":
            interpretation.evidence_ids,
            "contradicting_evidence_ids":
            interpretation
            .contradicting_evidence_ids,
            "missing_evidence":
            interpretation
            .missing_evidence,
            "timeline": [
                item.model_dump()
                for item in (
                    interpretation.timeline
                )
            ],
            "validation": validation,
            "model": result.model,
            "response_status":
            result.response_status,
            "latency_ms": (
                result.latency_ms
                or measured_latency
            ),
            "usage": result.usage,
            "evidence_pack_chars":
            len(evidence_pack),
            "known_evidence_id_count":
            len(
                model_input
                .known_evidence_ids
            ),
            "truth_exposed_to_model":
            False,
        })

    answered_cases = [
        item
        for item in case_results
        if item["answered"]
    ]
    correct_cases = [
        item
        for item in answered_cases
        if item["correct"]
    ]
    evaluation_correct_cases = [
        item
        for item in case_results
        if item[
            "evaluation_correct"
        ]
    ]
    recoverable_cases = [
        item
        for item in case_results
        if item["raw_recoverable"]
    ]
    recoverable_answered = [
        item
        for item in recoverable_cases
        if item["answered"]
    ]
    recoverable_correct = [
        item
        for item in recoverable_answered
        if item["correct"]
    ]
    unsupported_answers = [
        item
        for item in case_results
        if (
            not item[
                "prediction_grounded"
            ]
        )
    ]
    valid_citations = [
        item
        for item in case_results
        if item["validation"][
            "citation_valid"
        ]
    ]
    valid_contracts = [
        item
        for item in case_results
        if item["validation"][
            "claim_contract_valid"
        ]
    ]
    confusion = Counter(
        (
            item["truth"],
            item["prediction"],
        )
        for item in case_results
    )
    total = len(selected)
    successful = len(case_results)
    contract_gate = (
        total > 0
        and not failures
        and successful == total
        and len(valid_citations)
        == successful
        and len(valid_contracts)
        == successful
        and all(
            not item[
                "truth_exposed_to_model"
            ]
            for item in case_results
        )
    )
    diagnostic_gate = (
        _ratio(
            len(
                evaluation_correct_cases
            ),
            successful,
        ) >= 1.0
        and _ratio(
            len(
                recoverable_answered
            ),
            len(recoverable_cases),
        ) >= 0.75
        and _ratio(
            len(
                recoverable_correct
            ),
            len(
                recoverable_answered
            ),
        ) >= 0.75
        and not unsupported_answers
    )
    return {
        "evaluation":
        "blind_hadoop_evidence_pack_llm_v2",
        "prompt_version":
        "hadoop-classifier/v1",
        "evidence_pack_version":
        EVIDENCE_PACK_VERSION,
        "signal_catalog_version":
        SIGNAL_CATALOG_VERSION,
        "excluded_application_ids":
        sorted(
            excluded_application_ids
        ),
        "included_application_ids":
        (
            sorted(
                included_application_ids
            )
            if included_application_ids
            is not None
            else None
        ),
        "cases_requested": total,
        "cases_successful": successful,
        "provider_failures": failures,
        "sample_limit_per_application":
        sample_limit,
        "truth_exposed_to_model":
        False,
        "metrics": {
            "coverage": _ratio(
                len(answered_cases),
                successful,
            ),
            "abstention_rate": _ratio(
                successful
                - len(answered_cases),
                successful,
            ),
            "selective_accuracy":
            _ratio(
                len(correct_cases),
                len(answered_cases),
            ),
            "overall_exact_accuracy":
            _ratio(
                len(correct_cases),
                successful,
            ),
            "correct_or_abstain_accuracy":
            _ratio(
                len(
                    evaluation_correct_cases
                ),
                successful,
            ),
            "grounded_response_rate":
            _ratio(
                len(
                    evaluation_correct_cases
                ),
                successful,
            ),
            "recoverable_coverage":
            _ratio(
                len(
                    recoverable_answered
                ),
                len(recoverable_cases),
            ),
            "recoverable_selective_accuracy":
            _ratio(
                len(
                    recoverable_correct
                ),
                len(
                    recoverable_answered
                ),
            ),
            "unsupported_answer_rate":
            _ratio(
                len(
                    unsupported_answers
                ),
                successful,
            ),
            "data_ceiling_limited_cases":
            len([
                item
                for item in case_results
                if item[
                    "data_ceiling_limited"
                ]
            ]),
            "label_evidence_conflict_cases":
            len([
                item
                for item in case_results
                if item[
                    "label_evidence_conflict"
                ]
            ]),
            "citation_valid_rate":
            _ratio(
                len(valid_citations),
                successful,
            ),
            "claim_contract_valid_rate":
            _ratio(
                len(valid_contracts),
                successful,
            ),
        },
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
        "usage": dict(
            sorted(usage.items())
        ),
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
                "Provisional balanced-eight baseline; "
                "not a production SLO."
            ),
        },
        "cases": case_results,
    }
