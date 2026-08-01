"""Transparent deterministic candidate ranking before any model reasoning."""

from datetime import datetime

from utils.candidate_contract import (
    CANDIDATE_SCHEMA_VERSION,
    finalize_candidates,
)
from utils.signal_observations import (
    IMPACT_ASSESSMENT_SCHEMA_VERSION,
    OBSERVED_SIGNAL_SCHEMA_VERSION,
    build_observed_signals,
)
from utils.observation_patterns import (
    OBSERVATION_PATTERN_SCHEMA_VERSION,
    build_observation_patterns,
)


LEVEL_POINTS = {
    "critical": 35,
    "high": 30,
    "medium": 18,
    "low": 8,
}

_DIRECT_SIGNAL_CANDIDATES = {
    (
        "machine_availability",
        "unavailable",
    ): {
        "title": "Machine or worker became unavailable",
        "category": "machine_down",
        "verification": (
            "Confirm node loss in cluster membership and host health "
            "for the cited event window."
        ),
    },
    (
        "network_transport",
        "unreachable",
    ): {
        "title": "Network peer became unreachable",
        "category": "network_disconnection",
        "verification": (
            "Confirm the cited peer-unreachable events against bounded "
            "network or node telemetry."
        ),
    },
    (
        "network_transport",
        "disconnected",
    ): {
        "title": "Network peer became unreachable",
        "category": "network_disconnection",
        "verification": (
            "Confirm the cited disconnect events against bounded "
            "network or node telemetry."
        ),
    },
    (
        "storage_capacity",
        "exhausted",
    ): {
        "title": "Storage capacity was exhausted",
        "category": "disk_full",
        "verification": (
            "Confirm filesystem capacity and write failures for the "
            "cited event window."
        ),
    },
}


def _signal_candidates(observations):
    """Promote impact-linked observations; never raw signals or dataset labels."""
    collected = {}
    for observation in observations:
        if not observation.get(
            "cause_candidate_eligible"
        ):
            continue
        key = (
            observation.get("signal_family"),
            observation.get("status"),
        )
        spec = _DIRECT_SIGNAL_CANDIDATES.get(key)
        if not spec:
            continue
        category = spec["category"]
        impact = observation.get(
            "impact_assessment", {}
        ) or {}
        impact_status = impact.get(
            "impact_status",
            "not_established",
        )
        score = (
            78
            if impact.get(
                "adverse_outcome_event_ids"
            )
            else 68
            if category == "disk_full"
            else 60
        )
        if observation.get(
            "recovery_observed"
        ):
            score = min(score, 60)
        item = collected.setdefault(
            category,
            {
                "id": "candidate-signal-" + category,
                "title": spec["title"],
                "category": category,
                "event_ids": [],
                "score": score,
                "reasons": [
                    (
                        "direct versioned signal plus "
                        "explicit impact context"
                    )
                ],
                "evidence": [],
                "weaknesses": [],
                "verification": spec["verification"],
                "observation_ids": [],
                "impact_links": [],
                "impact_event_ids": [],
                "adverse_outcome_event_ids": [],
                "outcome_event_ids": [],
                "recovery_event_ids": [],
                "successful_completion_event_ids": [],
                "contradicting_event_ids": [],
            },
        )
        item["score"] = max(
            item["score"],
            score,
        )
        event_id = observation.get(
            "event_id"
        )
        if event_id and event_id not in item["event_ids"]:
            item["event_ids"].append(event_id)
        observation_id = observation.get(
            "observation_id"
        )
        if (
            observation_id
            and observation_id
            not in item["observation_ids"]
        ):
            item["observation_ids"].append(
                observation_id
            )
        item["impact_links"].extend(
            impact.get("links", [])
            or []
        )
        for field in (
            "impact_event_ids",
            "adverse_outcome_event_ids",
            "outcome_event_ids",
            "recovery_event_ids",
            "successful_completion_event_ids",
            "contradicting_event_ids",
        ):
            item[field].extend(
                impact.get(field, [])
                or []
            )
        item["evidence"].append(
            (
                "signal={}:{}; rule={}; event={}; "
                "impact={}; entity_match={}; time_relation={}"
            ).format(
                observation.get("signal_family"),
                observation.get("status"),
                observation.get("rule_id"),
                event_id,
                impact_status,
                impact.get("entity_match", "unknown"),
                impact.get("time_relation", "unknown"),
            )
        )
        item["weaknesses"].extend(
            observation.get(
                "limitations", []
            )
            or []
        )
    for item in collected.values():
        item["event_ids"] = item["event_ids"][:12]
        item["observation_ids"] = item[
            "observation_ids"
        ][:12]
        item["impact_links"] = item[
            "impact_links"
        ][:12]
        for field in (
            "impact_event_ids",
            "adverse_outcome_event_ids",
            "outcome_event_ids",
            "recovery_event_ids",
            "successful_completion_event_ids",
            "contradicting_event_ids",
        ):
            item[field] = list(
                dict.fromkeys(item[field])
            )[:12]
        item["evidence"] = list(
            dict.fromkeys(item["evidence"])
        )[:12]
        item["weaknesses"] = list(
            dict.fromkeys(item["weaknesses"])
        )[:12]
    return list(collected.values())


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _metric(features, name):
    for item in features.get("metric_features", []):
        if item.get("metric") == name:
            return item
    return {}


def _before_anchor(group, anchor):
    seen = _parse(group.get("first_seen"))
    anchor_time = _parse((anchor or {}).get("timestamp"))
    if not seen or not anchor_time:
        return False
    delta = (anchor_time - seen).total_seconds()
    return 0 <= delta <= 15 * 60


def _candidate_for_detection(detection, groups, state):
    group = next(
        (
            item for item in groups
            if item.get("event_id") == detection.get("event_id")
        ),
        {},
    )
    labels = group.get("labels", {}) or {}
    score = LEVEL_POINTS.get(detection.get("level"), 10)
    evidence = [
        "rule={}; event={}; count={}".format(
            detection.get("id"),
            detection.get("event_id"),
            detection.get("group_count", 0),
        )
    ]
    reasons = ["detection rule matched"]
    if labels.get("level") in ("error", "fatal"):
        score += 12
        reasons.append("error-level template")
    if _before_anchor(group, state.get("anchor_event")):
        score += 14
        reasons.append("template precedes anchor")
    if group.get("related_deploys"):
        score += 16
        deploy = group["related_deploys"][0]
        evidence.append(
            "deploy={} {}m before first error".format(
                deploy.get("commit"),
                deploy.get("minutes_before_first_error"),
            )
        )
        reasons.append("same-service deploy precedes template")
    dimensions = group.get("dimensions", {}) or {}
    pod_count = (dimensions.get("pod", {}) or {}).get("unique", 0)
    if pod_count >= 2:
        score += 5
        evidence.append("observed across {} pods".format(pod_count))
    return {
        "id": "candidate-" + str(detection.get("event_id")),
        "title": detection.get("title") or labels.get("error_type") or "Detected failure",
        "category": detection.get("category") or "detected_failure",
        "event_ids": [detection.get("event_id")],
        "score": score,
        "reasons": reasons,
        "evidence": evidence,
        "weaknesses": [],
        "verification": "Inspect the representative trace and affected dependency before remediation.",
    }


def _traffic_candidate(features):
    request_rate = _metric(features, "request_rate_rps")
    ratio = request_rate.get("change_ratio")
    if ratio is None or ratio < 1.5:
        return None
    return {
        "id": "candidate-traffic-change",
        "title": "Traffic increase may amplify the failure",
        "category": "traffic_change",
        "event_ids": [],
        "score": min(55, 15 + int(ratio * 10)),
        "reasons": ["request rate rose {}x from first sample".format(ratio)],
        "evidence": ["request_rate_rps peak={}".format(request_rate.get("peak_value"))],
        "weaknesses": ["No historical baseline was collected."],
        "verification": "Compare traffic with a same-hour historical recording rule.",
    }


def _dependency_candidate(groups):
    for group in groups:
        labels = group.get("labels", {}) or {}
        text = " ".join([
            str(labels.get("error_type", "")),
            str(labels.get("event_signature", "")),
        ]).lower()
        if "upstream" not in text and "dependency" not in text:
            continue
        return {
            "id": "candidate-dependency-" + str(group.get("event_id")),
            "title": "Upstream dependency degradation",
            "category": "dependency_failure",
            "event_ids": [group.get("event_id")],
            "score": 42,
            "reasons": ["timeout template names an upstream dependency"],
            "evidence": [
                "event={}; count={}".format(
                    group.get("event_id"), group.get("count", 0)
                )
            ],
            "weaknesses": [
                "No dependency-specific error metric or shared trace has confirmed the edge."
            ],
            "verification": "Query the named dependency or inspect a shared trace across scoped services.",
        }
    return None


def _merge_same_event_candidates(candidates):
    """Several rules on one template are evidence for one cause, not rivals."""
    merged = {}
    for candidate in candidates:
        event_ids = tuple(
            item for item in candidate.get("event_ids", []) if item
        )
        key = event_ids or (candidate["category"], candidate["id"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        existing["score"] = max(existing["score"], candidate["score"])
        existing["confidence"] = existing["score"]
        existing["reasons"] = list(dict.fromkeys(
            existing["reasons"] + candidate["reasons"]
        ))
        existing["evidence"] = list(dict.fromkeys(
            existing["evidence"] + candidate["evidence"]
        ))
        existing["weaknesses"] = list(dict.fromkeys(
            existing["weaknesses"] + candidate["weaknesses"]
        ))
        categories = existing.setdefault(
            "supporting_categories", [existing["category"]]
        )
        if candidate["category"] not in categories:
            categories.append(candidate["category"])
    return list(merged.values())


def _contradictions(groups, features):
    """Surface simple, factual conflicts instead of hiding them in prose."""
    contradictions = []
    error_groups = [
        group for group in groups
        if (group.get("labels", {}) or {}).get("level") in {"error", "fatal"}
    ]
    error_rate = _metric(features, "error_rate")
    value = error_rate.get("value")
    if error_groups and value is not None:
        try:
            if float(value) <= 0:
                contradictions.append(
                    "error-level log evidence conflicts with error_rate=0 from Prometheus"
                )
        except (TypeError, ValueError):
            pass
    return contradictions


def score_candidates(state):
    groups = state.get("log_groups", []) or []
    features = state.get("incident_features", {}) or {}
    observations = build_observed_signals(
        groups
    )
    observation_patterns = (
        build_observation_patterns(
            observations,
            groups,
        )
    )
    candidates = [
        _candidate_for_detection(item, groups, state)
        for item in state.get("detections", []) or []
    ]
    candidates.extend(
        _signal_candidates(observations)
    )
    dependency = _dependency_candidate(groups)
    traffic = _traffic_candidate(features)
    if dependency:
        candidates.append(dependency)
    if traffic:
        candidates.append(traffic)

    ranked = sorted(
        _merge_same_event_candidates(candidates),
        key=lambda item: item["score"],
        reverse=True,
    )
    source_failures = features.get("source_failures", [])
    contradictions = _contradictions(groups, features)
    cap = 60 if source_failures else 100
    for candidate in ranked:
        candidate["score"] = min(candidate["score"], cap, 100)
        candidate["confidence"] = candidate["score"]
        if source_failures:
            candidate["weaknesses"].append(
                "Missing source data: " + ", ".join(source_failures)
            )
        if contradictions:
            candidate["weaknesses"].extend(contradictions)

    ranked = finalize_candidates(ranked)

    top_gap = None
    if len(ranked) > 1:
        top_gap = ranked[0]["score"] - ranked[1]["score"]
    abstain_reasons = []
    observed_categories = {
        spec["category"]
        for observation in observations
        for spec in [
            _DIRECT_SIGNAL_CANDIDATES.get(
                (
                    observation.get(
                        "signal_family"
                    ),
                    observation.get(
                        "status"
                    ),
                )
            )
        ]
        if spec
    }
    if not ranked:
        abstain_reasons.append("no deterministic candidate has supporting evidence")
    if not ranked and observations and not any(
        item.get("cause_candidate_eligible")
        for item in observations
    ):
        abstain_reasons.append(
            "direct signals were observed without an incident-impact link"
        )
    if source_failures:
        abstain_reasons.append("required evidence source failed: " + ", ".join(source_failures))
    if top_gap is not None and top_gap < 15:
        abstain_reasons.append("top deterministic candidates are materially tied")
    competing_observations = (
        len(observed_categories) > 1
    )
    if competing_observations:
        abstain_reasons.append(
            "direct observations span competing failure categories"
        )
    return {
        "method": "deterministic_rule_entity_impact_score_v3",
        "observation_schema_version":
        OBSERVED_SIGNAL_SCHEMA_VERSION,
        "impact_assessment_schema_version":
        IMPACT_ASSESSMENT_SCHEMA_VERSION,
        "observed_signals": observations,
        "observation_pattern_schema_version":
        OBSERVATION_PATTERN_SCHEMA_VERSION,
        "observation_patterns":
        observation_patterns,
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidates": ranked[:3],
        "top_score_gap": top_gap,
        "abstain": bool(abstain_reasons),
        "abstain_reasons": abstain_reasons,
        "contradictions": contradictions,
        "expansion_recommended": (
            bool(source_failures)
            or not ranked
            or (top_gap is not None and top_gap < 15)
            or competing_observations
        ),
        "expansion_reason": (
            "source failure or competing candidates require targeted evidence"
            if (
                source_failures
                or (
                    top_gap is not None
                    and top_gap < 15
                )
                or competing_observations
            )
            else (
                "no supported deterministic candidate; collect discriminating evidence"
                if not ranked
                else "current deterministic evidence is sufficient for initial review"
            )
        ),
    }
