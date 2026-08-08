"""Small versioned JSON contract for accepted incident alert payloads."""

from datetime import datetime


ALERT_CONTRACT_VERSION = "grafana-alertmanager/v1"
ALLOWED_ALERT_STATUSES = {"firing", "resolved"}


class AlertContractError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _is_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _validate_text(alert, field, max_field_length):
    value = alert.get(field)
    if value is None:
        return
    if not isinstance(value, str):
        raise AlertContractError(
            "invalid_field_type",
            f"{field} must be a string.",
        )
    if len(value) > max_field_length:
        raise AlertContractError(
            "field_too_long",
            f"{field} exceeds the maximum length.",
        )


def _validate_mapping(alert, field, maximum, max_field_length):
    value = alert.get(field, {})
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise AlertContractError(
            "invalid_field_type",
            f"{field} must be an object.",
        )
    if len(value) > maximum:
        raise AlertContractError(
            "too_many_fields",
            f"{field} exceeds the maximum number of entries.",
        )
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise AlertContractError(
                "invalid_field_type",
                f"{field} keys and values must be strings.",
            )
        if len(key) > max_field_length or len(item) > max_field_length:
            raise AlertContractError(
                "field_too_long",
                f"{field} contains an entry exceeding the maximum length.",
            )


def _has_identity(alert):
    labels = alert.get("labels") or {}
    return any(
        isinstance(value, str) and value.strip()
        for value in (
            alert.get("alertname"),
            alert.get("service"),
            labels.get("alertname"),
            labels.get("service"),
            labels.get("job"),
        )
    )


def _validate_alert(
    alert,
    max_labels,
    max_annotations,
    max_field_length,
    supported_services=None,
    supported_environments=None,
    default_environment=None,
):
    if not isinstance(alert, dict):
        raise AlertContractError(
            "invalid_alert",
            "Each alert must be an object.",
        )

    for field in (
        "incident_id",
        "service",
        "severity",
        "alertname",
        "message",
        "fingerprint",
        "generatorURL",
    ):
        _validate_text(alert, field, max_field_length)

    _validate_mapping(
        alert,
        "labels",
        max_labels,
        max_field_length,
    )
    _validate_mapping(
        alert,
        "annotations",
        max_annotations,
        max_field_length,
    )

    status = alert.get("status")
    if status is not None and status not in ALLOWED_ALERT_STATUSES:
        raise AlertContractError(
            "invalid_status",
            "status must be firing or resolved.",
        )

    for field in ("startsAt", "endsAt"):
        value = alert.get(field)
        if value is not None and not _is_timestamp(value):
            raise AlertContractError(
                "invalid_timestamp",
                f"{field} must be an ISO-8601 timestamp.",
            )

    if not _has_identity(alert):
        raise AlertContractError(
            "missing_identity",
            "An alert must include an alertname or service identity.",
        )

    labels = alert.get("labels") or {}
    service = alert.get("service") or labels.get("service") or labels.get("job")
    if supported_services is not None and service not in supported_services:
        raise AlertContractError(
            "unsupported_service",
            "service is outside the configured incident support scope.",
        )
    environment = (
        alert.get("environment")
        or labels.get("environment")
        or labels.get("env")
        or default_environment
    )
    if supported_environments is not None and environment not in supported_environments:
        raise AlertContractError(
            "unsupported_environment",
            "environment is outside the configured incident support scope.",
        )


def validate_alert_payload(
    payload,
    max_alerts,
    max_labels,
    max_annotations,
    max_field_length,
    supported_services=None,
    supported_environments=None,
    default_environment=None,
):
    """Validate a Grafana single alert or Alertmanager alert batch.

    The return value is the normalized list of source alert objects. The caller
    still owns lifecycle handling for resolved events and durable ingestion.
    """
    if not isinstance(payload, dict):
        raise AlertContractError(
            "invalid_payload",
            "Webhook JSON must be an object.",
        )

    if "alerts" in payload:
        alerts = payload["alerts"]
        if not isinstance(alerts, list):
            raise AlertContractError(
                "invalid_alerts",
                "alerts must be an array.",
            )
        if not alerts:
            raise AlertContractError(
                "empty_alerts",
                "alerts must contain at least one alert.",
            )
    else:
        alerts = [payload]

    if len(alerts) > max_alerts:
        raise AlertContractError(
            "too_many_alerts",
            "alerts exceeds the maximum batch size.",
        )

    for alert in alerts:
        _validate_alert(
            alert,
            max_labels=max_labels,
            max_annotations=max_annotations,
            max_field_length=max_field_length,
            supported_services=supported_services,
            supported_environments=supported_environments,
            default_environment=default_environment,
        )

    return alerts
