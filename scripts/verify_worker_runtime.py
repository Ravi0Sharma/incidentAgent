#!/usr/bin/env python3
"""Direct local MySQL verification of worker heartbeat and crash recovery."""

import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from webhook import worker
from webhook.incident_store import (
    QueueCapacityError,
    _connection,
    claim_next_job,
    complete_job,
    list_events,
    record_event_and_enqueue,
    record_worker_heartbeat,
)


def _job_state(job_id):
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status,attempt_count,worker_id,leased_until "
            "FROM incident_jobs WHERE job_id=%s",
            (job_id,),
        )
        job = cur.fetchone()
        cur.execute(
            "SELECT worker_id,leased_until FROM incident_job_locks "
            "WHERE job_id=%s",
            (job_id,),
        )
        lock = cur.fetchone()
    return {"job": job, "lock": lock}


def _active_job_count():
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM incident_jobs "
            "WHERE status IN ('pending','leased')"
        )
        return int(cur.fetchone()[0])


async def _verify_heartbeat(incident_id):
    created = record_event_and_enqueue(
        incident_id,
        hashlib.sha256(f"{incident_id}:heartbeat".encode()).hexdigest(),
        "firing",
        {"alertname": "WorkerHeartbeatVerification", "service": "verifier"},
    )
    worker_id = "runtime-verifier-heartbeat"
    samples = []

    async def slow_handler(job):
        samples.append(_job_state(job["job_id"]))
        await asyncio.sleep(0.8)
        samples.append(_job_state(job["job_id"]))
        return {"revision": "runtime-verification"}

    original_lease = worker.JOB_LEASE_SECONDS
    original_heartbeat = worker.JOB_HEARTBEAT_INTERVAL_SECONDS
    worker.JOB_LEASE_SECONDS = 2
    worker.JOB_HEARTBEAT_INTERVAL_SECONDS = 0.2
    try:
        outcome = await worker.process_one(slow_handler, worker_id=worker_id)
    finally:
        worker.JOB_LEASE_SECONDS = original_lease
        worker.JOB_HEARTBEAT_INTERVAL_SECONDS = original_heartbeat
        record_worker_heartbeat(worker_id, "stopped", None)

    first_lease = samples[0]["job"][3]
    renewed_lease = samples[1]["job"][3]
    if outcome["status"] != "completed" or renewed_lease <= first_lease:
        raise RuntimeError("job lease heartbeat was not observed")
    if samples[1]["lock"] is None or samples[1]["lock"][1] != renewed_lease:
        raise RuntimeError("incident lock did not track the renewed job lease")
    final = _job_state(created["job_id"])
    if final["job"][0] != "completed" or final["lock"] is not None:
        raise RuntimeError("completed job retained an incident lock")
    return {
        "job_id": created["job_id"],
        "first_lease": first_lease,
        "renewed_lease": renewed_lease,
        "final_status": final["job"][0],
        "lock_after_completion": final["lock"],
    }


async def _main():
    if settings.ENVIRONMENT not in {"local", "development"}:
        raise RuntimeError("this fault-injection verifier only runs locally")
    if _active_job_count():
        raise RuntimeError("refusing to run while another queue job is active")

    suffix = uuid.uuid4().hex[:10].upper()
    heartbeat_incident = f"INC-WORKER-HEARTBEAT-{suffix}"
    heartbeat = await _verify_heartbeat(heartbeat_incident)

    crash_incident = f"INC-WORKER-CRASH-{suffix}"
    created = record_event_and_enqueue(
        crash_incident,
        hashlib.sha256(f"{crash_incident}:crash".encode()).hexdigest(),
        "firing",
        {"alertname": "WorkerCrashVerification", "service": "verifier"},
    )
    abandoned = claim_next_job("runtime-verifier-crashed", lease_seconds=1)
    if abandoned is None or abandoned["job_id"] != created["job_id"]:
        raise RuntimeError("crash probe did not lease its expected job")
    leased = _job_state(created["job_id"])
    await asyncio.sleep(1.2)
    recovered = claim_next_job("runtime-verifier-recovery", lease_seconds=2)
    if recovered is None or recovered["attempt_count"] != 2:
        raise RuntimeError("expired job was not reclaimed on attempt two")
    complete_job(recovered["job_id"], "runtime-verifier-recovery")
    recovered_state = _job_state(recovered["job_id"])

    rejected_incident = f"INC-WORKER-CAPACITY-{suffix}"
    try:
        record_event_and_enqueue(
            rejected_incident,
            hashlib.sha256(f"{rejected_incident}:capacity".encode()).hexdigest(),
            "firing",
            {"alertname": "QueueCapacityVerification"},
            max_pending_jobs=0,
        )
    except QueueCapacityError:
        pass
    else:
        raise RuntimeError("zero-capacity queue admitted a job")
    if list_events(rejected_incident):
        raise RuntimeError("capacity rejection committed an orphan event")

    report = {
        "schema_version": "worker-runtime-verification/v1",
        "heartbeat": heartbeat,
        "crash_recovery": {
            "job_id": created["job_id"],
            "leased_before_crash": leased,
            "recovered_attempt": recovered["attempt_count"],
            "final_status": recovered_state["job"][0],
            "lock_after_completion": recovered_state["lock"],
        },
        "queue_capacity": {
            "rejected": True,
            "orphan_events": len(list_events(rejected_incident)),
        },
    }
    print(json.dumps(report, default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main())
