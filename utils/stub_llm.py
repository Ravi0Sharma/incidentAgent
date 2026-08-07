"""Evidence-only degraded outputs for --no-llm / provider outage.

These render deterministic candidates and explicit evidence gaps. They must
never invent an alternative cause, a systemic root cause, or a remediation.
"""


def _top_detection(state):

    dets = state.get(
        "detections", []
    ) or []

    return dets[0] if dets else None


def _top_group(state):

    groups = state.get(
        "log_groups", []
    ) or []

    return (
        groups[0] if groups else {}
    )


def _group_for_detection(state, detection):

    if not detection:
        return _top_group(state)

    event_id = detection.get(
        "event_id"
    )

    if event_id:
        for group in state.get(
            "log_groups", []
        ) or []:
            if group.get("event_id") == event_id:
                return group

    det_labels = detection.get(
        "group_labels"
    )
    for group in state.get(
        "log_groups", []
    ) or []:
        if group.get("labels") == det_labels:
            return group

    return _top_group(state)


def _candidates(state):
    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    return assessment.get(
        "candidates", []
    ) or []


def _selected_candidate(state, chosen=1):
    candidates = _candidates(state)
    try:
        index = max(int(chosen) - 1, 0)
    except (TypeError, ValueError):
        index = 0
    return (
        candidates[index]
        if index < len(candidates)
        else None
    )


def _candidate_evidence(
    state,
    candidate,
):
    evidence = list(
        candidate.get("evidence", [])
        if candidate
        else []
    )
    event_ids = list(
        candidate.get("event_ids", [])
        if candidate
        else []
    )
    if not evidence:
        detection = _top_detection(state)
        if detection:
            evidence.append(
                "rule={}; event={}; count={}".format(
                    detection.get("id"),
                    detection.get("event_id"),
                    detection.get(
                        "group_count", 0
                    ),
                )
            )
    if not evidence and event_ids:
        evidence.extend(
            f"event={event_id}"
            for event_id in event_ids
            if event_id
        )
    return list(dict.fromkeys(evidence))


def _candidate_gaps(candidate):
    if not candidate:
        return [
            "No deterministic candidate has supporting evidence."
        ]
    gaps = (
        candidate.get("gaps")
        or candidate.get("weaknesses")
        or []
    )
    return list(gaps) or [
        "The causal mechanism and root cause are not established."
    ]


def _service(state):
    scope = state.get(
        "scope_expansion", {}
    ) or {}
    alert = state.get("alert", {}) or {}
    group = _top_group(state)
    return (
        scope.get("alert_service")
        or (
            group.get("labels", {})
            or {}
        ).get("service")
        or alert.get("service")
        or "unknown"
    )


def _abstention(state, limitation):
    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    reasons = assessment.get(
        "abstain_reasons", []
    ) or [
        "No deterministic candidate has supporting evidence."
    ]
    return (
        "## TL;DR\n\n"
        "No supported root cause yet.\n\n"
        "## Evidence gaps\n\n- "
        + "\n- ".join(reasons)
        + "\n- "
        + limitation
        + "\n\n## Suggested next steps\n\n"
        "Collect the smallest missing source or discriminating trace, "
        "then rerun deterministic scoring before proposing remediation."
    )


def stub_interpretation(state, limitation=None):

    limitation = limitation or (
        "Degraded output: no model analysis was performed."
    )
    candidates = _candidates(state)[:3]
    assessment = state.get(
        "deterministic_assessment", {}
    ) or {}
    if assessment.get("abstain") or not candidates:
        return _abstention(state, limitation)

    blocks = []
    verifications = []
    for index, candidate in enumerate(
        candidates, start=1
    ):
        title = candidate.get(
            "title", "Unknown candidate"
        )
        confidence = str(
            candidate.get(
                "confidence_label", "low"
            )
        ).title()
        evidence = _candidate_evidence(
            state, candidate
        )
        gaps = _candidate_gaps(candidate)
        verification = (
            candidate.get("next_verification")
            or candidate.get("verification")
            or "Collect discriminating evidence."
        )
        verifications.append(verification)
        blocks.append(
            f"## Hypothesis {index}: {title}\n"
            f"Confidence: {confidence} "
            "(uncalibrated)\n\n"
            "Evidence:\n- "
            + "\n- ".join(
                evidence
                or ["No cited evidence."]
            )
            + "\n\nCorrelation:\n"
            "Deterministic scoring prioritized this candidate. "
            "It requires verification and is not an established root cause.\n\n"
            "Weaknesses:\n- "
            + "\n- ".join(gaps)
        )

    steps = [
        f"{index}. {value}"
        for index, value in enumerate(
            dict.fromkeys(verifications),
            start=1,
        )
    ]
    return (
        "## TL;DR\n"
        "Leading evidence-backed candidate for verification: "
        f"{candidates[0].get('title', 'unknown')}. "
        "Root cause is not established.\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n\n## Blast radius\n"
        f"Observed scope: service={_service(state)}. "
        "No broader impact is claimed by degraded mode.\n\n"
        "## Suggested next steps\n"
        + "\n".join(steps)
        + "\n\nLimitations:\n- "
        + limitation
    )


def stub_semantic_correlation(state):

    top_group = _top_group(state)
    deploys = state.get(
        "deploys", []
    ) or []
    metrics = state.get(
        "metrics", []
    ) or []

    cause_event = (
        deploys[0].get("event_id")
        if deploys
        else None
    )
    effect_event = (
        top_group.get("event_id")
        or "alert-1"
    )

    evidence = []
    if top_group:
        evidence.append(
            "top log group "
            f"{effect_event} has count="
            f"{top_group.get('count')} labels="
            f"{top_group.get('labels')}"
        )
    if deploys:
        evidence.append(
            "recent deploy "
            f"{cause_event} at "
            f"{deploys[0].get('time')}"
        )
    if metrics:
        evidence.append(
            "metric "
            f"{metrics[0].get('event_id')} "
            f"{metrics[0].get('metric')}="
            f"{metrics[0].get('value')}"
        )

    chains = []
    if cause_event and effect_event:
        top_candidate = _selected_candidate(
            state
        ) or {}
        chains.append(
            {
                "cause_event":
                cause_event,
                "effect_event":
                effect_event,
                "relationship":
                "correlated_with",
                "confidence": min(
                    int(
                        top_candidate.get(
                            "score", 0
                        )
                    ),
                    60,
                ),
                "evidence": evidence,
                "reasoning": (
                    "Stubbed semantic layer: "
                    "uses deterministic timeline, "
                    "top log group, metrics and "
                    "deploy proximity."
                )
            }
        )

    return {
        "primary_chain": chains,
        "alternative_links": [],
        "missing_evidence": [
            (
                "SKIP_LLM=1: run with a real "
                "LLM to perform semantic "
                "tool searches."
            )
        ],
        "searches_performed": []
    }


def stub_rca(state, chosen):

    candidate = _selected_candidate(
        state, chosen
    )
    if not candidate:
        title = "No supported candidate"
        evidence = [
            "No deterministic candidate has supporting evidence."
        ]
        gaps = evidence
        verification = (
            "Collect discriminating evidence and rerun scoring."
        )
    else:
        title = candidate.get(
            "title", "Unknown candidate"
        )
        evidence = _candidate_evidence(
            state, candidate
        ) or ["No cited evidence."]
        gaps = _candidate_gaps(candidate)
        verification = (
            candidate.get("next_verification")
            or candidate.get("verification")
            or "Collect discriminating evidence."
        )

    return (
        "## Surface symptom\n"
        f"Alert observed for service {_service(state)}.\n\n"
        "## Why 1: Which candidate was prioritized?\n"
        f"Answer: {title} was prioritized for verification.\n"
        "Evidence: "
        + " | ".join(evidence)
        + "\n\n"
        "## Why 2: Is its causal mechanism established?\n"
        "Answer: Unknown; deterministic scoring establishes priority, "
        "not causality.\n"
        "Evidence: "
        + " | ".join(gaps)
        + "\n\n"
        "## Why 3: Why did the underlying condition occur?\n"
        "Answer: Unknown from the available evidence.\n"
        "Evidence: no direct evidence\n\n"
        "## Why 4: Why was it not prevented earlier?\n"
        "Answer: Unknown from the available evidence.\n"
        "Evidence: no process or prevention evidence\n\n"
        "## Why 5: Is a systemic cause established?\n"
        "Answer: No; degraded mode cannot establish one.\n"
        "Evidence: no direct systemic evidence\n\n"
        "## Systemic root cause\n"
        "Not established. The selected item remains a hypothesis candidate "
        "until its mechanism and impact link are verified.\n\n"
        "## Contributing factors\n"
        "- No verified contributing factors are recorded.\n\n"
        "## Detection gap\n"
        f"Next discriminating check: {verification}\n\n"
        f"(Hypothesis {chosen} — "
        "degraded evidence-only output)\n"
    )


def stub_postmortem(state, chosen):

    incident_id = state.get(
        "incident_id", "unknown"
    )
    severity = state.get(
        "severity", "SEV?"
    )
    candidate = _selected_candidate(
        state, chosen
    )
    title = (
        candidate.get(
            "title", "unknown"
        )
        if candidate
        else "no supported candidate"
    )
    evidence = _candidate_evidence(
        state, candidate
    )
    verification = (
        (
            candidate.get("next_verification")
            or candidate.get("verification")
        )
        if candidate
        else None
    ) or (
        "Collect discriminating evidence and rerun scoring."
    )

    return (
        f"# Postmortem: {incident_id}\n\n"
        f"**Severity:** {severity}\n\n"
        "**Postmortem Owner:** "
        "(assign after publish)\n\n"
        "## Overview\n"
        f"Incident {incident_id} "
        f"({severity}) has {title} as an "
        "unverified investigation candidate. "
        "No root cause is established.\n\n"
        "## What Happened\n"
        f"Observed evidence: "
        + (
            " | ".join(evidence)
            if evidence
            else "none sufficient"
        )
        + ".\n\n"
        "## Root Cause\n"
        "Not established. Approval selected a candidate for review; it did "
        "not convert deterministic correlation into causal proof.\n\n"
        "## Contributing Factors\n"
        "- No verified contributing factors are recorded.\n\n"
        "## Resolution\n"
        "Under investigation. No completed "
        "mitigation was recorded in the evidence.\n\n"
        "## Impact\n"
        "| Metric | Value |\n"
        "| --- | --- |\n"
        f"| Severity | {severity} |\n"
        "| Duration | ~<fill> min |\n"
        "| Users affected | <fill> |\n\n"
        "## Action Items\n"
        f"- [ ] [owner-team] {verification}\n\n"
        f"(Hypothesis {chosen} — "
        "degraded evidence-only output)\n"
    )
