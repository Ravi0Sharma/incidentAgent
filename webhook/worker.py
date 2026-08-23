"""Durable MySQL worker with heartbeat and graceful drain semantics."""

import asyncio
import os
import socket
import time
import uuid

from settings import (
    JOB_HEARTBEAT_INTERVAL_SECONDS,
    JOB_LEASE_SECONDS,
    WORKER_POLL_INTERVAL_SECONDS,
)
from webhook.incident_store import (
    claim_next_job,
    complete_job,
    fail_job,
    ensure_schema,
    record_worker_heartbeat,
    renew_job_lease,
)
from utils.logging import emit_log_event
from utils.metrics import increment, observe


class TerminalJobError(ValueError):
    """A job failure that must not consume retry budget."""


class LeaseLostError(RuntimeError):
    """The worker can no longer safely commit the active job."""


def is_retryable_failure(error):
    """Keep invalid input and authorization failures out of retry loops."""
    return not isinstance(error, (TerminalJobError, PermissionError, ValueError, TypeError))


def default_worker_id():
    """Return a collision-resistant identity for each worker process."""
    host = socket.gethostname().split(".", 1)[0][:64]
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:12]}"[:128]


def _lease_lost_result(job, error):
    increment("jobs", kind=job["kind"], outcome="lease_lost")
    emit_log_event(
        "job_lease_lost",
        severity="ERROR",
        incident_id=job["incident_id"],
        node="worker",
        error_category="lease_lost",
        details={"job_id": job["job_id"], "kind": job["kind"]},
    )
    return {
        "status": "lease_lost",
        "job_id": job["job_id"],
        "error": str(error),
    }


async def _maintain_lease(job, worker_id, stop):
    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=JOB_HEARTBEAT_INTERVAL_SECONDS,
            )
        except asyncio.TimeoutError:
            try:
                await asyncio.to_thread(
                    renew_job_lease,
                    job["job_id"],
                    worker_id,
                    JOB_LEASE_SECONDS,
                )
                await asyncio.to_thread(
                    record_worker_heartbeat,
                    worker_id,
                    "running",
                    job["job_id"],
                )
            except Exception as exc:
                raise LeaseLostError(
                    "worker lost the job or incident lease"
                ) from exc


async def process_one(handler, worker_id=None):
    """Claim and process one job; return its outcome without losing failures."""
    worker_id = worker_id or default_worker_id()
    job = await asyncio.to_thread(
        claim_next_job,
        worker_id,
        JOB_LEASE_SECONDS,
    )
    if not job:
        increment("queue_poll", outcome="empty")
        return {"status": "empty"}
    await asyncio.to_thread(
        record_worker_heartbeat,
        worker_id,
        "running",
        job["job_id"],
    )
    started = time.monotonic()
    stop_heartbeat = asyncio.Event()
    handler_task = asyncio.create_task(handler(job))
    heartbeat_task = asyncio.create_task(
        _maintain_lease(job, worker_id, stop_heartbeat)
    )
    try:
        done, _ = await asyncio.wait(
            {handler_task, heartbeat_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat_task in done and not handler_task.done():
            handler_task.cancel()
            await asyncio.gather(handler_task, return_exceptions=True)
            heartbeat_task.result()
        result = await handler_task
        stop_heartbeat.set()
        await heartbeat_task
        try:
            await asyncio.to_thread(
                complete_job,
                job["job_id"],
                worker_id,
                result,
            )
        except ValueError as exc:
            raise LeaseLostError(str(exc)) from exc
        await asyncio.to_thread(
            record_worker_heartbeat,
            worker_id,
            "running",
            None,
        )
        observe("job_duration_seconds", time.monotonic() - started, kind=job["kind"], outcome="completed")
        increment("jobs", kind=job["kind"], outcome="completed")
        emit_log_event("job_completed", incident_id=job["incident_id"], revision_id=result.get("revision"), node="worker", details={"job_id": job["job_id"], "kind": job["kind"]})
        return {"status": "completed", "job_id": job["job_id"], "result": result}
    except LeaseLostError as exc:
        return _lease_lost_result(job, exc)
    except Exception as exc:
        stop_heartbeat.set()
        try:
            await heartbeat_task
        except LeaseLostError as lease_error:
            return _lease_lost_result(job, lease_error)
        try:
            outcome = await asyncio.to_thread(
                fail_job,
                job,
                worker_id,
                exc,
                1 if not is_retryable_failure(exc) else 3,
            )
        except ValueError as lease_error:
            if "job lease is not owned" in str(lease_error):
                return _lease_lost_result(
                    job,
                    LeaseLostError(str(lease_error)),
                )
            raise
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


async def run_forever(handler, *, worker_id=None, stop_event=None):
    """Poll continuously; stop admission on signal and finish the active job."""
    worker_id = worker_id or default_worker_id()
    stop_event = stop_event or asyncio.Event()
    await asyncio.to_thread(ensure_schema)
    await asyncio.to_thread(record_worker_heartbeat, worker_id, "running", None)
    emit_log_event(
        "worker_started",
        node="worker",
        details={"worker_id": worker_id},
    )
    try:
        while not stop_event.is_set():
            await asyncio.to_thread(
                record_worker_heartbeat, worker_id, "running", None
            )
            outcome = await process_one(handler, worker_id)
            if outcome["status"] != "empty":
                continue
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=WORKER_POLL_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await asyncio.to_thread(
            record_worker_heartbeat, worker_id, "stopped", None
        )
        emit_log_event(
            "worker_stopped",
            node="worker",
            details={"worker_id": worker_id},
        )
