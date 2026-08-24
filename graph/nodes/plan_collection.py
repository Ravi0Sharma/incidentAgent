from settings import (
    INITIAL_LOG_QUERY_LIMIT,
    LOG_QUERY_LIMIT,
    MAX_EXPANSION_ROUNDS,
    MAX_INVESTIGATION_ELAPSED_SECONDS,
    MAX_INVESTIGATION_RESULT_BYTES,
    MAX_SCOPE_SERVICES,
    SEV1_LOG_QUERY_LIMIT,
    SEV2_LOG_QUERY_LIMIT,
)
from utils.model_usage import initialize_deadline


def plan_collection(state):
    """Make the first investigation cheap; expand only for concrete gaps."""
    severity = state.get("severity", "SEV4")
    alert = state.get("alert", {}) or {}
    labels = alert.get("labels", {}) or {}
    service = (
        (state.get("business_context", {}) or {}).get("service")
        or alert.get("service")
        or labels.get("service")
        or "unknown"
    )
    requested_limit = INITIAL_LOG_QUERY_LIMIT
    if severity == "SEV1":
        requested_limit = max(requested_limit, SEV1_LOG_QUERY_LIMIT)
    elif severity == "SEV2":
        requested_limit = max(requested_limit, SEV2_LOG_QUERY_LIMIT)
    requested_limit = min(max(int(requested_limit), 1), LOG_QUERY_LIMIT)

    return {
        "analysis_deadline": initialize_deadline(
            state.get("analysis_deadline")
        ),
        "collection_plan": {
            "strategy": "severity_aware_time_and_signal_stratified_evidence",
            "alert_service": service,
            "log_fetch_limit": requested_limit,
            "exact_log_count_required": True,
            "metric_features": [
                "error_rate",
                "latency_p95_ms",
                "request_rate_rps",
            ],
            "max_scope_services": MAX_SCOPE_SERVICES,
            "max_scope_depth": 1,
            "max_expansion_rounds": MAX_EXPANSION_ROUNDS,
            "max_targeted_result_bytes":
            MAX_INVESTIGATION_RESULT_BYTES,
            "max_targeted_elapsed_seconds":
            MAX_INVESTIGATION_ELAPSED_SECONDS,
            "expand_only_when": [
                "top candidates are close",
                "source data is missing or contradictory",
                "reviewer requests a specific verification",
                "shared trace/request ID crosses service boundary",
            ],
            "allowed_expansion_evidence": [
                "service observed in the bounded incident window",
                "direct dependency or reverse dependency in the approved service map",
                "shared trace or request ID",
                "deployment metadata for an already scoped service",
            ],
        }
    }
