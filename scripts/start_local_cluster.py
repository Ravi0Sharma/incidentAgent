#!/usr/bin/env python3
"""Start one local API and multiple independently supervised worker processes."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _spawn(command, environment):
    return subprocess.Popen(
        [sys.executable, *command],
        cwd=PROJECT_ROOT,
        env=environment,
    )


def run_cluster(workers=2, api_port=8000, metrics_base_port=9100):
    if workers < 2:
        raise ValueError("local production topology requires at least two workers")
    base = os.environ.copy()
    base.update(
        {
            "ENVIRONMENT": base.get("ENVIRONMENT", "development"),
            "API_DRAIN_JOBS": "false",
            "RUNTIME_SCHEMA_DDL_ENABLED": "false",
        }
    )
    api_environment = {
        **base,
        "PROCESS_ROLE": "api",
        "PORT": str(api_port),
    }
    processes = [("api", _spawn(["scripts/start_api.py"], api_environment))]
    for index in range(workers):
        worker_environment = {
            **base,
            "PROCESS_ROLE": "worker",
            "WORKER_METRICS_PORT": str(metrics_base_port + index),
        }
        processes.append(
            (
                f"worker-{index + 1}",
                _spawn(["scripts/run_worker.py"], worker_environment),
            )
        )

    stopping = False

    def stop_cluster(signum, frame):
        nonlocal stopping
        stopping = True
        for _, process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGINT, stop_cluster)
    signal.signal(signal.SIGTERM, stop_cluster)
    try:
        while True:
            failed = [
                (name, process.returncode)
                for name, process in processes
                if process.poll() is not None
            ]
            if failed:
                if stopping and all(
                    code in {0, -signal.SIGTERM} for _, code in failed
                ):
                    break
                raise RuntimeError(f"local cluster process exited: {failed}")
            time.sleep(0.25)
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 15
        for _, process in processes:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--metrics-base-port", type=int, default=9100)
    args = parser.parse_args(argv)
    run_cluster(args.workers, args.api_port, args.metrics_base_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
