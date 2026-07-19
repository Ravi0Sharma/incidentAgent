from utils.service_registry import (
    get_service
)


ALERT_SEVERITY_RANK = {
    "critical": 3,
    "high": 3,
    "error": 3,
    "warning": 2,
    "warn": 2,
    "medium": 2,
    "info": 1,
    "low": 1
}


def _extract_service(alert):

    return (
        alert.get("service")
        or alert
        .get("labels", {})
        .get("service", "")
    )


def _extract_alert_severity(alert):

    raw = (
        alert.get("severity")
        or alert
        .get("labels", {})
        .get("severity", "")
        or ""
    )

    return (
        raw.lower().strip()
        if isinstance(raw, str)
        else ""
    )


def _sev_from_tier_and_alert(
    tier,
    alert_rank,
    customer_facing
):

    if (
        tier == 0
        and alert_rank >= 3
    ):
        return (
            "SEV2",
            "Tier-0 service with "
            "critical alert; impact pending metrics"
        )

    if (
        tier == 0
        and alert_rank == 2
    ):
        return (
            "SEV2",
            "Tier-0 service with "
            "warning-level alert"
        )

    if (
        tier == 1
        and alert_rank >= 3
    ):
        return (
            "SEV2",
            "Tier-1 service with "
            "critical alert"
        )

    if (
        tier == 1
        and alert_rank == 2
    ):
        return (
            "SEV3",
            "Tier-1 service with "
            "warning-level alert"
        )

    if (
        tier >= 2
        and alert_rank >= 3
        and customer_facing
    ):
        return (
            "SEV3",
            "Lower-tier but "
            "customer-facing "
            "with critical alert"
        )

    if (
        tier >= 2
        and alert_rank >= 3
    ):
        return (
            "SEV4",
            "Internal service "
            "with critical alert"
        )

    return (
        "SEV4",
        "Low-impact alert"
    )


def classify_severity(state):

    alert = state["alert"]

    service_name = _extract_service(
        alert
    )
    alert_severity = (
        _extract_alert_severity(alert)
    )
    alert_rank = (
        ALERT_SEVERITY_RANK.get(
            alert_severity, 1
        )
    )

    svc = get_service(service_name)

    tier = svc["tier"]
    customer_facing = svc[
        "customer_facing"
    ]

    sev, sev_reason = (
        _sev_from_tier_and_alert(
            tier,
            alert_rank,
            customer_facing
        )
    )

    business_context = {
        "service": service_name,
        "tier": tier,
        "customer_facing":
        customer_facing,
        "owner": svc["owner"],
        "runbook": svc.get("runbook"),
        "description":
        svc.get("description", "")
    }

    impact = {
        "primary_service":
        service_name,
        "customer_facing":
        customer_facing,
        "estimated_scope": (
            "external customers"
            if customer_facing
            else "internal users"
        )
    }

    return {
        "severity": sev,
        "severity_reason": sev_reason,
        "business_context":
        business_context,
        "impact": impact
    }
