"""Typed model interpretation and deterministic claim-level grounding."""

import json
import re


INTERPRETATION_SCHEMA_VERSION = "model-interpretation/v1"
GROUNDING_SCHEMA_VERSION = "claim-grounding/v1"
CLAIM_SCHEMA_VERSION = "model-claim/v1"

_ALLOWED_CONFIDENCE = {"low", "medium", "high"}
_ALLOWED_CLAIM_STATUS = {
    "observed",
    "inferred",
    "hypothesis",
    "unknown",
}
_READ_ONLY_ACTION = re.compile(
    r"^\s*(inspect|check|verify|confirm|query|compare|review|search|read|"
    r"list|describe|collect|retrieve|measure|examine|trace|analy[sz]e|"
    r"capture|sample|look\s+up)\b",
    re.IGNORECASE,
)
_MUTATING_ACTION = re.compile(
    r"\b(roll\s*back|restart|redeploy|deploy|delete|terminate|kill|scale|"
    r"disable|enable|drain|fail\s*over|switch|promote|demote|rotate|"
    r"revoke|invalidate|flush|purge|patch|upgrade|downgrade|modify|change|"
    r"update|write|create|remove|stop|start|reboot|reschedule|cordon|"
    r"uncordon)\b",
    re.IGNORECASE,
)
_EXECUTION_CLAIM = re.compile(
    r"\b(rolled\s*back|restarted|redeployed|deployed|deleted|terminated|"
    r"killed|scaled|disabled|enabled|drained|failed\s*over|rotated|revoked|"
    r"purged|patched|upgraded|modified|updated|created|removed|stopped|"
    r"started|rebooted|rescheduled|cordoned|uncordoned|executed|performed|"
    r"applied)\b",
    re.IGNORECASE,
)


def extract_interpretation_json(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty interpretation response")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(
                "interpretation response did not contain JSON"
            )
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("interpretation response must be an object")
    return value


def _known_evidence(state):
    graph = state.get("evidence_graph", {}) or {}
    return {
        str(node.get("event_id")): node
        for node in graph.get("nodes", []) or []
        if isinstance(node, dict) and node.get("event_id")
    }


def _candidate_for_rank(state, rank):
    candidates = (
        (state.get("deterministic_assessment", {}) or {})
        .get("candidates", [])
        or []
    )
    for candidate in candidates:
        if int(candidate.get("rank", 0) or 0) == rank:
            return candidate
    return None


def _string_list(value, limit=8):
    if not isinstance(value, list):
        return []
    return [
        str(item)[:500]
        for item in value
        if str(item).strip()
    ][:limit]


def _id_list(value, known, limit=12):
    supplied = _string_list(value, limit)
    valid = [item for item in supplied if item in known]
    unknown = [item for item in supplied if item not in known]
    return valid, unknown


def _candidate_evidence_roles(candidate, known, semantic_links):
    """Resolve evidence IDs to the only claim roles they may support."""
    known_ids = set(known)

    def ids(field):
        return {
            value
            for value in _string_list(candidate.get(field), 12)
            if value in known_ids
        }

    cause = ids("event_ids")
    impact = ids("impact_event_ids") | ids("adverse_outcome_event_ids")
    outcome = ids("outcome_event_ids")
    successful_completion = ids("successful_completion_event_ids")
    recovery = ids("recovery_event_ids")
    contradicting = ids("contradicting_event_ids")
    mechanism = set()
    for link in semantic_links:
        if not isinstance(link, dict):
            continue
        linked = {
            value
            for value in _string_list(
                link.get("supporting_event_ids"),
                12,
            )
            if value in known_ids
        }
        # A semantic link can extend a candidate mechanism only when it is a
        # genuine cross-event relation anchored in that candidate's evidence.
        if len(linked) >= 2 and cause.intersection(linked):
            mechanism.update(linked)
    return {
        "cause": cause,
        "mechanism": mechanism,
        "impact": impact,
        "outcome_context": outcome,
        "successful_completion_context": successful_completion,
        "recovery_context": recovery,
        "contradicting": contradicting,
    }


def _action_class(action):
    read_only = bool(_READ_ONLY_ACTION.search(action))
    if _EXECUTION_CLAIM.search(action) and not read_only:
        return "execution_claim"
    if _MUTATING_ACTION.search(action):
        return "proposal"
    if read_only:
        return "read_only"
    return "unknown"


def _claim(
    raw,
    *,
    field,
    rank,
    supporting_ids,
    known_evidence_ids,
    semantic_links,
    warnings,
):
    raw = raw if isinstance(raw, dict) else {}
    text = str(raw.get("text", "")).strip()[:700]
    status = str(raw.get("status", "unknown")).lower()
    if status not in _ALLOWED_CLAIM_STATUS:
        status = "unknown"
        warnings.append(
            f"hypothesis {rank} {field}: invalid claim status"
        )
    claim_ids = _string_list(raw.get("evidence_ids"), 12)
    valid_ids = [
        item for item in claim_ids
        if item in supporting_ids
    ]
    unknown_ids = [
        item for item in claim_ids
        if item not in known_evidence_ids
    ]
    incompatible_ids = [
        item for item in claim_ids
        if (
            item in known_evidence_ids
            and item not in supporting_ids
        )
    ]
    decision = "supported"
    reason = "claim references validated hypothesis evidence"
    final_status = status
    if not text:
        decision = "rejected"
        final_status = "unknown"
        reason = "claim text is empty"
    elif unknown_ids or incompatible_ids or not valid_ids:
        decision = "rejected"
        final_status = "unknown"
        reason = (
            "claim cites unknown evidence IDs"
            if unknown_ids
            else "claim lacks compatible validated hypothesis evidence IDs"
        )
    elif field == "cause" and status == "observed":
        decision = "downgraded"
        final_status = "hypothesis"
        reason = "correlation evidence does not establish root cause"
    elif field == "mechanism":
        linked = any(
            set(link.get("supporting_event_ids", []) or [])
            .issubset(set(valid_ids))
            and len(
                link.get("supporting_event_ids", []) or []
            ) >= 2
            for link in semantic_links
        )
        if not linked:
            decision = "rejected"
            final_status = "unknown"
            reason = (
                "mechanism lacks a validated cross-event semantic link"
            )
        elif status == "observed":
            decision = "downgraded"
            final_status = "inferred"
            reason = "validated semantic links remain model inference"
    elif field == "impact" and status == "observed":
        decision = "downgraded"
        final_status = "inferred"
        reason = "impact linkage is not directly established"
    if decision != "supported":
        warnings.append(
            f"hypothesis {rank} {field}: {reason}"
        )
    return {
        "claim_schema_version": CLAIM_SCHEMA_VERSION,
        "field": field,
        "text": text,
        "original_status": status,
        "status": final_status,
        "evidence_ids": valid_ids,
        "unknown_evidence_ids": unknown_ids,
        "incompatible_evidence_ids": incompatible_ids,
        "decision": decision,
        "reason": reason,
    }


def abstention_payload(reason, state=None):
    assessment = (
        (state or {}).get("deterministic_assessment", {})
        or {}
    )
    gaps = _string_list(
        assessment.get("abstain_reasons")
        or [reason],
        8,
    )
    return {
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
        "status": "abstained",
        "tldr": "No supported root cause yet.",
        "hypotheses": [],
        "blast_radius": {
            "summary": "Not established from current evidence.",
            "services": [],
            "evidence_ids": [],
        },
        "suggested_next_steps": [{
            "action": (
                "Collect the smallest missing source or "
                "discriminating trace."
            ),
            "action_type": "read_only",
            "evidence_ids": [],
            "requires_approval": False,
        }],
        "evidence_gaps": gaps,
    }


def deterministic_payload(state, limitation=None):
    assessment = state.get("deterministic_assessment", {}) or {}
    candidates = assessment.get("candidates", []) or []
    if assessment.get("abstain") or not candidates:
        return abstention_payload(
            limitation
            or "deterministic evidence is insufficient",
            state,
        )
    hypotheses = []
    for candidate in candidates[:3]:
        ids = _string_list(candidate.get("event_ids"), 12)
        hypotheses.append({
            "rank": candidate.get("rank"),
            "title": candidate.get("title"),
            "confidence": candidate.get("confidence_label", "low"),
            "supporting_evidence_ids": ids,
            "contradicting_evidence_ids": [],
            "cause_claim": {
                "text": candidate.get("cause") or candidate.get("title"),
                "status": "hypothesis",
                "evidence_ids": ids,
            },
            "mechanism_claim": {
                "text": "Mechanism not established.",
                "status": "unknown",
                "evidence_ids": [],
            },
            "impact_claim": {
                "text": "Impact linkage not established.",
                "status": "unknown",
                "evidence_ids": [],
            },
            "assumptions": _string_list(candidate.get("assumptions"), 5),
            "gaps": _string_list(candidate.get("gaps"), 5),
            "next_verification": candidate.get("next_verification"),
        })
    scope = state.get("scope_expansion", {}) or {}
    return {
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
        "status": "supported",
        "tldr": (
            str(candidates[0].get("title"))
            + " is the leading unverified hypothesis."
        ),
        "hypotheses": hypotheses,
        "blast_radius": {
            "summary": "Bounded to services observed in incident scope.",
            "services": _string_list(scope.get("services"), 8),
            "evidence_ids": [],
        },
        "suggested_next_steps": [{
            "action": candidates[0].get("next_verification"),
            "action_type": "read_only",
            "evidence_ids": _string_list(
                candidates[0].get("event_ids"),
                12,
            ),
            "requires_approval": False,
        }],
        "evidence_gaps": _string_list(
            ([limitation] if limitation else [])
            + list(candidates[0].get("gaps", []) or []),
            8,
        ),
    }


def validate_and_ground(payload, state):
    known = _known_evidence(state)
    warnings = []
    if not isinstance(payload, dict):
        payload = abstention_payload(
            "model output was not an object",
            state,
        )
    if payload.get("schema_version") != INTERPRETATION_SCHEMA_VERSION:
        return (
            abstention_payload(
                "model output used an invalid schema version",
                state,
            ),
            {
                "schema_version": GROUNDING_SCHEMA_VERSION,
                "passed": False,
                "abstained": True,
                "warnings": ["invalid interpretation schema version"],
                "claims": [],
            },
        )
    assessment = state.get("deterministic_assessment", {}) or {}
    if assessment.get("abstain") and payload.get("status") != "abstained":
        warning = (
            "model support was rejected because the deterministic "
            "assessment requires abstention"
        )
        return (
            abstention_payload(
                "; ".join(
                    _string_list(
                        assessment.get("abstain_reasons"),
                        8,
                    )
                )
                or warning,
                state,
            ),
            {
                "schema_version": GROUNDING_SCHEMA_VERSION,
                "passed": True,
                "abstained": True,
                "enforced_deterministic_abstention": True,
                "warnings": [warning],
                "claims": [],
            },
        )
    if payload.get("status") == "abstained":
        clean = abstention_payload(
            "; ".join(_string_list(payload.get("evidence_gaps"), 8))
            or "model abstained",
            state,
        )
        return clean, {
            "schema_version": GROUNDING_SCHEMA_VERSION,
            "passed": True,
            "abstained": True,
            "warnings": [],
            "claims": [],
        }

    semantic_links = (
        (state.get("semantic_correlation", {}) or {})
        .get("primary_chain", [])
        or []
    )
    cleaned_hypotheses = []
    claim_results = []
    seen_ranks = set()
    for raw in (payload.get("hypotheses") or [])[:3]:
        if not isinstance(raw, dict):
            warnings.append("discarded non-object hypothesis")
            continue
        try:
            rank = int(raw.get("rank"))
        except (TypeError, ValueError):
            warnings.append("discarded hypothesis with invalid rank")
            continue
        candidate = _candidate_for_rank(state, rank)
        if not candidate or rank in seen_ranks:
            warnings.append(
                f"discarded hypothesis {rank}: no matching deterministic candidate"
            )
            continue
        seen_ranks.add(rank)
        resolved_ids, unknown_ids = _id_list(
            raw.get("supporting_evidence_ids"),
            known,
        )
        evidence_roles = _candidate_evidence_roles(
            candidate,
            known,
            semantic_links,
        )
        allowed_supporting_ids = (
            evidence_roles["cause"]
            | evidence_roles["mechanism"]
            | evidence_roles["impact"]
        )
        valid_ids = [
            value
            for value in resolved_ids
            if value in allowed_supporting_ids
        ]
        role_incompatible_ids = [
            value
            for value in resolved_ids
            if value not in allowed_supporting_ids
        ]
        if unknown_ids:
            warnings.append(
                f"hypothesis {rank}: unknown evidence IDs discarded"
            )
        if role_incompatible_ids:
            warnings.append(
                f"hypothesis {rank}: role-incompatible supporting evidence IDs discarded"
            )
        if not valid_ids or (
            evidence_roles["cause"]
            and not evidence_roles["cause"].intersection(valid_ids)
        ):
            warnings.append(
                f"discarded hypothesis {rank}: no compatible candidate evidence"
            )
            continue
        resolved_contradictions, contradiction_unknown = _id_list(
            raw.get("contradicting_evidence_ids"),
            known,
        )
        contradiction_ids = [
            value
            for value in resolved_contradictions
            if value in evidence_roles["contradicting"]
        ]
        incompatible_contradictions = [
            value
            for value in resolved_contradictions
            if value not in evidence_roles["contradicting"]
        ]
        if contradiction_unknown:
            warnings.append(
                f"hypothesis {rank}: unknown contradiction IDs discarded"
            )
        if incompatible_contradictions:
            warnings.append(
                f"hypothesis {rank}: role-incompatible contradiction IDs discarded"
            )
        confidence = str(raw.get("confidence", "low")).lower()
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "low"
            warnings.append(
                f"hypothesis {rank}: invalid confidence downgraded"
            )
        source_failed = any(
            isinstance(item, dict)
            and item.get("status") == "failed"
            for item in (
                state.get("source_status", {}) or {}
            ).values()
        )
        truncated = bool(
            (
                (state.get("data_quality", {}) or {})
                .get("logs", {})
                or {}
            ).get("possibly_truncated")
        )
        if source_failed and confidence != "low":
            confidence = "low"
            warnings.append(
                f"hypothesis {rank}: confidence capped by source failure"
            )
        elif truncated and confidence == "high":
            confidence = "medium"
            warnings.append(
                f"hypothesis {rank}: confidence capped by truncation"
            )
        claims = {}
        for field, key in (
            ("cause", "cause_claim"),
            ("mechanism", "mechanism_claim"),
            ("impact", "impact_claim"),
        ):
            compatible_ids = (
                evidence_roles[field]
                & set(valid_ids)
            )
            claim = _claim(
                raw.get(key),
                field=field,
                rank=rank,
                supporting_ids=compatible_ids,
                known_evidence_ids=set(known),
                semantic_links=semantic_links,
                warnings=warnings,
            )
            claims[field] = claim
            claim_results.append({
                "hypothesis_rank": rank,
                **claim,
            })
        if claims["cause"]["decision"] == "rejected":
            warnings.append(
                f"discarded hypothesis {rank}: cause claim was not grounded"
            )
            continue
        cleaned_hypotheses.append({
            "rank": rank,
            "title": str(candidate.get("title"))[:300],
            "confidence": confidence,
            "supporting_evidence_ids": valid_ids,
            "contradicting_evidence_ids": contradiction_ids,
            "evidence_roles": {
                "cause": sorted(
                    evidence_roles["cause"]
                    & set(valid_ids)
                ),
                "mechanism": sorted(
                    evidence_roles["mechanism"]
                    & set(valid_ids)
                ),
                "impact": sorted(
                    evidence_roles["impact"]
                    & set(valid_ids)
                ),
                "contradicting": contradiction_ids,
                "recovery_context": sorted(
                    evidence_roles["recovery_context"]
                ),
                "outcome_context": sorted(
                    evidence_roles["outcome_context"]
                ),
                "successful_completion_context": sorted(
                    evidence_roles["successful_completion_context"]
                ),
            },
            "claims": claims,
            "assumptions": _string_list(raw.get("assumptions"), 6),
            "gaps": _string_list(raw.get("gaps"), 6),
            "next_verification": str(
                raw.get("next_verification")
                or candidate.get("next_verification")
            )[:500],
            "deterministic_candidate_id": candidate.get("id"),
        })

    if not cleaned_hypotheses:
        return (
            abstention_payload(
                "no model hypothesis passed claim grounding",
                state,
            ),
            {
                "schema_version": GROUNDING_SCHEMA_VERSION,
                "passed": False,
                "abstained": True,
                "warnings": warnings,
                "claims": claim_results,
            },
        )
    cleaned_hypotheses.sort(key=lambda item: item["rank"])
    accepted_ids = {
        evidence_id
        for hypothesis in cleaned_hypotheses
        for evidence_id in (
            hypothesis["supporting_evidence_ids"]
            + hypothesis["contradicting_evidence_ids"]
        )
    }
    steps = []
    for raw in (payload.get("suggested_next_steps") or [])[:3]:
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action", "")).strip()[:500]
        if not action:
            continue
        requires_approval = bool(raw.get("requires_approval"))
        action_type = str(raw.get("action_type", "read_only"))
        classified = _action_class(action)
        if classified == "execution_claim":
            warnings.append(
                "next step removed: unsupported executed-action claim"
            )
            continue
        if classified in {"proposal", "unknown"} and (
            not requires_approval or action_type != "proposal"
        ):
            warnings.append(
                "risky or unknown next step removed: missing proposal/approval markers"
            )
            continue
        resolved_step_ids, _ = _id_list(
            raw.get("evidence_ids"),
            known,
        )
        valid_step_ids = [
            value
            for value in resolved_step_ids
            if value in accepted_ids
        ]
        steps.append({
            "action": action,
            "action_type": (
                "proposal"
                if classified in {"proposal", "unknown"}
                else "read_only"
            ),
            "evidence_ids": valid_step_ids,
            "requires_approval": (
                True
                if classified in {"proposal", "unknown"}
                else requires_approval
            ),
        })
    if not steps:
        top = cleaned_hypotheses[0]
        fallback_action = top["next_verification"]
        if _action_class(fallback_action) != "read_only":
            fallback_action = (
                "Inspect the cited evidence and collect the smallest "
                "missing read-only signal."
            )
        steps.append({
            "action": fallback_action,
            "action_type": "read_only",
            "evidence_ids": top["supporting_evidence_ids"],
            "requires_approval": False,
        })
    validated = {
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
        "status": "supported",
        "tldr": (
            cleaned_hypotheses[0]["title"]
            + " is the leading grounded but unverified hypothesis."
        ),
        "hypotheses": cleaned_hypotheses,
        "blast_radius": {
            "summary": (
                "Only services inside the bounded incident scope "
                "are shown; user impact is not established."
            ),
            "services": [
                service
                for service in _string_list(
                    (payload.get("blast_radius") or {}).get("services"),
                    8,
                )
                if service in set(
                    _string_list(
                        (
                            state.get("scope_expansion", {})
                            or {}
                        ).get("services"),
                        12,
                    )
                )
            ],
            "evidence_ids": _id_list(
                (payload.get("blast_radius") or {}).get("evidence_ids"),
                known,
            )[0],
        },
        "suggested_next_steps": steps,
        "evidence_gaps": _string_list(
            payload.get("evidence_gaps"),
            8,
        ),
    }
    validated["blast_radius"]["evidence_ids"] = [
        value
        for value in validated["blast_radius"]["evidence_ids"]
        if value in accepted_ids
    ]
    return validated, {
        "schema_version": GROUNDING_SCHEMA_VERSION,
        "passed": True,
        "abstained": False,
        "warnings": warnings,
        "claims": claim_results,
        "accepted_hypotheses": len(cleaned_hypotheses),
        "known_evidence_count": len(known),
    }


def render_grounded_interpretation(validated, state):
    if validated.get("status") == "abstained":
        gaps = _string_list(validated.get("evidence_gaps"), 8)
        return (
            "## TL;DR\n\nNo supported root cause yet.\n\n"
            "## Evidence gaps\n\n- "
            + "\n- ".join(gaps or ["No hypothesis passed grounding."])
            + "\n\n## Suggested next steps\n\n"
            "1. Collect the smallest missing source or discriminating trace."
        )
    candidates = {
        int(item.get("rank", 0)): item
        for item in (
            (state.get("deterministic_assessment", {}) or {})
            .get("candidates", [])
            or []
        )
    }
    sections = [
        "## TL;DR\n\n"
        + str(validated.get("tldr") or "Grounded hypotheses are available.")
    ]
    for item in validated.get("hypotheses", []):
        rank = item["rank"]
        candidate = candidates.get(rank, {})
        sections.append(
            f"## Hypothesis {rank}: {item['title']}\n\n"
            f"Confidence: {item['confidence'].title()} (uncalibrated)\n\n"
            "Claim status: "
            + item["claims"]["cause"]["status"]
            + "\n\nEvidence:\n"
            + "\n".join(
                f"- `{evidence_id}`"
                for evidence_id in item["supporting_evidence_ids"]
            )
            + "\n\nEvidence roles:\n"
            + "\n".join(
                "- "
                + role.replace("_", " ").title()
                + ": "
                + (
                    ", ".join(
                        f"`{evidence_id}`"
                        for evidence_id in ids
                    )
                    if ids
                    else "none"
                )
                for role, ids in item.get("evidence_roles", {}).items()
            )
            + "\n\nGrounded deterministic facts:\n"
            + "\n".join(
                "- " + text
                for text in _string_list(
                    candidate.get("supporting_evidence")
                    or candidate.get("evidence"),
                    5,
                )
            )
            + "\n\nMechanism:\n"
            + (
                item["claims"]["mechanism"]["text"]
                if item["claims"]["mechanism"]["decision"]
                != "rejected"
                else "Not established."
            )
            + "\n\nWeaknesses:\n"
            + "\n".join(
                "- " + value
                for value in (
                    item["gaps"]
                    or ["No additional model-supplied gap."]
                )
            )
        )
    blast = validated.get("blast_radius", {}) or {}
    sections.append(
        "## Blast radius\n\n"
        + str(blast.get("summary") or "Not established.")
        + (
            "\n\nServices: "
            + ", ".join(blast.get("services", []))
            if blast.get("services")
            else ""
        )
    )
    steps = validated.get("suggested_next_steps", []) or []
    sections.append(
        "## Suggested next steps\n\n"
        + "\n".join(
            f"{index}. {item['action']}"
            + (
                " (proposal; requires approval)"
                if item.get("requires_approval")
                else ""
            )
            for index, item in enumerate(steps, start=1)
        )
    )
    return "\n\n".join(sections)
