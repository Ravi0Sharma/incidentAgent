#!/usr/bin/env python3
"""Exercise MySQL checkpoints, process kill, and concurrent worker processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHILD = PROJECT_ROOT / "scripts" / "runtime_probe_child.py"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from graph.checkpointer import MySQLSaver
from utils.mysql import connection as mysql_connection
from webhook.incident_store import record_event_and_enqueue


def _child_environment():
    environment = os.environ.copy()
    environment.update(
        {
            "PROCESS_ROLE": "worker",
            "API_DRAIN_JOBS": "false",
            "RUNTIME_SCHEMA_DDL_ENABLED": "false",
        }
    )
    return environment


def _run_child(*arguments, timeout=30):
    completed = subprocess.run(
        [sys.executable, str(CHILD), *map(str, arguments)],
        cwd=PROJECT_ROOT,
        env=_child_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _active_jobs():
    with mysql_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM incident_jobs "
            "WHERE status IN ('pending','leased')"
        )
        return int(cursor.fetchone()[0])


def _enqueue(incident_id, sequence):
    key = hashlib.sha256(f"{incident_id}:{sequence}".encode()).hexdigest()
    return record_event_and_enqueue(
        incident_id,
        key,
        "firing",
        {
            "alertname": "DistributedRuntimeProbe",
            "service": "runtime-verifier",
            "sequence": sequence,
        },
    )


def _kill_after_effect():
    process = subprocess.Popen(
        [
            sys.executable,
            str(CHILD),
            "crash-after-effect",
            "--worker-id",
            "probe-crashed-worker",
            "--lease-seconds",
            "1",
        ],
        cwd=PROJECT_ROOT,
        env=_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    if not selector.select(timeout=10):
        process.kill()
        stdout, stderr = process.communicate(timeout=5)
        raise RuntimeError(
            "crash child did not report its durable effect: " + stderr + stdout
        )
    line = process.stdout.readline()
    effect = json.loads(line)
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=5)
    process.stdout.close()
    process.stderr.close()
    if process.returncode not in {-signal.SIGKILL, 128 + signal.SIGKILL}:
        raise RuntimeError("crash child was not terminated with SIGKILL")
    return effect


def _verify_rows(incident_prefix, expected_jobs):
    with mysql_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*),COUNT(DISTINCT worker_id),"
            "SUM(status='completed'),SUM(attempt_count>1),SUM(result IS NOT NULL) "
            "FROM incident_jobs WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        jobs = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*),COUNT(DISTINCT job_id) FROM incident_revisions "
            "WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        revisions = cursor.fetchone()
    if int(jobs[0]) != expected_jobs or int(jobs[2] or 0) != expected_jobs:
        raise RuntimeError("not every distributed probe job completed")
    if int(jobs[1]) < 2:
        raise RuntimeError("the probe did not observe multiple worker owners")
    if int(jobs[4] or 0) != expected_jobs:
        raise RuntimeError("completed jobs are missing durable results")
    if tuple(map(int, revisions)) != (expected_jobs, expected_jobs):
        raise RuntimeError("job effects were duplicated or omitted")
    return {
        "jobs": int(jobs[0]),
        "distinct_worker_owners": int(jobs[1]),
        "recovered_jobs": int(jobs[3] or 0),
        "durable_results": int(jobs[4] or 0),
        "revisions": int(revisions[0]),
    }


def _cleanup(incident_prefix, checkpoint_thread):
    MySQLSaver().delete_thread(checkpoint_thread)
    with mysql_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM incident_job_locks WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_admission_locks WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_dead_letters WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_jobs WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_analysis_evidence WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_analysis_revisions WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_revisions WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_revision_heads WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        cursor.execute(
            "DELETE FROM incident_events WHERE incident_id LIKE %s",
            (incident_prefix + "%",),
        )
        connection.commit()


def run_probe(*, jobs=32, workers=4):
    if settings.ENVIRONMENT not in {"local", "development"}:
        raise RuntimeError("distributed fault injection may only run locally")
    if jobs < workers or workers < 2:
        raise ValueError("jobs must cover at least two worker processes")
    if _active_jobs():
        raise RuntimeError("refusing to mix the probe with active queue jobs")

    suffix = uuid.uuid4().hex[:12].upper()
    incident_prefix = f"INC-DISTRIBUTED-{suffix}-"
    checkpoint_thread = f"checkpoint-process-{suffix.lower()}"
    checkpoint_value = "visible-across-exec-processes"
    total_jobs = jobs + 1
    try:
        writer = _run_child(
            "checkpoint-write",
            checkpoint_thread,
            checkpoint_value,
        )
        reader = _run_child(
            "checkpoint-read",
            checkpoint_thread,
            checkpoint_value,
        )
        if writer["checkpoint_id"] != reader["checkpoint_id"]:
            raise RuntimeError("reader observed a different checkpoint")

        crash_incident = incident_prefix + "CRASH"
        crash_job = _enqueue(crash_incident, "crash")
        killed = _kill_after_effect()
        if killed["job_id"] != crash_job["job_id"]:
            raise RuntimeError("the killed process claimed an unexpected job")
        time.sleep(1.2)
        recovered = _run_child(
            "drain",
            "--worker-id",
            "probe-recovery-worker",
            "--lease-seconds",
            "5",
            "--work-delay",
            "0",
        )
        if recovered["completed"] != [crash_job["job_id"]]:
            raise RuntimeError(
                "the killed job was not recovered exactly once: "
                f"expected={[crash_job['job_id']]}, recovered={recovered['completed']}"
            )

        for index in range(jobs):
            # Use unique incidents so this probe measures cross-incident
            # worker concurrency. Same-incident admission and serialization
            # are covered by the MySQL lifecycle tests; pending events for one
            # incident now intentionally coalesce into one analysis job.
            incident_id = incident_prefix + f"LOAD-{index}"
            _enqueue(incident_id, index)

        start_at = time.time() + 0.5
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(CHILD),
                    "drain",
                    "--start-at",
                    str(start_at),
                    "--work-delay",
                    "0.03",
                ],
                cwd=PROJECT_ROOT,
                env=_child_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(workers)
        ]
        worker_reports = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            if process.returncode:
                raise RuntimeError("worker child failed: " + stderr + stdout)
            lines = [line for line in stdout.splitlines() if line.strip()]
            worker_reports.append(json.loads(lines[-1]))

        rows = _verify_rows(incident_prefix, total_jobs)
        return {
            "schema_version": "distributed-runtime-verification/v1",
            "checkpoint": {
                "writer_pid_boundary": True,
                "reader_pid_boundary": True,
                "checkpoint_id": writer["checkpoint_id"],
            },
            "sigkill_recovery": {
                "job_id": crash_job["job_id"],
                "revision": killed["revision"],
                "recovered_by": recovered["worker_id"],
            },
            "multi_worker": {
                **rows,
                "processes": workers,
                "reported_workers": [
                    report["worker_id"] for report in worker_reports
                ],
            },
        }
    finally:
        _cleanup(incident_prefix, checkpoint_thread)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=32)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    print(json.dumps(run_probe(jobs=args.jobs, workers=args.workers), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
