"""Shared decision gate for API and static review surfaces."""


def analysis_review_state(state, parsed=None):
    """Return whether one exact, grounded analysis revision is approvable."""
    state = state or {}
    structured = (
        parsed
        if isinstance(parsed, dict)
        else state.get(
            "interpretation_structured",
            {},
        )
    ) or {}
    hypotheses = structured.get(
        "hypotheses",
        [],
    ) or []
    candidates = (
        state.get(
            "deterministic_assessment",
            {},
        )
        or {}
    ).get("candidates", []) or []

    def ranks(items):
        output = set()
        for item in items:
            if not isinstance(
                item, dict
            ):
                continue
            try:
                rank = int(
                    item.get("rank")
                )
            except (
                TypeError,
                ValueError,
            ):
                continue
            if rank in (1, 2, 3):
                output.add(rank)
        return output

    hypothesis_ranks = ranks(
        hypotheses
    )
    candidate_ranks = ranks(
        candidates
    )
    approvable_ranks = sorted(
        hypothesis_ranks
        & candidate_ranks
    )
    interpretation = str(
        state.get(
            "interpretation", ""
        )
        or ""
    )
    trace = state.get(
        "interpretation_tool_trace",
        [],
    ) or []
    quality = state.get(
        "interpretation_quality",
        {},
    ) or {}
    grounding = state.get(
        "claim_grounding",
        {},
    ) or {}

    provider_degraded = any(
        isinstance(item, dict)
        and item.get("status")
        == "degraded"
        for item in trace
    )
    abstained = bool(
        quality.get("abstained")
    ) or structured.get("status") == "abstained" or any(
        isinstance(item, dict)
        and item.get("status")
        == "abstained"
        for item in trace
    )
    quality_passed = (
        quality.get("passed") is True
    )
    grounding_passed = (
        grounding.get("passed") is True
    )
    validation_passed = (
        quality_passed
        and grounding_passed
    )
    unavailable = (
        not interpretation.strip()
        or (
            provider_degraded
            and not validation_passed
        )
    )
    inconclusive = (
        not unavailable and abstained
    )
    can_approve = (
        bool(approvable_ranks)
        and validation_passed
        and not unavailable
        and not inconclusive
    )
    if unavailable:
        reason = "analysis_unavailable"
    elif inconclusive:
        reason = "analysis_abstained"
    elif not hypotheses:
        reason = "no_hypothesis"
    elif not approvable_ranks:
        reason = (
            "hypothesis_not_in_saved_candidates"
        )
    elif not quality_passed:
        reason = "interpretation_quality_failed"
    elif not grounding_passed:
        reason = "claim_grounding_failed"
    else:
        reason = "approvable"
    return {
        "unavailable": unavailable,
        "inconclusive": inconclusive,
        "can_approve": can_approve,
        "provider_degraded":
        provider_degraded,
        "quality_passed":
        quality_passed,
        "grounding_passed":
        grounding_passed,
        "validation_passed":
        validation_passed,
        "hypothesis_count": min(
            len(hypotheses), 3
        ),
        "approvable_ranks":
        approvable_ranks,
        "reason": reason,
    }
