import hashlib
import hmac

from langgraph.types import interrupt


def publish_review(state):
    """Require a distinct final decision after the draft has been rendered."""
    result = interrupt(
        {
            "review_stage": "publish",
            "incident_id": state.get("incident_id", "unknown"),
            "postmortem_draft": state.get("postmortem_draft", ""),
            "instructions": (
                "Resume with {'status': 'approved'} to publish the reviewed "
                "draft or {'status': 'rejected', 'feedback': '...'} to keep "
                "external publication blocked."
            ),
        }
    )
    status = str((result or {}).get("status", "rejected"))
    if status not in {"approved", "rejected"}:
        status = "rejected"
    draft_sha256 = hashlib.sha256(
        str(state.get("postmortem_draft", "")).encode("utf-8")
    ).hexdigest()
    approved_sha256 = str((result or {}).get("draft_sha256", ""))
    if status == "approved" and not hmac.compare_digest(
        approved_sha256,
        draft_sha256,
    ):
        raise ValueError("publication approval does not match the interrupted draft")
    return {
        "publish_review_status": status,
        "publish_review_feedback": str((result or {}).get("feedback", ""))[:2_000],
        "approved_draft_sha256": draft_sha256 if status == "approved" else "",
    }


def publish_review_router(state):
    return "publish" if state.get("publish_review_status") == "approved" else "end"
