"""Fail-fast validation for the configuration combinations we support today."""

import ipaddress
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


def _egress_host_allowed(host, allowlist):
    host = str(host or "").lower()
    for allowed in allowlist:
        allowed = str(allowed).lower()
        if allowed.startswith("*."):
            if host.endswith(allowed[1:]) and host != allowed[2:]:
                return True
        elif host == allowed:
            return True
    return False


def _configured_cidrs(config, name):
    values = getattr(config, name, ()) or ()
    if isinstance(values, str):
        values = values.split(",")
    errors = []
    for value in values:
        candidate = str(value).strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            errors.append(f"{name} contains an invalid CIDR: {candidate}")
    return errors


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
    deployment_tenant = str(
        getattr(config, "DEPLOYMENT_TENANT_ID", "")
    ).strip()
    if not deployment_tenant or deployment_tenant == "local":
        errors.append(f"DEPLOYMENT_TENANT_ID must be explicit in {mode}")
    if not str(getattr(config, "OIDC_TENANT_CLAIM", "")).strip():
        errors.append(f"OIDC_TENANT_CLAIM is required in {mode}")
    secrets_provider = str(
        getattr(config, "SECRETS_PROVIDER", "environment")
    ).lower()
    if secrets_provider not in {
        "aws-secrets-manager", "vault", "kubernetes"
    }:
        errors.append(
            f"SECRETS_PROVIDER must identify an approved managed provider in {mode}"
        )
    public_base_url = str(getattr(config, "PUBLIC_BASE_URL", ""))
    if urlparse(public_base_url).scheme != "https":
        errors.append(f"PUBLIC_BASE_URL must use https in {mode}")
    redirect_uri = str(getattr(config, "OIDC_REDIRECT_URI", ""))
    if (
        urlparse(redirect_uri).scheme != "https"
        or urlparse(redirect_uri).netloc != urlparse(public_base_url).netloc
    ):
        errors.append(f"OIDC_REDIRECT_URI must use the PUBLIC_BASE_URL host in {mode}")
    if not config.WEBHOOK_SHARED_SECRET:
        errors.append(
            "WEBHOOK_SHARED_SECRET is "
            f"required in {mode}"
        )
    errors.extend(_configured_cidrs(config, "WEBHOOK_TRUSTED_PROXY_CIDRS"))
    errors.extend(_configured_cidrs(config, "WEBHOOK_ALLOWED_SOURCE_CIDRS"))
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
    if len(str(getattr(config, "METRICS_BEARER_TOKEN", ""))) < 32:
        errors.append(f"METRICS_BEARER_TOKEN must contain at least 32 characters in {mode}")
    if len(str(getattr(config, "CANARY_SHARED_SECRET", ""))) < 32:
        errors.append(f"CANARY_SHARED_SECRET must contain at least 32 characters in {mode}")
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
    process_role = str(getattr(config, "PROCESS_ROLE", "")).lower()
    if process_role not in {"api", "worker"}:
        errors.append(f"PROCESS_ROLE must be api or worker in {mode}")
    role_user = str(
        getattr(
            config,
            "MYSQL_API_USER" if process_role == "api" else "MYSQL_WORKER_USER",
            "",
        )
    ).strip()
    if not role_user or role_user.lower() in {"root", "admin", "administrator"}:
        errors.append(f"a non-admin MySQL {process_role or 'runtime'} role is required in {mode}")
    if int(getattr(config, "MYSQL_POOL_SIZE", 0)) <= 0:
        errors.append(f"MYSQL_POOL_SIZE must be positive in {mode}")
    if float(getattr(config, "MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS", 0)) <= 0:
        errors.append(f"MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS must be positive in {mode}")
    if not getattr(config, "MYSQL_SSL_ENABLED", False):
        errors.append(f"MYSQL_SSL_ENABLED must be true in {mode}")
    if not getattr(config, "MYSQL_SSL_VERIFY_IDENTITY", False):
        errors.append(f"MYSQL_SSL_VERIFY_IDENTITY must be true in {mode}")
    if getattr(config, "RUNTIME_SCHEMA_DDL_ENABLED", True):
        errors.append(f"RUNTIME_SCHEMA_DDL_ENABLED must be false in {mode}")
    if getattr(config, "API_DRAIN_JOBS", False):
        errors.append(
            f"API_DRAIN_JOBS must be false in {mode}; use the dedicated worker"
        )
    lease_seconds = int(getattr(config, "JOB_LEASE_SECONDS", 120))
    heartbeat_seconds = float(
        getattr(config, "JOB_HEARTBEAT_INTERVAL_SECONDS", 30)
    )
    worker_poll_seconds = float(
        getattr(config, "WORKER_POLL_INTERVAL_SECONDS", 1)
    )
    worker_stale_seconds = float(
        getattr(config, "WORKER_HEARTBEAT_STALE_SECONDS", 15)
    )
    if lease_seconds < 30:
        errors.append(f"JOB_LEASE_SECONDS must be at least 30 in {mode}")
    if heartbeat_seconds <= 0 or heartbeat_seconds * 2 >= lease_seconds:
        errors.append(
            "JOB_HEARTBEAT_INTERVAL_SECONDS must be positive and less than "
            f"half JOB_LEASE_SECONDS in {mode}"
        )
    if worker_poll_seconds <= 0:
        errors.append(f"WORKER_POLL_INTERVAL_SECONDS must be positive in {mode}")
    if worker_stale_seconds <= worker_poll_seconds * 2:
        errors.append(
            "WORKER_HEARTBEAT_STALE_SECONDS must be greater than twice "
            f"WORKER_POLL_INTERVAL_SECONDS in {mode}"
        )
    if int(getattr(config, "MAX_PENDING_JOBS", 1000)) <= 0:
        errors.append(f"MAX_PENDING_JOBS must be positive in {mode}")
    bucket_seconds = int(getattr(config, "INCIDENT_BUCKET_SECONDS", 300))
    coalesce_seconds = float(
        getattr(config, "INCIDENT_COALESCE_SECONDS", 0)
    )
    coalesce_max_seconds = float(
        getattr(config, "INCIDENT_COALESCE_MAX_SECONDS", 30)
    )
    if bucket_seconds <= 0:
        errors.append(f"INCIDENT_BUCKET_SECONDS must be positive in {mode}")
    if coalesce_seconds <= 0 or coalesce_seconds >= bucket_seconds:
        errors.append(
            "INCIDENT_COALESCE_SECONDS must be positive and less than "
            f"INCIDENT_BUCKET_SECONDS in {mode}"
        )
    if (
        coalesce_max_seconds < coalesce_seconds
        or coalesce_max_seconds > bucket_seconds
    ):
        errors.append(
            "INCIDENT_COALESCE_MAX_SECONDS must be at least "
            "INCIDENT_COALESCE_SECONDS and at most "
            f"INCIDENT_BUCKET_SECONDS in {mode}"
        )
    if int(getattr(config, "MIN_ACTIVE_WORKERS", 0)) < 2:
        errors.append(f"MIN_ACTIVE_WORKERS must be at least 2 in {mode}")
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
    connectors_enabled = bool(getattr(config, "CONNECTORS_ENABLED", True))
    model_enabled = bool(getattr(config, "MODEL_ENABLED", True))
    required_urls = []
    if model_enabled:
        required_urls.append("OPENAI_BASE_URL")
    if connectors_enabled and log_source == "loki":
        required_urls.append("LOKI_URL")
    if connectors_enabled and metric_source == "prometheus":
        required_urls.append("PROMETHEUS_URL")
    for name in required_urls:
        value = getattr(config, name, "")
        if urlparse(value).scheme != "https":
            errors.append(
                f"{name} must use https "
                f"in {mode}"
            )
    if connectors_enabled and "cloudwatch" in {log_source, metric_source}:
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
    if model_enabled and (not api_key or api_key == "lm-studio"):
        errors.append(
            "OPENAI_API_KEY must use a "
            f"hosted provider key in {mode}"
        )
    if model_enabled and getattr(config, "SKIP_LLM", False):
        errors.append(
            f"SKIP_LLM is not allowed in {mode}"
        )
    if connectors_enabled and (not getattr(
        config,
        "GITHUB_TOKEN",
        "",
    ) or not getattr(
        config,
        "GITHUB_REPO",
        "",
    )):
        errors.append(
            "GitHub read-only change source "
            f"is required in {mode}"
        )
    if model_enabled and float(
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
    if model_enabled and int(
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
        if model_enabled and int(value) <= 0:
            errors.append(f"{name} must be positive in {mode}")
    if model_enabled and float(getattr(config, "LLM_MAX_COST_USD_PER_INCIDENT", 0)) <= 0:
        errors.append(
            f"LLM_MAX_COST_USD_PER_INCIDENT must be positive in {mode}"
        )
    for name in (
        "LLM_INPUT_USD_PER_MILLION_TOKENS",
        "LLM_OUTPUT_USD_PER_MILLION_TOKENS",
    ):
        if model_enabled and float(getattr(config, name, 0)) <= 0:
            errors.append(f"{name} must be positive in {mode}")
    egress_hosts = set(getattr(config, "EGRESS_ALLOWED_HOSTS", set()))
    if not egress_hosts:
        errors.append(f"EGRESS_ALLOWED_HOSTS is required in {mode}")
    egress_urls = {
        "PUBLIC_BASE_URL": public_base_url,
        "OIDC_ISSUER": getattr(config, "OIDC_ISSUER", ""),
        "OIDC_JWKS_URL": getattr(config, "OIDC_JWKS_URL", ""),
        "OIDC_METADATA_URL": getattr(config, "OIDC_METADATA_URL", ""),
        "OTEL_EXPORTER_OTLP_ENDPOINT": getattr(
            config, "OTEL_EXPORTER_OTLP_ENDPOINT", ""
        ),
    }
    for name in required_urls:
        egress_urls[name] = getattr(config, name, "")
    for name, value in egress_urls.items():
        parsed = urlparse(str(value))
        if name == "OTEL_EXPORTER_OTLP_ENDPOINT" and not value:
            errors.append(f"{name} is required in {mode}")
            continue
        if parsed.hostname and not _egress_host_allowed(parsed.hostname, egress_hosts):
            errors.append(f"{name} host is not present in EGRESS_ALLOWED_HOSTS")
    if connectors_enabled and not _egress_host_allowed("api.github.com", egress_hosts):
        errors.append("api.github.com is not present in EGRESS_ALLOWED_HOSTS")
    if (
        connectors_enabled
        and "cloudwatch" in {log_source, metric_source}
        and "*.amazonaws.com" not in egress_hosts
    ):
        errors.append("*.amazonaws.com is required in EGRESS_ALLOWED_HOSTS")
    if config.PUBLISH_EXTERNAL:
        if mode == "shadow":
            errors.append("external publishing must remain disabled in shadow")
        slack_url = str(getattr(config, "SLACK_WEBHOOK_URL", ""))
        if urlparse(slack_url).scheme != "https":
            errors.append("SLACK_WEBHOOK_URL must use https for external publishing")
        if not str(getattr(config, "SLACK_CHANNEL", "")).strip():
            errors.append("SLACK_CHANNEL is required for external publishing")
        if not str(getattr(config, "GITHUB_TOKEN", "")).strip():
            errors.append("GITHUB_TOKEN is required for external publishing")
        if not str(getattr(config, "GITHUB_REPO", "")).strip():
            errors.append("GITHUB_REPO is required for external publishing")
        slack_host = urlparse(slack_url).hostname
        if slack_host and not _egress_host_allowed(slack_host, egress_hosts):
            errors.append(
                "SLACK_WEBHOOK_URL host is not present in EGRESS_ALLOWED_HOSTS"
            )
    if errors:
        raise ValueError(
            f"Unsafe {mode} configuration: "
            + "; ".join(errors)
        )
    return []
