"""Bounded, auditable control state for targeted evidence expansion."""

import json
from datetime import datetime, timezone

from settings import (
    MAX_EXPANSION_ROUNDS,
    MAX_INVESTIGATION_ELAPSED_SECONDS,
    MAX_INVESTIGATION_RESULT_BYTES,
    MAX_SCOPE_SERVICES,
)
from utils.redaction import redact_data


INVESTIGATION_LOOP_VERSION = "investigation-loop/v1"
INVESTIGATION_REVISION_VERSION = "investigation-revision/v1"


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _parse(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


def initialize_loop(existing=None, now=None):
    """Preserve consumed limits while filling the versioned loop contract."""
    existing = dict(existing or {})
    current = now or _now()
    return {
        "schema_version": INVESTIGATION_LOOP_VERSION,
        "round": int(existing.get("round", 0)),
        "max_rounds": max(
            int(existing.get("max_rounds", MAX_EXPANSION_ROUNDS)),
            1,
        ),
        "max_services": max(
            int(existing.get("max_services", MAX_SCOPE_SERVICES)),
            1,
        ),
        "max_result_bytes": max(
            int(
                existing.get(
                    "max_result_bytes",
                    MAX_INVESTIGATION_RESULT_BYTES,
                )
            ),
            1,
        ),
        "used_result_bytes": max(
            int(existing.get("used_result_bytes", 0)),
            0,
        ),
        "max_elapsed_seconds": max(
            float(
                existing.get(
                    "max_elapsed_seconds",
                    MAX_INVESTIGATION_ELAPSED_SECONDS,
                )
            ),
            1.0,
        ),
        "started_at": (
            existing.get("started_at")
            or _iso(current)
        ),
        "elapsed_seconds": max(
            float(existing.get("elapsed_seconds", 0.0)),
            0.0,
        ),
        "continue_expansion": bool(
            existing.get("continue_expansion", False)
        ),
        "stop_reason": existing.get("stop_reason"),
        "stop_details": existing.get("stop_details"),
    }


def result_size_bytes(value):
    return len(
        json.dumps(
            value,
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        ).encode("utf-8")
    )


def elapsed_seconds(loop, now=None):
    started = _parse((loop or {}).get("started_at"))
    if not started:
        return 0.0
    current = now or _now()
    return max((current - started).total_seconds(), 0.0)


def _result_failed(result):
    if not isinstance(result, dict):
        return False
    if result.get("error"):
        return True
    checked = result.get("services_checked") or []
    return bool(checked) and all(
        isinstance(item, dict) and item.get("error")
        for item in checked
    )


def _trace_summary(traces):
    rows = []
    for trace in traces or []:
        result = trace.get("result") or {}
        rows.append(
            redact_data(
                {
                    "tool": trace.get("tool"),
                    "args": trace.get("args") or {},
                    "result_summary": trace.get("result_summary"),
                    "status": (
                        "error"
                        if _result_failed(result)
                        else "ok"
                    ),
                    "error": (
                        result.get("error")
                        if isinstance(result, dict)
                        else None
                    ),
                    "total_matched": (
                        result.get("total_matched")
                        if isinstance(result, dict)
                        else None
                    ),
                }
            )
        )
    return rows


def complete_round(
    state,
    *,
    targeted_evidence,
    query_ids,
    now=None,
):
    """Record one query/result revision and choose continue vs. stop."""
    current = now or _now()
    budget = dict(state.get("investigation_budget", {}) or {})
    loop = initialize_loop(
        budget.get("expansion_loop"),
        now=current,
    )
    loop["round"] += 1
    loop["elapsed_seconds"] = round(
        elapsed_seconds(loop, current),
        3,
    )

    traces = state.get(
        "semantic_correlation_tool_trace",
        [],
    ) or []
    assessment = state.get(
        "deterministic_assessment",
        {},
    ) or {}
    targeted = dict(targeted_evidence or {})
    added = int(targeted.get("integrated_records", 0) or 0)
    source_failures = (
        (state.get("incident_features", {}) or {})
        .get("source_failures", [])
        or []
    )
    max_remote = int(budget.get("max_remote_units", 0))
    used_remote = int(budget.get("used_remote_units", 0))
    all_tools_failed = bool(traces) and all(
        _result_failed(trace.get("result"))
        for trace in traces
    )

    reason = None
    details = None
    can_continue = False
    if (
        loop["elapsed_seconds"]
        >= loop["max_elapsed_seconds"]
    ):
        reason = "elapsed_time_budget_exhausted"
        details = "targeted investigation exceeded its elapsed-time limit"
    elif (
        loop["used_result_bytes"]
        >= loop["max_result_bytes"]
    ):
        reason = "result_byte_budget_exhausted"
        details = "targeted tool results reached the retained-byte limit"
    elif not assessment.get("expansion_recommended"):
        reason = "enough_evidence"
        details = assessment.get("expansion_reason")
    elif loop["round"] >= loop["max_rounds"]:
        reason = "round_budget_exhausted"
        details = "maximum targeted expansion rounds reached"
    elif max_remote <= used_remote:
        reason = "remote_query_budget_exhausted"
        details = "no remote query units remain"
    elif all_tools_failed or (
        source_failures and not traces
    ):
        reason = "source_unavailable"
        details = "targeted evidence sources were unavailable"
    elif added <= 0:
        reason = "safe_abstention"
        details = (
            targeted.get("reason")
            or "no new evidence was integrated; do not invent a conclusion"
        )
    else:
        can_continue = True

    loop["continue_expansion"] = can_continue
    loop["stop_reason"] = reason
    loop["stop_details"] = details
    budget["expansion_loop"] = loop

    revisions = list(
        state.get("investigation_revisions", [])
        or []
    )
    revision_number = len(revisions) + 1
    revisions.append(
        {
            "schema_version": INVESTIGATION_REVISION_VERSION,
            "revision": revision_number,
            "previous_revision": (
                revision_number - 1
                if revision_number > 1
                else None
            ),
            "round": loop["round"],
            "created_at": _iso(current),
            "query_ids": sorted(set(query_ids or [])),
            "tool_results": _trace_summary(traces),
            "integrated_records": added,
            "candidate_ranking": [
                {
                    "id": item.get("id"),
                    "score": item.get("score"),
                    "event_ids": item.get("event_ids", []),
                }
                for item in (
                    assessment.get("candidates", [])
                    or []
                )[:3]
            ],
            "expansion_recommended": bool(
                assessment.get("expansion_recommended")
            ),
            "decision": (
                "continue"
                if can_continue
                else "stop"
            ),
            "stop_reason": reason,
        }
    )
    return {
        "investigation_budget": budget,
        "investigation_loop": loop,
        "investigation_revisions": revisions,
    }


def expansion_router(state):
    loop = (
        state.get("investigation_loop")
        or (
            state.get("investigation_budget", {})
            or {}
        ).get("expansion_loop")
        or {}
    )
    return (
        "semantic_correlate"
        if loop.get("continue_expansion")
        else "interpret_incident"
    )
