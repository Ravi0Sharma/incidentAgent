"""Deterministic reviewer guardrails for the narrative LLM output."""

import re

from settings import LOCAL_LLM_FORMAT_FALLBACK
from utils.stub_llm import stub_interpretation


_CORE_HEADERS = (
    "## TL;DR",
    "## Blast radius",
    "## Suggested next steps",
)
_HYPOTHESIS_HEADER = re.compile(
    r"^## Hypothesis (\d+):",
    re.MULTILINE,
)

_RISKY_ACTION = re.compile(
    r"\b(rollback|restart|delete|terminate|scale down|disable)\b",
    re.IGNORECASE,
)


def assess_interpretation(text, state):
    text = str(text or "")
    if "No supported root cause yet" in text:
        return {
            "passed": True,
            "abstained": True,
            "citation_hits": 0,
            "warnings": [],
        }
    warnings = []
    missing_headers = [
        header for header in _CORE_HEADERS
        if header not in text
    ]
    if missing_headers:
        warnings.append(
            "missing required sections: "
            + ", ".join(missing_headers)
        )
    hypothesis_numbers = [
        int(value)
        for value in _HYPOTHESIS_HEADER.findall(
            text
        )
    ]
    if not hypothesis_numbers:
        warnings.append(
            "no supported hypothesis section found"
        )
    elif (
        len(hypothesis_numbers) > 3
        or hypothesis_numbers
        != list(
            range(
                1,
                len(hypothesis_numbers) + 1,
            )
        )
    ):
        warnings.append(
            "hypothesis sections must be sequential and limited to three"
        )

    known = {
        node.get("event_id")
        for node in (
            state.get("evidence_graph", {}) or {}
        ).get("nodes", [])
        if node.get("event_id")
    }
    detections = {
        item.get("id")
        for item in state.get("detections", []) or []
        if item.get("id")
    }
    citation_hits = sum(
        1 for value in known | detections
        if value and value in text
    )
    if citation_hits == 0:
        warnings.append(
            "no event ID or detection-rule citation found"
        )
    if "Evidence:" not in text:
        warnings.append("no evidence section found")

    risky = _RISKY_ACTION.search(text)
    if risky and not re.search(
        r"\b(approval|approve|propose|risk)\b",
        text,
        re.IGNORECASE,
    ):
        warnings.append(
            "risky action appears without approval or risk language"
        )

    source_failures = [
        name for name, status in (
            state.get("source_status", {}) or {}
        ).items()
        if isinstance(status, dict)
        and status.get("status") == "failed"
    ]
    if source_failures:
        warnings.append(
            "failed sources not necessarily reflected in confidence: "
            + ", ".join(source_failures)
        )

    return {
        "passed": not warnings,
        "citation_hits": citation_hits,
        "warnings": warnings,
    }


def enforce_interpretation_quality(text, state):
    """Return a review-safe abstention instead of an unsupported narrative."""
    quality = assess_interpretation(text, state)
    if quality["passed"]:
        return text, quality

    assessment = state.get("deterministic_assessment", {}) or {}
    candidates = assessment.get("candidates", []) or []
    format_only_warnings = all(
        warning.startswith("missing required sections:")
        or warning == "no evidence section found"
        or warning == "no supported hypothesis section found"
        or warning
        == "hypothesis sections must be sequential and limited to three"
        for warning in quality["warnings"]
    )
    can_rebuild_local_format = (
        LOCAL_LLM_FORMAT_FALLBACK
        and not assessment.get("abstain", True)
        and bool(candidates)
        and quality.get("citation_hits", 0) > 0
        and bool(quality["warnings"])
        and format_only_warnings
    )
    if can_rebuild_local_format:
        rebuilt = stub_interpretation(
            state,
            limitation=(
                "The local model cited known evidence but missed the review "
                "format; this view was rebuilt from deterministic evidence."
            ),
        )
        rebuilt_quality = assess_interpretation(rebuilt, state)
        if rebuilt_quality["passed"]:
            return rebuilt, {
                **rebuilt_quality,
                "format_fallback": True,
                "local_only": True,
                "original_warnings": quality["warnings"],
            }

    reasons = "; ".join(quality["warnings"])
    safe_text = (
        "## TL;DR\n\n"
        "No supported root cause yet.\n\n"
        "## Evidence gaps\n\n"
        "- Generated interpretation did not meet the evidence/output safety contract: "
        + reasons
        + "\n\n## Suggested next steps\n\n"
        "1. Verify the cited incident evidence and regenerate a grounded interpretation.\n"
        "2. Collect the smallest missing source or discriminating trace."
    )
    return safe_text, {
        **quality,
        "passed": True,
        "abstained": True,
        "enforced_abstention": True,
    }
