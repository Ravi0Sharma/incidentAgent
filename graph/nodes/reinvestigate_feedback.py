from utils.investigation_loop import initialize_loop


def reinvestigate_feedback(state):
    """Route reviewer feedback through semantic tools before rewriting text."""
    feedback = (state.get("review_feedback") or "").strip()
    decision = state.get("review_status", "rejected")
    budget = dict(state.get("investigation_budget", {}) or {})
    # A reviewer-triggered attempt gets a fresh bounded tool allowance. Keeping
    # the previous attempt's spent units would make every requested verification
    # fail immediately with "remote query budget exhausted".
    budget["used_remote_units"] = 0
    budget["tool_cache"] = {}
    budget["tool_history"] = []
    previous_loop = (
        budget.get("expansion_loop")
        or state.get("investigation_loop")
        or {}
    )
    budget["expansion_loop"] = initialize_loop({
        key: previous_loop.get(key)
        for key in {
            "max_rounds",
            "max_services",
            "max_result_bytes",
            "max_elapsed_seconds",
        }
        if previous_loop.get(key) is not None
    })
    return {
        "review_status": decision,
        "investigation_request": (
            "Reviewer requested more evidence: " + feedback
            if decision == "request_more_evidence"
            else feedback or (
                "Reviewer rejected the interpretation; verify the "
                "ranking and missing evidence."
            )
        ),
        "investigation_budget": budget,
        "investigation_loop": budget["expansion_loop"],
    }
