"""Small dependency-free Prometheus exposition for local operational signals.

The process-local registry intentionally has no durability or multi-process
aggregation guarantee.  It gives deployments a stable scrape surface until a
shared metrics backend is configured.
"""

from collections import defaultdict
from threading import Lock


_LOCK = Lock()
_COUNTERS = defaultdict(float)
_HISTOGRAMS = defaultdict(lambda: {"count": 0, "sum": 0.0})


def _labels(labels):
    return tuple(sorted((str(key), str(value)) for key, value in (labels or {}).items()))


def increment(name, value=1, **labels):
    with _LOCK:
        _COUNTERS[(name, _labels(labels))] += float(value)


def observe(name, value, **labels):
    with _LOCK:
        item = _HISTOGRAMS[(name, _labels(labels))]
        item["count"] += 1
        item["sum"] += float(value)


def _format_labels(labels):
    if not labels:
        return ""
    escaped = []
    for key, value in labels:
        safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        escaped.append(f'{key}="{safe}"')
    return "{" + ",".join(escaped) + "}"


def prometheus_text():
    """Return a deterministic Prometheus text exposition snapshot."""
    lines = []
    with _LOCK:
        counters = sorted(_COUNTERS.items())
        histograms = sorted((key, dict(value)) for key, value in _HISTOGRAMS.items())
    for (name, labels), value in counters:
        lines.append(f"incident_agent_{name}_total{_format_labels(labels)} {value:g}")
    for (name, labels), value in histograms:
        lines.append(f"incident_agent_{name}_count{_format_labels(labels)} {value['count']}")
        lines.append(f"incident_agent_{name}_sum{_format_labels(labels)} {value['sum']:g}")
    return "\n".join(lines) + ("\n" if lines else "")


def prometheus_gauges(values):
    """Render trusted internal numeric gauges using the project namespace."""
    lines = []
    for name, value in sorted(values.items()):
        safe_name = "".join(
            char if char.isalnum() or char == "_" else "_"
            for char in str(name)
        )
        lines.append(f"incident_agent_{safe_name} {float(value):g}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset_for_tests():
    with _LOCK:
        _COUNTERS.clear()
        _HISTOGRAMS.clear()
