import os

from dotenv import load_dotenv

load_dotenv()


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "google/gemma-4-12b"
)

OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "http://127.0.0.1:1234/v1"
)

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    "lm-studio"
)

# Local-only temporary allowance for the current hardware-constrained
# LM Studio model. Do not carry this timeout to hosted or production LLMs.
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "660"))
LLM_RETRY_ATTEMPTS = int(os.getenv("LLM_RETRY_ATTEMPTS", "1"))
LLM_RETRY_BACKOFF_SECONDS = float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "0.5"))
LLM_CIRCUIT_OPEN_SECONDS = int(os.getenv("LLM_CIRCUIT_OPEN_SECONDS", "30"))

INCIDENT_ANALYSIS_DEADLINE_SECONDS = float(
    os.getenv(
        "INCIDENT_ANALYSIS_DEADLINE_SECONDS",
        "900",
    )
)

LLM_INPUT_USD_PER_MILLION_TOKENS = float(
    os.getenv(
        "LLM_INPUT_USD_PER_MILLION_TOKENS",
        "0",
    )
)

LLM_OUTPUT_USD_PER_MILLION_TOKENS = float(
    os.getenv(
        "LLM_OUTPUT_USD_PER_MILLION_TOKENS",
        "0",
    )
)

LLM_MAX_CALLS_PER_INCIDENT = int(
    os.getenv("LLM_MAX_CALLS_PER_INCIDENT", "12")
)

LLM_MAX_INPUT_TOKENS_PER_INCIDENT = int(
    os.getenv("LLM_MAX_INPUT_TOKENS_PER_INCIDENT", "60000")
)

LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT = int(
    os.getenv("LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT", "12000")
)

LLM_MAX_TOTAL_TOKENS_PER_INCIDENT = int(
    os.getenv("LLM_MAX_TOTAL_TOKENS_PER_INCIDENT", "72000")
)

# Zero explicitly disables the currency gate for local development. Secure
# runtimes must configure a positive cap and non-zero model prices.
LLM_MAX_COST_USD_PER_INCIDENT = float(
    os.getenv("LLM_MAX_COST_USD_PER_INCIDENT", "0")
)


ENVIRONMENT = os.getenv(
    "ENVIRONMENT",
    "local"
).lower()

DEPLOYMENT_TENANT_ID = os.getenv("DEPLOYMENT_TENANT_ID", "local")
SECRETS_PROVIDER = os.getenv("SECRETS_PROVIDER", "environment").lower()
EGRESS_ALLOWED_HOSTS = {
    value.strip().lower()
    for value in os.getenv("EGRESS_ALLOWED_HOSTS", "").split(",")
    if value.strip()
}
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
INTAKE_ENABLED = os.getenv("INTAKE_ENABLED", "true").lower() == "true"
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() == "true"
CONNECTORS_ENABLED = os.getenv("CONNECTORS_ENABLED", "true").lower() == "true"
MODEL_ENABLED = os.getenv("MODEL_ENABLED", "true").lower() == "true"

# Temporary local-model compatibility: a small local LLM may ground its
# answer correctly but miss the exact Markdown headings required by review.
# This is forcibly disabled outside the local environment.
LOCAL_LLM_FORMAT_FALLBACK = (
    ENVIRONMENT == "local"
    and os.getenv(
        "LOCAL_LLM_FORMAT_FALLBACK",
        "true",
    ).lower() == "true"
)

SERVICE_VERSION = os.getenv(
    "SERVICE_VERSION",
    "local"
)

SUPPORTED_INCIDENT_ENVIRONMENTS = {
    value.strip().lower()
    for value in os.getenv(
        "SUPPORTED_INCIDENT_ENVIRONMENTS",
        "local,development,staging,production",
    ).split(",")
    if value.strip()
}

DEFAULT_ALERT_ENVIRONMENT = os.getenv(
    "DEFAULT_ALERT_ENVIRONMENT",
    ENVIRONMENT,
).lower()

MAX_TOKENS_INTERPRETATION = int(
    os.getenv(
        "MAX_TOKENS_INTERPRETATION",
        "1200"
    )
)

MAX_TOKENS_POSTMORTEM = int(
    os.getenv(
        "MAX_TOKENS_POSTMORTEM",
        "1800"
    )
)

MAX_TOKENS_RCA = int(
    os.getenv(
        "MAX_TOKENS_RCA",
        "1000"
    )
)


USE_TOOL_CALLING = (
    os.getenv(
        "USE_TOOL_CALLING",
        "true"
    ).lower() == "true"
)

SKIP_LLM = (
    not MODEL_ENABLED
    or os.getenv("SKIP_LLM", "false").lower() == "true"
)

MAX_TOOL_CALLS = int(
    os.getenv(
        "MAX_TOOL_CALLS",
        "3"
    )
)


HTML_OUTPUT_DIR = os.getenv(
    "HTML_OUTPUT_DIR",
    "output"
)

REVIEW_API_BASE = os.getenv(
    "REVIEW_API_BASE",
    "http://127.0.0.1:8000"
)


LOKI_URL = os.getenv("LOKI_URL")
LOKI_USER = os.getenv("LOKI_USER")
LOKI_API_KEY = os.getenv(
    "LOKI_API_KEY"
)

PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL"
)
PROMETHEUS_USER = os.getenv(
    "PROMETHEUS_USER"
)
PROMETHEUS_API_KEY = os.getenv(
    "PROMETHEUS_API_KEY"
)


# Evidence backends are selected by deployment configuration, never by
# untrusted alert fields.  Loki/Prometheus remain the local defaults while the
# first production source path is CloudWatch.
LOG_SOURCE = os.getenv(
    "LOG_SOURCE",
    "loki",
).strip().lower()

METRIC_SOURCE = os.getenv(
    "METRIC_SOURCE",
    "prometheus",
).strip().lower()

CLOUDWATCH_REGION = os.getenv(
    "CLOUDWATCH_REGION",
    "",
).strip()

CLOUDWATCH_SOURCE_MAP_PATH = os.getenv(
    "CLOUDWATCH_SOURCE_MAP_PATH",
    "",
).strip()

CLOUDWATCH_LOG_QUERY_LIMIT = int(
    os.getenv(
        "CLOUDWATCH_LOG_QUERY_LIMIT",
        "1000",
    )
)

CLOUDWATCH_LOG_POLL_ATTEMPTS = int(
    os.getenv(
        "CLOUDWATCH_LOG_POLL_ATTEMPTS",
        "12",
    )
)

CLOUDWATCH_LOG_POLL_INTERVAL_SECONDS = float(
    os.getenv(
        "CLOUDWATCH_LOG_POLL_INTERVAL_SECONDS",
        "0.5",
    )
)

CLOUDWATCH_METRIC_PAGE_LIMIT = int(
    os.getenv(
        "CLOUDWATCH_METRIC_PAGE_LIMIT",
        "5",
    )
)


GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN"
)
GITHUB_REPO = os.getenv(
    "GITHUB_REPO"
)


SLACK_WEBHOOK_URL = os.getenv(
    "SLACK_WEBHOOK_URL"
)
SLACK_CHANNEL = os.getenv(
    "SLACK_CHANNEL",
    "#incidents"
)


LOG_LOOKBACK_MINUTES = int(
    os.getenv(
        "LOG_LOOKBACK_MINUTES",
        "15"
    )
)

INCIDENT_WINDOW_PRE_MINUTES = int(
    os.getenv(
        "INCIDENT_WINDOW_PRE_MINUTES",
        "10"
    )
)

INCIDENT_WINDOW_MAX_MINUTES = int(
    os.getenv(
        "INCIDENT_WINDOW_MAX_MINUTES",
        "120"
    )
)

METRIC_LOOKBACK_MINUTES = int(
    os.getenv(
        "METRIC_LOOKBACK_MINUTES",
        "15"
    )
)

DEPLOY_LOOKBACK_HOURS = int(
    os.getenv(
        "DEPLOY_LOOKBACK_HOURS",
        "48"
    )
)

LOG_QUERY_LIMIT = int(
    os.getenv(
        "LOG_QUERY_LIMIT",
        "1000"
    )
)

LOG_TOOL_QUERY_LIMIT = int(
    os.getenv(
        "LOG_TOOL_QUERY_LIMIT",
        "50"
    )
)

INITIAL_LOG_QUERY_LIMIT = int(
    os.getenv(
        "INITIAL_LOG_QUERY_LIMIT",
        "300"
    )
)

MAX_SCOPE_SERVICES = int(
    os.getenv(
        "MAX_SCOPE_SERVICES",
        "12"
    )
)

MAX_EXPANSION_ROUNDS = int(
    os.getenv(
        "MAX_EXPANSION_ROUNDS",
        "2",
    )
)

MAX_INVESTIGATION_RESULT_BYTES = int(
    os.getenv(
        "MAX_INVESTIGATION_RESULT_BYTES",
        "131072",
    )
)

MAX_INVESTIGATION_ELAPSED_SECONDS = float(
    os.getenv(
        "MAX_INVESTIGATION_ELAPSED_SECONDS",
        "120",
    )
)

SOURCE_RETRY_ATTEMPTS = int(
    os.getenv("SOURCE_RETRY_ATTEMPTS", "2")
)

SOURCE_RETRY_BACKOFF_SECONDS = float(
    os.getenv("SOURCE_RETRY_BACKOFF_SECONDS", "0.25")
)

SOURCE_CIRCUIT_OPEN_SECONDS = int(
    os.getenv("SOURCE_CIRCUIT_OPEN_SECONDS", "30")
)


def _source_request_policy(name, timeout_default):
    prefix = name.upper()
    return {
        "timeout_seconds": float(
            os.getenv(
                f"{prefix}_TIMEOUT_SECONDS",
                str(timeout_default),
            )
        ),
        "retry_attempts": int(
            os.getenv(
                f"{prefix}_RETRY_ATTEMPTS",
                str(SOURCE_RETRY_ATTEMPTS),
            )
        ),
        "retry_backoff_seconds": float(
            os.getenv(
                f"{prefix}_RETRY_BACKOFF_SECONDS",
                str(SOURCE_RETRY_BACKOFF_SECONDS),
            )
        ),
        "circuit_open_seconds": int(
            os.getenv(
                f"{prefix}_CIRCUIT_OPEN_SECONDS",
                str(SOURCE_CIRCUIT_OPEN_SECONDS),
            )
        ),
    }


SOURCE_REQUEST_POLICIES = {
    "loki": _source_request_policy("loki", 30.0),
    "prometheus": _source_request_policy("prometheus", 30.0),
    "cloudwatch_logs": _source_request_policy("cloudwatch_logs", 30.0),
    "cloudwatch_metrics": _source_request_policy("cloudwatch_metrics", 30.0),
    "github": _source_request_policy("github", 15.0),
    "slack": _source_request_policy("slack", 15.0),
}

SEV1_ERROR_RATE_THRESHOLD = float(
    os.getenv(
        "SEV1_ERROR_RATE_THRESHOLD",
        "0.50"
    )
)

SEV2_ERROR_RATE_THRESHOLD = float(
    os.getenv(
        "SEV2_ERROR_RATE_THRESHOLD",
        "0.10"
    )
)


CHECKPOINTER = os.getenv(
    "CHECKPOINTER",
    "mysql"
)

INCIDENT_STORE_PATH = os.getenv(
    "INCIDENT_STORE_PATH",
    "data/incident-agent.sqlite3"
)

# Fail closed when a corrupted or attacker-controlled compressed row expands
# beyond the bounded local incident-log contract.
MAX_STORED_LOG_BYTES = int(
    os.getenv("MAX_STORED_LOG_BYTES", "5242880")
)
MAX_COMPRESSED_LOG_BYTES = int(
    os.getenv("MAX_COMPRESSED_LOG_BYTES", "1048576")
)

MYSQL_SIM_LOG_FILE = os.getenv(
    "MYSQL_SIM_LOG_FILE",
    "mysql_sim.log"
)

MYSQL_TABLE = os.getenv(
    "MYSQL_TABLE",
    "langgraph_checkpoints"
)

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "incident_agent")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
PROCESS_ROLE = os.getenv("PROCESS_ROLE", "combined").lower()
MYSQL_API_USER = os.getenv("MYSQL_API_USER", "")
MYSQL_API_PASSWORD = os.getenv("MYSQL_API_PASSWORD", "")
MYSQL_WORKER_USER = os.getenv("MYSQL_WORKER_USER", "")
MYSQL_WORKER_PASSWORD = os.getenv("MYSQL_WORKER_PASSWORD", "")
MYSQL_MIGRATOR_USER = os.getenv("MYSQL_MIGRATOR_USER", "")
MYSQL_MIGRATOR_PASSWORD = os.getenv("MYSQL_MIGRATOR_PASSWORD", "")
MYSQL_POOL_SIZE = int(os.getenv("MYSQL_POOL_SIZE", "8"))
MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS = float(
    os.getenv("MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS", "5")
)
MYSQL_CONNECT_TIMEOUT_SECONDS = int(os.getenv("MYSQL_CONNECT_TIMEOUT_SECONDS", "5"))
MYSQL_READ_TIMEOUT_SECONDS = int(os.getenv("MYSQL_READ_TIMEOUT_SECONDS", "30"))
MYSQL_WRITE_TIMEOUT_SECONDS = int(os.getenv("MYSQL_WRITE_TIMEOUT_SECONDS", "30"))
MYSQL_SSL_ENABLED = os.getenv("MYSQL_SSL_ENABLED", "false").lower() == "true"
MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA", "")
MYSQL_SSL_VERIFY_IDENTITY = (
    os.getenv("MYSQL_SSL_VERIFY_IDENTITY", "true").lower() == "true"
)
RUNTIME_SCHEMA_DDL_ENABLED = (
    os.getenv(
        "RUNTIME_SCHEMA_DDL_ENABLED",
        "true" if ENVIRONMENT in {"local", "development"} else "false",
    ).lower() == "true"
)


PII_REDACTION_ENABLED = (
    os.getenv(
        "PII_REDACTION_ENABLED",
        "true"
    ).lower() == "true"
)

REDACTION_SALT = os.getenv(
    "REDACTION_SALT",
    "local-incident-agent"
)

WEBHOOK_SHARED_SECRET = os.getenv(
    "WEBHOOK_SHARED_SECRET",
    ""
)

WEBHOOK_REPLAY_WINDOW_SECONDS = int(
    os.getenv("WEBHOOK_REPLAY_WINDOW_SECONDS", "300")
)

REVIEW_USERNAME = os.getenv(
    "REVIEW_USERNAME",
    ""
)

REVIEW_PASSWORD = os.getenv(
    "REVIEW_PASSWORD",
    ""
)

REVIEW_AUTH_MODE = os.getenv(
    "REVIEW_AUTH_MODE",
    "oidc" if ENVIRONMENT in {"shadow", "production"} else "basic",
).lower()

OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "")
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "")
OIDC_METADATA_URL = os.getenv(
    "OIDC_METADATA_URL",
    OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    if OIDC_ISSUER else "",
)
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")
OIDC_ROLE_CLAIM = os.getenv("OIDC_ROLE_CLAIM", "roles")
OIDC_TENANT_CLAIM = os.getenv("OIDC_TENANT_CLAIM", "tenant_id")
OIDC_VIEWER_ROLES = {
    value.strip()
    for value in os.getenv(
        "OIDC_VIEWER_ROLES",
        "incident-viewer,incident-reviewer,incident-admin",
    ).split(",")
    if value.strip()
}
OIDC_DECISION_ROLES = {
    value.strip()
    for value in os.getenv(
        "OIDC_DECISION_ROLES",
        "incident-reviewer,incident-admin",
    ).split(",")
    if value.strip()
}
OIDC_OPERATOR_ROLES = {
    value.strip()
    for value in os.getenv(
        "OIDC_OPERATOR_ROLES",
        "incident-operator,incident-admin",
    ).split(",")
    if value.strip()
}
REVIEW_CSRF_SECRET = os.getenv("REVIEW_CSRF_SECRET", "")
REVIEW_SESSION_SECRET = os.getenv("REVIEW_SESSION_SECRET", "")
REVIEW_SESSION_MAX_AGE_SECONDS = int(
    os.getenv("REVIEW_SESSION_MAX_AGE_SECONDS", "28800")
)
REVIEW_CSRF_TTL_SECONDS = int(
    os.getenv("REVIEW_CSRF_TTL_SECONDS", "900")
)

MAX_WEBHOOK_BODY_BYTES = int(
    os.getenv(
        "MAX_WEBHOOK_BODY_BYTES",
        "262144",
    )
)

WEBHOOK_GLOBAL_RATE_LIMIT = int(os.getenv("WEBHOOK_GLOBAL_RATE_LIMIT", "120"))
WEBHOOK_CALLER_RATE_LIMIT = int(os.getenv("WEBHOOK_CALLER_RATE_LIMIT", "60"))
WEBHOOK_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("WEBHOOK_RATE_LIMIT_WINDOW_SECONDS", "60"))
WEBHOOK_WORKER_BATCH_SIZE = int(os.getenv("WEBHOOK_WORKER_BATCH_SIZE", "10"))
API_DRAIN_JOBS = os.getenv(
    "API_DRAIN_JOBS",
    "true" if ENVIRONMENT in {"local", "development"} else "false",
).lower() == "true"
JOB_LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "120"))
JOB_HEARTBEAT_INTERVAL_SECONDS = float(
    os.getenv("JOB_HEARTBEAT_INTERVAL_SECONDS", "30")
)
WORKER_POLL_INTERVAL_SECONDS = float(
    os.getenv("WORKER_POLL_INTERVAL_SECONDS", "1")
)
WORKER_HEARTBEAT_STALE_SECONDS = float(
    os.getenv("WORKER_HEARTBEAT_STALE_SECONDS", "15")
)
MIN_ACTIVE_WORKERS = int(os.getenv("MIN_ACTIVE_WORKERS", "2"))
MAX_PENDING_JOBS = int(os.getenv("MAX_PENDING_JOBS", "1000"))
INCIDENT_BUCKET_SECONDS = int(
    os.getenv("INCIDENT_BUCKET_SECONDS", "300")
)
INCIDENT_COALESCE_SECONDS = float(
    os.getenv("INCIDENT_COALESCE_SECONDS", "0")
)
INCIDENT_COALESCE_MAX_SECONDS = float(
    os.getenv("INCIDENT_COALESCE_MAX_SECONDS", "30")
)
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
OBSERVABILITY_ENVIRONMENT = os.getenv("OBSERVABILITY_ENVIRONMENT", ENVIRONMENT)
CANARY_MAX_AGE_SECONDS = int(os.getenv("CANARY_MAX_AGE_SECONDS", "300"))
CANARY_SHARED_SECRET = os.getenv("CANARY_SHARED_SECRET", "")
METRICS_BEARER_TOKEN = os.getenv("METRICS_BEARER_TOKEN", "")
WORKER_METRICS_HOST = os.getenv("WORKER_METRICS_HOST", "0.0.0.0")
WORKER_METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9100"))
ANALYSIS_CODE_VERSION = os.getenv("ANALYSIS_CODE_VERSION", "incident-agent/v1")
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "prompts/v1")

MAX_ALERTS_PER_REQUEST = int(
    os.getenv(
        "MAX_ALERTS_PER_REQUEST",
        "50",
    )
)

MAX_ALERT_LABELS = int(
    os.getenv(
        "MAX_ALERT_LABELS",
        "50",
    )
)

MAX_ALERT_ANNOTATIONS = int(
    os.getenv(
        "MAX_ALERT_ANNOTATIONS",
        "50",
    )
)

MAX_ALERT_FIELD_LENGTH = int(
    os.getenv(
        "MAX_ALERT_FIELD_LENGTH",
        "4096",
    )
)

PUBLISH_EXTERNAL = (
    os.getenv(
        "PUBLISH_EXTERNAL",
        "false"
    ).lower() == "true"
)

if ENVIRONMENT == "production":
    _default_origins = ""
else:
    _default_origins = "*"

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        _default_origins
    ).split(",")
    if origin.strip()
]
