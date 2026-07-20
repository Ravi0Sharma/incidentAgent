"""Re-run deterministic processing when bounded tools discover new logs."""

import json

from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.apply_detection_rules import (
    apply_detection_rules,
)
from graph.nodes.build_evidence_pack import (
    build_evidence_pack,
)
from graph.nodes.enrich_groups import (
    enrich_groups,
)
from graph.nodes.normalize_logs import (
    normalize_logs,
)
from graph.nodes.correlate import correlate
from utils.candidate_scoring import (
    score_candidates,
)
from utils.incident_features import (
    build_features,
)
from utils.investigation_loop import (
    complete_round,
)
from utils.llm_context import (
    build_decision_brief,
    build_policy_profiles,
)
from utils.log_store import get_logs


def _samples(result):
    result = (
        result
        if isinstance(result, dict)
        else {}
    )
    rows = list(
        result.get("sample", [])
        or []
    )
    for service in (
        result.get(
            "services_checked", []
        )
        or []
    ):
        rows.extend(
            service.get("sample", [])
            or []
        )
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("timestamp")
        and row.get("message") is not None
    ]


def _key(log):
    return json.dumps(
        {
            "timestamp": log.get(
                "timestamp"
            ),
            "message": log.get(
                "message"
            ),
            "labels": (
                log.get("labels", {})
            ),
        },
        sort_keys=True,
        default=str,
    )


def _finish_round(state, result, query_ids):
    decision_state = {
        **state,
        **result,
    }
    control = complete_round(
        decision_state,
        targeted_evidence=result.get(
            "targeted_evidence", {}
        ),
        query_ids=query_ids,
    )
    return {
        **result,
        **control,
    }


def integrate_targeted_evidence(
    state,
):
    traces = state.get(
        "semantic_correlation_tool_trace",
        [],
    ) or []
    targeted = []
    query_ids = set()
    for trace in traces:
        result = trace.get(
            "result"
        ) or {}
        source_provenance = (
            result.get(
                "provenance", {}
            )
            if isinstance(
                result, dict
            )
            else {}
        )
        if source_provenance.get(
            "query_id"
        ):
            query_ids.add(
                source_provenance[
                    "query_id"
                ]
            )
        for service_result in (
            result.get(
                "services_checked", []
            )
            if isinstance(
                result, dict
            )
            else []
        ) or []:
            nested = (
                service_result.get(
                    "provenance", {}
                )
                or {}
            )
            if nested.get(
                "query_id"
            ):
                query_ids.add(
                    nested["query_id"]
                )
        targeted.extend(
            _samples(
                result
            )
        )
    if not targeted:
        result = {
            "targeted_evidence": {
                "integrated_records": 0,
                "rescored": False,
                "reason": (
                    "semantic pass returned no usable "
                    "targeted log records"
                ),
            }
        }
        return _finish_round(
            state,
            result,
            query_ids,
        )

    existing = get_logs(
        state.get("incident_id")
    )
    combined = {}
    for log in (
        list(existing)
        + targeted
    ):
        combined[_key(log)] = log
    new_keys = {
        _key(log)
        for log in targeted
    } - {
        _key(log)
        for log in existing
    }
    if not new_keys:
        result = {
            "targeted_evidence": {
                "integrated_records": 0,
                "rescored": False,
                "reason": (
                    "tool samples already existed "
                    "in canonical incident logs"
                ),
            }
        }
        return _finish_round(
            state,
            result,
            query_ids,
        )

    known_total = state.get(
        "raw_log_count"
    )
    total_count = (
        int(known_total)
        + len(new_keys)
        if isinstance(
            known_total, int
        )
        else len(combined)
    )
    working = {
        **state,
        "logs": list(
            combined.values()
        ),
        "log_query": {
            "total_count": total_count,
            "count_is_exact": False,
            "fetched_count": len(
                combined
            ),
            "sample_limit": len(
                combined
            ),
            "possibly_truncated": True,
            "sampling_strategy": (
                "initial_plus_targeted_tool_evidence"
            ),
        },
    }
    working.update(
        normalize_logs(working)
    )
    working.update(
        aggregate_by_labels(working)
    )
    working.update(
        apply_detection_rules(
            working
        )
    )
    working.update(
        enrich_groups(working)
    )
    working[
        "incident_features"
    ] = build_features(working)
    working.update(
        correlate(working)
    )
    working[
        "deterministic_assessment"
    ] = score_candidates(working)
    budget = working.get(
        "investigation_budget", {}
    ) or {}
    working[
        "decision_brief"
    ] = build_decision_brief(
        working,
        budget,
    )
    working[
        "skill_policy_profiles"
    ] = build_policy_profiles(
        working
    )
    working.update(
        build_evidence_pack(working)
    )

    keys = (
        "logs",
        "raw_log_count",
        "log_groups",
        "suppressed_groups",
        "pivots",
        "data_quality",
        "detections",
        "incident_features",
        "metrics",
        "deploys",
        "timeline",
        "anchor_event",
        "frequency_histogram",
        "frequency_heatmap_ascii",
        "evidence_graph",
        "deterministic_assessment",
        "decision_brief",
        "skill_policy_profiles",
        "evidence_pack",
    )
    result = {
        **{
            key: working[key]
            for key in keys
            if key in working
        },
        "targeted_evidence": {
            "integrated_records": len(
                new_keys
            ),
            "rescored": True,
            "source": (
                "bounded semantic tool results"
            ),
            "source_query_ids":
            sorted(query_ids),
        },
    }
    return _finish_round(
        working,
        result,
        query_ids,
    )
