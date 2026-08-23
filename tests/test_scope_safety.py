import base64
import asyncio
import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from graph.nodes import gather_deploys
from graph.nodes import gather_logs
from graph.nodes import gather_metrics
from webhook import api


class _Request:
    def __init__(self, headers=None, session=None):
        self.headers = headers or {}
        self.session = session or {}


class ScopeSafetyTests(unittest.TestCase):
    def test_production_rejects_webhook_when_secret_is_missing(self):
        with patch.multiple(
            api,
            ENVIRONMENT="production",
            WEBHOOK_SHARED_SECRET="",
        ):
            self.assertFalse(
                api._valid_webhook_signature(
                    _Request(), b'{"alert": "test"}'
                )
            )

    def test_webhook_signature_must_match_the_body(self):
        body = b'{"alert": "test"}'
        secret = "test-webhook-secret"
        signature = "sha256=" + hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        with patch.object(api, "WEBHOOK_SHARED_SECRET", secret):
            self.assertTrue(
                api._valid_webhook_signature(
                    _Request({"x-incident-signature": signature}), body
                )
            )
            self.assertFalse(
                api._valid_webhook_signature(
                    _Request({"x-incident-signature": signature}),
                    b'{"alert": "changed"}',
                )
            )

    def test_production_rejects_review_when_credentials_are_missing(self):
        with patch.multiple(
            api,
            ENVIRONMENT="production",
            REVIEW_USERNAME="",
            REVIEW_PASSWORD="",
        ):
            self.assertFalse(api._review_authenticated(_Request()))

    def test_shadow_requires_webhook_and_review_authentication(
        self,
    ):
        with patch.multiple(
            api,
            ENVIRONMENT="shadow",
            WEBHOOK_SHARED_SECRET="",
            REVIEW_USERNAME="",
            REVIEW_PASSWORD="",
        ):
            self.assertFalse(
                api._valid_webhook_signature(
                    _Request(),
                    b'{"alert": "test"}',
                )
            )
            self.assertFalse(
                api._review_authenticated(
                    _Request()
                )
            )

    def test_valid_reviewer_basic_credentials_are_required(self):
        encoded = base64.b64encode(
            b"reviewer:strong-test-password"
        ).decode("ascii")
        with patch.multiple(
            api,
            REVIEW_USERNAME="reviewer",
            REVIEW_PASSWORD="strong-test-password",
        ):
            self.assertTrue(
                api._review_authenticated(
                    _Request({"authorization": f"Basic {encoded}"})
                )
            )
            self.assertFalse(
                api._review_authenticated(
                    _Request({"authorization": "Basic invalid"})
                )
            )

    def test_oidc_roles_separate_view_decision_and_operator_access(self):
        jwks = Mock()
        jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(
            key="public-key"
        )
        request = _Request({"authorization": "Bearer signed-token"})
        with patch.multiple(
            api,
            ENVIRONMENT="production",
            REVIEW_AUTH_MODE="oidc",
            OIDC_ISSUER="https://identity.example.test/",
            OIDC_AUDIENCE="incident-agent",
            OIDC_JWKS_URL="https://identity.example.test/jwks",
            OIDC_ROLE_CLAIM="roles",
            OIDC_TENANT_CLAIM="tenant_id",
            DEPLOYMENT_TENANT_ID="tenant-a",
            OIDC_VIEWER_ROLES={"incident-reviewer"},
            OIDC_DECISION_ROLES={"incident-reviewer"},
            OIDC_OPERATOR_ROLES={"incident-operator"},
            _OIDC_JWKS_CLIENT=jwks,
            _OIDC_JWKS_CLIENT_URL="https://identity.example.test/jwks",
        ), patch.object(api.jwt, "decode", return_value={
            "iss": "https://identity.example.test/",
            "sub": "user-123",
            "exp": 2_000_000_000,
            "roles": ["incident-reviewer"],
            "tenant_id": "tenant-a",
        }):
            self.assertTrue(api._review_authorized(request, "view"))
            self.assertTrue(api._review_authorized(request, "decision"))
            self.assertFalse(api._review_authorized(request, "operator"))
            self.assertTrue(api._reviewer_identity(request).startswith("oidc:"))

    def test_oidc_token_without_required_role_is_denied(self):
        with patch.object(api, "_oidc_principal", return_value={
            "identity": "oidc:test",
            "roles": {"unrelated-role"},
            "auth_mode": "oidc",
        }), patch.object(api, "_basic_principal", return_value=None), patch.multiple(
            api,
            OIDC_VIEWER_ROLES={"incident-viewer"},
            OIDC_DECISION_ROLES={"incident-reviewer"},
        ):
            self.assertFalse(api._review_authorized(_Request(), "view"))
            self.assertFalse(api._review_authorized(_Request(), "decision"))

    def test_signed_oidc_session_uses_same_rbac_policy(self):
        request = _Request(session={
            "review_claims": {
                "iss": "https://identity.example.test/",
                "sub": "reviewer-123",
                "exp": 2_000_000_000,
                "roles": ["incident-viewer"],
                "tenant_id": "tenant-a",
            },
        })
        with patch.multiple(
            api,
            ENVIRONMENT="production",
            REVIEW_AUTH_MODE="oidc",
            OIDC_ISSUER="https://identity.example.test/",
            OIDC_ROLE_CLAIM="roles",
            OIDC_TENANT_CLAIM="tenant_id",
            DEPLOYMENT_TENANT_ID="tenant-a",
            OIDC_VIEWER_ROLES={"incident-viewer"},
            OIDC_DECISION_ROLES={"incident-reviewer"},
        ):
            self.assertTrue(api._review_authorized(request, "view"))
            self.assertFalse(api._review_authorized(request, "decision"))

    def test_csrf_token_is_bound_to_incident_identity_and_expiry(self):
        with patch.multiple(
            api,
            ENVIRONMENT="local",
            REVIEW_CSRF_SECRET="csrf-secret-with-more-than-32-characters",
            REVIEW_CSRF_TTL_SECONDS=300,
        ):
            token = api._issue_review_csrf("INC-1", "oidc:user", now=1000)
            self.assertTrue(api._valid_review_csrf(
                token, "INC-1", "oidc:user", now=1100
            ))
            self.assertFalse(api._valid_review_csrf(
                token, "INC-2", "oidc:user", now=1100
            ))
            self.assertFalse(api._valid_review_csrf(
                token, "INC-1", "oidc:other", now=1100
            ))
            self.assertFalse(api._valid_review_csrf(
                token, "INC-1", "oidc:user", now=1400
            ))
            self.assertFalse(api._valid_review_csrf(
                token + "tampered", "INC-1", "oidc:user", now=1100
            ))

    def test_review_middleware_enforces_csrf_after_authorization(self):
        identity = "oidc:test-reviewer"
        with patch.multiple(
            api,
            ENVIRONMENT="local",
            REVIEW_CSRF_SECRET="csrf-secret-with-more-than-32-characters",
        ), patch.object(
            api, "_review_authorized", return_value=True
        ) as authorized, patch.object(
            api, "_reviewer_identity", return_value=identity
        ):
            missing = SimpleNamespace(
                url=SimpleNamespace(path="/alerts/INC-1/review"),
                method="POST",
                headers={},
            )
            response = asyncio.run(api.protect_reviewer_surface(
                missing, lambda _request: None
            ))
            self.assertEqual(response.status_code, 403)

            token = api._issue_review_csrf("INC-1", identity)
            valid = SimpleNamespace(
                url=SimpleNamespace(path="/alerts/INC-1/review"),
                method="POST",
                headers={"x-csrf-token": token},
            )

            async def accepted(_request):
                return "accepted"

            self.assertEqual(
                asyncio.run(api.protect_reviewer_surface(valid, accepted)),
                "accepted",
            )

            publish = SimpleNamespace(
                url=SimpleNamespace(path="/alerts/INC-1/publish"),
                method="POST",
                headers={"x-csrf-token": token},
            )
            self.assertEqual(
                asyncio.run(api.protect_reviewer_surface(publish, accepted)),
                "accepted",
            )
            self.assertIn("operator", [call.args[1] for call in authorized.call_args_list])

    def test_optional_evidence_source_failures_are_explicit(self):
        state = {
            "alert": {
                "service": "payments",
                "labels": {"service": "payments"},
            },
            "incident_window": {
                "start": "2026-07-21T10:00:00Z",
                "end": "2026-07-21T10:10:00Z",
            },
        }

        with patch.object(
            gather_logs.loki,
            "get_log_stats",
            side_effect=RuntimeError("loki unavailable"),
        ):
            logs = gather_logs.gather_logs(state)
        with patch.object(
            gather_metrics.prometheus,
            "query_metrics",
            side_effect=RuntimeError("prometheus unavailable"),
        ):
            metrics = gather_metrics.gather_metrics(state)
        with patch.object(
            gather_deploys.github,
            "get_recent_deploys",
            side_effect=RuntimeError("deployments unavailable"),
        ):
            deploys = gather_deploys.gather_deploys(state)

        self.assertEqual(logs["source_status"]["loki"]["status"], "failed")
        self.assertEqual(
            metrics["source_status"]["prometheus"]["status"], "failed"
        )
        self.assertEqual(
            deploys["source_status"]["deployments"]["status"], "failed"
        )
