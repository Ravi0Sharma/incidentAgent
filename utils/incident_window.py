"""Build one immutable investigation window for an incident."""

from datetime import datetime, timedelta, timezone

from settings import (
    INCIDENT_WINDOW_MAX_MINUTES,
    INCIDENT_WINDOW_PRE_MINUTES,
    LOG_LOOKBACK_MINUTES,
)


def _parse(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None


def _iso(value):
    return value.astimezone(timezone.utc).isoformat()


def build_incident_window(alert, now=None):
    """Use alert time when available; never silently query only 'now'."""
    alert = alert or {}
    now = now or datetime.now(timezone.utc)
    started = _parse(alert.get("started_at"))
    ended = _parse(alert.get("ended_at"))
    received = _parse(alert.get("received_at")) or now

    if started is None:
        anchor = received
        anchor_source = "received_at"
    else:
        anchor = started
        anchor_source = "started_at"

    start = anchor - timedelta(minutes=INCIDENT_WINDOW_PRE_MINUTES)
    if ended and ended > anchor:
        end = ended
        end_source = "ended_at"
    else:
        end = received
        end_source = "received_at"

    # A firing alert can remain open for days. Keep an initial triage query
    # bounded while retaining the original firing time as immutable evidence.
    max_end = start + timedelta(minutes=INCIDENT_WINDOW_MAX_MINUTES)
    truncated = end > max_end
    if truncated:
        end = max_end

    if end <= start:
        end = start + timedelta(minutes=LOG_LOOKBACK_MINUTES)

    return {
        "anchor_time": _iso(anchor),
        "anchor_source": anchor_source,
        "start": _iso(start),
        "end": _iso(end),
        "end_source": end_source,
        "truncated": truncated,
        "max_minutes": INCIDENT_WINDOW_MAX_MINUTES,
    }


def parse_window(window):
    window = window or {}
    start = _parse(window.get("start"))
    end = _parse(window.get("end"))
    if start and end:
        return start, end
    now = datetime.now(timezone.utc)
    return now - timedelta(minutes=LOG_LOOKBACK_MINUTES), now
