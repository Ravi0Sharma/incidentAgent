"""Fail-closed outbound URL policy for configured HTTP integrations."""

from urllib.parse import urlparse

from settings import EGRESS_ALLOWED_HOSTS, ENVIRONMENT


def _host_allowed(host):
    host = str(host or "").lower()
    for allowed in EGRESS_ALLOWED_HOSTS:
        if allowed.startswith("*."):
            suffix = allowed[1:]
            if host.endswith(suffix) and host != suffix[1:]:
                return True
        elif host == allowed:
            return True
    return False


def assert_egress_url(url, *, source="external"):
    """Reject non-HTTPS or non-allowlisted destinations outside local modes."""
    if ENVIRONMENT not in {"shadow", "production"}:
        return str(url)
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{source} egress must use an absolute HTTPS URL")
    if not _host_allowed(parsed.hostname):
        raise ValueError(f"{source} egress host is not allowlisted")
    return str(url)
