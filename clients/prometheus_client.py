from datetime import datetime, timezone

from settings import (
    PROMETHEUS_URL,
    PROMETHEUS_USER,
    PROMETHEUS_API_KEY,
)

from utils.incident_window import parse_window
from utils.resilience import request


DEFAULT_QUERIES = {
    "latency_p95_ms": (
        "histogram_quantile("
        "0.95, "
        "sum by (le) ("
        "rate("
        "http_request_duration_"
        "seconds_bucket"
        "{{service=\"{service}\"}}"
        "[5m])"
        ")"
        ") * 1000"
    ),
    "error_rate": (
        "sum(rate("
        "http_requests_total"
        "{{service=\"{service}\","
        "code=~\"5..\"}}[5m]))"
        " / "
        "sum(rate("
        "http_requests_total"
        "{{service=\"{service}\"}}"
        "[5m]))"
    ),
    "request_rate_rps": (
        "sum(rate("
        "http_requests_total"
        "{{service=\"{service}\"}}"
        "[5m]))"
    )
}


class RealPrometheusClient:

    def __init__(
        self,
        base_url,
        user,
        api_key
    ):
        self.base_url = (
            base_url.rstrip("/")
        )
        self.auth = (
            (user, api_key)
            if user and api_key
            else None
        )

    def query_metrics(
        self,
        service,
        alert_labels=None,
        window=None,
    ):

        start, end = parse_window(window)

        results = []

        for name, tpl in (
            DEFAULT_QUERIES.items()
        ):

            query = tpl.format(
                service=service
            )

            try:
                resp = request(
                    "prometheus", "GET",
                    (
                        f"{self.base_url}"
                        "/api/v1"
                        "/query_range"
                    ),
                    params={
                        "query": query,
                        "start":
                        start.timestamp(),
                        "end":
                        end.timestamp(),
                        "step": "60s"
                    },
                    auth=self.auth,
                )
                data = resp.json()

                series = (
                    data
                    .get("data", {})
                    .get("result", [])
                )

                values = []
                for s in series:
                    for pt in s.get(
                        "values", []
                    ):
                        ts, val = pt
                        values.append({
                            "t": ts,
                            "v": (
                                float(
                                    val
                                )
                            )
                        })

                latest_value = (
                    values[-1]["v"]
                    if values
                    else None
                )

                peak = max(
                    values,
                    key=lambda item: item["v"],
                    default=None,
                )
                first = values[0] if values else None
                latest = values[-1] if values else None

                results.append({
                    "metric": name,
                    "query": query,
                    "value":
                    latest_value,
                    "timestamp": (
                        datetime.fromtimestamp(
                            float(latest["t"]),
                            tz=timezone.utc,
                        ).isoformat()
                        if latest else None
                    ),
                    "peak_value": peak["v"] if peak else None,
                    "peak_timestamp": (
                        datetime.fromtimestamp(
                            float(peak["t"]),
                            tz=timezone.utc,
                        ).isoformat()
                        if peak else None
                    ),
                    "first_value": first["v"] if first else None,
                    "trend": (
                        "rising" if first and latest and latest["v"] > first["v"]
                        else "falling" if first and latest and latest["v"] < first["v"]
                        else "flat"
                    ),
                    "samples":
                    len(values)
                })

            except Exception as e:
                results.append({
                    "metric": name,
                    "query": query,
                    "error": str(e)
                })

        return results


class MockPrometheusClient:

    def query_metrics(
        self,
        service,
        alert_labels=None,
        window=None,
    ):
        start, end = parse_window(window)
        return [
            {
                "metric":
                "latency_p95_ms",
                "value": 5400,
                "timestamp": end.isoformat(),
                "peak_value": 5400,
                "peak_timestamp": end.isoformat(),
                "first_value": 900,
                "trend": "rising",
            },
            {
                "metric": "error_rate",
                "value": 0.34,
                "timestamp": end.isoformat(),
                "peak_value": 0.34,
                "peak_timestamp": end.isoformat(),
                "first_value": 0.01,
                "trend": "rising",
            },
            {
                "metric":
                "request_rate_rps",
                "value": 128,
                "timestamp": end.isoformat(),
                "peak_value": 128,
                "peak_timestamp": end.isoformat(),
                "first_value": 126,
                "trend": "flat",
            }
        ]


def _make_client():

    if PROMETHEUS_URL:
        return RealPrometheusClient(
            PROMETHEUS_URL,
            PROMETHEUS_USER,
            PROMETHEUS_API_KEY
        )

    print(
        "[prometheus_client] "
        "PROMETHEUS_URL not set, "
        "using mock"
    )
    return MockPrometheusClient()


prometheus = _make_client()
