"""Redact secrets and directly identifying values before persistence or LLM use."""

import hashlib
import re

from settings import PII_REDACTION_ENABLED, REDACTION_SALT


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization|api[_-]?key|token|password|secret)\s*[=:]\s*['\"]?[^\s,'\"]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer [REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[OPENAI_KEY_REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), "[GITHUB_TOKEN_REDACTED]"),
    (re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{16,}\b", re.IGNORECASE), "[SLACK_TOKEN_REDACTED]"),
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[EMAIL_REDACTED]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[CARD_REDACTED]"),
    (
        re.compile(
            r"(?i)\b(user|ruser|logname|account|acct)"
            r"\s*=\s*[^\s,;]+"
        ),
        r"\1=[USER_REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(rhost|remote_host|hostname|host)"
            r"\s*=\s*[^\s,;]+"
        ),
        r"\1=[HOST_REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(\bfrom\s+(?:\[IP\]|"
            r"(?:\d{1,3}\.){3}\d{1,3})\s*)\([^)]*\)"
        ),
        r"\1([HOST_REDACTED])",
    ),
    (
        re.compile(
            r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"
        ),
        "[IP_REDACTED]",
    ),
)

_SENSITIVE_LABELS = {
    "authorization", "api_key", "apikey", "token", "password", "secret",
    "email", "user_email", "customer_email", "user_id", "customer_id",
}

_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "email",
    "user_id",
    "customer_id",
)


def _pseudonym(value):
    if isinstance(value, str) and (
        value.startswith("redacted-")
        or value in {
            "[REDACTED]",
            "[OPENAI_KEY_REDACTED]",
            "[GITHUB_TOKEN_REDACTED]",
            "[SLACK_TOKEN_REDACTED]",
            "[EMAIL_REDACTED]",
            "[CARD_REDACTED]",
            "[USER_REDACTED]",
            "[HOST_REDACTED]",
            "[IP_REDACTED]",
        }
    ):
        return value
    digest = hashlib.sha256(
        f"{REDACTION_SALT}:{value}".encode("utf-8")
    ).hexdigest()[:12]
    return f"redacted-{digest}"


def redact_message(message):
    text = str(message or "")
    if not PII_REDACTION_ENABLED:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_labels(labels):
    labels = labels or {}
    if not PII_REDACTION_ENABLED:
        return dict(labels)
    cleaned = {}
    for key, value in labels.items():
        lower = str(key).lower()
        if lower in _SENSITIVE_LABELS:
            cleaned[key] = _pseudonym(value)
        else:
            cleaned[key] = value
    return cleaned


def _is_sensitive_key(key):
    lower = str(key).lower()
    return (
        lower in _SENSITIVE_LABELS
        or any(
            fragment in lower
            for fragment in _SENSITIVE_KEY_FRAGMENTS
        )
    )


def redact_data(value):
    """Recursively redact structured values before state or report storage."""
    if not PII_REDACTION_ENABLED:
        return value
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                cleaned[key] = _pseudonym(item)
            else:
                cleaned[key] = redact_data(item)
        return cleaned
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_data(item) for item in value)
    if isinstance(value, str):
        return redact_message(value)
    return value


def redact_log(log):
    log = log or {}
    return {
        **log,
        "message": redact_message(log.get("message", "")),
        "labels": redact_data(log.get("labels", {})),
    }
