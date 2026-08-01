from clients.loki_client import loki

from utils.connector_result import (
    provenance,
    query_spec,
)
from utils.log_store import (
    get_logs
)

from utils.search import (
    search_summary
)

from utils.service_registry import (
    dependencies_for,
    get_service,
    related_services
)

def _alert_labels(state):
    return (
        (state.get("alert", {}) or {})
        .get("labels", {})
        or {}
    )


def _incident_logs(state):
    return get_logs(
        state.get("incident_id")
    )


def discover_related_services(state):

    scope = state.get(
        "scope_expansion", {}
    ) or {}
    service = scope.get(
        "alert_service"
    )

    configured = []
    for name in (
        [service]
        + dependencies_for(service)
        + related_services(service)
    ):
        if name and name not in configured:
            configured.append(name)

    return {
        "configured_scope":
        configured,
        "loki_discovered": scope.get(
            "discovered_services", []
        ),
        "current_scope":
        scope.get("services", [])
    }


def search_logs(
    state,
    pattern=None,
    service=None,
    level=None
):

    scope = state.get(
        "scope_expansion", {}
    ) or {}
    alert_service = scope.get(
        "alert_service"
    )

    allowed = set(scope.get("services", []))
    if service and allowed and service not in allowed:
        return {
            "error": (
                f"service {service!r} is outside the bounded "
                "incident scope"
            )
        }
    if pattern and len(str(pattern)) > 240:
        return {"error": "pattern exceeds 240 character tool limit"}

    if (
        not service
        or service == alert_service
    ):
        query_description = query_spec(
            source=
            "incident-log-store",
            operation=
            "bounded_local_search",
            service=service
            or alert_service,
            filters={
                "pattern": pattern,
                "level": level,
            },
            window=scope.get(
                "window", {}
            ),
            limits={
                "sample_limit": 3,
            },
            query_template=(
                "local canonical incident "
                "log search"
            ),
        )
        local = search_summary(
            _incident_logs(state),
            pattern=pattern,
            service=service,
            level=level
        )
        provenance_data = provenance(
            source=
            "incident-log-store",
            backend=
            "canonical-incident-log-store",
            query_specification=
            query_description,
            source_schema_id=
            "canonical-incident-log/v1",
            connector_version=
            "incident-log-search/v2",
            window=scope.get(
                "window", {}
            ),
            result_count=local.get(
                "total_matched", 0
            ),
            fetched_count=len(
                local.get(
                    "sample", []
                )
                or []
            ),
            reduced_count=len(
                local.get(
                    "sample", []
                )
                or []
            ),
        )
        local["source"] = "incident-log-store"
        local["count_is_exact"] = True
        local["window"] = scope.get("window", {})
        local[
            "provenance"
        ] = provenance_data
        for sample in (
            local.get("sample", [])
            or []
        ):
            sample.setdefault(
                "connector_metadata",
                provenance_data,
            )
        # The first log sample is the cheap evidence tier. Do not silently
        # turn an empty local search into a broad external query.
        return local

    try:
        query_description = query_spec(
            source="loki",
            operation=
            "targeted_log_search",
            service=service,
            filters={
                "pattern": pattern,
                "level": level,
            },
            window=scope.get(
                "window", {}
            ),
            limits={
                "sample_limit": 50,
            },
            sampling={
                "strategy":
                "pattern_match_representatives",
            },
            query_template=(
                "{service + allowlisted alert "
                "labels} |~ {redacted pattern}"
            ),
        )
        result = loki.query_logs_by_pattern(
            service=service,
            alert_labels=_alert_labels(state),
            pattern=pattern,
            level=level,
            limit=50,
            window=scope.get("window"),
        )
        result["source"] = "loki"
        provenance_data = provenance(
            source="loki",
            backend=getattr(
                loki,
                "base_url",
                "mock-loki",
            ),
            query_specification=
            query_description,
            source_schema_id=
            "loki-log-record/v1",
            connector_version=
            "loki-connector/v2",
            window=scope.get(
                "window", {}
            ),
            result_count=result.get(
                "total_matched", 0
            ),
            fetched_count=len(
                result.get(
                    "sample", []
                )
                or []
            ),
            reduced_count=len(
                result.get(
                    "sample", []
                )
                or []
            ),
            truncated=not result.get(
                "count_is_exact", False
            ),
        )
        result[
            "provenance"
        ] = provenance_data
        for sample in (
            result.get(
                "sample", []
            )
            or []
        ):
            sample[
                "connector_metadata"
            ] = provenance_data
        return result
    except Exception as exc:
        return {
            "error": str(exc),
            "provenance": provenance(
                source="loki",
                backend=getattr(
                    loki,
                    "base_url",
                    "mock-loki",
                ),
                query_specification=
                query_description,
                source_schema_id=
                "loki-log-record/v1",
                connector_version=
                "loki-connector/v2",
                window=scope.get(
                    "window", {}
                ),
            ),
        }


def get_trace(state, trace_id=None):

    if not trace_id:
        return {
            "error": "trace_id is required"
        }

    scope = state.get("scope_expansion", {}) or {}
    alert_service = scope.get("alert_service")
    services = [alert_service] if alert_service else []
    for service in scope.get("services", []):
        if service and service != alert_service:
            services.append(service)
        if len(services) >= 3:
            break

    results = []
    total = 0
    exact = True
    for service in [name for name in services if name]:
        result = search_logs(
            state,
            pattern=trace_id,
            service=service,
            level=None,
        )
        if result.get("error"):
            results.append({"service": service, "error": result["error"]})
            exact = False
            continue
        matched = result.get("total_matched")
        if matched is None:
            exact = False
        else:
            total += matched
        results.append({
            "service": service,
            "total_matched": matched,
            "sample": result.get("sample", [])[:3],
            "provenance":
            result.get("provenance"),
        })

    return {
        "trace_id": trace_id,
        "total_matched": total if exact else None,
        "count_is_exact": exact,
        "services_checked": results,
        "scope_was_limited": len(
            scope.get("services", [])
        ) > len(services),
    }


def get_log_context(state, event_id=None):

    if not event_id:
        return {
            "error": "event_id is required"
        }

    for group in state.get(
        "log_groups", []
    ) or []:
        if group.get("event_id") != event_id:
            continue

        labels = group.get(
            "labels", {}
        ) or {}
        return {
            "event_id": event_id,
            "group": {
                "labels": labels,
                "count": group.get("count"),
                "first_seen":
                group.get("first_seen"),
                "last_seen":
                group.get("last_seen"),
                "sample_messages":
                group.get(
                    "sample_messages", []
                )
            },
            "raw_samples": group.get(
                "representative_samples", []
            )[:3],
        }

    return {
        "error":
        f"unknown event_id: {event_id}"
    }


def get_service_dependencies(
    state,
    service=None
):

    scope = state.get(
        "scope_expansion", {}
    ) or {}
    name = (
        service
        or scope.get("alert_service")
    )
    allowed = set(scope.get("services", []))
    if service and allowed and service not in allowed:
        return {
            "error": (
                f"service {service!r} is outside the bounded "
                "incident scope"
            )
        }
    svc = get_service(name)

    return {
        "service": name,
        "owner": svc.get("owner"),
        "tier": svc.get("tier"),
        "customer_facing":
        svc.get("customer_facing"),
        "runbook": svc.get("runbook"),
        "dependencies":
        dependencies_for(name),
        "related_services":
        related_services(name)
    }
