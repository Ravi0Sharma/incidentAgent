import importlib
import unittest
from unittest.mock import patch

from graph.nodes.classify_severity import classify_severity
from webhook.interpretation import (
    clean_meta,
    dedup_hypotheses,
    parse_confidence,
    parse_interpretation,
    promote_sublabels,
    score_hypothesis,
    split_hypothesis_body,
)


severity_module = importlib.import_module("graph.nodes.classify_severity")
scope_module = importlib.import_module("graph.nodes.scope_expansion")


class SeverityDecisionTests(unittest.TestCase):
    def test_tier_and_alert_matrix_covers_each_severity_policy(self):
        scenarios = [
            (0, True, "critical", "SEV2", "critical alert"),
            (0, True, "warning", "SEV2", "warning-level"),
            (1, True, "error", "SEV2", "critical alert"),
            (1, True, "warn", "SEV3", "warning-level"),
            (2, True, "high", "SEV3", "customer-facing"),
            (3, False, "critical", "SEV4", "Internal service"),
            (2, False, "info", "SEV4", "Low-impact"),
        ]

        for tier, customer_facing, alert_level, expected, reason in scenarios:
            with self.subTest(
                tier=tier,
                customer_facing=customer_facing,
                alert_level=alert_level,
            ), patch.object(
                severity_module,
                "get_service",
                return_value={
                    "tier": tier,
                    "customer_facing": customer_facing,
                    "owner": "test-owner",
                    "runbook": "https://runbooks.example.test/service",
                    "description": "test service",
                },
            ):
                result = classify_severity({
                    "alert": {
                        "service": "checkout",
                        "severity": alert_level,
                    }
                })

            self.assertEqual(result["severity"], expected)
            self.assertIn(reason, result["severity_reason"])
            self.assertEqual(result["business_context"]["tier"], tier)
            self.assertEqual(
                result["impact"]["estimated_scope"],
                "external customers" if customer_facing else "internal users",
            )

    def test_labels_and_unknown_severity_use_safe_low_impact_default(self):
        with patch.object(
            severity_module,
            "get_service",
            return_value={
                "tier": 2,
                "customer_facing": False,
                "owner": "unknown",
            },
        ) as get_service:
            result = classify_severity({
                "alert": {
                    "labels": {
                        "service": "batch-worker",
                        "severity": 500,
                    }
                }
            })

        get_service.assert_called_once_with("batch-worker")
        self.assertEqual(result["severity"], "SEV4")
        self.assertIsNone(result["business_context"]["runbook"])
        self.assertEqual(result["business_context"]["description"], "")


class ScopeExpansionDecisionTests(unittest.TestCase):
    @staticmethod
    def _service(name):
        return {
            "owner": f"owner-{name}",
            "tier": 1,
            "customer_facing": True,
            "runbook": f"https://runbooks.example.test/{name}",
        }

    def test_scope_combines_observed_configured_and_discovered_services(self):
        dependencies = {
            "payments": ["checkout", "auth"],
            "checkout": ["catalog"],
        }
        state = {
            "alert": {
                "service": "payments",
                "labels": {
                    "service": "payments",
                    "namespace": "commerce",
                    "cluster": "prod-1",
                    "ignored": "not-forwarded",
                },
            },
            "log_groups": [
                {"labels": {"service": "checkout"}},
                {"labels": {"service": "payments"}},
                {"labels": {}},
            ],
            "pivots": {
                "trace_id": [f"trace-{index}" for index in range(8)],
                "request_id": ["request-1"],
            },
            "incident_window": {"start": "2026-08-09T10:00:00Z"},
        }

        with patch.object(
            scope_module,
            "dependencies_for",
            side_effect=lambda name: dependencies.get(name, []),
        ), patch.object(
            scope_module,
            "related_services",
            return_value=["billing-batch", "auth"],
        ), patch.object(
            scope_module,
            "get_service",
            side_effect=self._service,
        ), patch.object(
            scope_module.loki,
            "discover_services",
            return_value=[
                {"service": "search"},
                {"service": "auth"},
                {"service": ""},
            ],
        ):
            result = scope_module.scope_expansion(state)["scope_expansion"]

        self.assertEqual(
            result["services"],
            ["payments", "checkout", "auth", "billing-batch", "search"],
        )
        self.assertEqual(result["service_depths"]["payments"], 0)
        self.assertEqual(
            result["service_reasons"]["checkout"],
            "observed in grouped logs",
        )
        self.assertEqual(len(result["trace_ids"]), 5)
        self.assertEqual(
            result["environment_labels"],
            {"namespace": "commerce", "cluster": "prod-1"},
        )
        checkout = next(
            item for item in result["service_summaries"]
            if item["service"] == "checkout"
        )
        self.assertEqual(checkout["dependencies"], ["catalog"])

    def test_discovery_failure_is_explicit_and_does_not_expand_scope(self):
        state = {
            "business_context": {"service": "catalog"},
            "alert": {"labels": {"service": "ignored-alert-service"}},
        }
        with patch.object(
            scope_module,
            "dependencies_for",
            return_value=[],
        ), patch.object(
            scope_module,
            "related_services",
            return_value=[],
        ), patch.object(
            scope_module,
            "get_service",
            side_effect=self._service,
        ), patch.object(
            scope_module.loki,
            "discover_services",
            side_effect=RuntimeError("loki unavailable"),
        ):
            result = scope_module.scope_expansion(state)["scope_expansion"]

        self.assertEqual(result["services"], ["catalog"])
        self.assertEqual(
            result["discovered_services"],
            [{"error": "loki unavailable"}],
        )
        self.assertEqual(result["window"], {})

    def test_scope_limit_is_enforced_after_deduplication(self):
        state = {
            "alert": {"labels": {}},
            "log_groups": [
                {"labels": {"service": "observed-a"}},
                {"labels": {"service": "observed-b"}},
            ],
        }
        with patch.object(
            scope_module,
            "MAX_SCOPE_SERVICES",
            2,
        ), patch.object(
            scope_module,
            "dependencies_for",
            return_value=["dependency-a"],
        ), patch.object(
            scope_module,
            "related_services",
            return_value=["related-a"],
        ), patch.object(
            scope_module,
            "get_service",
            side_effect=self._service,
        ), patch.object(
            scope_module.loki,
            "discover_services",
            return_value=[{"service": "discovered-a"}],
        ):
            result = scope_module.scope_expansion(state)["scope_expansion"]

        self.assertEqual(result["alert_service"], "unknown")
        self.assertEqual(result["services"], ["unknown", "observed-a"])
        self.assertEqual(result["scope_limit"], 2)


class InterpretationParsingTests(unittest.TestCase):
    def test_clean_meta_removes_reasoning_notes_but_preserves_findings(self):
        text = "\n".join([
            "*Wait, need to refine this*",
            "Root cause is not established.",
            "- Check word count",
            "\n",
            "Evidence remains incomplete.",
        ])
        self.assertEqual(
            clean_meta(text),
            "Root cause is not established.\n\nEvidence remains incomplete.",
        )
        self.assertEqual(clean_meta(""), "")

    def test_promote_sublabels_handles_plain_and_bold_labels(self):
        body = "Evidence:\nlog-1\n**Correlation:**\nclose in time\nWeaknesses:\nno trace"
        promoted = promote_sublabels(body)
        self.assertIn("#### Evidence", promoted)
        self.assertIn("#### Correlation", promoted)
        self.assertIn("#### Weaknesses", promoted)
        self.assertEqual(promote_sublabels(""), "")

    def test_parse_confidence_accepts_supported_formats_and_rejects_missing(self):
        self.assertEqual(parse_confidence("Confidence: High 91%"), ("High", "91"))
        self.assertEqual(parse_confidence("(Medium confidence, ~63%)"), ("Medium", "63"))
        self.assertEqual(parse_confidence("Low confidence around 20"), ("Low", "20"))
        self.assertEqual(parse_confidence("No confidence label"), (None, None))
        self.assertEqual(parse_confidence(""), (None, None))

    def test_split_hypothesis_body_separates_evidence_and_unknown_preamble(self):
        parsed = split_hypothesis_body(
            "Context before sections\nEvidence:\nlog-1\n---\n"
            "Correlation:\nSame trace\nWeaknesses:\nNo metric"
        )
        self.assertEqual(parsed["other"], "Context before sections")
        self.assertEqual(parsed["evidence"], "log-1")
        self.assertEqual(parsed["correlation"], "Same trace")
        self.assertEqual(parsed["weaknesses"], "No metric")
        self.assertEqual(
            split_hypothesis_body("Unstructured but useful")["other"],
            "Unstructured but useful",
        )
        self.assertEqual(split_hypothesis_body(""), {
            "evidence": "",
            "correlation": "",
            "weaknesses": "",
            "other": "",
        })

    def test_hypothesis_dedup_keeps_the_richer_duplicate(self):
        weak = {"num": "1", "title": "Timeout", "body": "brief", "confidence": None}
        rich = {
            "num": "1",
            "title": "Database connection timeout after pool saturation",
            "body": "Evidence:\nlog-1\nCorrelation:\ntrace-1",
            "confidence": "High",
        }
        second = {"num": "2", "title": "Deploy regression", "body": "details"}

        result = dedup_hypotheses([weak, second, rich])

        self.assertEqual(result, [rich, second])
        self.assertGreater(score_hypothesis(rich), score_hypothesis(weak))

    def test_markdown_interpretation_extracts_review_sections(self):
        parsed = parse_interpretation("""
# TL;DR
Errors increased, but the root cause is not established.

## Hypothesis 1: Database pool saturation
Confidence: High 88%
Evidence:
log-db
---
Weaknesses:
No database metric.

## Blast radius
Checkout requests may be affected.

## Next steps
Inspect database pool metrics.
""")

        self.assertIn("root cause is not established", parsed["tldr"])
        self.assertEqual(len(parsed["hypotheses"]), 1)
        self.assertEqual(parsed["hypotheses"][0]["num"], "1")
        self.assertEqual(parsed["hypotheses"][0]["confidence"], "High")
        self.assertEqual(parsed["hypotheses"][0]["pct"], "88")
        self.assertNotIn("Confidence:", parsed["hypotheses"][0]["body"])
        self.assertIn("Checkout", parsed["blast_radius"])
        self.assertIn("pool metrics", parsed["next_steps"])

    def test_inline_interpretation_extracts_multiple_hypotheses(self):
        parsed = parse_interpretation("""
Hypothesis 1 (Medium, 60%): Queue backlog
Evidence:
log-queue
Correlation:
Errors follow queue growth.

Hypothesis 2 - Upstream timeout (Low confidence 25%)
Weaknesses:
No upstream trace.
""")

        self.assertEqual([item["num"] for item in parsed["hypotheses"]], ["1", "2"])
        self.assertEqual(parsed["hypotheses"][0]["confidence"], "Medium")
        self.assertEqual(parsed["hypotheses"][0]["pct"], "60")
        self.assertEqual(parsed["hypotheses"][1]["confidence"], "Low")
        self.assertEqual(parsed["hypotheses"][1]["pct"], "25")

    def test_empty_interpretation_is_safe(self):
        self.assertEqual(parse_interpretation("")["hypotheses"], [])


if __name__ == "__main__":
    unittest.main()
