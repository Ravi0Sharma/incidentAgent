from datetime import datetime


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_features(metrics):
    features = []
    for metric in metrics or []:
        if metric.get("error"):
            continue
        first = _number(metric.get("first_value"))
        peak = _number(metric.get("peak_value", metric.get("value")))
        current = _number(metric.get("value"))
        change_ratio = None
        if first not in (None, 0) and peak is not None:
            change_ratio = round(peak / first, 2)
        features.append({
            "metric": metric.get("metric"),
            "value": current,
            "peak_value": peak,
            "peak_timestamp": metric.get("peak_timestamp"),
            "first_value": first,
            "trend": metric.get("trend", "unknown"),
            "change_ratio": change_ratio,
            "baseline": metric.get("baseline_value"),
            "baseline_status": (
                "available"
                if metric.get("baseline_value") is not None
                else "not_collected"
            ),
        })
    return features


def _log_features(groups):
    rows = []
    for group in groups or []:
        buckets = group.get("time_buckets", []) or []
        peak = max(
            buckets,
            key=lambda item: item.get("count", 0),
            default={},
        )
        labels = group.get("labels", {}) or {}
        rows.append({
            "event_id": group.get("event_id"),
            "service": labels.get("service"),
            "level": labels.get("level"),
            "error_type": labels.get("error_type"),
            "template": labels.get("event_signature"),
            "count": group.get("count", 0),
            "first_seen": group.get("first_seen"),
            "last_seen": group.get("last_seen"),
            "peak_bucket": peak.get("bucket"),
            "peak_per_minute": peak.get("count", 0),
            "spread": group.get("dimensions", {}),
            "detection_ids": [
                match.get("id")
                for match in group.get("detections", []) or []
                if match.get("id")
            ],
        })
    return rows


def _window_duration_minutes(window):
    try:
        start = datetime.fromisoformat(
            str(window.get("start")).replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            str(window.get("end")).replace("Z", "+00:00")
        )
        return max(round((end - start).total_seconds() / 60, 1), 1)
    except (TypeError, ValueError):
        return None


def build_features(state):
    """Facts only. This output deliberately contains no causal conclusion."""
    window = state.get("incident_window", {}) or {}
    return {
        "window_minutes": _window_duration_minutes(window),
        "log_templates": _log_features(state.get("log_groups", [])),
        "metric_features": _metric_features(state.get("metrics", [])),
        "trace_ids": (state.get("pivots", {}) or {}).get("trace_id", [])[:10],
        "request_ids": (state.get("pivots", {}) or {}).get("request_id", [])[:10],
        "source_failures": [
            name
            for name, status in (state.get("source_status", {}) or {}).items()
            if isinstance(status, dict) and status.get("status") == "failed"
        ],
        "raw_log_count": state.get("raw_log_count", 0),
        "sampled_log_count": len(state.get("logs", []) or []),
    }
