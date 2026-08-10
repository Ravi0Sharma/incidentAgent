from webhook import registry
from webhook.incident_store import (
    get_analysis_revision_diff,
    list_events,
    record_analysis_revision,
)

from settings import (
    HTML_OUTPUT_DIR
)
from utils.render_safety import safe_report_filename


def is_awaiting_review(state):
    return bool(state.get("__interrupt__"))


def sync_registry(
    thread_id,
    normalized,
    state,
    analysis_revision=None,
    latest_event_id=None,
    expected_pending_version=None,
):
    revision_diff = None
    if analysis_revision is not None:
        # The pending-review payload is convenient UI state.  The compact
        # analysis snapshot is the durable revision boundary used by review
        # decisions and later reproducibility checks.
        record_analysis_revision(
            thread_id,
            analysis_revision,
            state,
            event_id=latest_event_id,
        )
        revision_diff = get_analysis_revision_diff(
            thread_id,
            analysis_revision,
        )
    if is_awaiting_review(state):
        registry.add_pending(
            thread_id,
            {
                "alertname": normalized.get(
                    "alertname", "Incident"
                ),
                "service": normalized.get(
                    "service", "unknown"
                ),
                "severity": normalized.get(
                    "severity", "unknown"
                ),
                "message": normalized.get(
                    "message", ""
                ),
                "interpretation": state.get(
                    "interpretation", ""
                ),
                "attempt": state.get(
                "interpretation_attempts", 1
                ),
                "interpretation_quality": state.get(
                    "interpretation_quality", {}
                ),
                "interpretation_structured": state.get(
                    "interpretation_structured", {}
                ),
                "claim_grounding": state.get(
                    "claim_grounding", {}
                ),
                "interpretation_tool_trace": state.get(
                    "interpretation_tool_trace", []
                ),
                "timeline": state.get("timeline", []),
                "log_groups": state.get("log_groups", []),
                "evidence_pack": state.get(
                    "evidence_pack", ""
                ),
                "scope_expansion": state.get(
                    "scope_expansion", {}
                ),
                "semantic_correlation": state.get(
                    "semantic_correlation", {}
                ),
                "semantic_correlation_tool_trace":
                state.get(
                    "semantic_correlation_tool_trace",
                    []
                ),
                "metrics": state.get("metrics", []),
                "deploys": state.get("deploys", []),
                "detections": state.get(
                    "detections", []
                ),
                "pivots": state.get("pivots", {}),
                "raw_log_count": state.get(
                    "raw_log_count", 0
                ),
                "incident_window": state.get(
                    "incident_window", {}
                ),
                "source_status": state.get(
                    "source_status", {}
                ),
                "data_quality": state.get(
                    "data_quality", {}
                ),
                "deterministic_assessment": state.get(
                    "deterministic_assessment", {}
                ),
                "decision_brief": state.get(
                    "decision_brief", {}
                ),
                "investigation_budget": state.get(
                    "investigation_budget", {}
                ),
                "investigation_loop": state.get(
                    "investigation_loop", {}
                ),
                "investigation_revisions": state.get(
                    "investigation_revisions", []
                ),
                "analysis_deadline": state.get(
                    "analysis_deadline", {}
                ),
                "model_usage_ledger": state.get(
                    "model_usage_ledger", {}
                ),
                "review_html_path": (
                    f"{HTML_OUTPUT_DIR}/"
                    + safe_report_filename(
                        thread_id,
                        "-review.html",
                    )
                ),
                "analysis_revision": analysis_revision,
                "revision_diff": revision_diff,
                "latest_event_id": latest_event_id,
                "event_history": list_events(thread_id),
            },
            expected_version=expected_pending_version,
        )
    else:
        registry.remove_pending(thread_id, expected_version=expected_pending_version)
