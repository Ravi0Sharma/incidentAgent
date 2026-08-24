#!/usr/bin/env python3
"""Exercise high-volume alert bucketing through the webhook and workers.

The probe sends distinct Alertmanager events sharing one fingerprint and
event-time bucket. It verifies durable event preservation, then waits until
the worker queue for that incident has drained. It is intentionally restricted
to a local/development environment and cleans up only its run-scoped rows unless
``--keep-data`` is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from graph.checkpointer import MySQLSaver
from webhook.incident_store import _connection


def _headers(body: bytes, secret: str, *, secure: bool) -> dict[str, str]:
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = secrets.token_urlsafe(24)
    signed = (
        timestamp.encode() + b"." + nonce.encode() + b"." + body
        if secure
        else body
    )
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Incident-Signature": "sha256=" + signature,
        "X-Incident-Client-ID": "bucket-admission-load",
    }
    if secure:
        headers["X-Incident-Timestamp"] = timestamp
        headers["X-Incident-Nonce"] = nonce
    return headers


def _body(
    *,
    fingerprint: str,
    started_at: str,
    service: str,
    environment: str,
    tenant: str,
    start: int,
    count: int,
) -> bytes:
    alerts = []
    for sequence in range(start, start + count):
        alerts.append(
            {
                "status": "firing",
                "labels": {
                    "alertname": "IncidentAgentBucketAdmissionLoad",
                    "service": service,
                    "severity": "warning",
                    "environment": environment,
                    "tenant_id": tenant,
                },
                "annotations": {
                    "summary": "Synthetic bucket-admission load probe",
                    "sequence": str(sequence),
                },
                "startsAt": started_at,
                "fingerprint": fingerprint,
            }
        )
    return json.dumps({"status": "firing", "alerts": alerts}, separators=(",", ":")).encode()


async def _submit(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    body: bytes,
    secret: str,
    secure: bool,
    retries: int,
) -> dict:
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = await client.post(
                base_url.rstrip("/") + "/v1/alerts",
                content=body,
                headers=_headers(body, secret, secure=secure),
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt == retries:
                break
            await asyncio.sleep(0.1 * (attempt + 1))
    raise RuntimeError(f"webhook batch failed after retries: {last_error}")


def _incident_snapshot(incident_id: str) -> dict[str, int]:
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM incident_events WHERE incident_id=%s",
            (incident_id,),
        )
        events = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*),SUM(status='completed'),"
            "SUM(status IN ('pending','leased')) FROM incident_jobs "
            "WHERE incident_id=%s AND kind='analyze'",
            (incident_id,),
        )
        jobs = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM incident_analysis_revisions WHERE incident_id=%s",
            (incident_id,),
        )
        revisions = int(cur.fetchone()[0])
    return {
        "events": events,
        "analysis_jobs": int(jobs[0] or 0),
        "completed_jobs": int(jobs[1] or 0),
        "active_jobs": int(jobs[2] or 0),
        "analysis_revisions": revisions,
    }


def _model_usage_summary(incident_id: str) -> dict[str, int]:
    """Read the latest cumulative provider telemetry without prompts/responses."""
    totals = {
        "provider_calls": 0,
        "failed_calls": 0,
        "blocked_calls": 0,
        "usage_reported_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT state_summary FROM incident_analysis_revisions "
            "WHERE incident_id=%s ORDER BY revision DESC LIMIT 1",
            (incident_id,),
        )
        row = cur.fetchone()
    if not row:
        return totals
    summary = row[0]
    if isinstance(summary, (str, bytes, bytearray)):
        summary = json.loads(summary)
    ledger = (summary or {}).get("model_usage_ledger", {}) or {}
    for key in (
        "provider_calls",
        "failed_calls",
        "blocked_calls",
        "usage_reported_calls",
    ):
        ledger_key = {
            "provider_calls": "call_count",
            "failed_calls": "failed_call_count",
            "blocked_calls": "blocked_call_count",
            "usage_reported_calls": "usage_reported_calls",
        }[key]
        totals[key] = int(ledger.get(ledger_key, 0) or 0)

    token_values_available = 1
    for total_key, ledger_key in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
    ):
        try:
            totals[total_key] = int(ledger.get(ledger_key, 0) or 0)
        except (TypeError, ValueError):
            # Some runtimes mask provider usage in persisted telemetry. Keep the
            # call result usable without attempting to reconstruct the values.
            token_values_available = 0
    totals["token_values_available"] = token_values_available
    totals["total_tokens"] = (
        totals["input_tokens"] + totals["output_tokens"]
    )
    return totals


def _cleanup(incident_id: str) -> None:
    MySQLSaver().delete_thread(incident_id)
    with _connection() as conn, conn.cursor() as cur:
        for table in (
            "incident_job_locks",
            "incident_admission_locks",
            "incident_dead_letters",
            "incident_jobs",
            "incident_analysis_evidence",
            "incident_analysis_revisions",
            "incident_evidence_records",
            "incident_revisions",
            "incident_revision_heads",
            "pending_reviews",
            "incident_lifecycle",
            "incident_events",
        ):
            column = "thread_id" if table in {"pending_reviews", "incident_lifecycle"} else "incident_id"
            cur.execute(f"DELETE FROM {table} WHERE {column}=%s", (incident_id,))
        cur.execute("DELETE FROM incident_id_map WHERE incident_id=%s", (incident_id,))
        conn.commit()


async def run_probe(args) -> dict:
    if settings.ENVIRONMENT not in {"local", "development"}:
        raise RuntimeError("bucket admission load probe may only run locally")
    if args.events <= 0 or args.batch_size <= 0 or args.events % args.batch_size:
        raise ValueError("events must be positive and divisible by batch-size")
    if args.batch_size > 50:
        raise ValueError("batch-size must not exceed the webhook contract limit of 50")
    if args.concurrency <= 0:
        raise ValueError("concurrency must be positive")
    secret = os.getenv("WEBHOOK_SHARED_SECRET", "")
    if not secret:
        raise RuntimeError("WEBHOOK_SHARED_SECRET is required")

    run_id = uuid.uuid4().hex
    fingerprint = "bucket-admission-load-" + run_id
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started = time.monotonic()
    readiness = None
    responses = []
    incident_id = None

    async with httpx.AsyncClient(timeout=args.request_timeout_seconds) as client:
        readiness_response = await client.get(args.base_url.rstrip("/") + "/readyz")
        readiness_response.raise_for_status()
        readiness = readiness_response.json()
        semaphore = asyncio.Semaphore(args.concurrency)

        async def submit_batch(offset: int):
            async with semaphore:
                return await _submit(
                    client,
                    base_url=args.base_url,
                    body=_body(
                        fingerprint=fingerprint,
                        started_at=started_at,
                        service=args.service,
                        environment=args.environment,
                        tenant=args.tenant,
                        start=offset,
                        count=args.batch_size,
                    ),
                    secret=secret,
                    secure=settings.ENVIRONMENT in {"shadow", "production"},
                    retries=args.retries,
                )

        batches = range(0, args.events, args.batch_size)
        for completed in asyncio.as_completed([submit_batch(offset) for offset in batches]):
            responses.append(await completed)

    all_results = [
        item
        for response in responses
        for item in response.get("results", [])
    ]
    if len(all_results) != args.events:
        raise RuntimeError(
            f"expected {args.events} webhook results, received {len(all_results)}"
        )
    incident_ids = {item.get("incident_id") for item in all_results}
    if len(incident_ids) != 1 or None in incident_ids:
        raise RuntimeError(f"events did not converge on one incident: {incident_ids}")
    incident_id = incident_ids.pop()
    statuses = Counter(item.get("status") for item in all_results)

    deadline = time.monotonic() + args.drain_timeout_seconds
    snapshot = _incident_snapshot(incident_id)
    while snapshot["active_jobs"] and time.monotonic() < deadline:
        await asyncio.sleep(1)
        snapshot = _incident_snapshot(incident_id)
    if snapshot["active_jobs"]:
        raise RuntimeError(f"incident jobs did not drain: {snapshot}")
    if snapshot["events"] != args.events:
        raise RuntimeError(f"durable event count mismatch: {snapshot}")
    if snapshot["analysis_jobs"] != snapshot["completed_jobs"]:
        raise RuntimeError(f"analysis jobs did not complete: {snapshot}")

    model_usage = _model_usage_summary(incident_id)

    result = {
        "schema_version": "bucket-admission-load/v1",
        "events_requested": args.events,
        "events_durable": snapshot["events"],
        "incident_id": incident_id,
        "webhook_statuses": dict(sorted(statuses.items())),
        "analysis_jobs": snapshot["analysis_jobs"],
        "analysis_revisions": snapshot["analysis_revisions"],
        "model_usage": model_usage,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "readiness": readiness,
        "model_enabled": bool(settings.MODEL_ENABLED and not settings.SKIP_LLM),
    }
    if not args.keep_data:
        _cleanup(incident_id)
        result["cleanup"] = "completed"
    else:
        result["cleanup"] = "retained"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--request-timeout-seconds", type=float, default=30)
    parser.add_argument("--drain-timeout-seconds", type=float, default=300)
    parser.add_argument("--service", default="checkout")
    parser.add_argument("--environment", default="development")
    parser.add_argument("--tenant", default="local-compose")
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(run_probe(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
