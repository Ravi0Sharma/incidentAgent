#!/usr/bin/env python3
"""Continuous incident worker entry point for staging/shadow deployments."""

import asyncio
import signal
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from utils.runtime_config import validate_runtime_config
from webhook.job_handler import run_incident_job
from webhook.metrics_server import start_worker_metrics_server
from webhook.worker import run_forever


async def _main():
    validate_runtime_config(settings)
    if not settings.WORKER_ENABLED:
        raise RuntimeError("WORKER_ENABLED is false; worker kill switch is active")
    if settings.API_DRAIN_JOBS:
        raise RuntimeError(
            "API_DRAIN_JOBS must be false when the dedicated worker is running"
        )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, name, None)
        if value is not None:
            loop.add_signal_handler(value, stop.set)
    metrics_server = await start_worker_metrics_server()
    try:
        await run_forever(run_incident_job, stop_event=stop)
    finally:
        metrics_server.close()
        await metrics_server.wait_closed()


if __name__ == "__main__":
    asyncio.run(_main())
