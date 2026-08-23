import html
import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode, urlsplit
import time
from pathlib import Path
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import (
    CORSMiddleware
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse
)
from fastapi.staticfiles import (
    StaticFiles
)
import jwt
from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.middleware.sessions import SessionMiddleware

from langgraph.types import Command

from graph.workflow import graph
from settings import (
    CORS_ORIGINS,
    ENVIRONMENT,
    HTML_OUTPUT_DIR,
    MAX_ALERT_ANNOTATIONS,
    MAX_ALERT_FIELD_LENGTH,
    MAX_ALERT_LABELS,
    MAX_ALERTS_PER_REQUEST,
    MAX_WEBHOOK_BODY_BYTES,
    METRICS_BEARER_TOKEN,
    REVIEW_PASSWORD,
    REVIEW_USERNAME,
    REVIEW_AUTH_MODE,
    REVIEW_CSRF_SECRET,
    REVIEW_CSRF_TTL_SECONDS,
    REVIEW_SESSION_MAX_AGE_SECONDS,
    REVIEW_SESSION_SECRET,
    OIDC_AUDIENCE,
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    OIDC_DECISION_ROLES,
    OIDC_ISSUER,
    OIDC_JWKS_URL,
    OIDC_METADATA_URL,
    OIDC_OPERATOR_ROLES,
    OIDC_REDIRECT_URI,
    OIDC_ROLE_CLAIM,
    OIDC_TENANT_CLAIM,
    OIDC_VIEWER_ROLES,
    DEFAULT_ALERT_ENVIRONMENT,
    DEPLOYMENT_TENANT_ID,
    INTAKE_ENABLED,
    SUPPORTED_INCIDENT_ENVIRONMENTS,
    WEBHOOK_SHARED_SECRET,
    WEBHOOK_REPLAY_WINDOW_SECONDS,
    WEBHOOK_GLOBAL_RATE_LIMIT,
    WEBHOOK_CALLER_RATE_LIMIT,
    WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    WEBHOOK_WORKER_BATCH_SIZE,
    API_DRAIN_JOBS,
    CANARY_SHARED_SECRET,
    WORKER_HEARTBEAT_STALE_SECONDS,
)
from utils.service_registry import list_services

from webhook import registry
from webhook.grafana import (
    normalize_grafana_alert
)
from webhook.alert_contract import (
    AlertContractError,
    validate_alert_payload,
)
from webhook.intake_stats import (
    record_rejection,
)
from webhook.replay import ReplayError, validate_and_record_nonce
from webhook.rate_limit import allow as allow_rate_limit
from webhook.incident_store import (
    QueueCapacityError,
    append_event,
    canary_job_status,
    enqueue_reprocessing,
    get_or_create_incident_id,
    operational_snapshot,
    readiness_check,
    record_event_and_enqueue,
    record_postmortem_draft,
    record_review_decision,
    replay_dead_letter,
)
from webhook.worker import drain as drain_jobs
from webhook.job_handler import (
    run_incident_job as _run_incident_job,
    run_normalized_alert as _run_normalized_alert,
)
from webhook.interpretation import (
    parse_interpretation
)
from webhook.state_sync import (
    is_awaiting_review,
    sync_registry
)
from utils.review_gate import (
    analysis_review_state,
)
from webhook.timeline import (
    timeline_items
)
from webhook.views import (
    page,
    render_hypothesis,
    render_revision_diff,
)
from utils.audit import record_audit_event
from utils.incident_ids import next_incident_id
from utils.logging import emit_log_event
from utils.metrics import increment, prometheus_gauges, prometheus_text
from utils.mysql import pool_stats
from utils.runtime_config import (
    SECURE_RUNTIME_MODES,
    validate_runtime_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_FIXTURE_PATH = (
    PROJECT_ROOT / "fixtures" / "latency_alert.json"
)


app = FastAPI(
    title="Incident Agent Webhook",
    version="1.0.0",
    description="Versioned, idempotent incident intake API."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

oauth = OAuth()
if OIDC_METADATA_URL and OIDC_CLIENT_ID:
    oauth.register(
        name="review_oidc",
        server_metadata_url=OIDC_METADATA_URL,
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        client_kwargs={"scope": "openid profile email"},
    )


@app.on_event("startup")
async def _validate_configuration_before_serving():
    validate_runtime_config(
        __import__("settings")
    )


def _secure_runtime():
    return (
        ENVIRONMENT
        in SECURE_RUNTIME_MODES
    )


_OIDC_JWKS_CLIENT = None
_OIDC_JWKS_CLIENT_URL = None


def _basic_principal(request):
    if REVIEW_AUTH_MODE != "basic" or _secure_runtime():
        return None
    if not REVIEW_USERNAME or not REVIEW_PASSWORD:
        return {
            "identity": "local-unauthenticated",
            "roles": {"viewer", "decision", "operator"},
            "auth_mode": "local",
            "tenant": DEPLOYMENT_TENANT_ID,
        }
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(
            header.split(" ", 1)[1], validate=True
        ).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    if not (
        hmac.compare_digest(username, REVIEW_USERNAME)
        and hmac.compare_digest(password, REVIEW_PASSWORD)
    ):
        return None
    return {
        "identity": "basic:" + username,
        "roles": {"viewer", "decision", "operator"},
        "auth_mode": "basic",
        "tenant": DEPLOYMENT_TENANT_ID,
    }


def _claim_roles(claims):
    value = claims.get(OIDC_ROLE_CLAIM, [])
    if isinstance(value, str):
        return {item for item in value.replace(",", " ").split() if item}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if str(item)}
    return set()


def _claim_tenant(claims):
    return str(claims.get(OIDC_TENANT_CLAIM, "")).strip()


def _oidc_principal(request):
    global _OIDC_JWKS_CLIENT, _OIDC_JWKS_CLIENT_URL
    if REVIEW_AUTH_MODE != "oidc":
        return None
    try:
        session_claims = request.session.get("review_claims") or {}
    except (AssertionError, AttributeError):
        session_claims = {}
    if session_claims:
        try:
            if (
                str(session_claims.get("iss")) == OIDC_ISSUER
                and str(session_claims.get("sub", ""))
                and int(session_claims.get("exp", 0)) >= int(time.time())
            ):
                roles = _claim_roles(session_claims)
                tenant = _claim_tenant(session_claims)
                if tenant != DEPLOYMENT_TENANT_ID:
                    return None
                stable_id = hashlib.sha256(
                    (
                        str(session_claims["iss"])
                        + "\0"
                        + str(session_claims["sub"])
                    ).encode("utf-8")
                ).hexdigest()[:32]
                return {
                    "identity": "oidc:" + stable_id,
                    "roles": roles,
                    "auth_mode": "oidc",
                    "tenant": tenant,
                }
        except (TypeError, ValueError):
            return None
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token or not OIDC_ISSUER or not OIDC_AUDIENCE or not OIDC_JWKS_URL:
        return None
    try:
        if _OIDC_JWKS_CLIENT is None or _OIDC_JWKS_CLIENT_URL != OIDC_JWKS_URL:
            _OIDC_JWKS_CLIENT = jwt.PyJWKClient(
                OIDC_JWKS_URL,
                cache_keys=True,
                lifespan=300,
            )
            _OIDC_JWKS_CLIENT_URL = OIDC_JWKS_URL
        signing_key = _OIDC_JWKS_CLIENT.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
            leeway=30,
            options={"require": ["exp", "sub"]},
        )
    except Exception:
        return None
    roles = _claim_roles(claims)
    tenant = _claim_tenant(claims)
    subject = str(claims.get("sub", ""))
    if not subject or tenant != DEPLOYMENT_TENANT_ID:
        return None
    stable_id = hashlib.sha256(
        (str(claims.get("iss", OIDC_ISSUER)) + "\0" + subject).encode("utf-8")
    ).hexdigest()[:32]
    return {
        "identity": "oidc:" + stable_id,
        "roles": roles,
        "auth_mode": "oidc",
        "tenant": tenant,
    }


def _review_principal(request):
    cached = getattr(getattr(request, "state", None), "review_principal", None)
    if cached:
        return cached
    principal = _oidc_principal(request) or _basic_principal(request)
    if principal and getattr(request, "state", None) is not None:
        request.state.review_principal = principal
    return principal


def _review_authorized(request, action="view"):
    principal = _review_principal(request)
    if not principal:
        return False
    if principal["auth_mode"] in {"local", "basic"}:
        return True
    required = {
        "view": OIDC_VIEWER_ROLES,
        "decision": OIDC_DECISION_ROLES,
        "operator": OIDC_OPERATOR_ROLES,
    }.get(action, set())
    return bool(set(principal["roles"]) & set(required))


def _review_authenticated(request):
    return _review_authorized(request, "view")


def _reviewer_identity(request):
    principal = _review_principal(request)
    return (principal or {}).get("identity", "unauthenticated")


def _csrf_secret():
    if REVIEW_CSRF_SECRET:
        return REVIEW_CSRF_SECRET.encode("utf-8")
    if _secure_runtime():
        return b""
    return (REVIEW_PASSWORD or "local-development-csrf-only").encode("utf-8")


def _issue_review_csrf(thread_id, identity, now=None):
    secret = _csrf_secret()
    if not secret:
        raise RuntimeError("review CSRF secret is unavailable")
    issued_at = int(time.time() if now is None else now)
    payload = json.dumps(
        {
            "purpose": "review:" + str(thread_id),
            "identity_hash": hashlib.sha256(str(identity).encode("utf-8")).hexdigest(),
            "issued_at": issued_at,
            "expires_at": issued_at + max(int(REVIEW_CSRF_TTL_SECONDS), 60),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(secret, encoded, hashlib.sha256).hexdigest()
    return encoded.decode("ascii") + "." + signature


def _valid_review_csrf(token, thread_id, identity, now=None):
    secret = _csrf_secret()
    if not secret or not token or "." not in str(token):
        return False
    encoded, supplied = str(token).rsplit(".", 1)
    expected = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        return False
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        )
        current = int(time.time() if now is None else now)
        return (
            payload.get("purpose") == "review:" + str(thread_id)
            and payload.get("identity_hash")
            == hashlib.sha256(str(identity).encode("utf-8")).hexdigest()
            and int(payload.get("issued_at", 0)) <= current + 30
            and current <= int(payload.get("expires_at", 0))
        )
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return False


def _valid_webhook_signature(request, body):
    if not WEBHOOK_SHARED_SECRET:
        return not _secure_runtime()
    supplied = request.headers.get(
        "x-incident-signature", ""
    )
    timestamp = request.headers.get("x-incident-timestamp", "")
    nonce = request.headers.get("x-incident-nonce", "")
    signed_body = body
    if _secure_runtime():
        if not timestamp or not nonce:
            return False
        signed_body = (
            timestamp.encode("utf-8") + b"." + nonce.encode("utf-8") + b"." + body
        )
    expected = "sha256=" + hmac.new(
        WEBHOOK_SHARED_SECRET.encode("utf-8"),
        signed_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(supplied, expected)


def _validate_webhook_replay(request):
    if (
        not _secure_runtime()
        or not WEBHOOK_SHARED_SECRET
    ):
        return
    validate_and_record_nonce(
        request.headers.get("x-incident-timestamp"),
        request.headers.get("x-incident-nonce"),
        WEBHOOK_REPLAY_WINDOW_SECONDS,
    )


def _rate_limit_key(request):
    return request.headers.get("x-incident-client-id") or getattr(
        getattr(request, "client", None), "host", "anonymous"
    )


def _allow_webhook_request(request):
    allowed, retry_after = allow_rate_limit(
        "global", WEBHOOK_GLOBAL_RATE_LIMIT, WEBHOOK_RATE_LIMIT_WINDOW_SECONDS
    )
    if not allowed:
        return False, retry_after, "global_rate_limit"
    allowed, retry_after = allow_rate_limit(
        "caller:" + _rate_limit_key(request),
        WEBHOOK_CALLER_RATE_LIMIT,
        WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
    )
    return allowed, retry_after, "caller_rate_limit"


class ReviewRequestError(ValueError):
    pass


def _review_resume_payload(payload, pending=None):
    """Normalize browser input before resuming an interrupted graph."""
    payload = payload if isinstance(payload, dict) else {}
    status = payload.get("status", "rejected")
    if status not in (
        "approved", "rejected", "request_more_evidence"
    ):
        status = "rejected"
    try:
        chosen = int(payload.get("chosen_hypothesis", 1))
    except (TypeError, ValueError):
        chosen = 1
    normalized = {
        "status": status,
        "feedback": str(payload.get("feedback") or "")[:2_000],
        "chosen_hypothesis": chosen if chosen in (1, 2, 3) else 1,
    }
    if normalized["status"] == "approved":
        candidates = ((pending or {}).get("deterministic_assessment", {}) or {}).get(
            "candidates", []
        )
        permitted = {item.get("rank") for item in candidates if isinstance(item, dict)}
        if not permitted or normalized["chosen_hypothesis"] not in permitted:
            raise ReviewRequestError("chosen hypothesis is not present in the reviewed candidate set")
    if (
        normalized["status"] == "request_more_evidence"
        and not normalized["feedback"].strip()
    ):
        raise ReviewRequestError(
            "request_more_evidence requires concrete feedback"
        )
    return normalized


def _timeline_height(group_count):
    return max(260, min(460, 110 + group_count * 78))


def _analysis_review_state(pending, parsed):
    return analysis_review_state(
        pending,
        parsed,
    )


def _timeline_window(incident_window):
    window = incident_window or {}
    start = window.get("start")
    end = window.get("end")
    if not start or not end:
        return {}
    try:
        start_dt = datetime.fromisoformat(
            str(start).replace("Z", "+00:00")
        )
        end_dt = datetime.fromisoformat(
            str(end).replace("Z", "+00:00")
        )
    except ValueError:
        return {}
    if end_dt <= start_dt:
        return {}
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


def _safe_local_redirect(value, default="/"):
    candidate = str(value or "")
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(char) < 32 for char in candidate)
    ):
        return default
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return default
    return candidate[:2_000]


@app.middleware("http")
async def protect_reviewer_surface(request, call_next):
    path = request.url.path
    if (
        path in {"/alerts", "/v1/alerts"}
        and request.method == "POST"
        and not INTAKE_ENABLED
    ):
        increment("alerts", outcome="intake_disabled")
        return JSONResponse(
            status_code=503,
            content={
                "error": "incident intake is disabled",
                "code": "intake_disabled",
            },
            headers={"Retry-After": "60"},
        )
    if path in {
        "/healthz", "/readyz", "/metrics", "/auth/login", "/auth/callback"
    } or (
        path in {"/alerts", "/v1/alerts"} and request.method == "POST"
    ) or (
        path.startswith("/v1/canary/jobs/") and request.method == "GET"
    ):
        return await call_next(request)
    action = "view"
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        action = (
            "view"
            if path == "/auth/logout"
            else (
                "decision"
                if path.startswith("/alerts/") and path.endswith("/review")
                else "operator"
            )
        )
    if _review_authorized(request, action):
        if action == "decision":
            thread_id = path[len("/alerts/"):-len("/review")].strip("/")
            token = request.headers.get("x-csrf-token", "")
            identity = _reviewer_identity(request)
            if not _valid_review_csrf(token, thread_id, identity):
                try:
                    record_audit_event(
                        "csrf_validation_failed",
                        thread_id,
                        reviewer_identity=identity,
                        request_id=request.headers.get("x-request-id"),
                    )
                except Exception:
                    pass
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": "A valid review CSRF token is required.",
                        "code": "csrf_validation_failed",
                    },
                )
        return await call_next(request)
    try:
        record_audit_event(
            "authentication_failed",
            route=path,
            method=request.method,
            request_id=request.headers.get("x-request-id"),
        )
    except Exception:
        # Authentication must still fail closed if audit storage is unavailable.
        pass
    increment("authentication_failures", route=path)
    if (
        REVIEW_AUTH_MODE == "oidc"
        and request.method == "GET"
        and "text/html" in request.headers.get("accept", "")
    ):
        return RedirectResponse(
            "/auth/login?" + urlencode({"next": _safe_local_redirect(path)}),
            status_code=303,
        )
    return JSONResponse(
        status_code=401,
        content={
            "error": "Reviewer authentication is required."
        },
        headers={
            "WWW-Authenticate": (
                "Bearer" if REVIEW_AUTH_MODE == "oidc" else "Basic"
            )
        },
    )


app.add_middleware(
    SessionMiddleware,
    secret_key=(
        REVIEW_SESSION_SECRET
        or REVIEW_PASSWORD
        or "local-development-session-only"
    ),
    session_cookie="incident_review_session",
    max_age=max(int(REVIEW_SESSION_MAX_AGE_SECONDS), 60),
    same_site="lax",
    https_only=_secure_runtime(),
)


@app.get("/auth/login")
async def review_login(request: Request, next: str = "/"):
    client = oauth.create_client("review_oidc")
    if REVIEW_AUTH_MODE != "oidc" or client is None:
        return JSONResponse(
            status_code=503,
            content={"error": "OIDC review login is not configured."},
        )
    return_to = _safe_local_redirect(next)
    request.session["review_return_to"] = return_to
    redirect_uri = OIDC_REDIRECT_URI or str(request.url_for("review_callback"))
    return await client.authorize_redirect(
        request, redirect_uri, nonce=secrets.token_urlsafe(32)
    )


@app.get("/auth/callback")
async def review_callback(request: Request):
    client = oauth.create_client("review_oidc")
    if REVIEW_AUTH_MODE != "oidc" or client is None:
        return JSONResponse(status_code=503, content={"error": "OIDC is unavailable."})
    try:
        token = await client.authorize_access_token(request)
        claims = dict(token.get("userinfo") or {})
        if not claims:
            claims = dict(await client.userinfo(token=token))
    except (OAuthError, ValueError, TypeError):
        return JSONResponse(status_code=401, content={"error": "OIDC login failed."})
    subject = str(claims.get("sub", ""))
    roles = _claim_roles(claims)
    tenant = _claim_tenant(claims)
    if (
        not subject
        or tenant != DEPLOYMENT_TENANT_ID
        or not (roles & set(OIDC_VIEWER_ROLES))
    ):
        request.session.clear()
        return JSONResponse(
            status_code=403,
            content={"error": "OIDC identity lacks an incident review role."},
        )
    request.session["review_claims"] = {
        "iss": OIDC_ISSUER,
        "sub": subject,
        "exp": min(
            int(claims.get("exp", int(time.time()) + REVIEW_SESSION_MAX_AGE_SECONDS)),
            int(time.time()) + REVIEW_SESSION_MAX_AGE_SECONDS,
        ),
        OIDC_ROLE_CLAIM: sorted(roles),
        OIDC_TENANT_CLAIM: tenant,
    }
    return_to = _safe_local_redirect(
        request.session.pop("review_return_to", "/")
    )
    return RedirectResponse(return_to, status_code=303)


@app.post("/auth/logout")
async def review_logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "logged_out"})

app.mount(
    "/output",
    StaticFiles(directory=HTML_OUTPUT_DIR),
    name="output"
)


async def _drain_incident_jobs():
    return await drain_jobs(_run_incident_job, max_jobs=WEBHOOK_WORKER_BATCH_SIZE)


@app.get(
    "/", response_class=HTMLResponse
)
async def index():

    pending = registry.list_pending()

    if not pending:
        rows = (
            "<tr><td colspan='5' "
            "class='muted'>No incidents"
            " awaiting review.</td>"
            "</tr>"
        )
    else:
        rows = ""
        for p in pending:
            sev = p.get("severity", "")
            rows += (
                "<tr>"
                "<td><a href='/incidents/"
                + html.escape(
                    p["thread_id"]
                )
                + "'>"
                + html.escape(
                    p["thread_id"]
                )
                + "</a></td>"
                "<td>"
                + html.escape(
                    str(
                        p.get(
                            "alertname",
                            ""
                        )
                    )
                )
                + "</td>"
                "<td>"
                + html.escape(
                    str(
                        p.get(
                            "service",
                            ""
                        )
                    )
                )
                + "</td>"
                "<td class='sev sev-"
                + html.escape(sev)
                + "'>"
                + html.escape(sev)
                + "</td>"
                "<td class='muted'>"
                "attempt "
                + str(
                    p.get("attempt", 1)
                )
                + " &middot; "
                + html.escape(
                    str(
                        p.get(
                            "updated_at",
                            ""
                        )
                    )
                )
                + "</td>"
                "</tr>"
            )

    body = (
        "<h1>Incident Agent</h1>"
        "<div class='card'>"
        "<h3>Demo</h3>"
        "<p class='muted'>Starta den syntetiska, trace-länkade"
        " databasincidenten i den här webhook-servern. Då fungerar"
        " approve/reject-knapparna på review-skärmen."
        "</p>"
        "<form method='post' action='/demo/fixture'>"
        "<button type='submit'>Start demo incident"
        "</button></form></div>"
        "<h2>Awaiting review</h2>"
        "<div class='card'>"
        "<table><thead><tr>"
        "<th>Incident</th>"
        "<th>Alert</th>"
        "<th>Service</th>"
        "<th>Severity</th>"
        "<th>Status</th>"
        "</tr></thead><tbody>"
        + rows
        + "</tbody></table></div>"
        "<p class='muted'>Auto-refreshes"
        " every 10s.</p>"
        "<script>setTimeout(function(){"
        "location.reload()},10000);"
        "</script>"
    )

    return page(body)


@app.post("/demo/fixture")
async def demo_fixture():
    try:
        with open(DEMO_FIXTURE_PATH) as f:
            payload = json.load(f)
    except OSError as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": (
                    "Could not load demo fixture: "
                    f"{exc}"
                )
            }
        )

    payload["incident_id"] = next_incident_id(
        HTML_OUTPUT_DIR
    )
    normalized = normalize_grafana_alert(
        payload
    )
    result = await _run_normalized_alert(
        normalized
    )

    return RedirectResponse(
        url=(
            "/incidents/"
            + result["incident_id"]
        ),
        status_code=303
    )



@app.get(
    "/incidents/{thread_id}",
    response_class=HTMLResponse
)
async def incident_detail(
    thread_id: str,
    request: Request,
):

    p = registry.get_pending(thread_id)

    if not p:
        return page(
            "<h1>Not found</h1>"
            "<p class='muted'>No pending"
            " incident with id "
            + html.escape(thread_id)
            + ".</p><p><a href='/'>"
            "&larr; back</a></p>"
        )

    items, groups = timeline_items(
        p.get("timeline", [])
    )
    timeline_window = _timeline_window(
        p.get("incident_window", {})
    )
    timeline_height = _timeline_height(len(groups))

    parsed = parse_interpretation(
        p.get("interpretation", "")
    )
    analysis_state = _analysis_review_state(p, parsed)
    agent_unavailable = analysis_state["unavailable"]
    analysis_inconclusive = analysis_state["inconclusive"]
    can_approve = analysis_state["can_approve"]

    tid = html.escape(thread_id)
    csrf_token = _issue_review_csrf(
        thread_id, _reviewer_identity(request)
    )
    sev = html.escape(
        str(p.get("severity", ""))
    )

    tldr_html = ""
    if parsed["tldr"].strip():
        tldr_html = (
            "<div class='card tldr'>"
            "<h3>TL;DR</h3>"
            "<div class='body md' "
            "data-md="
            + json.dumps(
                parsed["tldr"]
            )
            + "></div></div>"
        )

    hyps_html = ""
    if parsed["hypotheses"]:
        hyps_html = (
            "<h2 style='margin-top:"
            "28px'>Ranked hypotheses"
            "</h2>"
        )
        for h in parsed["hypotheses"]:
            hyps_html += (
                render_hypothesis(h)
            )
    else:
        interpretation_status = ""
        if agent_unavailable:
            interpretation_status = (
                "<span class='pill agent-unavailable'>"
                "agent analysis unavailable"
                "</span>"
            )
        elif analysis_inconclusive:
            interpretation_status = (
                "<span class='pill agent-unavailable'>"
                "AI abstained: inconclusive evidence"
                "</span>"
            )
        hyps_html = (
            "<div class='card'>"
            "<h3>Interpretation</h3>"
            + interpretation_status
            + (
                "<p class='muted'>"
                "No agent analysis was available for this incident."
                " Start the LLM and retry the analysis."
                "</p>"
                if not parsed["raw"].strip()
                else "<div class='body md' data-md="
                + json.dumps(parsed["raw"])
                + "></div>"
            )
            + "</div>"
        )

    extras_html = ""
    revision_diff_html = render_revision_diff(
        p.get("revision_diff")
    )
    semantic = p.get(
        "semantic_correlation", {}
    ) or {}
    if semantic:
        extras_html += (
            "<div class='card'>"
            "<h3>Semantic correlation</h3>"
            "<pre style='white-space:"
            "pre-wrap;overflow-x:auto'>"
            + html.escape(
                json.dumps(
                    semantic,
                    indent=2,
                    default=str
                )
            )
            + "</pre></div>"
        )
    deterministic = p.get(
        "deterministic_assessment", {}
    ) or {}
    if deterministic:
        extras_html += (
            "<div class='card'>"
            "<h3>Deterministic candidate ranking</h3>"
            "<pre style='white-space:pre-wrap;overflow-x:auto'>"
            + html.escape(
                json.dumps(
                    deterministic,
                    indent=2,
                    default=str,
                )
            )
            + "</pre></div>"
        )
    grounding = p.get("claim_grounding", {}) or {}
    if grounding:
        extras_html += (
            "<div class='card'>"
            "<h3>Claim grounding</h3>"
            "<pre style='white-space:pre-wrap;overflow-x:auto'>"
            + html.escape(
                json.dumps(
                    grounding,
                    indent=2,
                    default=str,
                )
            )
            + "</pre></div>"
        )
    budget = p.get("investigation_budget", {}) or {}
    if budget:
        extras_html += (
            "<div class='card'>"
            "<h3>Investigation budget</h3>"
            "<pre style='white-space:pre-wrap;overflow-x:auto'>"
            + html.escape(
                json.dumps(budget, indent=2, default=str)
            )
            + "</pre></div>"
        )
    model_controls = {
        "analysis_deadline": p.get("analysis_deadline", {}),
        "model_usage_ledger": p.get("model_usage_ledger", {}),
    }
    if any(model_controls.values()):
        extras_html += (
            "<div class='card'>"
            "<h3>Model usage and hard budget</h3>"
            "<pre style='white-space:pre-wrap;overflow-x:auto'>"
            + html.escape(json.dumps(
                model_controls, indent=2, default=str
            ))
            + "</pre></div>"
        )
    coverage = {
        "incident_window": p.get("incident_window", {}),
        "data_quality": p.get("data_quality", {}),
        "source_status": p.get("source_status", {}),
    }
    if any(coverage.values()):
        extras_html += (
            "<div class='card'>"
            "<h3>Evidence coverage</h3>"
            "<pre style='white-space:pre-wrap;overflow-x:auto'>"
            + html.escape(json.dumps(coverage, indent=2, default=str))
            + "</pre></div>"
        )
    if parsed["blast_radius"]:
        extras_html += (
            "<div class='card'>"
            "<h3>Blast radius</h3>"
            "<div class='body md' "
            "data-md="
            + json.dumps(
                parsed["blast_radius"]
            )
            + "></div></div>"
        )
    if parsed["next_steps"]:
        extras_html += (
            "<div class='card'>"
            "<h3>Suggested next steps"
            "</h3>"
            "<div class='body md' "
            "data-md="
            + json.dumps(
                parsed["next_steps"]
            )
            + "></div></div>"
        )

    if not can_approve:
        if agent_unavailable:
            decision_status = "approval disabled: no agent analysis"
            decision_message = (
                "There is no hypothesis to approve. Start the LLM, then "
                "retry the analysis."
            )
        else:
            decision_status = "approval disabled: inconclusive analysis"
            decision_message = (
                "The agent abstained because the evidence was inconclusive. "
                "Collect discriminating evidence or add reviewer context, "
                "then retry the analysis."
            )
        decision_html = (
            "<div class='card'>"
            "<h3>Decision</h3>"
            "<span class='pill agent-unavailable'>"
            + decision_status
            + "</span>"
            "<p class='muted'>"
            + decision_message
            + "</p>"
            "<textarea id='fb' placeholder="
            "'Optional context for the next analysis run'>"
            "</textarea>"
            "<div class='row' style='margin-top:10px'>"
            "<button class='reject' onclick='reject()'>"
            "Retry agent analysis</button>"
            "</div>"
            "<p id='status' class='status-msg'></p></div>"
        )
    else:
        decision_html = (
            "<div class='card'>"
            "<h3>Decision</h3>"
            "<div class='row'>"
            "<label>Approve hypothesis "
            "<select id='hyp'>"
            "<option value='1'>1</option>"
            "<option value='2'>2</option>"
            "<option value='3'>3</option>"
            "</select></label>"
            "<button onclick='approve()'>"
            "Approve &amp; write postmortem"
            "</button></div>"
            "<p class='muted' style="
            "'margin-top:14px'>or reject "
            "with feedback to make the "
            "agent re-interpret:</p>"
            "<textarea id='fb' placeholder="
            "'Why is the interpretation "
            "wrong? What did it miss?'>"
            "</textarea>"
            "<div class='row' style='"
            "margin-top:10px'>"
            "<button class='reject' "
            "onclick='reject()'>Reject "
            "&amp; re-interpret</button>"
            "<button onclick='requestMore()'>"
            "Request more evidence</button>"
            "</div>"
            "<p id='status' class='"
            "status-msg'></p></div>"
        )

    body = (
        "<p><a href='/'>&larr; all "
        "incidents</a></p>"
        "<h1>"
        + html.escape(
            str(p.get("alertname"))
        )
        + "</h1>"
        "<div style='margin-bottom:"
        "18px'>"
        "<span class='pill'>"
        + tid
        + "</span>"
        "<span class='pill'>service: "
        + html.escape(
            str(p.get("service"))
        )
        + "</span>"
        "<span class='pill sev sev-"
        + sev
        + "'>severity: "
        + sev
        + "</span>"
        "<span class='pill'>attempt "
        + str(p.get("attempt", 1))
        + "</span>"
        + (
            "<span class='pill agent-unavailable'>"
            "agent analysis unavailable"
            "</span>"
            if agent_unavailable
            else (
                "<span class='pill agent-unavailable'>"
                "AI abstained: inconclusive"
                "</span>"
                if analysis_inconclusive
                else ""
            )
        )
        + "<span class='pill'><a href='/"
        + html.escape(
            str(
                p.get(
                    "review_html_path",
                    ""
                )
            )
        )
        + "'>full reviewer screen</a>"
        "</span></div>"
        "<div class='card'>"
        "<h3>Alert</h3>"
        "<p>"
        + html.escape(
            str(p.get("message", ""))
        )
        + "</p></div>"
        + revision_diff_html
        + tldr_html
        + "<div class='card'>"
        "<h3>Timeline</h3>"
        "<div id='tl' style='height:"
        + str(timeline_height)
        + "px;overflow:hidden'></div></div>"
        + hyps_html
        + extras_html
        + decision_html
        + "<script>"
        "var items=" + json.dumps(items)
        + ";var groups="
        + json.dumps(groups)
        + ";var timelineWindow="
        + json.dumps(timeline_window)
        + ";var pendingRevision="
        + json.dumps(p.get("pending_revision"))
        + ";var csrfToken="
        + json.dumps(csrf_token)
        + ";"
        "function norm(t){if(!t)return"
        " null;if(/^\\d{1,2}:\\d{2}/"
        ".test(t))return '2026-01-01T'"
        "+(t.length==5?t+':00':t);"
        "return t;}"
        "items.forEach(function(i){i"
        ".start=norm(i.start);if(i"
        ".end)i.end=norm(i.end);});"
        "if(items.length){var c="
        "document.getElementById('tl')"
        ";var ds=new vis.DataSet("
        "items);var gs=new vis.DataSet"
        "(groups);new vis.Timeline(c,"
        "ds,gs,Object.assign({stack:true,"
        "verticalScroll:true,showCurrentTime:false,"
        "margin:{item:8},zoomable:true},timelineWindow));}"
        "else{document.getElementById("
        "'tl').innerHTML=\"<span "
        "class='muted'>no timeline "
        "data</span>\";}"
        "function post(b){var s="
        "document.getElementById("
        "'status');s.className='"
        "status-msg working';s"
        ".textContent='Processing... "
        "local LLM can take several "
        "minutes.';return fetch('/"
        "alerts/" + tid + "/review',{"
        "method:'POST',headers:{'"
        "Content-Type':'application/"
        "json','X-CSRF-Token':csrfToken},body:JSON.stringify(b"
        ")}).then(function(r){return "
        "r.json().then(function(d){"
        "if(!r.ok){throw new Error("
        "d.error||('HTTP '+r.status)"
        ");}return d;})}).then("
        "function(d){"
        "if(d.awaiting_review){s"
        ".textContent=(d.review_status==='request_more_evidence'"
        "?'More evidence collected. Reloading...'"
        ":'Re-interpreted. Reloading...');setTimeout("
        "function(){location.reload()"
        "},1500);}else{s.className='"
        "status-msg done';s"
        ".textContent='Done. "
        "Postmortem published.';"
        "setTimeout(function(){"
        "location.href='/'},1800);}}"
        ").catch(function(e){s."
        "className='status-msg error';"
        "s.textContent='Review failed: "
        "'+e.message;});}"
        "function approve(){post({pending_revision:pendingRevision,"
        "status:'approved',"
        "chosen_hypothesis:parseInt("
        "document.getElementById('hyp'"
        ").value)});}"
        "function reject(){post({pending_revision:pendingRevision,"
        "status:'rejected',feedback:"
        "document.getElementById('fb'"
        ").value});}"
        "function requestMore(){post({pending_revision:pendingRevision,"
        "status:'request_more_evidence',feedback:"
        "document.getElementById('fb'"
        ").value});}"
        "</script>"
    )

    return page(body)


@app.post("/alerts")
@app.post("/v1/alerts")
async def alerts(request: Request, background_tasks: BackgroundTasks = None):

    declared_length = request.headers.get("content-length")
    if declared_length:
        try:
            too_large = int(declared_length) > MAX_WEBHOOK_BODY_BYTES
        except ValueError:
            record_rejection("invalid_content_length")
            return JSONResponse(
                status_code=400,
                content={"error": "Content-Length must be an integer."},
            )
        if too_large:
            record_rejection("body_too_large")
            return JSONResponse(
                status_code=413,
                content={"error": "Webhook request body is too large."},
            )

    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        record_rejection("body_too_large")
        return JSONResponse(
            status_code=413,
            content={"error": "Webhook request body is too large."},
        )
    if not _valid_webhook_signature(request, body):
        record_rejection("invalid_webhook_signature")
        return JSONResponse(
            status_code=401,
            content={
                "error": "Invalid or missing webhook signature."
            },
        )
    try:
        _validate_webhook_replay(request)
    except ReplayError as exc:
        record_rejection(exc.code)
        return JSONResponse(
            status_code=401,
            content={"error": str(exc), "code": exc.code},
        )
    allowed, retry_after, reason = _allow_webhook_request(request)
    if not allowed:
        record_rejection(reason)
        return JSONResponse(
            status_code=429,
            content={"error": "Webhook rate limit exceeded.", "code": reason},
            headers={"Retry-After": str(retry_after)},
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        record_rejection("invalid_json")
        return JSONResponse(
            status_code=400,
            content={"error": "Webhook body must be valid JSON."},
        )
    try:
        incoming = validate_alert_payload(
            payload,
            max_alerts=MAX_ALERTS_PER_REQUEST,
            max_labels=MAX_ALERT_LABELS,
            max_annotations=MAX_ALERT_ANNOTATIONS,
            max_field_length=MAX_ALERT_FIELD_LENGTH,
            supported_services=set(list_services()),
            supported_environments=SUPPORTED_INCIDENT_ENVIRONMENTS,
            default_environment=DEFAULT_ALERT_ENVIRONMENT,
        )
    except AlertContractError as exc:
        record_rejection(exc.code)
        return JSONResponse(
            status_code=(
                413
                if exc.code == "too_many_alerts"
                else 400
            ),
            content={"error": str(exc), "code": exc.code},
        )

    results = []

    for alert in incoming:
        labels = alert.get("labels", {}) if isinstance(alert, dict) else {}
        supplied_tenant = str(
            labels.get("tenant_id") or labels.get("tenant") or ""
        ).strip()
        if supplied_tenant and supplied_tenant != DEPLOYMENT_TENANT_ID:
            record_rejection("tenant_mismatch")
            increment("alerts", outcome="tenant_mismatch")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "alert tenant does not match this deployment",
                    "code": "tenant_mismatch",
                },
            )
        normalized = normalize_grafana_alert(alert)
        normalized["tenant_id"] = DEPLOYMENT_TENANT_ID
        normalized["incident_id"] = get_or_create_incident_id(
            normalized
        )
        idempotency_key = hashlib.sha256(
            json.dumps(alert, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        try:
            event = record_event_and_enqueue(
                normalized["incident_id"],
                idempotency_key,
                normalized["status"],
                normalized,
                event_time=normalized.get("started_at"),
                source_time=normalized.get("ended_at") or normalized.get("started_at"),
            )
        except QueueCapacityError as exc:
            record_rejection("queue_capacity")
            increment("alerts", outcome="queue_capacity_rejected")
            emit_log_event(
                "alert_rejected",
                severity="WARNING",
                incident_id=normalized["incident_id"],
                node="webhook",
                error_category="queue_capacity",
                request_id=request.headers.get("x-request-id"),
            )
            return JSONResponse(
                status_code=503,
                content={
                    "error": str(exc),
                    "code": "queue_capacity",
                    "processed_before_rejection": len(results),
                },
                headers={"Retry-After": "30"},
            )
        if not event["inserted"]:
            increment("alerts", outcome="deduplicated")
            emit_log_event("alert_deduplicated", incident_id=normalized["incident_id"], node="webhook", request_id=request.headers.get("x-request-id"))
            results.append({
                "incident_id": normalized["incident_id"],
                "alertname": normalized["alertname"],
                "status": "duplicate_event",
            })
            continue
        increment("alerts", outcome="accepted")
        emit_log_event("alert_accepted", incident_id=normalized["incident_id"], node="webhook", request_id=request.headers.get("x-request-id"), details={"event_id": event["event_id"], "job_id": event["job_id"]})
        results.append({
            "incident_id": normalized["incident_id"],
            "alertname": normalized["alertname"],
            "event_id": event["event_id"],
            "job_id": event["job_id"],
            "status": "accepted",
        })

    if (
        API_DRAIN_JOBS
        and background_tasks
        and any(result["status"] == "accepted" for result in results)
    ):
        background_tasks.add_task(_drain_incident_jobs)

    return {
        "processed": len(results),
        "results": results
    }


@app.post("/v1/dead-letters/{job_id}/replay")
async def replay_dead_letter_job(job_id: int, payload: dict = None, background_tasks: BackgroundTasks = None):
    try:
        result = replay_dead_letter(job_id, run_context=payload or None)
    except QueueCapacityError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": "queue_capacity"},
            headers={"Retry-After": "30"},
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    if API_DRAIN_JOBS and background_tasks:
        background_tasks.add_task(_drain_incident_jobs)
    record_audit_event("dead_letter_replayed", result["incident_id"], job_id=job_id)
    increment("dead_letter_replays")
    return {"status": "accepted", **result}


@app.post("/v1/incidents/{thread_id}/reprocess")
async def reprocess_incident(thread_id: str, payload: dict = None, background_tasks: BackgroundTasks = None):
    try:
        result = enqueue_reprocessing(thread_id, run_context=payload or None)
    except QueueCapacityError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": "queue_capacity"},
            headers={"Retry-After": "30"},
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    if API_DRAIN_JOBS and background_tasks:
        background_tasks.add_task(_drain_incident_jobs)
    record_audit_event("incident_reprocessing_requested", thread_id, run_context=result["run_context"])
    increment("reprocessing", outcome="accepted")
    return {"status": "accepted", **result}


@app.post(
    "/alerts/{thread_id}/review"
)
async def review(
    thread_id: str, payload: dict, request: Request
):

    pending = (
        registry.get_pending(thread_id)
        or {}
    )

    if not pending:
        return JSONResponse(
            status_code=409,
            content={
                "thread_id": thread_id,
                "error": (
                    "No saved pending review exists "
                    "for this incident. This usually "
                    "means the review HTML is a stale "
                    "snapshot from run_fixture.py, or "
                    "the incident store was cleared. "
                    "Open the webhook home page and "
                    "start a new demo incident, or send "
                    "a fresh POST /alerts."
                ),
                "recovery": (
                    "Open http://127.0.0.1:8000/ "
                    "and start a new demo incident."
                ),
                "awaiting_review": False
            }
        )

    lifecycle = registry.get_lifecycle(thread_id)
    if lifecycle and lifecycle.get("status") == "resolved":
        return JSONResponse(
            status_code=409,
            content={
                "thread_id": thread_id,
                "error": "Resolved incidents cannot decide an older analysis.",
                "code": "incident_resolved",
            },
        )

    try:
        submitted_version = int(payload.get("pending_revision"))
    except (TypeError, ValueError):
        return JSONResponse(status_code=409, content={"error": "pending review version is required", "code": "stale_incident_revision"})
    if submitted_version != pending.get("pending_revision"):
        return JSONResponse(status_code=409, content={"error": "pending review has changed; reload before deciding", "code": "stale_incident_revision"})

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    try:
        resume = _review_resume_payload(payload, pending)
    except ReviewRequestError as exc:
        record_audit_event("review_rejected_invalid_request", thread_id, reason=str(exc))
        return JSONResponse(status_code=400, content={"error": str(exc)})

    record_audit_event(
        "review_submitted",
        thread_id,
        decision=resume["status"],
        chosen_hypothesis=resume["chosen_hypothesis"],
        feedback=resume["feedback"],
        request_id=request.headers.get("x-request-id"),
    )
    try:
        decision_record = record_review_decision(
            thread_id,
            submitted_version,
            resume["status"],
            _reviewer_identity(request),
            rationale=resume["feedback"],
            request_id=request.headers.get("x-request-id"),
            selected_hypothesis=(resume["chosen_hypothesis"] if resume["status"] == "approved" else None),
            analysis_revision=pending.get("analysis_revision"),
            candidate_snapshot=(pending.get("deterministic_assessment", {}) or {}).get("candidates", []),
            displayed_evidence_ids=[
                item.get("event_id")
                for item in (pending.get("event_history", []) or [])
                if isinstance(item, dict) and item.get("event_id") is not None
            ],
            enforce_pending=True,
        )
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc), "code": "stale_incident_revision"})
    if decision_record.get("deduplicated"):
        return JSONResponse(
            status_code=202,
            content={
                "thread_id": thread_id,
                "review_status": resume["status"],
                "awaiting_review": True,
                "deduplicated": True,
                "message": (
                    "This exact decision is already being processed; "
                    "refresh review status before retrying."
                ),
            },
        )
    review_event_key = hashlib.sha256(
        (thread_id + ":review:" + str(submitted_version) + ":" + json.dumps(resume, sort_keys=True)).encode("utf-8")
    ).hexdigest()
    append_event(
        thread_id,
        review_event_key,
        "review_" + resume["status"],
        {"incident_id": thread_id, "review": resume, "pending_revision": submitted_version},
        clock_quality="server_received_time",
    )
    lifecycle = registry.get_lifecycle(thread_id)
    registry.transition_lifecycle(
        thread_id,
        "drafting_postmortem" if resume["status"] == "approved" else "analyzing",
        (
            "review approved"
            if resume["status"] == "approved"
            else (
                "review requested more evidence"
                if resume["status"] == "request_more_evidence"
                else "review rejected"
            )
        ),
        lifecycle["version"] if lifecycle else None,
    )
    state = await graph.ainvoke(Command(resume=resume), config=config)

    try:
        sync_registry(
            thread_id,
            {
                "alertname": pending.get("alertname", "Incident"),
                "service": pending.get("service", "unknown"),
                "severity": pending.get("severity", "unknown"),
                "message": pending.get("message", ""),
            },
            state,
            expected_pending_version=pending.get("pending_revision"),
        )
        lifecycle = registry.get_lifecycle(thread_id)
        registry.transition_lifecycle(
            thread_id,
            "awaiting_analysis_review" if is_awaiting_review(state) else "completed",
            "revised analysis awaits review" if is_awaiting_review(state) else "review workflow completed",
            lifecycle["version"] if lifecycle else None,
        )
    except registry.RevisionConflictError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc), "code": "stale_incident_revision"})

    draft_record = None
    if not is_awaiting_review(state) and state.get("postmortem_draft"):
        draft_record = record_postmortem_draft(
            thread_id,
            state["postmortem_draft"],
            analysis_revision=pending.get("analysis_revision"),
            source="generated",
        )

    return {
        "thread_id": thread_id,
        "review_status": state.get(
            "review_status"
        ),
        "awaiting_review":
        is_awaiting_review(state),
        "postmortem_url": state.get(
            "postmortem_url", ""
        ),
        "postmortem_draft": state.get(
            "postmortem_draft", ""
        ),
        "postmortem_draft_version": (draft_record or {}).get("version"),
    }


@app.get(
    "/alerts/{thread_id}/review/status"
)
async def review_status(thread_id: str, request: Request):
    pending = registry.get_pending(
        thread_id
    )

    if not pending:
        return {
            "thread_id": thread_id,
            "awaiting_review": False,
            "error": (
                "This review screen is not "
                "connected to a pending "
                "incident in the running "
                "webhook server. Start a "
                "new demo from the webhook "
                "home page."
            ),
            "recovery": (
                "Open http://127.0.0.1:8000/ "
                "and click Start demo incident."
            )
        }

    return {
        "thread_id": thread_id,
        "awaiting_review": True,
        "attempt": pending.get(
            "attempt", 1
        ),
        "pending_revision": pending.get("pending_revision"),
        "csrf_token": _issue_review_csrf(
            thread_id, _reviewer_identity(request)
        ),
        "updated_at": pending.get(
            "updated_at"
        )
    }


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/canary/jobs/{job_id}")
async def canary_status(job_id: int, incident_id: str, request: Request):
    supplied = request.headers.get("x-canary-token", "")
    if not CANARY_SHARED_SECRET or not hmac.compare_digest(
        supplied,
        CANARY_SHARED_SECRET,
    ):
        return JSONResponse(status_code=401, content={"error": "invalid canary token"})
    status = canary_job_status(job_id, incident_id)
    if status is None:
        return JSONResponse(status_code=404, content={"error": "canary job not found"})
    return status


@app.get("/readyz")
async def readyz():
    try:
        validate_runtime_config(__import__("settings"))
    except ValueError as exc:
        return JSONResponse(status_code=503, content={"status": "not_ready", "error": str(exc)})
    dependencies = readiness_check(
        require_worker=not API_DRAIN_JOBS,
        worker_max_age_seconds=WORKER_HEARTBEAT_STALE_SECONDS,
    )
    if (
        dependencies["database"] != "ready"
        or dependencies["queue"] != "ready"
        or dependencies["worker"]["status"] == "unavailable"
    ):
        return JSONResponse(status_code=503, content={"status": "not_ready", "dependencies": dependencies})
    return {"status": "ready", "dependencies": dependencies}


@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    if METRICS_BEARER_TOKEN:
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + METRICS_BEARER_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"error": "metrics authentication is required"},
            )
    gauges = operational_snapshot(WORKER_HEARTBEAT_STALE_SECONDS)
    for name, value in pool_stats().items():
        gauges[f"mysql_pool_{name}"] = value
    body = prometheus_text() + prometheus_gauges(gauges)
    return HTMLResponse(
        body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
