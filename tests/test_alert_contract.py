import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import unittest
import uuid
from unittest.mock import patch

from webhook import api
from webhook.alert_contract import (
    ALERT_CONTRACT_VERSION,
    AlertContractError,
    validate_alert_payload,
)
from webhook import intake_stats
from webhook import replay
from webhook import rate_limit


def _alert(**overrides):
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "HighPaymentLatency",
            "service": "payments",
        },
        "annotations": {"summary": "Latency is high"},
        "startsAt": "2026-07-21T10:00:00Z",
    }
    alert.update(overrides)
    return alert


def _validate(payload, **overrides):
    return validate_alert_payload(
        payload,
        max_alerts=overrides.get("max_alerts", 2),
        max_labels=overrides.get("max_labels", 2),
        max_annotations=overrides.get("max_annotations", 2),
        max_field_length=overrides.get("max_field_length", 32),
    )


class _Request:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    async def body(self):
        return self._body


class AlertContractTests(unittest.TestCase):
    def setUp(self):
        intake_stats.reset_for_tests()
        replay.reset_for_tests()
        rate_limit.reset_for_tests()

    def test_contract_version_is_explicit(self):
        self.assertEqual(ALERT_CONTRACT_VERSION, "grafana-alertmanager/v1")

    def test_single_and_batch_alerts_are_accepted(self):
        self.assertEqual(_validate(_alert()), [_alert()])
        batch = {"alerts": [_alert(), _alert(fingerprint="second")]}
        self.assertEqual(_validate(batch), batch["alerts"])

    def test_alert_contract_rejects_invalid_shapes_and_boundaries(self):
        cases = [
            ([], "invalid_payload"),
            ({"alerts": "not-a-list"}, "invalid_alerts"),
            ({"alerts": []}, "empty_alerts"),
            ({"alerts": [_alert(), _alert(), _alert()]}, "too_many_alerts"),
            (_alert(labels={"service": "payments", "a": "1", "b": "2"}), "too_many_fields"),
            (_alert(status="unknown"), "invalid_status"),
            (_alert(startsAt="not-a-timestamp"), "invalid_timestamp"),
            (_alert(labels={}, annotations={}, service="", alertname=""), "missing_identity"),
            (_alert(service=7), "invalid_field_type"),
            (_alert(message="x" * 33), "field_too_long"),
        ]
        for payload, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(AlertContractError) as caught:
                    _validate(payload)
                self.assertEqual(caught.exception.code, code)

    def test_support_matrix_rejects_unknown_service_and_environment(self):
        kwargs = {
            "max_alerts": 2,
            "max_labels": 2,
            "max_annotations": 2,
            "max_field_length": 32,
            "supported_services": {"payments"},
            "supported_environments": {"staging"},
            "default_environment": "staging",
        }
        with self.assertRaisesRegex(AlertContractError, "service") as caught:
            validate_alert_payload(_alert(service="unknown-service"), **kwargs)
        self.assertEqual(caught.exception.code, "unsupported_service")
        with self.assertRaisesRegex(AlertContractError, "environment") as caught:
            validate_alert_payload(_alert(labels={"service": "payments", "environment": "dev"}), **kwargs)
        self.assertEqual(caught.exception.code, "unsupported_environment")

    def test_production_signature_binds_timestamp_and_nonce_and_rejects_replay(self):
        body = b'{"labels":{"service":"payments"}}'
        timestamp = datetime.now(timezone.utc).isoformat()
        nonce = "nonce-" + uuid.uuid4().hex
        signed = timestamp.encode() + b"." + nonce.encode() + b"." + body
        signature = "sha256=" + hmac.new(
            b"test-secret", signed, hashlib.sha256
        ).hexdigest()
        request = _Request(body, {
            "x-incident-timestamp": timestamp,
            "x-incident-nonce": nonce,
            "x-incident-signature": signature,
        })
        with (
            patch.object(api, "ENVIRONMENT", "production"),
            patch.object(api, "WEBHOOK_SHARED_SECRET", "test-secret"),
        ):
            self.assertTrue(api._valid_webhook_signature(request, body))
            api._validate_webhook_replay(request)
            with self.assertRaisesRegex(replay.ReplayError, "already used"):
                api._validate_webhook_replay(request)

    def test_rate_limiter_bounds_caller_and_recovers_after_window(self):
        self.assertEqual(rate_limit.allow("caller", 2, 10, now=0), (True, 0))
        self.assertEqual(rate_limit.allow("caller", 2, 10, now=1), (True, 0))
        allowed, retry_after = rate_limit.allow("caller", 2, 10, now=2)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        self.assertEqual(rate_limit.allow("caller", 2, 10, now=10), (True, 0))

    def test_body_limit_returns_413_before_body_is_read(self):
        request = _Request(
            b"ignored",
            headers={"content-length": "11"},
        )
        with patch.object(api, "MAX_WEBHOOK_BODY_BYTES", 10):
            response = asyncio.run(api.alerts(request))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(intake_stats.rejection_count("body_too_large"), 1)

    def test_body_without_content_length_is_still_limited(self):
        request = _Request(b"x" * 11)
        with patch.object(api, "MAX_WEBHOOK_BODY_BYTES", 10):
            response = asyncio.run(api.alerts(request))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(intake_stats.rejection_count("body_too_large"), 1)

    def test_invalid_contract_is_rejected_before_workflow_invocation(self):
        request = _Request(json.dumps({"alerts": []}).encode("utf-8"))
        with patch.object(api, "_run_normalized_alert") as run_workflow:
            response = asyncio.run(api.alerts(request))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(run_workflow.call_count, 0)
        self.assertEqual(intake_stats.rejection_count("empty_alerts"), 1)

    def test_batch_limit_returns_413_before_workflow_invocation(self):
        request = _Request(
            json.dumps({"alerts": [_alert(), _alert()]}).encode("utf-8")
        )
        with (
            patch.object(api, "MAX_ALERTS_PER_REQUEST", 1),
            patch.object(api, "_run_normalized_alert") as run_workflow,
        ):
            response = asyncio.run(api.alerts(request))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(run_workflow.call_count, 0)
        self.assertEqual(intake_stats.rejection_count("too_many_alerts"), 1)
