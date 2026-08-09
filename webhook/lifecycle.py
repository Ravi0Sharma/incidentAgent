"""Versioned local lifecycle state machine for incident intake.

It provides explicit state semantics for v0. A durable queue, leases, and
cross-worker optimistic locking are still required before production.
"""

LIFECYCLE_VERSION = "incident-lifecycle/v1"

ALLOWED_TRANSITIONS = {
    None: {"received"},
    "received": {"collecting", "resolved", "failed"},
    "collecting": {"analyzing", "degraded", "resolved", "failed"},
    "analyzing": {"awaiting_analysis_review", "degraded", "resolved", "failed"},
    "awaiting_analysis_review": {"analyzing", "drafting_postmortem", "resolved", "failed"},
    "drafting_postmortem": {"awaiting_publish_review", "completed", "resolved", "failed"},
    "awaiting_publish_review": {"completed", "drafting_postmortem", "resolved", "failed"},
    "degraded": {"analyzing", "awaiting_analysis_review", "resolved", "failed"},
    "completed": {"resolved"},
    # A later firing observation may reopen the same upstream occurrence. It
    # must re-enter through intake, never jump directly to review/completed.
    "resolved": {"received"},
    "failed": set(),
}


class LifecycleTransitionError(ValueError):
    pass


def validate_transition(current, target):
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise LifecycleTransitionError(
            f"illegal lifecycle transition: {current or 'none'} -> {target}"
        )
    return target
