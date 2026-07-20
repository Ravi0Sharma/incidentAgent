from clients.loki_client import loki
from clients.cloudwatch_client import (
    cloudwatch_logs,
)

from settings import LOG_QUERY_LIMIT, LOG_SOURCE
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


def gather_logs(state):

    alert = state["alert"]

    service = (
        alert.get("service")
        or alert
        .get("labels", {})
        .get("service", "")
    )

    labels = alert.get("labels", {})
    use_cloudwatch = LOG_SOURCE == "cloudwatch"
    source = (
        "cloudwatch_logs"
        if use_cloudwatch
        else "loki"
    )
    connector = (
        cloudwatch_logs
        if use_cloudwatch
        else loki
    )
    source_schema_id = (
        "cloudwatch-insights-log-record/v1"
        if use_cloudwatch
        else "loki-log-record/v1"
    )
    connector_version = (
        "cloudwatch-logs-connector/v1"
        if use_cloudwatch
        else "loki-connector/v2"
    )
    plan = state.get("collection_plan", {}) or {}
    sample_limit = min(
        int(plan.get("log_fetch_limit", LOG_QUERY_LIMIT)),
        LOG_QUERY_LIMIT,
    )
    query_description = query_spec(
        source=source,
        operation=(
            "logs_insights_query"
            if use_cloudwatch
            else "logql_range"
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
            "sample_limit":
            sample_limit,
        },
        sampling={
            "strategy": getattr(
                connector,
                "sampling_strategy",
                "connector_defined",
            ),
            "reserved_signals":
            "semantic_and_high_signal_shapes",
        },
        query_template=(
            (
                "allowlisted service log groups; fixed fields; "
                "chronological bounded result"
            )
            if use_cloudwatch
            else (
                "{service + allowlisted labels}; "
                "time-stratified range plus "
                "high-signal selector"
            )
        ),
    )

    try:
        if connector is None:
            raise RuntimeError(
                "configured log connector is unavailable"
            )
        stats = connector.get_log_stats(
            service,
            labels,
            window=state.get("incident_window")
        )
        raw_logs = []
        if stats.get("total_count") != 0:
            raw_logs = connector.query_logs(
                service,
                labels,
                window=state.get("incident_window"),
                limit=sample_limit,
            )
        fetched = len(raw_logs)
        connector_metadata = getattr(
            connector,
            "last_query_metadata",
            {},
        ) or {}
        if (
            stats.get("total_count") is None
            and connector_metadata.get("matched_count")
            is not None
        ):
            stats["total_count"] = int(
                connector_metadata["matched_count"]
            )
        for log in raw_logs:
            if not isinstance(
                log, dict
            ):
                continue
            log_labels = log.setdefault(
                "labels", {}
            )
            if (
                service
                and isinstance(
                    log_labels, dict
                )
            ):
                log_labels.setdefault(
                    "service", service
                )
        logs, quality = assess_records(
            raw_logs,
            source_schema_id=
            source_schema_id,
            timestamp_fields=(
                "timestamp",
            ),
            required_fields=(
                "timestamp",
                "message",
            ),
            window=state.get(
                "incident_window", {}
            ),
            quarantine_invalid_timestamp=
            True,
        )
        total_count = stats.get(
            "total_count"
        )
        truncated = (
            (
                total_count is not None
                and total_count > fetched
            )
            or (
                total_count is None
                and fetched >= sample_limit
            )
            or bool(
                connector_metadata.get(
                    "truncated"
                )
            )
        )
        provenance_data = provenance(
            source=source,
            backend=getattr(
                connector,
                "base_url",
                "mock-loki",
            ),
            query_specification=
            query_description,
            source_schema_id=
            source_schema_id,
            connector_version=
            connector_version,
            window=state.get("incident_window", {}),
            result_count=(
                stats.get("total_count")
                if stats.get("total_count")
                is not None
                else fetched
            ),
            fetched_count=fetched,
            reduced_count=len(logs),
            truncated=truncated,
            request_id=connector_metadata.get(
                "request_id"
            ),
        )
        for log in logs:
            log["connector_metadata"] = provenance_data
        return {
            "logs": logs,
            "log_query": {
                **stats,
                "fetched_count": fetched,
                "usable_count":
                len(logs),
                "data_quality":
                quality,
                "sample_limit": sample_limit,
                "possibly_truncated": truncated,
                "sampling_strategy": getattr(
                    connector,
                    "sampling_strategy",
                    "connector_defined",
                ),
            },
            "source_status": {
                source: {
                    **source_result(
                        status_for_count(
                            stats.get("total_count", fetched),
                            truncated=truncated,
                        ),
                        provenance_data,
                    ),
                    "records_fetched": fetched,
                    "records_usable":
                    len(logs),
                    "total_count": stats.get("total_count"),
                    "count_is_exact": stats.get("count_is_exact", False),
                    "window": state.get("incident_window", {}),
                    "data_quality":
                    quality,
                }
            }
        }
    except Exception as exc:
        category = (
            exc.category
            if isinstance(exc, ConnectorRequestError)
            else "failed"
        )
        provenance_data = provenance(
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
        )
        return {
            "logs": [],
            "log_query": {
                "total_count": None,
                "count_is_exact": False,
                "error": str(exc),
            },
            "source_status": {
                source: {
                    **source_result(
                        category,
                        provenance_data,
                        diagnostic=(
                            exc.diagnostic
                            if isinstance(exc, ConnectorRequestError)
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
