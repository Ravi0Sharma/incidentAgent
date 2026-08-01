"""Typed contract for deterministic hypothesis candidates."""


CANDIDATE_SCHEMA_VERSION = "deterministic-candidate/v1"


def _string_list(value, field):
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ValueError(f"{field} must be a list of strings")


def validate_candidate(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    required_strings = (
        "id",
        "title",
        "cause",
        "category",
        "claim_type",
        "causal_status",
        "verification",
        "next_verification",
        "trigger",
        "root_cause_status",
        "confidence_label",
    )
    for field in required_strings:
        if not isinstance(candidate.get(field), str) or not candidate[field]:
            raise ValueError(f"{field} must be a non-empty string")
    if candidate.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise ValueError("candidate schema version is invalid")
    if candidate.get("claim_type") != "hypothesis_candidate":
        raise ValueError("claim_type must be hypothesis_candidate")
    if candidate.get("causal_status") != "requires_verification":
        raise ValueError("causal_status must require verification")
    if candidate.get("root_cause_status") != "not_established":
        raise ValueError("deterministic candidates cannot establish root cause")
    if candidate.get("confidence_label") not in {"low", "medium", "high"}:
        raise ValueError("confidence_label must be low, medium, or high")
    for field in (
        "event_ids",
        "impact_event_ids",
        "adverse_outcome_event_ids",
        "outcome_event_ids",
        "recovery_event_ids",
        "successful_completion_event_ids",
        "contradicting_event_ids",
        "reasons",
        "evidence",
        "supporting_evidence",
        "weaknesses",
        "contradicting_evidence",
        "assumptions",
        "gaps",
        "contributing_factors",
        "symptoms",
        "recovery_actions",
    ):
        _string_list(candidate.get(field), field)
    for field in ("score", "confidence", "rank"):
        value = candidate.get(field)
        if not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
    if not 0 <= candidate["score"] <= 100:
        raise ValueError("score must be between 0 and 100")
    if not 0 <= candidate["confidence"] <= 100:
        raise ValueError("confidence must be between 0 and 100")
    if candidate["rank"] < 1:
        raise ValueError("rank must be at least 1")
    if candidate.get("mechanism") is not None:
        raise ValueError("deterministic candidates cannot claim a mechanism")
    if candidate.get("impact_link") is not None:
        raise ValueError("deterministic candidates cannot claim an impact link")
    return candidate


def finalize_candidates(candidates):
    finalized = []
    for rank, raw in enumerate(candidates, start=1):
        score = raw["score"]
        candidate = {
            **raw,
            "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
            "rank": rank,
            "cause": raw["title"],
            "mechanism": None,
            "impact_link": None,
            "trigger": "observed incident signal",
            "root_cause_status": "not_established",
            "claim_type": "hypothesis_candidate",
            "causal_status": "requires_verification",
            "supporting_evidence": list(raw.get("evidence", [])),
            "contradicting_evidence": list(raw.get("weaknesses", [])),
            "assumptions": [
                "Deterministic ranking is not a verified root cause."
            ],
            "gaps": list(raw.get("weaknesses", [])),
            "contributing_factors": [],
            "symptoms": list(raw.get("evidence", [])),
            "recovery_actions": [],
            "confidence_label": (
                "high" if score >= 70 else "medium" if score >= 40 else "low"
            ),
            "confidence_calibration": "not_calibrated",
            "next_verification": raw["verification"],
            "impact_event_ids": list(
                raw.get("impact_event_ids", [])
            ),
            "adverse_outcome_event_ids": list(
                raw.get("adverse_outcome_event_ids", [])
            ),
            "outcome_event_ids": list(
                raw.get("outcome_event_ids", [])
            ),
            "recovery_event_ids": list(
                raw.get("recovery_event_ids", [])
            ),
            "successful_completion_event_ids": list(
                raw.get("successful_completion_event_ids", [])
            ),
            "contradicting_event_ids": list(
                raw.get("contradicting_event_ids", [])
            ),
        }
        finalized.append(validate_candidate(candidate))
    return finalized
