import html
from datetime import datetime


def _display(value):
    return html.escape(str(value or ""), quote=True)


def _valid_range(start, end):
    if not start or not end:
        return False
    try:
        return datetime.fromisoformat(
            str(end).replace("Z", "+00:00")
        ) > datetime.fromisoformat(
            str(start).replace("Z", "+00:00")
        )
    except ValueError:
        return False


def timeline_items(timeline):
    items = []
    groups = {
        "alert": False,
        "deploys": False,
        "logs": False,
        "metrics": False
    }

    for entry in timeline:
        timestamp = entry.get("timestamp")
        event_type = entry.get("type")

        if event_type == "alert" and timestamp:
            groups["alert"] = True
            items.append({
                "group": "alert",
                "start": timestamp,
                "type": "point",
                "content": "alert",
                "title": _display(entry.get("message", "alert")),
                "className": "alert",
            })
        elif event_type == "deploy":
            groups["deploys"] = True
            items.append({
                "group": "deploys",
                "start": timestamp,
                "type": "point",
                "content": "deploy " + _display(entry.get("commit", "")),
                "title": _display(entry),
                "className": "deploys",
            })
        elif event_type == "log_group":
            groups["logs"] = True
            labels = entry.get("labels", {})
            start = entry.get("first_seen") or timestamp
            end = entry.get("last_seen")
            items.append({
                "group": "logs",
                "start": start,
                "end": end if _valid_range(start, end) else None,
                "type": (
                    "range"
                    if _valid_range(start, end)
                    else "point"
                ),
                "content": (
                    _display(entry.get("count", ""))
                    + "x "
                    + _display(labels.get("error_type", "log"))
                ),
                "title": _display(entry),
                "className": "logs",
            })
        elif event_type == "metric" and timestamp:
            groups["metrics"] = True
            items.append({
                "group": "metrics",
                "start": timestamp,
                "type": "point",
                "content": (
                    _display(entry.get("metric", ""))
                    + "="
                    + _display(entry.get("value", ""))
                ),
                "title": _display(entry),
                "className": "metrics",
            })

    active_groups = [
        {"id": group, "content": group}
        for group, used in groups.items()
        if used
    ]

    return items, active_groups
