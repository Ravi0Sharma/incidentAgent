"""Dataset-neutral quality checks for typed impact observations."""

from collections import Counter


def assess_impact_contract(state, observations):
    known_ids = {
        str(node.get("event_id"))
        for node in (
            (state.get("evidence_graph", {}) or {})
            .get("nodes", [])
            or []
        )
        if node.get("event_id")
    }
    role_fields = (
        "fault_event_ids",
        "impact_event_ids",
        "adverse_outcome_event_ids",
        "outcome_event_ids",
        "recovery_event_ids",
        "contradicting_event_ids",
    )
    optional_role_fields = (
        "successful_completion_event_ids",
    )
    unknown_ids = []
    invalid = 0
    mismatch_candidates = 0
    pre_signal_candidates = 0
    status_counts = Counter()
    entity_match_counts = Counter()
    time_relation_counts = Counter()
    reason_code_counts = Counter()
    for observation in observations:
        impact = observation.get(
            "impact_assessment", {}
        ) or {}
        if (
            impact.get("schema_version")
            != "impact-assessment/v1"
            or impact.get("impact_status")
            not in {
                "established",
                "not_established",
                "contradicted",
            }
            or impact.get("entity_match")
            not in {
                "exact",
                "workload_only",
                "unknown",
                "mismatch",
            }
            or impact.get("time_relation")
            not in {
                "before",
                "during",
                "after",
                "unknown",
            }
        ):
            invalid += 1
        status_counts[
            impact.get("impact_status", "missing")
        ] += 1
        entity_match_counts[
            impact.get("entity_match", "missing")
        ] += 1
        time_relation_counts[
            impact.get("time_relation", "missing")
        ] += 1
        reason_code_counts.update(
            impact.get("reason_codes", [])
            or []
        )
        for field in (
            *role_fields,
            *optional_role_fields,
        ):
            values = impact.get(field)
            if (
                field
                in optional_role_fields
                and values is None
            ):
                continue
            if not isinstance(values, list):
                invalid += 1
                continue
            unknown_ids.extend(
                value
                for value in values
                if value not in known_ids
            )
        eligible = bool(
            impact.get("cause_candidate_eligible")
        )
        if (
            eligible
            and impact.get("entity_match")
            == "mismatch"
        ):
            mismatch_candidates += 1
        if (
            eligible
            and impact.get("time_relation")
            == "before"
        ):
            pre_signal_candidates += 1
    return {
        "valid": not invalid and not unknown_ids,
        "invalid_records": invalid,
        "unknown_role_evidence_ids": sorted(
            set(unknown_ids)
        ),
        "entity_mismatch_candidates": mismatch_candidates,
        "pre_signal_outcome_candidates": pre_signal_candidates,
        "status_counts": dict(status_counts),
        "entity_match_counts": dict(entity_match_counts),
        "time_relation_counts": dict(time_relation_counts),
        "reason_code_counts": dict(reason_code_counts),
    }
