import unittest
import uuid

from utils.audit import list_audit_events, record_audit_event
from utils.logging import build_log_event
from utils.metrics import increment, observe, prometheus_text, reset_for_tests
from utils.redaction import redact_data
from webhook.worker import TerminalJobError, is_retryable_failure
from webhook.views import render_hypothesis


class SecurityAndObservabilityTests(unittest.TestCase):
    def setUp(self):
        reset_for_tests()

    def test_recursive_redaction_covers_nested_payload_and_message_values(self):
        cleaned = redact_data({
            "outer": [{"api_token": "super-secret"}],
            "message": "contact person@example.test with Bearer abc.def",
            "url": "https://example.test/?email=person@example.test",
        })
        rendered = str(cleaned)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("person@example.test", rendered)
        self.assertNotIn("abc.def", rendered)

    def test_reviewer_hypothesis_text_is_not_client_side_markdown(self):
        html = render_hypothesis({
            "rank": 1,
            "confidence": "high",
            "title": "<img src=x onerror=alert(1)>",
            "body": "Evidence:\n<script>alert(1)</script>",
        })
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("onerror=alert(1)>", html)
        self.assertIn("<pre class='sub-body'>", html)

    def test_metrics_use_bounded_explicit_labels_and_prometheus_text(self):
        increment("alerts", outcome="accepted")
        observe("job_duration_seconds", 0.25, kind="analyze", outcome="completed")
        output = prometheus_text()
        self.assertIn('incident_agent_alerts_total{outcome="accepted"} 1', output)
        self.assertIn('incident_agent_job_duration_seconds_count{kind="analyze",outcome="completed"} 1', output)
        self.assertIn('incident_agent_job_duration_seconds_sum{kind="analyze",outcome="completed"} 0.25', output)

    def test_log_schema_contains_service_version_and_redacts_details(self):
        event = build_log_event("worker", token="top-secret")
        self.assertIn("service_version", event)
        self.assertNotIn("top-secret", str(event))

    def test_audit_event_is_redacted_and_readable_from_mysql(self):
        incident_id = "INC-AUDIT-" + uuid.uuid4().hex[:16]
        record_audit_event("test_audit", incident_id, token="top-secret", feedback="person@example.test")
        events = list_audit_events(incident_id)
        self.assertEqual(events[0]["event_type"], "test_audit")
        self.assertNotIn("top-secret", str(events[0]))
        self.assertNotIn("person@example.test", str(events[0]))

    def test_invalid_and_authorization_worker_failures_are_terminal(self):
        self.assertFalse(is_retryable_failure(TerminalJobError("invalid state")))
        self.assertFalse(is_retryable_failure(PermissionError("forbidden")))
        self.assertFalse(is_retryable_failure(ValueError("invalid input")))
        self.assertTrue(is_retryable_failure(RuntimeError("temporary database outage")))
