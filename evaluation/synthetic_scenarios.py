"""Synthetic incidents with explicit pre-review expectations.

The corpus is intentionally deterministic and contains no production data.
Each scenario isolates one ingest, reduction, or temporal-correlation risk.
"""

from datetime import (
    datetime,
    timedelta,
    timezone,
)


BASE = datetime(
    2026,
    7,
    22,
    10,
    0,
    tzinfo=timezone.utc,
)


def _ts(
    minutes=0,
    seconds=0,
):
    return (
        BASE
        + timedelta(
            minutes=minutes,
            seconds=seconds,
        )
    ).isoformat().replace(
        "+00:00", "Z"
    )


def _alert(
    scenario_id,
    service="payments",
    minute=8,
):
    timestamp = _ts(minute)
    return {
        "incident_id": scenario_id,
        "alertname": "SyntheticIncident",
        "service": service,
        "started_at": timestamp,
        "received_at": timestamp,
        "labels": {
            "service": service,
            "environment": "local",
            "severity": "warning",
        },
        "message": (
            "synthetic pre-review "
            "evaluation alert"
        ),
    }


def _log(
    minute,
    message,
    *,
    service="payments",
    level="info",
    error_type="",
    seconds=0,
    timestamp=None,
    **labels,
):
    return {
        "timestamp": (
            timestamp
            if timestamp is not None
            else _ts(minute, seconds)
        ),
        "message": message,
        "labels": {
            "service": service,
            "level": level,
            "error_type": error_type,
            **labels,
        },
    }


def _rare_signal():
    logs = [
        _log(
            index % 8,
            (
                "health poll completed "
                f"request_id=noise-{index}"
            ),
            error_type="ok",
            seconds=index % 60,
        )
        for index in range(5_000)
    ]
    logs.insert(
        2_503,
        _log(
            4,
            (
                "connection pool exhausted "
                "SQLSTATE[53300] "
                "trace_id=rare-signal"
            ),
            level="error",
            error_type="db_timeout",
            pod="payments-2",
        ),
    )
    return {
        "id": "rare-signal-in-noise",
        "description": (
            "One causal candidate among "
            "five thousand benign records."
        ),
        "alert": _alert(
            "EVAL-RARE"
        ),
        "logs": logs,
        "metrics": [],
        "deploys": [],
        "sample_limit": 120,
        "expect": {
            "detection_ids": [
                "db-connection-pool-exhausted"
            ],
            "top_candidate": (
                "Database connection pool exhausted"
            ),
            "retained_text": [
                "connection pool exhausted"
            ],
            "truncated": True,
        },
    }


def _semantic_codes():
    return {
        "id": "semantic-codes-do-not-merge",
        "description": (
            "Materially different SQLSTATE "
            "codes remain separate groups."
        ),
        "alert": _alert(
            "EVAL-CODES"
        ),
        "logs": [
            _log(
                2,
                (
                    "database operation failed "
                    "SQLSTATE[53300]"
                ),
                level="error",
                error_type="database_error",
            ),
            _log(
                3,
                (
                    "database operation failed "
                    "SQLSTATE[08006]"
                ),
                level="error",
                error_type="database_error",
            ),
        ],
        "metrics": [],
        "deploys": [],
        "expect": {
            "group_count": 2,
            "signatures": [
                "sqlstate=53300",
                "sqlstate=08006",
            ],
            "abstain": True,
        },
    }


def _deploy_after_error():
    return {
        "id": "deploy-after-error",
        "description": (
            "A later deploy must not become "
            "a deploy-regression signal."
        ),
        "alert": _alert(
            "EVAL-LATE-DEPLOY",
            minute=6,
        ),
        "logs": [
            _log(
                2,
                (
                    "dns lookup failed "
                    "NXDOMAIN for inventory"
                ),
                level="error",
                error_type="dns_error",
            )
        ],
        "metrics": [],
        "deploys": [
            {
                "event_id": "deploy-late",
                "commit": "late123",
                "time": _ts(3),
                "environment": "payments",
            }
        ],
        "expect": {
            "detection_ids": [
                "dns-resolution-failure"
            ],
            "forbidden_detection_ids": [
                "deploy-regression"
            ],
            "related_deploy_count": 0,
            "temporal_relationships": [
                "precedes_anchor"
            ],
        },
    }


def _timezone_ordering():
    return {
        "id": "timezone-and-out-of-order",
        "description": (
            "Source order and timezone offsets "
            "must not alter event order."
        ),
        "alert": _alert(
            "EVAL-TIME",
            minute=4,
        ),
        "logs": [
            _log(
                0,
                "dns lookup failed SERVFAIL",
                level="error",
                error_type="dns_error",
                timestamp=(
                    "2026-07-22T12:00:00+02:00"
                ),
            ),
            _log(
                0,
                "dns lookup failed SERVFAIL",
                level="error",
                error_type="dns_error",
                timestamp=(
                    "2026-07-22T09:59:00Z"
                ),
            ),
        ],
        "metrics": [],
        "deploys": [],
        "expect": {
            "first_seen": (
                "2026-07-22T09:59:00Z"
            ),
            "last_seen": (
                "2026-07-22T10:00:00Z"
            ),
        },
    }


def _cross_service_trace():
    return {
        "id": "cross-service-trace",
        "description": (
            "A shared trace remains visible "
            "across service groups."
        ),
        "alert": _alert(
            "EVAL-TRACE",
            minute=7,
        ),
        "logs": [
            _log(
                2,
                (
                    "connection pool exhausted "
                    "trace_id=abcdef1234567890"
                ),
                level="error",
                error_type="db_timeout",
            ),
            _log(
                3,
                (
                    "upstream timeout calling payments "
                    "trace_id=abcdef1234567890"
                ),
                service="checkout",
                level="error",
                error_type="dependency_timeout",
                dependency="payments",
            ),
        ],
        "metrics": [],
        "deploys": [],
        "expect": {
            "services": [
                "payments",
                "checkout",
            ],
            "pivot_values": [
                "abcdef1234567890"
            ],
        },
    }


def _contradicting_metric():
    return {
        "id": "log-metric-contradiction",
        "description": (
            "A zero error-rate metric remains "
            "visible as a contradiction."
        ),
        "alert": _alert(
            "EVAL-CONTRADICTION"
        ),
        "logs": [
            _log(
                3,
                "connection pool exhausted",
                level="error",
                error_type="db_timeout",
            )
        ],
        "metrics": [
            {
                "event_id": "metric-error-rate",
                "metric": "error_rate",
                "value": 0,
                "timestamp": _ts(8),
            }
        ],
        "deploys": [],
        "expect": {
            "contradiction": True,
        },
    }


def _insufficient_evidence():
    return {
        "id": "insufficient-evidence",
        "description": (
            "Benign records produce abstention."
        ),
        "alert": _alert(
            "EVAL-ABSTAIN"
        ),
        "logs": [
            _log(
                2,
                "request completed",
                error_type="ok",
            ),
            _log(
                3,
                "cache refresh completed",
                error_type="ok",
            ),
        ],
        "metrics": [],
        "deploys": [],
        "expect": {
            "abstain": True,
            "detection_ids": [],
        },
    }


def _sample_honesty():
    logs = [
        _log(
            index % 8,
            (
                "background operation completed "
                f"request_id=sample-{index}"
            ),
            error_type="ok",
            seconds=index % 60,
        )
        for index in range(1_000)
    ]
    return {
        "id": "truncated-sample-honesty",
        "description": (
            "A bounded sample never reports "
            "group counts as full-window truth."
        ),
        "alert": _alert(
            "EVAL-SAMPLE"
        ),
        "logs": logs,
        "metrics": [],
        "deploys": [],
        "sample_limit": 50,
        "expect": {
            "truncated": True,
            "group_counts_exact": False,
            "raw_log_count": 1_000,
        },
    }


def scenarios():
    return [
        _rare_signal(),
        _semantic_codes(),
        _deploy_after_error(),
        _timezone_ordering(),
        _cross_service_trace(),
        _contradicting_metric(),
        _insufficient_evidence(),
        _sample_honesty(),
    ]
