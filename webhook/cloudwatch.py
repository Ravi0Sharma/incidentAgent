"""Translate allowlisted CloudWatch alarm state changes to the alert contract."""

from datetime import datetime, timezone

from webhook.alert_contract import AlertContractError


CLOUDWATCH_EVENT_SOURCE = "aws.cloudwatch"
CLOUDWATCH_EVENT_TYPE = "CloudWatch Alarm State Change"


def _text(value):
    return str(value or "").strip()


def cloudwatch_alarm_to_alert(event, source_map, received_at=None):
    """Return a Grafana-compatible alert object from one EventBridge event.

    Alarm-to-service attribution is deliberately configuration-owned.  Event
    fields cannot introduce a new service, environment or severity.
    """
    if not isinstance(event, dict):
        raise AlertContractError(
            "invalid_cloudwatch_event",
            "CloudWatch event must be an object.",
        )
    if (
        event.get("source") != CLOUDWATCH_EVENT_SOURCE
        or event.get("detail-type") != CLOUDWATCH_EVENT_TYPE
    ):
        raise AlertContractError(
            "unsupported_cloudwatch_event",
            "Only CloudWatch alarm state-change events are accepted.",
        )
    detail = event.get("detail") or {}
    alarm_name = _text(detail.get("alarmName"))
    alarm_config = (source_map.get("alarms", {}) or {}).get(alarm_name)
    if not isinstance(alarm_config, dict):
        raise AlertContractError(
            "unsupported_cloudwatch_alarm",
            "Alarm is outside the configured incident support scope.",
        )
    service = _text(alarm_config.get("service"))
    environment = _text(alarm_config.get("environment"))
    severity = _text(alarm_config.get("severity")) or "unknown"
    if not service or not environment:
        raise AlertContractError(
            "invalid_cloudwatch_mapping",
            "Alarm mapping requires service and environment.",
        )
    state = detail.get("state") or {}
    state_value = _text(state.get("value")).upper()
    if state_value == "ALARM":
        status = "firing"
    elif state_value == "OK":
        status = "resolved"
    else:
        raise AlertContractError(
            "unsupported_cloudwatch_state",
            "Only ALARM and OK states enter the incident lifecycle.",
        )
    event_time = _text(state.get("timestamp") or event.get("time"))
    if not event_time:
        event_time = (
            received_at
            or datetime.now(timezone.utc).isoformat()
        )
    labels = {
        "service": service,
        "environment": environment,
        "severity": severity,
        "alertname": alarm_name,
        "source": "cloudwatch",
    }
    if event.get("region"):
        labels["aws_region"] = _text(event.get("region"))
    alert = {
        "service": service,
        "environment": environment,
        "severity": severity,
        "alertname": alarm_name,
        "message": _text(state.get("reason")),
        "labels": labels,
        "annotations": {
            "cloudwatch_state": state_value,
        },
        "startsAt": event_time,
        "fingerprint": _text(event.get("id")) or None,
        "status": status,
    }
    if status == "resolved":
        alert["endsAt"] = event_time
    return alert
