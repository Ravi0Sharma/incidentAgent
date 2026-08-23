#!/usr/bin/env python3
"""Submit and verify one signed, duplicate-safe shadow canary over HTTPS."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone

import httpx


def _headers(body, webhook_secret, secure=True):
    timestamp = datetime.now(timezone.utc).isoformat()
    nonce = secrets.token_urlsafe(24)
    signed = (
        timestamp.encode() + b"." + nonce.encode() + b"." + body
        if secure
        else body
    )
    signature = hmac.new(
        webhook_secret.encode(),
        signed,
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Incident-Signature": "sha256=" + signature,
        "X-Incident-Client-ID": "shadow-canary",
    }
    if secure:
        headers["X-Incident-Timestamp"] = timestamp
        headers["X-Incident-Nonce"] = nonce
    return headers


def _payload(service, environment, tenant):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    fingerprint = "shadow-canary-" + secrets.token_hex(8)
    return {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "IncidentAgentShadowCanary",
                    "service": service,
                    "severity": "warning",
                    "environment": environment,
                    "tenant_id": tenant,
                },
                "annotations": {
                    "summary": "Synthetic read-only incident-agent shadow canary",
                },
                "startsAt": now,
                "fingerprint": fingerprint,
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    if not args.base_url.startswith("https://") and os.getenv("ENVIRONMENT") != "local":
        raise RuntimeError("shadow canary requires HTTPS")
    webhook_secret = os.environ["WEBHOOK_SHARED_SECRET"]
    canary_secret = os.environ["CANARY_SHARED_SECRET"]
    body = json.dumps(_payload(args.service, args.environment, args.tenant), separators=(",", ":")).encode()

    with httpx.Client(timeout=15) as client:
        first = client.post(
            args.base_url.rstrip("/") + "/v1/alerts",
            content=body,
            headers=_headers(body, webhook_secret, secure=not args.local),
        )
        first.raise_for_status()
        accepted = first.json()["results"][0]
        duplicate = client.post(
            args.base_url.rstrip("/") + "/v1/alerts",
            content=body,
            headers=_headers(body, webhook_secret, secure=not args.local),
        )
        duplicate.raise_for_status()
        duplicate_result = duplicate.json()["results"][0]
        if duplicate_result["status"] != "duplicate_event":
            raise RuntimeError("identical redelivery was not deduplicated")

        deadline = time.monotonic() + args.timeout_seconds
        status = None
        while time.monotonic() < deadline:
            response = client.get(
                args.base_url.rstrip("/") + f"/v1/canary/jobs/{accepted['job_id']}",
                params={"incident_id": accepted["incident_id"]},
                headers={"X-Canary-Token": canary_secret},
            )
            response.raise_for_status()
            status = response.json()
            if status["status"] in {"completed", "dead_letter"}:
                break
            time.sleep(1)
    if not status or status["status"] != "completed":
        raise RuntimeError(f"canary did not complete: {status}")
    if status["attempt_count"] != 1 or status["analysis_revisions"] < 1:
        raise RuntimeError(f"canary completion was not exactly-once: {status}")
    print(
        json.dumps(
            {
                "schema_version": "shadow-canary-result/v1",
                "incident_id": accepted["incident_id"],
                "job_id": accepted["job_id"],
                "duplicate_status": duplicate_result["status"],
                "job_status": status,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
