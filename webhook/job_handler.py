"""Incident analysis handler shared by local draining and dedicated workers."""

from graph.workflow import graph
from utils.logging import emit_log_event
from webhook import registry
from webhook.incident_store import create_revision
from webhook.state_sync import is_awaiting_review, sync_registry


async def run_normalized_alert(
    normalized,
    analysis_revision=None,
    latest_event_id=None,
    run_context=None,
):
    thread_id = normalized["incident_id"]
    config = {"configurable": {"thread_id": thread_id}}

    lifecycle = registry.get_lifecycle(thread_id)
    if lifecycle is None:
        registry.transition_lifecycle(thread_id, "received", "validated webhook alert")
        registry.transition_lifecycle(thread_id, "collecting", "workflow started")
        registry.transition_lifecycle(
            thread_id,
            "analyzing",
            "evidence collection started",
        )
    elif lifecycle["status"] == "resolved":
        registry.reopen_incident(
            thread_id,
            "new firing observation requires a new analysis revision",
        )
    elif lifecycle["status"] == "awaiting_analysis_review":
        registry.transition_lifecycle(
            thread_id,
            "analyzing",
            "new observation requires analysis revision",
            lifecycle["version"],
        )
    emit_log_event("workflow_started", incident_id=thread_id, node="webhook")
    state = await graph.ainvoke(
        {"alert": normalized, "execution_log": []},
        config=config,
    )

    sync_registry(
        thread_id,
        normalized,
        state,
        analysis_revision,
        latest_event_id,
        run_context=run_context,
    )
    awaiting_review = is_awaiting_review(state)
    registry.transition_lifecycle(
        thread_id,
        "awaiting_analysis_review" if awaiting_review else "completed",
        "human review required" if awaiting_review else "workflow completed",
    )
    emit_log_event(
        "workflow_paused" if awaiting_review else "workflow_completed",
        incident_id=thread_id,
        node="webhook",
    )
    return {
        "incident_id": thread_id,
        "alertname": normalized["alertname"],
        "status": "awaiting_review" if awaiting_review else "completed",
    }


async def run_incident_job(job):
    """Create a revision only after the caller has leased the durable job."""
    normalized = job["payload"]
    thread_id = job["incident_id"]
    revision = create_revision(
        thread_id,
        "reprocessing stored event" if job["kind"] == "reprocess"
        else "new alert observation",
        run_context=job.get("run_context"),
    )
    if normalized.get("status") == "resolved":
        return {
            "incident_id": thread_id,
            "revision": revision,
            "resolution": registry.resolve_incident(thread_id),
        }
    result = await run_normalized_alert(
        normalized,
        revision,
        job["event_id"],
        run_context=job.get("run_context"),
    )
    return {**result, "revision": revision}
