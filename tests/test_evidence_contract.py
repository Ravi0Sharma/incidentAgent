import json
import unittest

from utils.log_normalizer import (
    CANONICAL_LOG_SCHEMA_VERSION,
    normalize_log,
)
from webhook.grafana import normalize_grafana_alert
from utils.redaction import redact_data


class EvidenceContractTests(unittest.TestCase):
    def test_recursive_redaction_is_idempotent_across_multiple_sinks(self):
        value = {
            "api_key": "raw-api-key",
            "nested": {
                "customer_id": "customer-123",
                "message": "token=raw-token",
            },
        }
        once = redact_data(value)
        twice = redact_data(once)

        self.assertEqual(once, twice)
        self.assertNotIn("raw-", json.dumps(twice, sort_keys=True))

    def test_alert_annotations_and_url_are_recursively_redacted(self):
        alert = {
            "labels": {
                "service": "payments",
                "customer_email": "customer@example.com",
            },
            "annotations": {
                "summary": "token=raw-token email=person@example.com",
                "nested": {
                    "api_key": "raw-api-key",
                    "customer_id": "customer-123",
                    "notes": ["Bearer raw-bearer-token"],
                },
            },
            "generatorURL": "https://grafana.example.test/d/1?token=raw-url-token",
        }

        normalized = normalize_grafana_alert(alert)
        serialized = json.dumps(normalized, sort_keys=True)

        for secret in (
            "raw-token",
            "person@example.com",
            "raw-api-key",
            "customer-123",
            "raw-bearer-token",
            "raw-url-token",
        ):
            self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertIn("redacted-", serialized)

    def test_normalized_log_has_versioned_canonical_schema(self):
        normalized = normalize_log(
            {
                "timestamp": "2026-07-21T10:00:00Z",
                "message": "failed token=raw-log-token",
                "labels": {
                    "service": "payments",
                    "severity": "ERROR",
                    "user_email": "person@example.com",
                },
            }
        )

        self.assertEqual(
            normalized["evidence_schema_version"],
            CANONICAL_LOG_SCHEMA_VERSION,
        )
        self.assertEqual(normalized["labels"]["service"], "payments")
        self.assertEqual(normalized["labels"]["level"], "error")
        self.assertNotIn("raw-log-token", normalized["message"])
        self.assertNotIn(
            "person@example.com",
            json.dumps(normalized, sort_keys=True),
        )
