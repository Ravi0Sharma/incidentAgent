def incident_skill_cards(state):
    """Small built-in runtime policy cards.

    Keep the useful policy signal without turning guidance into context bloat.
    """

    cards = [
        {
            "skill": "agent-incident-responder",
            "rules": [
                "Cite labels, counts, timestamps, rule IDs, pivots.",
                "Rank three hypotheses with confidence and weaknesses.",
                "Prefer first-firing symptom as anchor.",
                "Use tools only to verify or eliminate a concrete hypothesis.",
                "Do not propose destructive remediation as already executed."
            ]
        },
        {
            "skill": "severity-classification",
            "rules": [
                "Round severity up when impact is uncertain.",
                "Tier-0/customer-facing incidents deserve higher urgency."
            ]
        }
    ]

    if state.get("rca_chain") is not None:
        cards.append({
            "skill": "postmortem-writer",
            "rules": [
                "Use blameless language.",
                "Separate facts, contributing factors, and follow-ups.",
                "Avoid naming individuals or inventing process failures."
            ]
        })

    alert = state.get("alert", {}) or {}
    text = " ".join(
        str(v).lower()
        for v in alert.values()
    )
    if any(
        word in text
        for word in (
            "security",
            "breach",
            "credential",
            "unauthorized",
            "exfiltration"
        )
    ):
        cards.append({
            "skill": "security-incident",
            "rules": [
                "Treat uncertain security impact as security incident.",
                "Do not disclose details outside response team."
            ]
        })

    return cards
