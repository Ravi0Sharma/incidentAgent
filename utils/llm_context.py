"""Compact, phase-specific context for LLM calls and their shared budget."""

from utils.investigation_loop import initialize_loop
from utils.skill_cards import incident_skill_cards


def _short(value, limit=220):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _candidate_card(candidate):
    return {
        "title": candidate.get("title"),
        "score": candidate.get("score"),
        "event_ids": candidate.get("event_ids", []),
        "impact_event_ids": candidate.get("impact_event_ids", []),
        "adverse_outcome_event_ids": candidate.get(
            "adverse_outcome_event_ids", []
        ),
        "outcome_event_ids": candidate.get("outcome_event_ids", []),
        "recovery_event_ids": candidate.get("recovery_event_ids", []),
        "successful_completion_event_ids": candidate.get(
            "successful_completion_event_ids", []
        ),
        "contradicting_event_ids": candidate.get(
            "contradicting_event_ids", []
        ),
        "evidence": [
            _short(item, 180)
            for item in candidate.get("evidence", [])[:3]
        ],
        "weaknesses": [
            _short(item, 180)
            for item in candidate.get("weaknesses", [])[:2]
        ],
        "verification": _short(candidate.get("verification"), 180),
    }


def _observation_pattern_card(pattern):
    representatives = (
        pattern.get(
            "representative_evidence", []
        )
        or []
    )
    return {
        "pattern_id":
        pattern.get("pattern_id"),
        "service":
        pattern.get("service"),
        "signal_family":
        pattern.get("signal_family"),
        "status":
        pattern.get("status"),
        "impact_status":
        pattern.get("impact_status"),
        "causal_status":
        pattern.get(
            "causal_status",
            "not_established",
        ),
        "event_group_count":
        pattern.get(
            "event_group_count", 0
        ),
        "occurrence_count":
        pattern.get(
            "occurrence_count", 0
        ),
        "representative_event_ids": [
            item.get("event_id")
            for item in representatives[
                :3
            ]
            if item.get("event_id")
        ],
        "time_span_status":
        pattern.get(
            "time_span_status",
            "not_comparable",
        ),
    }


def build_investigation_budget(state):
    """Allocate remote query units once for the entire incident analysis."""
    existing = state.get("investigation_budget", {}) or {}
    assessment = state.get("deterministic_assessment", {}) or {}
    candidates = assessment.get("candidates", []) or []
    top = candidates[0] if candidates else {}
    feedback = state.get("investigation_request") or state.get("review_feedback")
    source_failures = (
        (state.get("incident_features", {}) or {})
        .get("source_failures", [])
    )
    strong = (
        top.get("score", 0) >= 70
        and not assessment.get("expansion_recommended")
        and not source_failures
    )
    severity = state.get("severity", "SEV4")
    if feedback or severity == "SEV1":
        limit, mode = 5, "deep_verification"
    elif strong:
        limit, mode = 0, "deterministic_explanation"
    else:
        limit, mode = 2, "targeted_verification"
    return {
        "mode": mode,
        "max_remote_units": limit,
        "used_remote_units": int(existing.get("used_remote_units", 0)),
        "tool_cache": existing.get("tool_cache", {}),
        "tool_history": existing.get("tool_history", []),
        "expansion_loop": initialize_loop(
            existing.get("expansion_loop")
            or state.get("investigation_loop")
        ),
    }


def budget_summary(budget):
    budget = budget or {}
    maximum = int(budget.get("max_remote_units", 0))
    used = int(budget.get("used_remote_units", 0))
    return {
        "mode": budget.get("mode", "unknown"),
        "max_remote_units": maximum,
        "used_remote_units": used,
        "remaining_remote_units": max(maximum - used, 0),
        "expansion_loop": {
            key: value
            for key, value in (
                budget.get("expansion_loop", {})
                or {}
            ).items()
            if key in {
                "round",
                "max_rounds",
                "max_services",
                "max_result_bytes",
                "used_result_bytes",
                "max_elapsed_seconds",
                "stop_reason",
            }
        },
    }


def build_policy_profiles(state):
    """Compile SKILL.md guidance into small phase-specific policy cards."""
    cards = incident_skill_cards(state)
    by_skill = {
        card.get("skill"): card.get("rules", [])
        for card in cards
    }
    core = by_skill.get("agent-incident-responder", [])
    security = by_skill.get("security-incident", [])
    return {
        "semantic": (
            core[:1]
            + core[2:4]
            + security[:2]
        ),
        "interpretation": (
            core[:2]
            + core[3:5]
            + security[:2]
        ),
    }


def build_decision_brief(state, budget):
    assessment = state.get("deterministic_assessment", {}) or {}
    scope = state.get("scope_expansion", {}) or {}
    quality = state.get("data_quality", {}) or {}
    anchor = state.get("anchor_event", {}) or {}
    alert = state.get("alert", {}) or {}
    return {
        "incident": {
            "id": state.get("incident_id"),
            "service": scope.get("alert_service") or alert.get("service"),
            "severity": state.get("severity"),
            "anchor_event": anchor.get("event_id"),
            "anchor_time": anchor.get("timestamp"),
        },
        "candidate_ranking": [
            _candidate_card(item)
            for item in assessment.get("candidates", [])[:3]
        ],
        "observation_patterns": [
            _observation_pattern_card(
                item
            )
            for item in assessment.get(
                "observation_patterns", []
            )[:5]
        ],
        "abstain_reasons":
        assessment.get(
            "abstain_reasons", []
        )[:4],
        "data_quality": {
            "raw_log_count": state.get("raw_log_count", 0),
            "log_sample_truncated": (
                quality.get("logs", {}) or {}
            ).get("possibly_truncated", False),
            "source_failures": (
                (state.get("incident_features", {}) or {})
                .get("source_failures", [])
            ),
        },
        "scope": {
            "services": scope.get("services", [])[:6],
            "dependencies": scope.get("configured_dependencies", [])[:6],
            "trace_ids": scope.get("trace_ids", [])[:3],
        },
        "tool_policy": {
            "mode": budget["mode"],
            "remote_units_remaining": max(
                budget["max_remote_units"] - budget["used_remote_units"], 0
            ),
            "instruction": (
                "Do not call external tools; explain the deterministic evidence."
                if budget["max_remote_units"] == 0
                else "Use external tools only for a named verification question."
            ),
        },
    }


def build_approved_context(
    state,
    chosen_hypothesis,
):
    """Build bounded evidence for RCA and postmortem generation.

    High event volume remains visible through aggregate counts. Raw records,
    unrelated candidates, and repeated narrative are intentionally excluded.
    """
    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    candidates = assessment.get(
        "candidates", []
    ) or []
    try:
        index = max(
            int(chosen_hypothesis) - 1,
            0,
        )
    except (TypeError, ValueError):
        index = 0
    candidate = (
        candidates[index]
        if index < len(candidates)
        else {}
    )
    anchor = state.get(
        "anchor_event", {}
    ) or {}
    alert = state.get("alert", {}) or {}
    business = state.get(
        "business_context", {}
    ) or {}
    quality = state.get(
        "data_quality", {}
    ) or {}

    return {
        "incident": {
            "id": state.get(
                "incident_id",
                alert.get("incident_id"),
            ),
            "service": business.get(
                "service",
                alert.get("service"),
            ),
            "severity": state.get("severity"),
            "anchor_event": anchor.get(
                "event_id"
            ),
            "anchor_time": anchor.get(
                "timestamp"
            ),
        },
        "approved_candidate": {
            key: candidate.get(key)
            for key in (
                "id",
                "rank",
                "title",
                "claim_type",
                "causal_status",
                "root_cause_status",
                "confidence_label",
                "confidence_calibration",
                "event_ids",
                "evidence",
                "weaknesses",
                "gaps",
                "next_verification",
            )
            if candidate.get(key) is not None
        },
        "timeline": [
            {
                key: event.get(key)
                for key in (
                    "event_id",
                    "type",
                    "timestamp",
                    "offset",
                    "is_anchor",
                )
                if event.get(key) is not None
            }
            for event in (
                state.get("timeline", [])
                or []
            )[:5]
        ],
        "metrics": [
            {
                key: metric.get(key)
                for key in (
                    "event_id",
                    "metric",
                    "value",
                    "peak_value",
                    "timestamp",
                )
                if metric.get(key) is not None
            }
            for metric in (
                state.get("metrics", [])
                or []
            )[:3]
        ],
        "deploys": [
            {
                key: deploy.get(key)
                for key in (
                    "event_id",
                    "commit",
                    "time",
                    "environment",
                )
                if deploy.get(key) is not None
            }
            for deploy in (
                state.get("deploys", [])
                or []
            )[:2]
        ],
        "volume": {
            "raw_log_count": state.get(
                "raw_log_count", 0
            ),
            "group_counts_are_exact": (
                quality.get("logs", {})
                or {}
            ).get(
                "group_counts_are_exact",
                False,
            ),
            "possibly_truncated": (
                quality.get("logs", {})
                or {}
            ).get(
                "possibly_truncated",
                False,
            ),
        },
    }
