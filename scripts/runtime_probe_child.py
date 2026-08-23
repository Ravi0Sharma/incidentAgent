#!/usr/bin/env python3
"""Child process used by the local distributed-runtime verifier."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from graph.checkpointer import MySQLSaver
from langgraph.checkpoint.base import empty_checkpoint
from webhook.incident_store import claim_next_job, complete_job, create_revision
from webhook.worker import default_worker_id


def _require_local():
    if settings.ENVIRONMENT not in {"local", "development"}:
        raise RuntimeError("runtime probe children may only run locally")


def _checkpoint_write(args):
    checkpoint = empty_checkpoint()
    version = "00000000000000000000000000000001.0000000000000000"
    checkpoint["channel_values"] = {"probe": args.value}
    checkpoint["channel_versions"] = {"probe": version}
    config = {
        "configurable": {
            "thread_id": args.thread_id,
            "checkpoint_ns": "",
        }
    }
    saved = MySQLSaver().put(config, checkpoint, {"source": "process-probe"}, {"probe": version})
    return {"checkpoint_id": saved["configurable"]["checkpoint_id"]}


def _checkpoint_read(args):
    loaded = MySQLSaver().get_tuple(
        {"configurable": {"thread_id": args.thread_id, "checkpoint_ns": ""}}
    )
    if loaded is None or loaded.checkpoint["channel_values"].get("probe") != args.value:
        raise RuntimeError("checkpoint was not visible in the reader process")
    return {"checkpoint_id": loaded.config["configurable"]["checkpoint_id"]}


def _drain(args):
    worker_id = args.worker_id or default_worker_id()
    completed = []
    if args.start_at:
        time.sleep(max(0.0, args.start_at - time.time()))
    while True:
        job = claim_next_job(worker_id, lease_seconds=args.lease_seconds)
        if job is None:
            break
        revision = create_revision(
            job["incident_id"],
            "distributed runtime probe",
            run_context=job.get("run_context"),
            job_id=job["job_id"],
        )
        if args.work_delay:
            time.sleep(args.work_delay)
        complete_job(
            job["job_id"],
            worker_id,
            {"revision": revision, "probe": "completed"},
        )
        completed.append(job["job_id"])
    return {"worker_id": worker_id, "completed": completed}


def _crash_after_effect(args):
    worker_id = args.worker_id or default_worker_id()
    job = claim_next_job(worker_id, lease_seconds=args.lease_seconds)
    if job is None:
        raise RuntimeError("crash probe found no job")
    revision = create_revision(
        job["incident_id"],
        "distributed crash probe",
        run_context=job.get("run_context"),
        job_id=job["job_id"],
    )
    print(
        json.dumps(
            {
                "worker_id": worker_id,
                "job_id": job["job_id"],
                "revision": revision,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    time.sleep(args.hold_seconds)
    raise RuntimeError("crash probe was not killed by its parent")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    writer = subparsers.add_parser("checkpoint-write")
    writer.add_argument("thread_id")
    writer.add_argument("value")
    writer.set_defaults(handler=_checkpoint_write)

    reader = subparsers.add_parser("checkpoint-read")
    reader.add_argument("thread_id")
    reader.add_argument("value")
    reader.set_defaults(handler=_checkpoint_read)

    drain = subparsers.add_parser("drain")
    drain.add_argument("--worker-id", default="")
    drain.add_argument("--lease-seconds", type=int, default=5)
    drain.add_argument("--work-delay", type=float, default=0.02)
    drain.add_argument("--start-at", type=float, default=0.0)
    drain.set_defaults(handler=_drain)

    crash = subparsers.add_parser("crash-after-effect")
    crash.add_argument("--worker-id", default="")
    crash.add_argument("--lease-seconds", type=int, default=1)
    crash.add_argument("--hold-seconds", type=float, default=300.0)
    crash.set_defaults(handler=_crash_after_effect)

    args = parser.parse_args(argv)
    _require_local()
    result = args.handler(args)
    if result is not None:
        print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
