"""Small durable MySQL queue worker used by the local webhook deployment."""

import socket
import time

from webhook.incident_store import claim_next_job, complete_job, fail_job
from utils.logging import emit_log_event
from utils.metrics import increment, observe


class TerminalJobError(ValueError):
    """A job failure that must not consume retry budget."""


def is_retryable_failure(error):
    """Keep invalid input and authorization failures out of retry loops."""
    return not isinstance(error, (TerminalJobError, PermissionError, ValueError, TypeError))


def default_worker_id():
    return socket.gethostname()[:96]


async def process_one(handler, worker_id=None):
    """Claim and process one job; return its outcome without losing failures."""
    worker_id = worker_id or default_worker_id()
    job = claim_next_job(worker_id)
    if not job:
        increment("queue_poll", outcome="empty")
        return {"status": "empty"}
    started = time.monotonic()
    try:
        result = await handler(job)
        complete_job(job["job_id"], worker_id)
        observe("job_duration_seconds", time.monotonic() - started, kind=job["kind"], outcome="completed")
        increment("jobs", kind=job["kind"], outcome="completed")
        emit_log_event("job_completed", incident_id=job["incident_id"], revision_id=result.get("revision"), node="worker", details={"job_id": job["job_id"], "kind": job["kind"]})
        return {"status": "completed", "job_id": job["job_id"], "result": result}
    except Exception as exc:
        outcome = fail_job(
            job,
            worker_id,
            exc,
            max_attempts=1 if not is_retryable_failure(exc) else 3,
        )
        observe("job_duration_seconds", time.monotonic() - started, kind=job["kind"], outcome=outcome)
        increment("jobs", kind=job["kind"], outcome=outcome)
        emit_log_event(
            "job_failed",
            severity="WARNING" if outcome == "retry" else "ERROR",
            incident_id=job["incident_id"], node="worker",
            error_category="terminal" if not is_retryable_failure(exc) else "transient",
            details={"job_id": job["job_id"], "kind": job["kind"], "error": str(exc)},
        )
        return {"status": outcome, "job_id": job["job_id"], "error": str(exc)}


async def drain(handler, max_jobs=10, worker_id=None):
    outcomes = []
    for _ in range(max_jobs):
        outcome = await process_one(handler, worker_id)
        outcomes.append(outcome)
        if outcome["status"] == "empty":
            break
    return outcomes
