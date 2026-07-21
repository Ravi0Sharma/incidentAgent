from settings import (
    SEV1_ERROR_RATE_THRESHOLD,
    SEV2_ERROR_RATE_THRESHOLD,
)


def _metric(state, name):
    for metric in state.get("metrics", []) or []:
        if metric.get("metric") != name:
            continue
        if metric.get("error"):
            return None
        return metric.get("peak_value", metric.get("value"))
    return None


def reassess_severity(state):
    """Only escalate provisional severity after measuring impact."""
    business = state.get("business_context", {}) or {}
    error_rate = _metric(state, "error_rate")
    current = state.get("severity", "SEV4")
    severity = current
    reason = state.get("severity_reason", "")

    if (
        business.get("tier") == 0
        and error_rate is not None
        and error_rate >= SEV1_ERROR_RATE_THRESHOLD
    ):
        severity = "SEV1"
        reason = (
            "Tier-0 service with measured peak error rate "
            f"{error_rate:.1%} >= {SEV1_ERROR_RATE_THRESHOLD:.1%}"
        )
    elif (
        current in ("SEV3", "SEV4")
        and error_rate is not None
        and error_rate >= SEV2_ERROR_RATE_THRESHOLD
    ):
        severity = "SEV2"
        reason = (
            "Measured peak error rate "
            f"{error_rate:.1%} >= {SEV2_ERROR_RATE_THRESHOLD:.1%}"
        )

    impact = {
        **(state.get("impact", {}) or {}),
        "measured_peak_error_rate": error_rate,
        "severity_is_provisional": error_rate is None,
    }
    return {
        "severity": severity,
        "severity_reason": reason,
        "impact": impact,
    }
