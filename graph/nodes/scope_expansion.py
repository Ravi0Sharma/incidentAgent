from clients.loki_client import (
    loki
)

from utils.service_registry import (
    dependencies_for,
    get_service,
    related_services
)

from settings import MAX_SCOPE_SERVICES


def _alert_service(state):

    alert = state.get("alert", {}) or {}
    bctx = state.get(
        "business_context", {}
    ) or {}

    return (
        bctx.get("service")
        or alert.get("service")
        or alert
        .get("labels", {})
        .get("service")
        or "unknown"
    )


def _observed_services(state):

    services = []

    for group in state.get(
        "log_groups", []
    ) or []:
        service = (
            group.get("labels", {})
            .get("service")
        )
        if service and service not in services:
            services.append(service)

    return services


def _top(values, limit=5):

    return list(values or [])[:limit]


def scope_expansion(state):

    service = _alert_service(state)
    alert_labels = (
        (state.get("alert", {}) or {})
        .get("labels", {})
        or {}
    )

    dependencies = dependencies_for(
        service
    )
    related = related_services(
        service
    )
    observed = _observed_services(
        state
    )

    discovered = []
    try:
        discovered = loki.discover_services(
            alert_labels=alert_labels,
            limit=20,
            window=state.get("incident_window"),
        )
    except Exception as exc:
        discovered = [{
            "error": str(exc)
        }]

    services = []
    reasons = {}
    depths = {}

    def add(name, reason, depth=1):
        if not name:
            return
        if name not in services and len(services) < MAX_SCOPE_SERVICES:
            services.append(name)
            reasons[name] = reason
            depths[name] = depth

    add(service, "alerted service", 0)
    for item in observed:
        add(item, "observed in grouped logs", 1)
    for item in dependencies:
        add(item, "approved direct dependency", 1)
    for item in related:
        add(item, "approved reverse dependency", 1)
    for item in discovered:
        add(
            item.get("service"),
            "observed in bounded Loki time window",
            1,
        )

    service_summaries = []
    for name in services:
        svc = get_service(name)
        service_summaries.append({
            "service": name,
            "owner": svc.get("owner"),
            "tier": svc.get("tier"),
            "customer_facing":
            svc.get("customer_facing"),
            "runbook": svc.get("runbook"),
            "dependencies":
            dependencies_for(name)
        })

    pivots = state.get("pivots", {}) or {}

    return {
        "scope_expansion": {
            "alert_service": service,
            "services": services,
            "service_summaries":
            service_summaries,
            "service_reasons": reasons,
            "service_depths": depths,
            "observed_services":
            observed,
            "configured_dependencies":
            dependencies,
            "configured_related_services":
            related,
            "discovered_services":
            discovered,
            "trace_ids":
            _top(pivots.get("trace_id")),
            "request_ids":
            _top(pivots.get("request_id")),
            "environment_labels": {
                k: v
                for k, v in (
                    alert_labels.items()
                )
                if k in (
                    "namespace",
                    "cluster",
                    "env",
                    "environment"
                )
            },
            "scope_limit": MAX_SCOPE_SERVICES,
            "depth_limit": 1,
            "window": state.get("incident_window", {}),
        }
    }
