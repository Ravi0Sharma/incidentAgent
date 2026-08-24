import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from clients import openai_client
from utils import observability
from utils.logging import build_log_event
from utils.runtime_config import LOCAL_REDACTION_SALT, validate_runtime_config
from webhook.api import (
    ReviewRequestError,
    _analysis_review_state,
    _review_resume_payload,
    review,
)


ROOT = Path(__file__).resolve().parents[1]


def _production_config(**overrides):
    values = {
        "ENVIRONMENT": "production",
        "WEBHOOK_SHARED_SECRET": "webhook-secret",
        "REVIEW_USERNAME": "reviewer",
        "REVIEW_PASSWORD": "strong-password",
        "REVIEW_AUTH_MODE": "oidc",
        "OIDC_ISSUER": "https://identity.example.test/",
        "OIDC_AUDIENCE": "incident-agent",
        "OIDC_JWKS_URL": "https://identity.example.test/.well-known/jwks.json",
        "OIDC_METADATA_URL": "https://identity.example.test/.well-known/openid-configuration",
        "OIDC_CLIENT_ID": "incident-agent",
        "OIDC_CLIENT_SECRET": "test-client-secret",
        "OIDC_REDIRECT_URI": "https://incident.example.test/auth/callback",
        "OIDC_TENANT_CLAIM": "tenant_id",
        "OIDC_VIEWER_ROLES": {
            "incident-viewer", "incident-reviewer", "incident-admin"
        },
        "OIDC_DECISION_ROLES": {"incident-reviewer", "incident-admin"},
        "OIDC_OPERATOR_ROLES": {"incident-operator", "incident-admin"},
        "REVIEW_CSRF_SECRET": "x" * 40,
        "REVIEW_SESSION_SECRET": "y" * 40,
        "METRICS_BEARER_TOKEN": "m" * 40,
        "CANARY_SHARED_SECRET": "c" * 40,
        "REVIEW_SESSION_MAX_AGE_SECONDS": 28800,
        "REDACTION_SALT": "environment-specific-secret",
        "CORS_ORIGINS": ["https://incident.example.test"],
        "CHECKPOINTER": "mysql",
        "DEPLOYMENT_TENANT_ID": "arcvial",
        "SECRETS_PROVIDER": "railway",
        "PUBLIC_BASE_URL": "https://incident.example.test",
        "PROCESS_ROLE": "api",
        "MYSQL_API_USER": "incident_api",
        "MYSQL_WORKER_USER": "incident_worker",
        "MYSQL_POOL_SIZE": 8,
        "MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS": 5,
        "MIN_ACTIVE_WORKERS": 2,
        "MYSQL_SSL_ENABLED": True,
        "MYSQL_SSL_VERIFY_IDENTITY": True,
        "RUNTIME_SCHEMA_DDL_ENABLED": False,
        "OPENAI_BASE_URL": "https://api.openai.example/v1",
        "OPENAI_API_KEY": "test-provider-key",
        "LOKI_URL": "https://loki.example.test",
        "PROMETHEUS_URL":
        "https://prometheus.example.test",
        "GITHUB_TOKEN": "read-only-token",
        "GITHUB_REPO": "example/repository",
        "PII_REDACTION_ENABLED": True,
        "SKIP_LLM": False,
        "LLM_TIMEOUT_SECONDS": 60,
        "LLM_RETRY_ATTEMPTS": 1,
        "LLM_MAX_CALLS_PER_INCIDENT": 12,
        "LLM_MAX_INPUT_TOKENS_PER_INCIDENT": 60000,
        "LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT": 12000,
        "LLM_MAX_TOTAL_TOKENS_PER_INCIDENT": 72000,
        "LLM_MAX_COST_USD_PER_INCIDENT": 1.0,
        "LLM_INPUT_USD_PER_MILLION_TOKENS": 1.0,
        "LLM_OUTPUT_USD_PER_MILLION_TOKENS": 1.0,
        "PUBLISH_EXTERNAL": False,
        "CONNECTORS_ENABLED": True,
        "MODEL_ENABLED": True,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test/v1/traces",
        "EGRESS_ALLOWED_HOSTS": {
            "incident.example.test",
            "identity.example.test",
            "api.openai.example",
            "loki.example.test",
            "prometheus.example.test",
            "otel.example.test",
            "api.github.com",
            "*.amazonaws.com",
        },
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class OperationalBaselineTests(unittest.TestCase):
    def test_api_import_creates_missing_static_output_directory(self):
        with tempfile.TemporaryDirectory() as root:
            output_dir = Path(root) / "new" / "output"
            env = {
                **os.environ,
                "HTML_OUTPUT_DIR": str(output_dir),
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import webhook.api; from pathlib import Path; "
                    "raise SystemExit(not Path(__import__('os').environ['HTML_OUTPUT_DIR']).is_dir())",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_resolved_incident_blocks_an_old_review_decision(self):
        request = Mock(headers={})
        with patch(
            "webhook.api.registry.get_pending",
            return_value={"pending_revision": 2},
        ), patch(
            "webhook.api.registry.get_lifecycle",
            return_value={"status": "resolved"},
        ):
            response = asyncio.run(review(
                "INC-RESOLVED",
                {"pending_revision": 2, "status": "approved"},
                request,
            ))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.body)["code"],
            "incident_resolved",
        )

    def test_abstained_analysis_cannot_be_approved_in_ui(self):
        status = _analysis_review_state(
            {
                "interpretation": "No supported root cause yet.",
                "interpretation_quality": {"abstained": True},
                "interpretation_tool_trace": [{"status": "abstained"}],
            },
            {"hypotheses": []},
        )
        self.assertTrue(status["inconclusive"])
        self.assertFalse(status["can_approve"])

    def test_grounded_provider_fallback_remains_human_reviewable(self):
        status = _analysis_review_state(
            {
                "interpretation": "Grounded deterministic hypothesis.",
                "interpretation_quality": {
                    "passed": True,
                    "abstained": False,
                },
                "claim_grounding": {
                    "passed": True,
                },
                "deterministic_assessment": {
                    "candidates": [{
                        "rank": 1,
                    }],
                },
                "interpretation_tool_trace": [{
                    "status": "degraded",
                }],
            },
            {"hypotheses": [{"rank": 1}]},
        )
        self.assertTrue(
            status["provider_degraded"]
        )
        self.assertTrue(
            status["validation_passed"]
        )
        self.assertTrue(
            status["can_approve"]
        )

    def test_ungrounded_hypothesis_cannot_be_approved_in_ui(self):
        status = _analysis_review_state(
            {
                "interpretation": "Unsupported hypothesis.",
                "interpretation_quality": {
                    "passed": True,
                    "abstained": False,
                },
                "claim_grounding": {
                    "passed": False,
                },
                "deterministic_assessment": {
                    "candidates": [{
                        "rank": 1,
                    }],
                },
            },
            {"hypotheses": [{"rank": 1}]},
        )
        self.assertEqual(
            status["reason"],
            "claim_grounding_failed",
        )
        self.assertFalse(
            status["can_approve"]
        )

    def test_production_configuration_rejects_local_defaults(self):
        with self.assertRaisesRegex(ValueError, "REDACTION_SALT"):
            validate_runtime_config(_production_config(REDACTION_SALT=LOCAL_REDACTION_SALT))
        with self.assertRaisesRegex(ValueError, "checkpointer"):
            validate_runtime_config(_production_config(CHECKPOINTER="sqlite"))

    def test_production_configuration_accepts_safe_baseline(self):
        self.assertEqual(validate_runtime_config(_production_config()), [])

    def test_secure_runtime_requires_dedicated_worker_and_safe_heartbeat(self):
        with self.assertRaisesRegex(ValueError, "API_DRAIN_JOBS"):
            validate_runtime_config(_production_config(API_DRAIN_JOBS=True))
        with self.assertRaisesRegex(ValueError, "HEARTBEAT"):
            validate_runtime_config(_production_config(
                JOB_LEASE_SECONDS=60,
                JOB_HEARTBEAT_INTERVAL_SECONDS=30,
            ))
        with self.assertRaisesRegex(ValueError, "WORKER_HEARTBEAT_STALE_SECONDS"):
            validate_runtime_config(_production_config(
                WORKER_POLL_INTERVAL_SECONDS=1,
                WORKER_HEARTBEAT_STALE_SECONDS=2,
            ))

    def test_production_rejects_basic_review_auth_and_shared_session_secret(self):
        with self.assertRaisesRegex(ValueError, "REVIEW_AUTH_MODE"):
            validate_runtime_config(_production_config(REVIEW_AUTH_MODE="basic"))
        with self.assertRaisesRegex(ValueError, "must differ"):
            validate_runtime_config(_production_config(
                REVIEW_SESSION_SECRET="x" * 40,
                REVIEW_CSRF_SECRET="x" * 40,
            ))

    def test_production_requires_enforceable_model_cost_budget(self):
        with self.assertRaisesRegex(
            ValueError, "LLM_MAX_COST_USD_PER_INCIDENT"
        ):
            validate_runtime_config(_production_config(
                LLM_MAX_COST_USD_PER_INCIDENT=0,
            ))
        with self.assertRaisesRegex(
            ValueError, "LLM_INPUT_USD_PER_MILLION_TOKENS"
        ):
            validate_runtime_config(_production_config(
                LLM_INPUT_USD_PER_MILLION_TOKENS=0,
            ))

    def test_production_accepts_cloudwatch_without_loki_or_prometheus_urls(self):
        config = _production_config(
            LOG_SOURCE="cloudwatch",
            METRIC_SOURCE="cloudwatch",
            LOKI_URL="",
            PROMETHEUS_URL="",
            CLOUDWATCH_REGION="eu-north-1",
            CLOUDWATCH_SOURCE_MAP_PATH="config/cloudwatch_sources.yaml",
        )
        self.assertEqual(validate_runtime_config(config), [])

    def test_production_cloudwatch_requires_region_and_source_map(self):
        with self.assertRaisesRegex(ValueError, "CLOUDWATCH_REGION"):
            validate_runtime_config(_production_config(
                LOG_SOURCE="cloudwatch",
                CLOUDWATCH_REGION="",
                CLOUDWATCH_SOURCE_MAP_PATH="",
            ))

    def test_shadow_rejects_mock_sources_and_external_publishing(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "LOKI_URL",
        ):
            validate_runtime_config(
                _production_config(
                    ENVIRONMENT="shadow",
                    LOKI_URL="",
                )
            )
        with self.assertRaisesRegex(
            ValueError,
            "external publishing",
        ):
            validate_runtime_config(
                _production_config(
                    ENVIRONMENT="shadow",
                    PUBLISH_EXTERNAL=True,
                )
            )

    def test_production_external_publishing_requires_guarded_provider_config(self):
        with self.assertRaisesRegex(ValueError, "SLACK_WEBHOOK_URL"):
            validate_runtime_config(
                _production_config(PUBLISH_EXTERNAL=True)
            )

        config = _production_config(
            PUBLISH_EXTERNAL=True,
            SLACK_WEBHOOK_URL="https://hooks.slack.example/services/test",
            SLACK_CHANNEL="#incident-review",
            EGRESS_ALLOWED_HOSTS={
                *_production_config().EGRESS_ALLOWED_HOSTS,
                "hooks.slack.example",
            },
        )
        self.assertEqual(validate_runtime_config(config), [])

    def test_unknown_runtime_mode_fails_closed(
        self,
    ):
        with self.assertRaisesRegex(
            ValueError,
            "Unsupported runtime",
        ):
            validate_runtime_config(
                _production_config(
                    ENVIRONMENT="prod-ish",
                )
            )

    def test_phoenix_tracing_is_local_only(
        self,
    ):
        with patch.object(
            observability,
            "ENVIRONMENT",
            "shadow",
        ), patch.dict(
            "os.environ",
            {"PHOENIX_ENABLED": "true"},
        ), patch(
            "builtins.__import__",
            side_effect=AssertionError(
                "instrumentation import attempted"
            ),
        ):
            observability._INITIALIZED = (
                False
            )
            observability.init_tracing()
        self.assertFalse(
            observability._INITIALIZED
        )

    def test_log_schema_redacts_nested_secret(self):
        record = build_log_event(
            "review_submitted", incident_id="INC-1", token="secret-value",
            nested={"email": "person@example.test"},
        )
        self.assertEqual(record["schema_version"], "incident-log-event/v1")
        self.assertNotIn("secret-value", str(record))
        self.assertNotIn("person@example.test", str(record))

    def test_review_approval_must_reference_saved_candidate(self):
        pending = {"deterministic_assessment": {"candidates": [{"rank": 2}]}}
        with self.assertRaises(ReviewRequestError):
            _review_resume_payload({"status": "approved", "chosen_hypothesis": 1}, pending)
        self.assertEqual(
            _review_resume_payload({"status": "approved", "chosen_hypothesis": 2}, pending)["chosen_hypothesis"],
            2,
        )

    def test_request_more_evidence_is_distinct_and_requires_feedback(self):
        with self.assertRaisesRegex(
            ReviewRequestError, "requires concrete feedback"
        ):
            _review_resume_payload({
                "status": "request_more_evidence",
                "feedback": "",
            })
        payload = _review_resume_payload({
            "status": "request_more_evidence",
            "feedback": "Check the preceding database metrics.",
        })
        self.assertEqual(payload["status"], "request_more_evidence")
        self.assertEqual(
            payload["feedback"], "Check the preceding database metrics."
        )

    def test_llm_client_uses_bounded_retry_and_circuit(self):
        create = Mock(side_effect=RuntimeError("provider unavailable"))
        with patch.object(openai_client.client.responses, "create", create), \
             patch.object(openai_client, "LLM_RETRY_ATTEMPTS", 0), \
             patch.object(openai_client, "LLM_CIRCUIT_OPEN_SECONDS", 30):
            openai_client.reset_circuit()
            with self.assertRaises(openai_client.LLMProviderError):
                openai_client.create_completion("test", model="x", messages=[])
            with self.assertRaisesRegex(openai_client.LLMProviderError, "circuit is open"):
                openai_client.create_completion("test", model="x", messages=[])
        self.assertEqual(create.call_count, 1)
