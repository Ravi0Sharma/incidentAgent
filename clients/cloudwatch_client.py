"""Bounded, read-only CloudWatch evidence connectors.

The incoming alert can select a configured service, but it cannot provide log
groups, metric namespaces, dimensions, regions, endpoints or credentials.
Those values come only from the versioned source map owned by the operator.
"""

from datetime import datetime, timezone
from pathlib import Path
import time

import yaml

from settings import (
    CLOUDWATCH_LOG_POLL_ATTEMPTS,
    CLOUDWATCH_LOG_POLL_INTERVAL_SECONDS,
    CLOUDWATCH_LOG_QUERY_LIMIT,
    CLOUDWATCH_METRIC_PAGE_LIMIT,
    CLOUDWATCH_REGION,
    CLOUDWATCH_SOURCE_MAP_PATH,
    LOG_SOURCE,
    METRIC_SOURCE,
    SOURCE_REQUEST_POLICIES,
)
from utils.incident_window import parse_window
from utils.resilience import ConnectorRequestError, SourceUnavailable


SOURCE_MAP_VERSION = "cloudwatch-source-map/v1"
ALLOWED_STATISTICS = frozenset({
    "Average",
    "Sum",
    "Minimum",
    "Maximum",
    "SampleCount",
})
MAX_LOG_GROUPS_PER_QUERY = 50
MAX_METRICS_PER_REQUEST = 500
MAX_LOG_QUERY_LIMIT = 100_000
MAX_METRIC_PAGES = 20


def load_source_map(path):
    if not path:
        raise ValueError("CLOUDWATCH_SOURCE_MAP_PATH is required")
    resolved = Path(path)
    with resolved.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if data.get("version") != SOURCE_MAP_VERSION:
        raise ValueError("unsupported CloudWatch source map version")
    services = data.get("services")
    if not isinstance(services, dict) or not services:
        raise ValueError("CloudWatch source map requires services")
    alarms = data.get("alarms", {}) or {}
    if not isinstance(alarms, dict):
        raise ValueError("CloudWatch alarms must be a mapping")
    return data


def _service_config(source_map, service):
    services = source_map.get("services", {})
    config = services.get(str(service or ""))
    if not isinstance(config, dict):
        raise ConnectorRequestError(
            "cloudwatch",
            "invalid_query",
            "service is outside the configured CloudWatch scope",
        )
    return config


def _request_id(response):
    return (
        (response or {})
        .get("ResponseMetadata", {})
        .get("RequestId")
    )


def _aws_error(source, exc):
    response = getattr(exc, "response", {}) or {}
    code = str(
        response.get("Error", {}).get("Code", "")
    )
    request_id = (
        response.get("ResponseMetadata", {}).get("RequestId")
    )
    lowered = code.lower()
    if any(value in lowered for value in ("accessdenied", "unauthorized", "forbidden")):
        category = "forbidden"
    elif any(value in lowered for value in ("throttl", "limitexceeded", "toomanyrequests")):
        category = "rate_limited"
    elif any(value in lowered for value in ("invalid", "malformed", "notfound")):
        category = "invalid_query"
    else:
        category = "failed"
    return ConnectorRequestError(
        source,
        category,
        code or type(exc).__name__,
        request_id=request_id,
    )


def _call(source, operation, **kwargs):
    try:
        return operation(**kwargs)
    except ConnectorRequestError:
        raise
    except Exception as exc:
        raise _aws_error(source, exc) from exc


def _iso(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return str(value or "")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class CloudWatchLogsClient:
    sampling_strategy = "cloudwatch_insights_bounded_chronological"

    def __init__(
        self,
        client,
        source_map,
        region,
        *,
        query_limit=CLOUDWATCH_LOG_QUERY_LIMIT,
        poll_attempts=CLOUDWATCH_LOG_POLL_ATTEMPTS,
        poll_interval=CLOUDWATCH_LOG_POLL_INTERVAL_SECONDS,
        sleep=time.sleep,
    ):
        self.client = client
        self.source_map = source_map
        self.region = str(region or "")
        self.base_url = f"aws://cloudwatch-logs/{self.region or 'unknown-region'}"
        self.query_limit = min(max(int(query_limit or 1), 1), MAX_LOG_QUERY_LIMIT)
        self.poll_attempts = min(max(int(poll_attempts or 1), 1), 120)
        self.poll_interval = max(float(poll_interval or 0), 0.0)
        self.sleep = sleep
        self.last_query_metadata = {}

    def _log_groups(self, service):
        groups = _service_config(self.source_map, service).get("log_groups", [])
        if not isinstance(groups, list) or not groups:
            raise ConnectorRequestError(
                "cloudwatch_logs",
                "invalid_query",
                "service has no configured CloudWatch log groups",
            )
        cleaned = [str(group) for group in groups if str(group).strip()]
        if not cleaned or len(cleaned) > MAX_LOG_GROUPS_PER_QUERY:
            raise ConnectorRequestError(
                "cloudwatch_logs",
                "invalid_query",
                "configured log-group count is outside the supported bound",
            )
        return cleaned

    def get_log_stats(self, service, alert_labels=None, window=None):
        self._log_groups(service)
        return {
            "total_count": None,
            "count_is_exact": False,
        }

    def query_logs(self, service, alert_labels=None, window=None, limit=None):
        groups = self._log_groups(service)
        start, end = parse_window(window)
        bounded_limit = min(
            max(int(limit or self.query_limit), 1),
            self.query_limit,
        )
        # Query text is fixed. Service attribution happens through the
        # allowlisted log-group mapping, not interpolation from the alert.
        query = (
            "fields @timestamp, @message, @logStream, @log | "
            "sort @timestamp asc | "
            f"limit {bounded_limit}"
        )
        started = _call(
            "cloudwatch_logs",
            self.client.start_query,
            logGroupNames=groups,
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
            limit=bounded_limit,
        )
        query_id = started.get("queryId")
        if not query_id:
            raise SourceUnavailable(
                "cloudwatch_logs",
                "StartQuery returned no query identifier",
                _request_id(started),
            )
        response = None
        for attempt in range(self.poll_attempts):
            response = _call(
                "cloudwatch_logs",
                self.client.get_query_results,
                queryId=query_id,
            )
            status = str(response.get("status", "Unknown"))
            if status == "Complete":
                break
            if status in {"Failed", "Cancelled", "Timeout", "Unknown"}:
                raise SourceUnavailable(
                    "cloudwatch_logs",
                    "Logs Insights query ended with status " + status,
                    _request_id(response),
                )
            if status not in {"Scheduled", "Running"}:
                raise SourceUnavailable(
                    "cloudwatch_logs",
                    "Logs Insights returned an unsupported status",
                    _request_id(response),
                )
            if attempt + 1 < self.poll_attempts and self.poll_interval:
                self.sleep(self.poll_interval)
        else:
            raise SourceUnavailable(
                "cloudwatch_logs",
                "Logs Insights exceeded the bounded polling budget",
                _request_id(response),
            )

        rows = []
        for result in response.get("results", []) or []:
            fields = {
                str(item.get("field")): item.get("value")
                for item in result
                if isinstance(item, dict) and item.get("field")
            }
            message = fields.get("@message")
            timestamp = fields.get("@timestamp")
            if message in (None, "") or timestamp in (None, ""):
                continue
            rows.append({
                "timestamp": _iso(timestamp),
                "message": str(message),
                "labels": {
                    "service": str(service),
                    "log_stream": str(fields.get("@logStream") or ""),
                    "log_group": str(fields.get("@log") or ""),
                },
            })
        self.last_query_metadata = {
            "status": "Complete",
            "request_id": _request_id(response) or _request_id(started),
            "matched_count": (
                (response.get("statistics") or {}).get("recordsMatched")
            ),
            "truncated": len(response.get("results", []) or []) >= bounded_limit,
        }
        return rows


class CloudWatchMetricsClient:
    def __init__(
        self,
        client,
        source_map,
        region,
        *,
        page_limit=CLOUDWATCH_METRIC_PAGE_LIMIT,
    ):
        self.client = client
        self.source_map = source_map
        self.region = str(region or "")
        self.base_url = f"aws://cloudwatch-metrics/{self.region or 'unknown-region'}"
        self.page_limit = min(max(int(page_limit or 1), 1), MAX_METRIC_PAGES)
        self.last_query_metadata = {}

    def _queries(self, service):
        metrics = _service_config(self.source_map, service).get("metrics", {})
        if not isinstance(metrics, dict) or not metrics:
            raise ConnectorRequestError(
                "cloudwatch_metrics",
                "invalid_query",
                "service has no configured CloudWatch metrics",
            )
        if len(metrics) > MAX_METRICS_PER_REQUEST:
            raise ConnectorRequestError(
                "cloudwatch_metrics",
                "invalid_query",
                "configured metric count exceeds the supported bound",
            )
        queries = []
        id_to_name = {}
        for index, (canonical_name, config) in enumerate(sorted(metrics.items())):
            if not isinstance(config, dict):
                raise ConnectorRequestError(
                    "cloudwatch_metrics", "invalid_query", "invalid metric configuration"
                )
            namespace = str(config.get("namespace") or "")
            metric_name = str(config.get("metric_name") or "")
            statistic = str(config.get("statistic") or "Average")
            period = int(config.get("period_seconds") or 60)
            dimensions = config.get("dimensions", {}) or {}
            if (
                not namespace
                or not metric_name
                or statistic not in ALLOWED_STATISTICS
                or period < 1
                or not isinstance(dimensions, dict)
            ):
                raise ConnectorRequestError(
                    "cloudwatch_metrics", "invalid_query", "invalid metric configuration"
                )
            query_id = f"m{index}"
            id_to_name[query_id] = str(canonical_name)
            queries.append({
                "Id": query_id,
                "MetricStat": {
                    "Metric": {
                        "Namespace": namespace,
                        "MetricName": metric_name,
                        "Dimensions": [
                            {"Name": str(name), "Value": str(value)}
                            for name, value in sorted(dimensions.items())
                        ],
                    },
                    "Period": period,
                    "Stat": statistic,
                },
                "ReturnData": True,
            })
        return queries, id_to_name

    def query_metrics(self, service, alert_labels=None, window=None):
        queries, id_to_name = self._queries(service)
        start, end = parse_window(window)
        by_id = {query_id: [] for query_id in id_to_name}
        statuses = {query_id: "Complete" for query_id in id_to_name}
        next_token = None
        pages = 0
        request_id = None
        while pages < self.page_limit:
            kwargs = {
                "MetricDataQueries": queries,
                "StartTime": start,
                "EndTime": end,
                "ScanBy": "TimestampAscending",
            }
            if next_token:
                kwargs["NextToken"] = next_token
            response = _call(
                "cloudwatch_metrics",
                self.client.get_metric_data,
                **kwargs,
            )
            pages += 1
            request_id = request_id or _request_id(response)
            for result in response.get("MetricDataResults", []) or []:
                query_id = str(result.get("Id") or "")
                if query_id not in by_id:
                    continue
                status = str(result.get("StatusCode") or "Complete")
                if status != "Complete":
                    statuses[query_id] = status
                timestamps = result.get("Timestamps", []) or []
                values = result.get("Values", []) or []
                by_id[query_id].extend(
                    (_iso(timestamp), float(value))
                    for timestamp, value in zip(timestamps, values)
                )
            next_token = response.get("NextToken")
            if not next_token:
                break

        results = []
        partial = bool(next_token)
        for query_id, canonical_name in id_to_name.items():
            points = sorted(set(by_id[query_id]), key=lambda item: item[0])
            status = statuses[query_id]
            if status != "Complete":
                partial = True
            if not points:
                if status not in {"Complete", "PartialData"}:
                    results.append({
                        "metric": canonical_name,
                        "error": status,
                    })
                continue
            first = points[0]
            latest = points[-1]
            peak = max(points, key=lambda item: item[1])
            results.append({
                "metric": canonical_name,
                "value": latest[1],
                "timestamp": latest[0],
                "peak_value": peak[1],
                "peak_timestamp": peak[0],
                "first_value": first[1],
                "trend": (
                    "rising" if latest[1] > first[1]
                    else "falling" if latest[1] < first[1]
                    else "flat"
                ),
                "samples": len(points),
                "partial": status != "Complete",
            })
        self.last_query_metadata = {
            "request_id": request_id,
            "pages": pages,
            "truncated": bool(next_token),
            "partial": partial,
        }
        return results


def _boto_client(name, region):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required when a CloudWatch source is enabled"
        ) from exc
    source = "cloudwatch_logs" if name == "logs" else "cloudwatch_metrics"
    policy = SOURCE_REQUEST_POLICIES[source]
    config = Config(
        connect_timeout=float(policy["timeout_seconds"]),
        read_timeout=float(policy["timeout_seconds"]),
        retries={
            "max_attempts": max(int(policy["retry_attempts"]), 1),
            "mode": "standard",
        },
    )
    return boto3.client(name, region_name=region, config=config)


def _make_logs_client():
    if LOG_SOURCE != "cloudwatch":
        return None
    source_map = load_source_map(CLOUDWATCH_SOURCE_MAP_PATH)
    return CloudWatchLogsClient(
        _boto_client("logs", CLOUDWATCH_REGION),
        source_map,
        CLOUDWATCH_REGION,
    )


def _make_metrics_client():
    if METRIC_SOURCE != "cloudwatch":
        return None
    source_map = load_source_map(CLOUDWATCH_SOURCE_MAP_PATH)
    return CloudWatchMetricsClient(
        _boto_client("cloudwatch", CLOUDWATCH_REGION),
        source_map,
        CLOUDWATCH_REGION,
    )


cloudwatch_logs = _make_logs_client()
cloudwatch_metrics = _make_metrics_client()
