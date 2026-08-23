"""Minimal authenticated Prometheus endpoint for the dedicated worker."""

import asyncio
import hmac

from settings import (
    METRICS_BEARER_TOKEN,
    WORKER_HEARTBEAT_STALE_SECONDS,
    WORKER_METRICS_HOST,
    WORKER_METRICS_PORT,
)
from utils.metrics import prometheus_gauges, prometheus_text
from utils.mysql import pool_stats
from webhook.incident_store import operational_snapshot


def _authorized(request):
    if not METRICS_BEARER_TOKEN:
        return True
    expected = "Bearer " + METRICS_BEARER_TOKEN
    for line in request.split("\r\n"):
        if line.lower().startswith("authorization:"):
            supplied = line.split(":", 1)[1].strip()
            return hmac.compare_digest(supplied, expected)
    return False


async def _body():
    gauges = await asyncio.to_thread(
        operational_snapshot,
        WORKER_HEARTBEAT_STALE_SECONDS,
    )
    for name, value in pool_stats().items():
        gauges[f"mysql_pool_{name}"] = value
    return (prometheus_text() + prometheus_gauges(gauges)).encode("utf-8")


async def _handle(reader, writer):
    try:
        request = (await reader.readuntil(b"\r\n\r\n")).decode(
            "latin-1", errors="replace"
        )
        first_line = request.split("\r\n", 1)[0]
        if first_line != "GET /metrics HTTP/1.1":
            status, payload = "404 Not Found", b"not found\n"
        elif not _authorized(request):
            status, payload = "401 Unauthorized", b"unauthorized\n"
        else:
            status, payload = "200 OK", await _body()
        writer.write(
            (
                f"HTTP/1.1 {status}\r\n"
                "Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            + payload
        )
        await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def start_worker_metrics_server():
    return await asyncio.start_server(
        _handle,
        WORKER_METRICS_HOST,
        WORKER_METRICS_PORT,
    )
