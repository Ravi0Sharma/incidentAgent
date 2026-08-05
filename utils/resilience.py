"""Small bounded retry and circuit-breaker helper for external evidence."""

import threading
import time

import httpx

from utils.redaction import redact_message

from settings import (
    SOURCE_CIRCUIT_OPEN_SECONDS,
    SOURCE_RETRY_ATTEMPTS,
    SOURCE_RETRY_BACKOFF_SECONDS,
    SOURCE_REQUEST_POLICIES,
)


class ConnectorRequestError(RuntimeError):
    """A sanitized, typed failure from a connector HTTP boundary."""

    def __init__(self, source, category, diagnostic, request_id=None):
        self.source = source
        self.category = category
        self.diagnostic = redact_message(diagnostic)[:300]
        self.request_id = redact_message(request_id or "")[:160] or None
        super().__init__(f"{source} {category}: {self.diagnostic}")


class SourceUnavailable(ConnectorRequestError):
    def __init__(self, source, diagnostic, request_id=None):
        super().__init__(source, "failed", diagnostic, request_id)


def _http_category(response):
    status = response.status_code
    if status in (401, 403):
        return "forbidden"
    if status == 429:
        return "rate_limited"
    if status in (400, 404, 405, 422):
        return "invalid_query"
    return "failed"


def _request_id(response):
    return (
        response.headers.get("x-request-id")
        or response.headers.get("x-amzn-requestid")
        or response.headers.get("x-github-request-id")
    )


_STATE = {}
_LOCK = threading.Lock()


def request(source, method, url, **kwargs):
    policy = SOURCE_REQUEST_POLICIES.get(
        source,
        {
            "timeout_seconds": 30.0,
            "retry_attempts": SOURCE_RETRY_ATTEMPTS,
            "retry_backoff_seconds": SOURCE_RETRY_BACKOFF_SECONDS,
            "circuit_open_seconds": SOURCE_CIRCUIT_OPEN_SECONDS,
        },
    )
    attempts = max(int(policy["retry_attempts"]), 1)
    retry_backoff = float(policy["retry_backoff_seconds"])
    circuit_open_seconds = int(policy["circuit_open_seconds"])
    kwargs.setdefault("timeout", float(policy["timeout_seconds"]))

    now = time.monotonic()
    with _LOCK:
        state = _STATE.get(source, {})
        if state.get("open_until", 0) > now:
            raise SourceUnavailable(
                source,
                "circuit open after repeated failures",
            )

    last_error = None
    for attempt in range(attempts):
        try:
            response = httpx.request(method, url, **kwargs)
            response.raise_for_status()
            with _LOCK:
                _STATE.pop(source, None)
            return response
        except httpx.HTTPStatusError as exc:
            category = _http_category(exc.response)
            request_id = _request_id(exc.response)
            # Authentication, validation and rate limits are not transient.
            if category in {"forbidden", "rate_limited", "invalid_query"}:
                raise ConnectorRequestError(
                    source,
                    category,
                    f"HTTP {exc.response.status_code}",
                    request_id,
                ) from exc
            last_error = exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(
                    retry_backoff * (attempt + 1)
                )

    with _LOCK:
        failures = _STATE.get(source, {}).get("failures", 0) + 1
        _STATE[source] = {
            "failures": failures,
            "open_until": (
                time.monotonic() + circuit_open_seconds
                if failures >= 3 else 0
            ),
        }
    raise SourceUnavailable(
        source,
        f"request failed after {attempts} attempts: {type(last_error).__name__}",
    )
