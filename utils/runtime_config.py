"""Fail-fast validation for the configuration combinations we support today."""

from urllib.parse import urlparse


LOCAL_REDACTION_SALT = "local-incident-agent"
SUPPORTED_RUNTIME_MODES = {
    "local",
    "development",
    "staging",
    "shadow",
    "production",
}
SECURE_RUNTIME_MODES = {
    "shadow",
    "production",
}


def validate_runtime_config(config):
    """Raise ValueError before serving traffic for unsafe production settings.

    This is intentionally strict: production storage, identity and publishing
    architecture have not yet been implemented, so they must not be enabled by
    accident through environment variables.
    """
    environment = str(
        getattr(
            config,
            "ENVIRONMENT",
            "",
        )
    ).lower()
    if (
        environment
        not in SUPPORTED_RUNTIME_MODES
    ):
        raise ValueError(
            "Unsupported runtime environment: "
            + (
                environment
                or "<missing>"
            )
        )
    if (
        environment
        not in SECURE_RUNTIME_MODES
    ):
        return []

    errors = []
    mode = environment
    if not config.WEBHOOK_SHARED_SECRET:
        errors.append(
            "WEBHOOK_SHARED_SECRET is "
            f"required in {mode}"
        )
    if getattr(config, "REVIEW_AUTH_MODE", "") != "oidc":
        errors.append(f"REVIEW_AUTH_MODE must be oidc in {mode}")
    for name in ("OIDC_ISSUER", "OIDC_JWKS_URL", "OIDC_METADATA_URL"):
        value = str(getattr(config, name, ""))
        if urlparse(value).scheme != "https":
            errors.append(f"{name} must use https in {mode}")
    if not str(getattr(config, "OIDC_AUDIENCE", "")).strip():
        errors.append(f"OIDC_AUDIENCE is required in {mode}")
    if not str(getattr(config, "OIDC_CLIENT_ID", "")).strip():
        errors.append(f"OIDC_CLIENT_ID is required in {mode}")
    if not str(getattr(config, "OIDC_CLIENT_SECRET", "")).strip():
        errors.append(f"OIDC_CLIENT_SECRET is required in {mode}")
    if not set(getattr(config, "OIDC_VIEWER_ROLES", set())):
        errors.append(f"OIDC_VIEWER_ROLES is required in {mode}")
    if not set(getattr(config, "OIDC_DECISION_ROLES", set())):
        errors.append(f"OIDC_DECISION_ROLES is required in {mode}")
    if not set(getattr(config, "OIDC_OPERATOR_ROLES", set())):
        errors.append(f"OIDC_OPERATOR_ROLES is required in {mode}")
    if len(str(getattr(config, "REVIEW_CSRF_SECRET", ""))) < 32:
        errors.append(
            f"REVIEW_CSRF_SECRET must contain at least 32 characters in {mode}"
        )
    if len(str(getattr(config, "REVIEW_SESSION_SECRET", ""))) < 32:
        errors.append(
            f"REVIEW_SESSION_SECRET must contain at least 32 characters in {mode}"
        )
    if (
        getattr(config, "REVIEW_SESSION_SECRET", "")
        == getattr(config, "REVIEW_CSRF_SECRET", "")
    ):
        errors.append(
            f"REVIEW_SESSION_SECRET and REVIEW_CSRF_SECRET must differ in {mode}"
        )
    session_age = int(getattr(config, "REVIEW_SESSION_MAX_AGE_SECONDS", 0))
    if session_age <= 0 or session_age > 86400:
        errors.append(
            f"REVIEW_SESSION_MAX_AGE_SECONDS must be 1..86400 in {mode}"
        )
    if not getattr(
        config,
        "PII_REDACTION_ENABLED",
        False,
    ):
        errors.append(
            "PII_REDACTION_ENABLED must "
            f"be true in {mode}"
        )
    if config.REDACTION_SALT in ("", LOCAL_REDACTION_SALT):
        errors.append("REDACTION_SALT must not use the local default")
    if not config.CORS_ORIGINS or "*" in config.CORS_ORIGINS:
        errors.append(
            "CORS_ORIGINS must contain "
            f"explicit {mode} origins"
        )
    if config.CHECKPOINTER != "mysql":
        errors.append(
            f"{mode} requires the "
            "MySQL checkpointer"
        )
    log_source = str(
        getattr(config, "LOG_SOURCE", "loki")
    ).lower()
    metric_source = str(
        getattr(config, "METRIC_SOURCE", "prometheus")
    ).lower()
    if log_source not in {"loki", "cloudwatch"}:
        errors.append("LOG_SOURCE must be loki or cloudwatch")
    if metric_source not in {"prometheus", "cloudwatch"}:
        errors.append("METRIC_SOURCE must be prometheus or cloudwatch")
    required_urls = ["OPENAI_BASE_URL"]
    if log_source == "loki":
        required_urls.append("LOKI_URL")
    if metric_source == "prometheus":
        required_urls.append("PROMETHEUS_URL")
    for name in required_urls:
        value = getattr(config, name, "")
        if urlparse(value).scheme != "https":
            errors.append(
                f"{name} must use https "
                f"in {mode}"
            )
    if "cloudwatch" in {log_source, metric_source}:
        if not str(
            getattr(config, "CLOUDWATCH_REGION", "")
        ).strip():
            errors.append(
                f"CLOUDWATCH_REGION is required in {mode}"
            )
        if not str(
            getattr(config, "CLOUDWATCH_SOURCE_MAP_PATH", "")
        ).strip():
            errors.append(
                "CLOUDWATCH_SOURCE_MAP_PATH is "
                f"required in {mode}"
            )
    api_key = str(
        getattr(
            config,
            "OPENAI_API_KEY",
            "",
        )
    ).strip()
    if (
        not api_key
        or api_key == "lm-studio"
    ):
        errors.append(
            "OPENAI_API_KEY must use a "
            f"hosted provider key in {mode}"
        )
    if getattr(
        config,
        "SKIP_LLM",
        False,
    ):
        errors.append(
            f"SKIP_LLM is not allowed in {mode}"
        )
    if not getattr(
        config,
        "GITHUB_TOKEN",
        "",
    ) or not getattr(
        config,
        "GITHUB_REPO",
        "",
    ):
        errors.append(
            "GitHub read-only change source "
            f"is required in {mode}"
        )
    if float(
        getattr(
            config,
            "LLM_TIMEOUT_SECONDS",
            0,
        )
    ) > 120:
        errors.append(
            "LLM_TIMEOUT_SECONDS must be "
            f"at most 120 in {mode}"
        )
    if int(
        getattr(
            config,
            "LLM_RETRY_ATTEMPTS",
            0,
        )
    ) > 2:
        errors.append(
            "LLM_RETRY_ATTEMPTS must be "
            f"at most 2 in {mode}"
        )
    positive_integer_budgets = {
        "LLM_MAX_CALLS_PER_INCIDENT": getattr(
            config, "LLM_MAX_CALLS_PER_INCIDENT", 0
        ),
        "LLM_MAX_INPUT_TOKENS_PER_INCIDENT": getattr(
            config, "LLM_MAX_INPUT_TOKENS_PER_INCIDENT", 0
        ),
        "LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT": getattr(
            config, "LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT", 0
        ),
        "LLM_MAX_TOTAL_TOKENS_PER_INCIDENT": getattr(
            config, "LLM_MAX_TOTAL_TOKENS_PER_INCIDENT", 0
        ),
    }
    for name, value in positive_integer_budgets.items():
        if int(value) <= 0:
            errors.append(f"{name} must be positive in {mode}")
    if float(getattr(config, "LLM_MAX_COST_USD_PER_INCIDENT", 0)) <= 0:
        errors.append(
            f"LLM_MAX_COST_USD_PER_INCIDENT must be positive in {mode}"
        )
    for name in (
        "LLM_INPUT_USD_PER_MILLION_TOKENS",
        "LLM_OUTPUT_USD_PER_MILLION_TOKENS",
    ):
        if float(getattr(config, name, 0)) <= 0:
            errors.append(f"{name} must be positive in {mode}")
    if config.PUBLISH_EXTERNAL:
        errors.append("external publishing requires the unimplemented approval/audit outbox")
    if errors:
        raise ValueError(
            f"Unsafe {mode} configuration: "
            + "; ".join(errors)
        )
    return []
