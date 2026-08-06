"""Validate model-produced correlation before it becomes reviewer evidence."""

ALLOWED_PRIMARY = {
    "likely_causes", "amplifies", "symptom_of", "correlated_with",
}
ALLOWED_ALTERNATIVE = {
    "possible_causes", "contradicts", "needs_validation",
}


def _known_events(state):
    graph = state.get("evidence_graph", {}) or {}
    return {
        node.get("event_id")
        for node in graph.get("nodes", [])
        if node.get("event_id")
    }


def _event_ref(value, known):
    value = str(value or "").strip()
    return value in known or value.startswith("external:")


def _confidence_cap(state):
    sources = state.get("source_status", {}) or {}
    if any(
        item.get("status") == "failed"
        for item in sources.values()
        if isinstance(item, dict)
    ):
        return 60
    logs = (state.get("data_quality", {}) or {}).get("logs", {})
    if logs.get("possibly_truncated"):
        return 80
    return 100


def _clean_link(item, known, allowed, cap, warnings):
    if not isinstance(item, dict):
        warnings.append("discarded non-object semantic link")
        return None
    cause = item.get("cause_event")
    effect = item.get("effect_event")
    relationship = item.get("relationship")
    evidence = [
        str(value)[:300]
        for value in (item.get("evidence") or [])
        if str(value).strip()
    ][:5]
    if (
        not _event_ref(cause, known)
        or not _event_ref(effect, known)
    ):
        warnings.append(
            "discarded semantic link with unknown event reference"
        )
        return None
    if relationship not in allowed:
        warnings.append(
            "discarded semantic link with invalid relationship"
        )
        return None
    if not evidence:
        warnings.append(
            "discarded semantic link without cited evidence"
        )
        return None
    try:
        confidence = int(item.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(confidence, cap, 100))
    return {
        "cause_event": str(cause),
        "effect_event": str(effect),
        "relationship": relationship,
        "confidence": confidence,
        "evidence": evidence,
        "reasoning": str(item.get("reasoning", ""))[:500],
        "edge_schema_version":
        "incident-edge/v1",
        "relation_type":
        "semantic_hypothesis",
        "provenance":
        "model_inferred",
        "method":
        "validated_llm_semantic_report_v1",
        "supporting_event_ids": [
            str(cause),
            str(effect),
        ],
        "direction":
        "cause_to_effect",
        "causal_status":
        "not_established",
    }


def validate_semantic_report(report, state, tool_trace):
    report = report if isinstance(report, dict) else {}
    known = _known_events(state)
    cap = _confidence_cap(state)
    warnings = []
    primary = [
        link
        for link in (
            _clean_link(
                item, known, ALLOWED_PRIMARY, cap, warnings
            )
            for item in report.get("primary_chain", [])[:8]
        )
        if link
    ]
    alternatives = [
        link
        for link in (
            _clean_link(
                item, known, ALLOWED_ALTERNATIVE, cap, warnings
            )
            for item in report.get("alternative_links", [])[:8]
        )
        if link
    ]
    missing = [
        str(item)[:300]
        for item in report.get("missing_evidence", [])[:8]
        if str(item).strip()
    ]
    return {
        "primary_chain": primary,
        "alternative_links": alternatives,
        "missing_evidence": missing,
        # Tool trace is system-generated. Never trust a model-created audit log.
        "searches_performed": tool_trace or [],
        "validation": {
            "known_event_count": len(known),
            "confidence_cap": cap,
            "warnings": warnings,
        },
    }
