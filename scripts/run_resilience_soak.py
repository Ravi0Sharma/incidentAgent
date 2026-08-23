#!/usr/bin/env python3
"""Repeat the distributed runtime probe to expose intermittent race failures."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_distributed_runtime import run_probe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--jobs-per-cycle", type=int, default=50)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.cycles <= 0:
        raise ValueError("cycles must be positive")
    started = time.monotonic()
    reports = []
    for cycle in range(1, args.cycles + 1):
        report = run_probe(jobs=args.jobs_per_cycle, workers=args.workers)
        reports.append(
            {
                "cycle": cycle,
                "jobs": report["multi_worker"]["jobs"],
                "worker_owners": report["multi_worker"]["distinct_worker_owners"],
                "recovered_jobs": report["multi_worker"]["recovered_jobs"],
                "revisions": report["multi_worker"]["revisions"],
            }
        )
    print(
        json.dumps(
            {
                "schema_version": "distributed-runtime-soak/v1",
                "cycles": args.cycles,
                "jobs_per_cycle": args.jobs_per_cycle + 1,
                "workers": args.workers,
                "total_jobs": sum(item["jobs"] for item in reports),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "results": reports,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
