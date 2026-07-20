from clients.prometheus_client import (
    prometheus
)
from clients.cloudwatch_client import (
    cloudwatch_metrics,
)
from settings import METRIC_SOURCE
from utils.connector_result import (
    provenance,
    query_spec,
    source_result,
    status_for_count,
)
from utils.data_quality import (
    assess_records,
    empty_quality,
)
from utils.resilience import ConnectorRequestError


def gather_metrics(state):

    alert = state["alert"]

    service = (
        alert.get("service")
        or alert
        .get("labels", {})
        .get("service", "")
    )

    labels = alert.get("labels", {})
    use_cloudwatch = (
        METRIC_SOURCE == "cloudwatch"
    )
    source = (
        "cloudwatch_metrics"
        if use_cloudwatch
        else "prometheus"
    )
    connector = (
        cloudwatch_metrics
        if use_cloudwatch
        else prometheus
    )
    source_schema_id = (
        "cloudwatch-incident-metric/v1"
        if use_cloudwatch
        else "prometheus-incident-metric/v1"
    )
    connector_version = (
        "cloudwatch-metrics-connector/v1"
        if use_cloudwatch
        else "prometheus-connector/v2"
    )
    query_description = query_spec(
        source=source,
        operation=
        (
            "get_metric_data"
            if use_cloudwatch
            else "fixed_incident_metric_set"
        ),
        service=service,
        filters={
            key: labels.get(key)
            for key in (
                "environment",
                "env",
                "cluster",
                "namespace",
            )
            if labels.get(key)
        },
        window=state.get(
            "incident_window", {}
        ),
        limits={
            "step_seconds": 60,
            "metric_names": [
                "latency_p95_ms",
                "error_rate",
                "request_rate_rps",
            ],
        },
        query_template=(
            (
                "allowlisted namespace, metric, dimensions and statistic"
            )
            if use_cloudwatch
            else (
                "versioned DEFAULT_QUERIES "
                "rendered for service"
            )
        ),
    )

    try:
        if connector is None:
            raise RuntimeError(
                "configured metric connector is unavailable"
            )
        raw_metrics = connector.query_metrics(
            service,
            labels,
            window=state.get("incident_window")
        )
        failed = [
            metric
            for metric in raw_metrics
            if isinstance(
                metric, dict
            )
            and metric.get("error")
        ]
        partial = [
            metric
            for metric in raw_metrics
            if isinstance(metric, dict)
            and metric.get("partial")
        ]
        connector_metadata = getattr(
            connector,
            "last_query_metadata",
            {},
        ) or {}
        metrics, quality = assess_records(
            raw_metrics,
            source_schema_id=
            source_schema_id,
            timestamp_fields=(
                "timestamp",
                "peak_timestamp",
            ),
            required_fields=(
                "metric",
            ),
            window=state.get(
                "incident_window", {}
            ),
            quarantine_invalid_timestamp=
            False,
        )
        returned = sum(
            1
            for metric in metrics
            if not metric.get("error")
        )
        provenance_data = provenance(
            source=source,
            backend=getattr(
                connector,
                "base_url",
                "mock-prometheus",
            ),
            query_specification=
            query_description,
            source_schema_id=
            source_schema_id,
            connector_version=
            connector_version,
            window=state.get("incident_window", {}),
            result_count=returned,
            fetched_count=len(
                raw_metrics
            ),
            reduced_count=len(
                metrics
            ),
            truncated=bool(
                connector_metadata.get(
                    "truncated"
                )
            ),
            request_id=connector_metadata.get(
                "request_id"
            ),
        )
        for metric in metrics:
            metric.pop("query", None)
            metric[
                "source_query_id"
            ] = provenance_data[
                "query_id"
            ]
            metric["connector_metadata"] = provenance_data
        return {
            "metrics": metrics,
            "source_status": {
                source: {
                    **source_result(
                        "partial" if (
                            partial
                            or connector_metadata.get("partial")
                            or (failed and returned)
                        ) else (
                            "failed" if failed else status_for_count(returned)
                        ),
                        provenance_data,
                        diagnostic=(
                            "; ".join(type(m.get("error")).__name__ for m in failed)
                            if failed else None
                        ),
                    ),
                    "metrics_returned": returned,
                    "records_fetched":
                    len(raw_metrics),
                    "records_usable":
                    len(metrics),
                    "errors": [type(m.get("error")).__name__ for m in failed],
                    "window": state.get("incident_window", {}),
                    "data_quality":
                    quality,
                }
            }
        }
    except Exception as exc:
        category = exc.category if isinstance(exc, ConnectorRequestError) else "failed"
        return {
            "metrics": [],
            "source_status": {
                source: {
                    **source_result(
                        category,
                        provenance(
                            source=source,
                            backend=getattr(
                                connector,
                                "base_url",
                                "unconfigured",
                            ),
                            query_specification=
                            query_description,
                            source_schema_id=
                            source_schema_id,
                            connector_version=
                            connector_version,
                            window=state.get("incident_window", {}),
                        ),
                        diagnostic=(
                            exc.diagnostic if isinstance(exc, ConnectorRequestError)
                            else type(exc).__name__
                        ),
                    ),
                    "window": state.get("incident_window", {}),
                    "data_quality":
                    empty_quality(
                        source_schema_id,
                        source_error_records=1,
                    ),
                }
            }
        }
