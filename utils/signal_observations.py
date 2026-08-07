"""Typed direct-signal observations with entity, burst, impact, and recovery context."""

from datetime import datetime
import re


OBSERVED_SIGNAL_SCHEMA_VERSION = "observed-signal/v1"
IMPACT_LINK_SCHEMA_VERSION = "signal-impact-link/v2"
IMPACT_ASSESSMENT_SCHEMA_VERSION = "impact-assessment/v1"

_ENTITY_KEYS = (
    "execution_id",
    "workload_id",
    "host",
    "pod",
)
_OPERATION_EFFECT = (
    (
        "execution_disrupted",
        re.compile(
            r"(?i)container\s+released\s+on\s+a\s+\*?lost\*?\s+node"
        ),
    ),
    (
        "block_operation_failed",
        re.compile(
            r"(?i)(?:could\s+not\s+read"
            r"\s+from\s+stream|"
            r"failed\s+to\s+read"
            r"\s+from\s+stream|"
            r"OP_READ_BLOCK|"
            r"OP_STATUS_ERROR|"
            r"could\s+not\s+(?:create\s+)?"
            r"BlockSender|"
            r"no\s+live\s+nodes\s+contain"
            r"\s+current\s+block|"
            r"could\s+not\s+obtain\s+block|"
            r"checksum\s+error)"
        ),
    ),
    (
        "operation_failed",
        re.compile(
            r"(?i)(?:failed\s+to\s+(?:connect|renew|read|write)|"
            r"add\s+to\s+deadnodes|write\s+failed)"
        ),
    ),
)


def _parse(value):
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


def _dimension_values(group, name):
    summary = (
        (group.get("dimensions", {}) or {})
        .get(name, {})
        or {}
    )
    return {
        str(item.get("value"))
        for item in summary.get("top", []) or []
        if item.get("value") not in (None, "")
    }


def _entities(group):
    return {
        name: sorted(_dimension_values(group, name))
        for name in _ENTITY_KEYS
        if _dimension_values(group, name)
    }


def _entity_match(left, right):
    """Classify entity compatibility without treating missing scope as a match."""
    left_entities = _entities(left)
    right_entities = _entities(right)
    execution_conflict = False
    left_execution = set(
        left_entities.get("execution_id", [])
    )
    right_execution = set(
        right_entities.get("execution_id", [])
    )
    if left_execution and right_execution:
        shared_execution = sorted(
            left_execution & right_execution
        )
        if shared_execution:
            return {
                "status": "exact",
                "matched_keys": ["execution_id"],
                "conflicting_keys": [],
                "shared_entities": {
                    "execution_id": shared_execution,
                },
            }
        execution_conflict = True
    for name, matched_status in (
        ("workload_id", "workload_only"),
        ("host", "exact"),
        ("pod", "exact"),
    ):
        left_values = set(left_entities.get(name, []))
        right_values = set(right_entities.get(name, []))
        if not left_values or not right_values:
            continue
        shared = sorted(left_values & right_values)
        if shared:
            return {
                "status": matched_status,
                "matched_keys": [name],
                "conflicting_keys": (
                    ["execution_id"]
                    if execution_conflict
                    else []
                ),
                "shared_entities": {name: shared},
            }
    if execution_conflict:
        return {
            "status": "mismatch",
            "matched_keys": [],
            "conflicting_keys": ["execution_id"],
            "shared_entities": {},
        }
    return {
        "status": "unknown",
        "matched_keys": [],
        "conflicting_keys": [],
        "shared_entities": {},
    }


def _time_relation(signal_group, lifecycle_group):
    if not _time_comparable(
        signal_group,
        lifecycle_group,
    ):
        return "unknown"
    signal_start = _parse(signal_group.get("first_seen"))
    signal_end = _parse(
        signal_group.get("last_seen")
        or signal_group.get("first_seen")
    )
    lifecycle_start = _parse(lifecycle_group.get("first_seen"))
    lifecycle_end = _parse(
        lifecycle_group.get("last_seen")
        or lifecycle_group.get("first_seen")
    )
    if not all(
        (signal_start, signal_end, lifecycle_start, lifecycle_end)
    ):
        return "unknown"
    if lifecycle_end < signal_start:
        return "before"
    if lifecycle_start > signal_end:
        return "after"
    return "during"


def _time_comparable(left, right):
    left_quality = (
        left.get("time_quality", {})
        or {}
    )
    right_quality = (
        right.get("time_quality", {})
        or {}
    )
    left_scopes = set(
        left_quality.get(
            "ordering_scopes", []
        )
        or ["global"]
    )
    right_scopes = set(
        right_quality.get(
            "ordering_scopes", []
        )
        or ["global"]
    )
    non_comparable = {
        "trace_only",
        "not_comparable",
        "unknown",
    }
    if (
        left_scopes & non_comparable
        or right_scopes
        & non_comparable
    ):
        return False
    if (
        "source_relative"
        in left_scopes
        or "source_relative"
        in right_scopes
    ):
        left_sources = set(
            left_quality.get(
                "source_datasets", []
            )
            or []
        )
        right_sources = set(
            right_quality.get(
                "source_datasets", []
            )
            or []
        )
        return bool(
            left_sources
            and right_sources
            and left_sources
            & right_sources
        )
    return True


def _operation_effect(group):
    text = "\n".join(
        str(value)
        for value in (
            group.get("example_message"),
            *(group.get("sample_messages", []) or []),
        )
        if value
    )
    for effect, pattern in _OPERATION_EFFECT:
        if pattern.search(text):
            return effect
    return None


def _lifecycle_groups(groups):
    rows = []
    for group in groups:
        for signal in group.get("signals", []) or []:
            if (
                signal.get("signal_family")
                in {
                    "job_lifecycle",
                    "workload_lifecycle",
                }
                and signal.get("directness") == "direct"
            ):
                rows.append((group, signal))
    return rows


def _lifecycle_relation(signal_group, lifecycle_group, lifecycle_signal):
    entity = _entity_match(
        signal_group,
        lifecycle_group,
    )
    time_relation = _time_relation(
        signal_group,
        lifecycle_group,
    )
    execution_conflict = (
        "execution_id"
        in entity.get("conflicting_keys", [])
    )
    status = lifecycle_signal.get("status")
    adverse = status == "failed"
    successful_completion = (
        status == "succeeded"
    )
    recovery = status in {
        "started",
        "resumed",
    }
    outcome_role = (
        "adverse"
        if adverse
        else "successful_completion"
        if successful_completion
        else "recovery"
        if recovery
        else "neutral"
    )
    accepted = (
        entity["status"] in {"exact", "workload_only"}
        and time_relation in {"during", "after"}
        and not (
            adverse
            and execution_conflict
        )
    )
    relation = {
        "accepted": accepted,
        "entity_match": entity["status"],
        "matched_entity_keys": entity["matched_keys"],
        "conflicting_entity_keys": entity.get(
            "conflicting_keys", []
        ),
        "shared_entities": entity["shared_entities"],
        "time_relation": time_relation,
        "outcome_status": status,
        "outcome_role": outcome_role,
        "outcome_event_id": lifecycle_group.get("event_id"),
        "rejection_reason": (
            None
            if accepted
            else "adverse_outcome_execution_mismatch"
            if adverse and execution_conflict
            else "entity_mismatch"
            if entity["status"] == "mismatch"
            else "entity_scope_unknown"
            if entity["status"] == "unknown"
            else "outcome_precedes_signal"
            if time_relation == "before"
            else "time_relation_unknown"
        ),
    }
    if accepted:
        relation["impact_link"] = {
            "schema_version": IMPACT_LINK_SCHEMA_VERSION,
            "relationship": (
                "precedes_adverse_job_outcome"
                if adverse
                else "precedes_successful_completion"
                if successful_completion
                else "precedes_recovery"
                if recovery
                else "precedes_neutral_lifecycle_context"
            ),
            "impact_kind": (
                "adverse_lifecycle"
                if adverse
                else "successful_completion_context"
                if successful_completion
                else "recovery_context"
                if recovery
                else "lifecycle_context"
            ),
            "from_event_id": signal_group.get("event_id"),
            "to_event_id": lifecycle_group.get("event_id"),
            "supporting_event_ids": [
                event_id
                for event_id in (
                    signal_group.get("event_id"),
                    lifecycle_group.get("event_id"),
                )
                if event_id
            ],
            "shared_entities": entity["shared_entities"],
            "entity_match": entity["status"],
            "conflicting_entity_keys": entity.get(
                "conflicting_keys", []
            ),
            "time_relation": time_relation,
            "method": "typed_entity_and_time_relation_v2",
            "confidence": (
                90
                if entity["status"] == "exact"
                else 70
            ),
            "causal_status": "not_established",
        }
    return relation


def _unique(values):
    return list(
        dict.fromkeys(
            value
            for value in values
            if value
        )
    )


def _best_status(values, order):
    value_set = set(values)
    return next(
        (
            value
            for value in order
            if value in value_set
        ),
        "unknown",
    )


def _impact_assessment(
    *,
    group,
    lifecycle_relations,
    operation_effect,
    direct_failure_condition,
    cause_candidate_allowed=True,
    recovery_applies_to_impact=True,
    successful_completion_contradicts_impact=True,
):
    accepted = [
        item
        for item in lifecycle_relations
        if item.get("accepted")
    ]
    links = [
        item["impact_link"]
        for item in accepted
    ]
    event_id = group.get("event_id")
    same_event_effect = bool(
        operation_effect
        or direct_failure_condition
    )
    if same_event_effect:
        links.append({
            "schema_version": IMPACT_LINK_SCHEMA_VERSION,
            "relationship": (
                "same_event_operation_effect"
                if operation_effect
                else "same_event_failure_condition"
            ),
            "impact_kind": (
                operation_effect
                or direct_failure_condition
            ),
            "from_event_id": event_id,
            "to_event_id": event_id,
            "supporting_event_ids": [event_id] if event_id else [],
            "shared_entities": _entities(group),
            "entity_match": (
                "exact"
                if _entities(group)
                else "unknown"
            ),
            "time_relation": "during",
            "method": (
                "explicit_operation_effect_text_v2"
                if operation_effect
                else "direct_failure_condition_v2"
            ),
            "confidence": 70 if operation_effect else 65,
            "causal_status": "not_established",
        })

    adverse_ids = _unique(
        item.get("outcome_event_id")
        for item in accepted
        if item.get("outcome_role") == "adverse"
    )
    lifecycle_recovery_context_ids = _unique(
        item.get("outcome_event_id")
        for item in accepted
        if item.get("outcome_role") == "recovery"
    )
    recovery_ids = (
        lifecycle_recovery_context_ids
        if recovery_applies_to_impact
        else []
    )
    successful_completion_ids = _unique(
        item.get("outcome_event_id")
        for item in accepted
        if item.get("outcome_role")
        == "successful_completion"
    )
    contradicting_ids = _unique([
        *recovery_ids,
        *(
            successful_completion_ids
            if successful_completion_contradicts_impact
            else []
        ),
    ])
    effect_ids = [event_id] if same_event_effect and event_id else []
    impact_ids = _unique(
        [
            *effect_ids,
            *adverse_ids,
        ]
    )
    outcome_ids = _unique(
        item.get("outcome_event_id")
        for item in accepted
    )
    impact_established = bool(
        adverse_ids
        or (
            same_event_effect
            and not contradicting_ids
        )
    )
    candidate_eligible = bool(
        cause_candidate_allowed
        and (
            adverse_ids
            or (
                same_event_effect
                and not contradicting_ids
            )
        )
    )
    impact_status = (
        "established"
        if impact_established
        else "contradicted"
        if contradicting_ids
        else "not_established"
    )
    accepted_entity_statuses = [
        item.get("entity_match")
        for item in accepted
    ]
    rejected_entity_statuses = [
        item.get("entity_match")
        for item in lifecycle_relations
        if not item.get("accepted")
    ]
    entity_match = (
        _best_status(
            accepted_entity_statuses,
            ("exact", "workload_only"),
        )
        if accepted
        else "exact"
        if same_event_effect and _entities(group)
        else _best_status(
            rejected_entity_statuses,
            (
                "exact",
                "workload_only",
                "mismatch",
                "unknown",
            ),
        )
    )
    accepted_time_relations = [
        item.get("time_relation")
        for item in accepted
    ]
    time_relation = (
        _best_status(
            accepted_time_relations,
            ("during", "after"),
        )
        if accepted
        else "during"
        if same_event_effect
        else _best_status(
            [
                item.get("time_relation")
                for item in lifecycle_relations
            ],
            ("before", "after", "during", "unknown"),
        )
    )
    reasons = []
    if adverse_ids:
        reasons.append("adverse_outcome_same_scope")
    if operation_effect:
        reasons.append("same_event_operation_effect")
    elif direct_failure_condition:
        reasons.append("same_event_failure_condition")
    if recovery_ids:
        reasons.append(
            "later_recovery_same_scope"
        )
    if (
        lifecycle_recovery_context_ids
        and not recovery_applies_to_impact
    ):
        reasons.append(
            "lifecycle_recovery_does_not_contradict_completed_latency_measurement"
        )
    if successful_completion_ids:
        reasons.append(
            "successful_completion_same_scope"
        )
        if not (
            successful_completion_contradicts_impact
        ):
            reasons.append(
                "successful_completion_does_not_contradict_latency_deviation"
            )
    if any(
        (
            item.get("entity_match") == "mismatch"
            or "execution_id"
            in item.get(
                "conflicting_entity_keys", []
            )
        )
        for item in lifecycle_relations
    ):
        reasons.append("mismatched_lifecycle_entity_excluded")
    if any(
        item.get("time_relation") == "before"
        for item in lifecycle_relations
    ):
        reasons.append("pre_signal_outcome_excluded")
    if not candidate_eligible:
        reasons.append("cause_candidate_not_eligible")
    return {
        "schema_version": IMPACT_ASSESSMENT_SCHEMA_VERSION,
        "fault_event_ids": [event_id] if event_id else [],
        "impact_event_ids": impact_ids,
        "adverse_outcome_event_ids": adverse_ids,
        "outcome_event_ids": outcome_ids,
        "recovery_event_ids": recovery_ids,
        "successful_completion_event_ids":
        successful_completion_ids,
        "contradicting_event_ids":
        contradicting_ids,
        "entity_match": entity_match,
        "time_relation": time_relation,
        "impact_status": impact_status,
        "cause_candidate_eligible": candidate_eligible,
        "reason_codes": _unique(reasons),
        "rejected_relation_count": sum(
            not item.get("accepted")
            for item in lifecycle_relations
        ),
        "links": links,
    }


def build_observed_signals(groups):
    """Return label-blind direct observations; no observation establishes cause."""
    groups = groups or []
    lifecycle = _lifecycle_groups(groups)
    observations = []
    seen = set()
    for group in groups:
        event_id = group.get("event_id")
        if not event_id:
            continue
        for signal in group.get("signals", []) or []:
            if (
                signal.get("directness") != "direct"
                or signal.get("signal_family")
                in {
                    "job_lifecycle",
                    "workload_lifecycle",
                }
            ):
                continue
            key = (
                event_id,
                signal.get("rule_id"),
                signal.get("status"),
            )
            if key in seen:
                continue
            seen.add(key)
            lifecycle_relations = [
                relation
                for lifecycle_group, lifecycle_signal in lifecycle
                for relation in [
                    _lifecycle_relation(
                        group,
                        lifecycle_group,
                        lifecycle_signal,
                    )
                ]
            ]
            effect = _operation_effect(group)
            family = signal.get(
                "signal_family"
            )
            direct_failure_condition = (
                "transport_failure"
                if family == "network_transport"
                else "capacity_failure"
                if family == "storage_capacity"
                else "operation_latency_deviation"
                if family == "operation_latency"
                else None
            )
            status = signal.get("status")
            cause_candidate_allowed = (
                (
                    family,
                    status,
                )
                in {
                    (
                        "machine_availability",
                        "unavailable",
                    ),
                    (
                        "network_transport",
                        "unreachable",
                    ),
                    (
                        "network_transport",
                        "disconnected",
                    ),
                    (
                        "storage_capacity",
                        "exhausted",
                    ),
                }
            )
            impact_assessment = _impact_assessment(
                group=group,
                lifecycle_relations=lifecycle_relations,
                operation_effect=effect,
                direct_failure_condition=direct_failure_condition,
                cause_candidate_allowed=
                cause_candidate_allowed,
                recovery_applies_to_impact=(
                    family
                    != "operation_latency"
                ),
                successful_completion_contradicts_impact=(
                    family
                    != "operation_latency"
                ),
            )
            links = impact_assessment["links"]
            has_adverse = bool(
                impact_assessment[
                    "adverse_outcome_event_ids"
                ]
            )
            has_recovery = bool(
                impact_assessment[
                    "recovery_event_ids"
                ]
            )
            has_successful_completion = bool(
                impact_assessment[
                    "successful_completion_event_ids"
                ]
            )
            candidate_eligible = impact_assessment[
                "cause_candidate_eligible"
            ]
            impact_status = (
                "adverse_lifecycle_linked"
                if has_adverse
                else "operation_effect_observed"
                if effect
                else "latency_deviation_observed"
                if family
                == "operation_latency"
                else "failure_condition_observed"
                if direct_failure_condition
                else "recovery_observed"
                if has_recovery
                else "successful_completion_observed"
                if has_successful_completion
                else "unlinked"
            )
            limitations = [
                (
                    "The direct signal proves an observed condition, "
                    "not that it caused the incident."
                )
            ]
            if has_recovery:
                limitations.append(
                    "A later recovery signal exists in the same scope."
                )
                if not has_adverse:
                    limitations.append(
                        (
                            "Without a linked adverse lifecycle event, the "
                            "recovered condition remains an observation only."
                        )
                    )
            if has_successful_completion:
                limitations.append(
                    "A successful completion signal exists in the same scope."
                )
                if family == "operation_latency":
                    limitations.append(
                        (
                            "Successful completion does not contradict "
                            "the measured latency deviation."
                        )
                    )
            if not candidate_eligible:
                limitations.append(
                    (
                        "The observation is not eligible as a root-cause "
                        "candidate without separate causal evidence."
                    )
                )
            observations.append({
                "schema_version": OBSERVED_SIGNAL_SCHEMA_VERSION,
                "observation_id": (
                    "observation-"
                    + event_id
                    + "-"
                    + str(signal.get("rule_id", "signal"))
                ),
                "event_id": event_id,
                "catalog_version": signal.get("catalog_version"),
                "rule_id": signal.get("rule_id"),
                "signal_family": signal.get("signal_family"),
                "status": signal.get("status"),
                "scope": signal.get("scope", "unknown"),
                "directness": "direct",
                "first_seen": group.get("first_seen"),
                "last_seen": group.get("last_seen"),
                "count": group.get("count", 0),
                "count_scope": group.get("count_scope", "unknown"),
                "burst": group.get("burst", {}) or {},
                "entities": _entities(group),
                "impact_links": links,
                "impact_assessment": impact_assessment,
                "impact_status": impact_status,
                "recovery_observed": has_recovery,
                "successful_completion_observed":
                has_successful_completion,
                "cause_candidate_eligible": candidate_eligible,
                "feature_evidence": (
                    group.get(
                        "operation_features",
                        [],
                    )
                    if family
                    == "operation_latency"
                    else []
                ),
                "limitations": limitations,
            })
    return observations
