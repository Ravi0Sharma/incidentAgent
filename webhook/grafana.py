from datetime import datetime, timezone

from utils.redaction import (
    redact_data,
    redact_labels,
    redact_message,
)
from settings import DEFAULT_ALERT_ENVIRONMENT


def normalize_grafana_alert(alert):
    labels = redact_labels(alert.get("labels", {}))
    annotations = redact_data(alert.get("annotations", {}))

    return {
        "incident_id": (
            alert.get("incident_id")
            or ""
        ),
        "service": (
            alert.get("service")
            or labels.get("service")
            or labels.get("job")
            or "unknown"
        ),
        "environment": (
            alert.get("environment")
            or labels.get("environment")
            or labels.get("env")
            or DEFAULT_ALERT_ENVIRONMENT
        ),
        "severity": (
            alert.get("severity")
            or labels.get("severity", "unknown")
        ),
        "alertname": (
            alert.get("alertname")
            or labels.get("alertname")
            or alert.get("service")
            or "unknown"
        ),
        "message": redact_message(
            alert.get("message")
            or annotations.get("summary")
            or annotations.get("description", "")
        ),
        "labels": labels,
        "annotations": annotations,
        "started_at": alert.get("startsAt"),
        "ended_at": alert.get("endsAt"),
        "received_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "generator_url": redact_message(
            alert.get("generatorURL", "")
        ),
        "fingerprint": alert.get("fingerprint"),
        "status": alert.get("status", "firing"),
    }
