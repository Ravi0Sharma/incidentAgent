import unittest
from unittest.mock import patch

from graph.nodes.enrich_groups import _related_deploys
from graph.nodes.interpret_incident import interpret_incident
from utils.candidate_contract import (
    CANDIDATE_SCHEMA_VERSION,
    validate_candidate,
)
from utils.candidate_scoring import score_candidates
from utils.interpretation_quality import enforce_interpretation_quality
from utils.llm_context import build_approved_context
from utils.stub_llm import (
    stub_interpretation,
    stub_postmortem,
    stub_rca,
)


class HypothesisContractTests(unittest.TestCase):
    def test_degraded_outputs_only_render_supported_candidates_and_gaps(self):
        candidate = {
            "title": "Database connection pool exhausted",
            "confidence_label": "high",
            "event_ids": ["log-db"],
            "evidence": [
                "rule=db-pool; event=log-db; count=72"
            ],
            "gaps": [
                "No trace confirms the causal mechanism."
            ],
            "next_verification": (
                "Inspect a representative database trace."
            ),
        }
        state = {
            "incident_id": "INC-DEGRADED",
            "severity": "SEV2",
            "alert": {"service": "payments"},
            "scope_expansion": {
                "alert_service": "payments"
            },
            "deterministic_assessment": {
                "abstain": False,
                "candidates": [candidate],
            },
        }

        interpretation = stub_interpretation(
            state
        )
        self.assertIn(
            "## Hypothesis 1: Database connection pool exhausted",
            interpretation,
        )
        self.assertNotIn(
            "## Hypothesis 2:",
            interpretation,
        )
        self.assertNotIn("%", interpretation)
        self.assertIn(
            "Root cause is not established",
            interpretation,
        )

        rca = stub_rca(state, 1)
        postmortem = stub_postmortem(
            state, 1
        )
        combined = (
            interpretation
            + rca
            + postmortem
        ).lower()
        for unsupported in (
            "traffic spike",
            "upstream dependency degradation",
            "auto-rollback",
            "load-mirroring",
            "lacks a canary",
        ):
            self.assertNotIn(
                unsupported,
                combined,
            )
        self.assertIn(
            "not established",
            rca.lower(),
        )
        self.assertIn(
            "not established",
            postmortem.lower(),
        )

    def test_approved_context_preserves_volume_but_bounds_detail(self):
        candidate = {
            "id": "candidate-log-db",
            "rank": 1,
            "title": "Database timeout",
            "event_ids": ["log-db"],
            "evidence": [
                "event=log-db; count=5000000"
            ],
            "gaps": ["Trace missing."],
            "next_verification": "Inspect trace.",
        }
        state = {
            "incident_id": "INC-HIGH-VOLUME",
            "raw_log_count": 5_000_000,
            "deterministic_assessment": {
                "candidates": [candidate],
            },
            "timeline": [
                {
                    "event_id": f"event-{index}",
                    "type": "log_group",
                    "timestamp": (
                        "2026-07-22T12:00:00Z"
                    ),
                }
                for index in range(100)
            ],
            "metrics": [
                {
                    "event_id": f"metric-{index}",
                    "metric": "error_rate",
                    "value": index,
                }
                for index in range(100)
            ],
            "deploys": [
                {
                    "event_id": f"deploy-{index}",
                    "commit": f"sha-{index}",
                }
                for index in range(100)
            ],
            "data_quality": {
                "logs": {
                    "group_counts_are_exact": True,
                    "possibly_truncated": False,
                }
            },
        }

        context = build_approved_context(
            state, 1
        )
        self.assertEqual(
            context["volume"]["raw_log_count"],
            5_000_000,
        )
        self.assertEqual(
            len(context["timeline"]),
            5,
        )
        self.assertEqual(
            len(context["metrics"]),
            3,
        )
        self.assertEqual(
            len(context["deploys"]),
            2,
        )

    def test_deterministic_candidates_are_typed_and_not_root_cause_claims(self):
        assessment = score_candidates(
            {
                "log_groups": [
                    {
                        "event_id": "log-db",
                        "count": 42,
                        "first_seen": "2026-07-21T10:00:00Z",
                        "labels": {
                            "level": "error",
                            "error_type": "db_timeout",
                        },
                        "related_deploys": [],
                        "dimensions": {},
                    }
                ],
                "detections": [
                    {
                        "id": "db-timeout",
                        "title": "Database timeout",
                        "category": "dependency_failure",
                        "level": "high",
                        "event_id": "log-db",
                        "group_count": 42,
                    }
                ],
                "incident_features": {"source_failures": []},
                "anchor_event": {"timestamp": "2026-07-21T10:05:00Z"},
            }
        )

        candidate = assessment["candidates"][0]
        self.assertEqual(
            assessment["candidate_schema_version"],
            CANDIDATE_SCHEMA_VERSION,
        )
        self.assertEqual(candidate["rank"], 1)
        self.assertEqual(candidate["claim_type"], "hypothesis_candidate")
        self.assertEqual(candidate["causal_status"], "requires_verification")
        self.assertIsNone(candidate["mechanism"])
        self.assertIsNone(candidate["impact_link"])
        self.assertEqual(validate_candidate(candidate), candidate)

    def test_candidate_contract_rejects_unverified_root_cause_claim(self):
        candidate = {
            "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
            "id": "candidate-1",
            "rank": 1,
            "title": "Database timeout",
            "cause": "Database timeout",
            "category": "dependency_failure",
            "claim_type": "hypothesis_candidate",
            "causal_status": "verified_root_cause",
            "mechanism": None,
            "impact_link": None,
            "score": 80,
            "confidence": 80,
            "event_ids": ["log-db"],
            "reasons": ["rule matched"],
            "evidence": ["event=log-db"],
            "supporting_evidence": ["event=log-db"],
            "weaknesses": [],
            "contradicting_evidence": [],
            "assumptions": ["requires verification"],
            "gaps": [],
            "verification": "Inspect trace.",
            "next_verification": "Inspect trace.",
        }
        with self.assertRaises(ValueError):
            validate_candidate(candidate)

    def test_deploy_correlation_requires_preceding_matching_service(self):
        related = _related_deploys(
            "2026-07-21T10:10:00Z",
            [
                {
                    "time": "2026-07-21T10:05:00Z",
                    "commit": "before-same-service",
                    "environment": "payments",
                },
                {
                    "time": "2026-07-21T10:05:00Z",
                    "commit": "before-other-service",
                    "environment": "catalog",
                },
                {
                    "time": "2026-07-21T10:11:00Z",
                    "commit": "after-error",
                    "environment": "payments",
                },
            ],
            service="payments",
        )

        self.assertEqual(
            [item["commit"] for item in related],
            ["before-same-service"],
        )

    def test_missing_or_tied_evidence_abstains_before_model_call(self):
        assessment = score_candidates(
            {
                "log_groups": [],
                "detections": [],
                "incident_features": {"source_failures": ["loki"]},
            }
        )
        result = interpret_incident(
            {
                "deterministic_assessment": assessment,
                "incident_window": {"start": "2026-07-21T10:00:00Z"},
            }
        )
        self.assertTrue(assessment["abstain"])
        self.assertIn("No supported root cause yet", result["interpretation"])
        self.assertTrue(result["interpretation_quality"]["abstained"])

    def test_unsupported_generated_output_is_replaced_with_safe_abstention(self):
        text, quality = enforce_interpretation_quality(
            "The root cause is definitely a deployment. Restart production now.",
            {"evidence_graph": {"nodes": [{"event_id": "log-1"}]}},
        )
        self.assertIn("No supported root cause yet", text)
        self.assertTrue(quality["enforced_abstention"])

    def test_local_model_format_miss_rebuilds_grounded_interpretation(self):
        state = {
            "deterministic_assessment": {
                "abstain": False,
                "candidates": [{"title": "Database connection pool exhausted"}],
            },
            "detections": [
                {
                    "id": "db-pool-exhausted",
                    "title": "Database connection pool exhausted",
                    "event_id": "log-db",
                }
            ],
            "log_groups": [
                {
                    "event_id": "log-db",
                    "count": 72,
                    "labels": {"service": "payments", "level": "error"},
                }
            ],
            "evidence_graph": {"nodes": [{"event_id": "log-db"}]},
            "anchor_event": {"timestamp": "2026-07-22T12:00:00Z"},
        }
        malformed = (
            "Database connection pool exhaustion is most likely because "
            "detection db-pool-exhausted matched log-db."
        )

        with patch(
            "utils.interpretation_quality.LOCAL_LLM_FORMAT_FALLBACK",
            True,
        ):
            text, quality = enforce_interpretation_quality(malformed, state)

        self.assertIn("## Hypothesis 1:", text)
        self.assertNotIn("No supported root cause yet", text)
        self.assertTrue(quality["format_fallback"])
        self.assertTrue(quality["local_only"])

    def test_local_format_fallback_does_not_override_evidence_abstention(self):
        state = {
            "deterministic_assessment": {
                "abstain": True,
                "candidates": [{"title": "Ambiguous candidate"}],
            },
            "evidence_graph": {"nodes": [{"event_id": "log-1"}]},
        }

        with patch(
            "utils.interpretation_quality.LOCAL_LLM_FORMAT_FALLBACK",
            True,
        ):
            text, quality = enforce_interpretation_quality(
                "Possibly related to log-1.",
                state,
            )

        self.assertIn("No supported root cause yet", text)
        self.assertTrue(quality["enforced_abstention"])
