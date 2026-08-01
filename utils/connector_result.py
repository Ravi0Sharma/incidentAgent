"""Common, redacted result metadata for read-only evidence connectors.

The collectors still return their domain objects (logs, metric samples and
deployments).  This module gives every collector a small common envelope so a
caller can distinguish an empty search from a backend failure without parsing
an exception string.
"""

from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import urlparse

from utils.redaction import redact_data, redact_message


CONNECTOR_PROVENANCE_VERSION = (
    "connector-provenance/v2"
)
QUERY_SPEC_VERSION = (
    "incident-query/v1"
)


RESULT_STATUSES = frozenset({
    "ok",
    "empty",
    "partial",
    "stale",
    "forbidden",
    "rate_limited",
    "invalid_query",
    "failed",
})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint_query(query):
    """Return a stable fingerprint without retaining the query or its values."""
    if isinstance(
        query, (dict, list, tuple)
    ):
        text = json.dumps(
            redact_data(query),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    else:
        text = str(query or "")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def query_spec(
    *,
    source,
    operation,
    service=None,
    filters=None,
    window=None,
    limits=None,
    sampling=None,
    query_template=None,
):
    """Build a bounded, sanitized query description that can be replayed."""
    spec = {
        "query_schema_version":
        QUERY_SPEC_VERSION,
        "source": str(source),
        "operation": str(operation),
        "service":
        redact_message(service or "")
        or None,
        "filters":
        redact_data(filters or {}),
        "window":
        redact_data(window or {}),
        "limits":
        redact_data(limits or {}),
        "sampling":
        redact_data(sampling or {}),
        "query_template":
        str(query_template or ""),
    }
    fingerprint = fingerprint_query(
        spec
    )
    return {
        **spec,
        "query_id":
        "qry-"
        + str(source).lower().replace(
            "_", "-"
        )[:20]
        + "-"
        + fingerprint.split(":", 1)[1],
        "query_fingerprint":
        fingerprint,
    }


def _safe_backend(value):
    raw = str(value or "")
    try:
        parsed = urlparse(raw)
    except ValueError:
        return redact_message(raw)
    if (
        parsed.scheme
        and parsed.hostname
    ):
        port = (
            f":{parsed.port}"
            if parsed.port
            else ""
        )
        return (
            f"{parsed.scheme}://"
            f"{parsed.hostname}{port}"
        )
    return redact_message(raw)


def provenance(
    *,
    source,
    backend,
    tenant=None,
    query=None,
    query_specification=None,
    source_schema_id=None,
    connector_version=None,
    window=None,
    result_count=0,
    fetched_count=0,
    reduced_count=None,
    truncated=False,
    request_id=None,
    collected_at=None,
    collection_revision=1,
):
    """Create the serializable provenance required by downstream evidence."""
    specification = (
        redact_data(
            query_specification
        )
        if query_specification
        else query_spec(
            source=source,
            operation=str(
                query
                or "unspecified"
            ),
            window=window,
        )
    )
    fingerprint = (
        specification.get(
            "query_fingerprint"
        )
        or fingerprint_query(
            specification
        )
    )
    query_id = (
        specification.get(
            "query_id"
        )
        or (
            "qry-"
            + str(source).lower()[:20]
            + "-"
            + fingerprint.split(
                ":", 1
            )[1]
        )
    )
    return {
        "provenance_schema_version":
        CONNECTOR_PROVENANCE_VERSION,
        "source": str(source),
        "source_schema_id": str(
            source_schema_id
            or f"{source}/unspecified"
        ),
        "connector_version": str(
            connector_version
            or f"{source}-connector/v1"
        ),
        "backend":
        _safe_backend(backend),
        "tenant": redact_message(tenant or "") or None,
        "query_id": query_id,
        "query_fingerprint":
        fingerprint,
        "query_specification":
        specification,
        "window": redact_data(window or {}),
        "collected_at": collected_at or utc_now(),
        "collection_revision":
        max(
            int(
                collection_revision
                or 1
            ),
            1,
        ),
        "result_count": max(int(result_count or 0), 0),
        "fetched_count": max(int(fetched_count or 0), 0),
        "reduced_count": (
            max(
                int(
                    reduced_count
                    if reduced_count
                    is not None
                    else fetched_count
                    or 0
                ),
                0,
            )
        ),
        "truncated": bool(truncated),
        "source_request_id": redact_message(request_id or "") or None,
    }


def status_for_count(result_count, *, truncated=False, stale=False):
    if stale:
        return "stale"
    if truncated:
        return "partial"
    return "ok" if int(result_count or 0) else "empty"


def source_result(status, provenance_data, *, diagnostic=None):
    """Build a source-status object and reject accidental unknown statuses."""
    if status not in RESULT_STATUSES:
        raise ValueError("unknown connector result status")
    result = {
        "status": status,
        "provenance": redact_data(provenance_data),
    }
    if diagnostic:
        result["diagnostic"] = redact_message(diagnostic)[:300]
    return result
