import json
import unittest
from unittest.mock import patch

from graph.nodes.interpret_incident import interpret_incident
from utils.interpretation_contract import (
    INTERPRETATION_SCHEMA_VERSION,
    render_grounded_interpretation,
    validate_and_ground,
)


def _state():
    return {
        "deterministic_assessment": {
            "abstain": False,
            "candidates": [{
                "id": "candidate-log-db",
                "rank": 1,
                "title": "Database connection pool exhausted",
                "cause": "Database connection pool exhausted",
                "confidence_label": "high",
                "event_ids": ["log-db"],
                "supporting_evidence": [
                    "event=log-db; rule=db-pool; count=72"
                ],
                "assumptions": [
                    "Root cause is not established."
                ],
                "gaps": ["Database saturation metric is missing."],
                "next_verification": "Inspect active database connections.",
            }],
        },
        "evidence_graph": {
            "nodes": [
                {"event_id": "log-db", "type": "log_group"},
                {"event_id": "metric-db", "type": "metric"},
            ],
        },
        "scope_expansion": {
            "services": ["payments", "orders"],
        },
        "source_status": {},
        "data_quality": {"logs": {"possibly_truncated": False}},
        "semantic_correlation": {"primary_chain": []},
        "investigation_budget": {
            "max_remote_units": 0,
            "used_remote_units": 0,
        },
    }


def _payload():
    return {
        "schema_version": INTERPRETATION_SCHEMA_VERSION,
        "status": "supported",
        "tldr": "A deployment definitely caused everything.",
        "hypotheses": [{
            "rank": 1,
            "title": "Invented root cause title",
            "confidence": "high",
            "supporting_evidence_ids": ["log-db"],
            "contradicting_evidence_ids": [],
            "cause_claim": {
                "text": "The pool failure is the root cause.",
                "status": "observed",
                "evidence_ids": ["log-db"],
            },
            "mechanism_claim": {
                "text": "Requests crossed into orders and exhausted the pool.",
                "status": "observed",
                "evidence_ids": ["log-db"],
            },
            "impact_claim": {
                "text": "All users were affected.",
                "status": "observed",
                "evidence_ids": ["log-db"],
            },
            "assumptions": [],
            "gaps": ["No saturation metric."],
            "next_verification": "Inspect active database connections.",
        }],
        "blast_radius": {
            "summary": "Every service and user was affected.",
            "services": ["payments", "unknown-service"],
            "evidence_ids": ["log-db"],
        },
        "suggested_next_steps": [{
            "action": "Restart production now.",
            "action_type": "read_only",
            "evidence_ids": ["log-db"],
            "requires_approval": False,
        }],
        "evidence_gaps": [],
    }


class ClaimGroundingTests(unittest.TestCase):
    def test_model_cannot_reactivate_candidate_when_assessment_abstains(self):
        state = _state()
        state["deterministic_assessment"]["abstain"] = True
        state["deterministic_assessment"]["abstain_reasons"] = [
            "multiple competing fault categories are observed"
        ]
        validated, grounding = validate_and_ground(
            _payload(),
            state,
        )
        self.assertEqual(validated["status"], "abstained")
        self.assertEqual(validated["hypotheses"], [])
        self.assertTrue(grounding["passed"])
        self.assertTrue(grounding["abstained"])
        self.assertTrue(
            grounding["enforced_deterministic_abstention"]
        )

    def test_model_cannot_promote_correlation_to_observed_root_cause(self):
        validated, grounding = validate_and_ground(
            _payload(),
            _state(),
        )
        hypothesis = validated["hypotheses"][0]
        self.assertEqual(
            hypothesis["title"],
            "Database connection pool exhausted",
        )
        self.assertEqual(
            hypothesis["claims"]["cause"]["status"],
            "hypothesis",
        )
        self.assertEqual(
            hypothesis["claims"]["cause"]["decision"],
            "downgraded",
        )
        self.assertEqual(
            hypothesis["claims"]["mechanism"]["decision"],
            "rejected",
        )
        self.assertTrue(grounding["passed"])
        rendered = render_grounded_interpretation(
            validated,
            _state(),
        )
        self.assertNotIn(
            "A deployment definitely caused everything",
            rendered,
        )
        self.assertNotIn("Invented root cause title", rendered)

    def test_unknown_supporting_evidence_forces_abstention(self):
        payload = _payload()
        payload["hypotheses"][0]["supporting_evidence_ids"] = [
            "invented-event"
        ]
        validated, grounding = validate_and_ground(
            payload,
            _state(),
        )
        self.assertEqual(validated["status"], "abstained")
        self.assertTrue(grounding["abstained"])
        self.assertFalse(grounding["passed"])

    def test_source_failure_caps_confidence_to_low(self):
        state = _state()
        state["source_status"] = {
            "prometheus": {"status": "failed"}
        }
        validated, grounding = validate_and_ground(
            _payload(),
            state,
        )
        self.assertEqual(
            validated["hypotheses"][0]["confidence"],
            "low",
        )
        self.assertTrue(
            any(
                "source failure" in warning
                for warning in grounding["warnings"]
            )
        )

    def test_unsafe_action_without_approval_is_removed(self):
        validated, grounding = validate_and_ground(
            _payload(),
            _state(),
        )
        actions = [
            item["action"]
            for item in validated["suggested_next_steps"]
        ]
        self.assertNotIn("Restart production now.", actions)
        self.assertTrue(
            any(
                "risky or unknown next step removed" in warning
                for warning in grounding["warnings"]
            )
        )

    def test_mutating_action_requires_explicit_proposal_and_approval(self):
        payload = _payload()
        payload["suggested_next_steps"] = [
            {
                "action": "Scale production to 20 replicas.",
                "action_type": "read_only",
                "evidence_ids": ["log-db"],
                "requires_approval": False,
            },
            {
                "action": "Deploy a bounded canary.",
                "action_type": "proposal",
                "evidence_ids": ["log-db"],
                "requires_approval": True,
            },
        ]
        validated, grounding = validate_and_ground(payload, _state())
        self.assertEqual(
            [item["action"] for item in validated["suggested_next_steps"]],
            ["Deploy a bounded canary."],
        )
        self.assertEqual(
            validated["suggested_next_steps"][0]["action_type"],
            "proposal",
        )
        self.assertTrue(validated["suggested_next_steps"][0]["requires_approval"])
        self.assertTrue(any(
            "risky or unknown next step removed" in warning
            for warning in grounding["warnings"]
        ))

    def test_executed_action_claim_is_removed_even_when_marked_proposal(self):
        payload = _payload()
        payload["suggested_next_steps"] = [{
            "action": "Production was restarted and the issue resolved.",
            "action_type": "proposal",
            "evidence_ids": ["log-db"],
            "requires_approval": True,
        }]
        validated, grounding = validate_and_ground(payload, _state())
        self.assertNotIn(
            "Production was restarted and the issue resolved.",
            [item["action"] for item in validated["suggested_next_steps"]],
        )
        self.assertTrue(any(
            "executed-action claim" in warning
            for warning in grounding["warnings"]
        ))

    def test_unsafe_candidate_fallback_becomes_read_only_verification(self):
        state = _state()
        state["deterministic_assessment"]["candidates"][0][
            "next_verification"
        ] = "Restart production immediately."
        payload = _payload()
        payload["hypotheses"][0]["next_verification"] = (
            "Restart production immediately."
        )
        payload["suggested_next_steps"] = []
        validated, _ = validate_and_ground(payload, state)
        fallback = validated["suggested_next_steps"][0]
        self.assertEqual(fallback["action_type"], "read_only")
        self.assertFalse(fallback["requires_approval"])
        self.assertTrue(fallback["action"].startswith("Inspect the cited evidence"))

    def test_mechanism_needs_validated_cross_event_link(self):
        state = _state()
        state["deterministic_assessment"]["candidates"][0][
            "event_ids"
        ] = ["log-db", "metric-db"]
        state["semantic_correlation"] = {
            "primary_chain": [{
                "supporting_event_ids": ["log-db", "metric-db"],
                "causal_status": "not_established",
            }]
        }
        payload = _payload()
        hypothesis = payload["hypotheses"][0]
        hypothesis["supporting_evidence_ids"] = [
            "log-db",
            "metric-db",
        ]
        hypothesis["mechanism_claim"]["evidence_ids"] = [
            "log-db",
            "metric-db",
        ]
        validated, _ = validate_and_ground(payload, state)
        mechanism = validated["hypotheses"][0]["claims"]["mechanism"]
        self.assertEqual(mechanism["decision"], "downgraded")
        self.assertEqual(mechanism["status"], "inferred")

    def test_impact_claim_accepts_typed_adverse_outcome_evidence(self):
        state = _state()
        state["deterministic_assessment"]["candidates"][0][
            "adverse_outcome_event_ids"
        ] = ["metric-db"]
        payload = _payload()
        payload["hypotheses"][0]["supporting_evidence_ids"] = [
            "log-db",
            "metric-db",
        ]
        payload["hypotheses"][0]["impact_claim"]["evidence_ids"] = [
            "metric-db",
        ]
        validated, grounding = validate_and_ground(payload, state)
        impact = validated["hypotheses"][0]["claims"]["impact"]
        self.assertNotEqual(impact["decision"], "rejected")
        self.assertEqual(impact["unknown_evidence_ids"], [])
        self.assertEqual(impact["incompatible_evidence_ids"], [])
        self.assertTrue(grounding["passed"])

    def test_successful_completion_cannot_support_adverse_impact(self):
        state = _state()
        candidate = state["deterministic_assessment"]["candidates"][0]
        candidate["outcome_event_ids"] = ["metric-db"]
        candidate["successful_completion_event_ids"] = ["metric-db"]
        payload = _payload()
        payload["hypotheses"][0]["supporting_evidence_ids"] = [
            "log-db",
            "metric-db",
        ]
        payload["hypotheses"][0]["impact_claim"]["evidence_ids"] = [
            "metric-db",
        ]
        validated, grounding = validate_and_ground(payload, state)
        hypothesis = validated["hypotheses"][0]
        self.assertEqual(
            hypothesis["claims"]["impact"]["decision"],
            "rejected",
        )
        self.assertEqual(
            hypothesis["evidence_roles"]["successful_completion_context"],
            ["metric-db"],
        )
        self.assertTrue(any(
            "role-incompatible supporting evidence" in warning
            for warning in grounding["warnings"]
        ))

    def test_known_but_role_incompatible_cause_id_forces_abstention(self):
        payload = _payload()
        payload["hypotheses"][0]["supporting_evidence_ids"] = [
            "log-db",
            "metric-db",
        ]
        payload["hypotheses"][0]["cause_claim"]["evidence_ids"] = [
            "metric-db",
        ]
        validated, grounding = validate_and_ground(payload, _state())
        self.assertEqual(validated["status"], "abstained")
        self.assertFalse(grounding["passed"])
        self.assertTrue(any(
            "role-incompatible supporting evidence" in warning
            for warning in grounding["warnings"]
        ))

    def test_role_incompatible_ids_do_not_reach_review_fields(self):
        payload = _payload()
        payload["hypotheses"][0]["contradicting_evidence_ids"] = [
            "metric-db",
        ]
        payload["blast_radius"]["evidence_ids"] = ["metric-db"]
        payload["suggested_next_steps"] = [{
            "action": "Inspect the bounded database metric.",
            "action_type": "read_only",
            "evidence_ids": ["metric-db"],
            "requires_approval": False,
        }]
        validated, grounding = validate_and_ground(payload, _state())
        hypothesis = validated["hypotheses"][0]
        self.assertEqual(hypothesis["contradicting_evidence_ids"], [])
        self.assertEqual(validated["blast_radius"]["evidence_ids"], [])
        self.assertEqual(
            validated["suggested_next_steps"][0]["evidence_ids"],
            [],
        )
        self.assertEqual(
            hypothesis["evidence_roles"]["cause"],
            ["log-db"],
        )
        rendered = render_grounded_interpretation(validated, _state())
        self.assertIn("Evidence roles", rendered)
        self.assertTrue(any(
            "role-incompatible contradiction" in warning
            for warning in grounding["warnings"]
        ))

    @patch(
        "graph.nodes.interpret_incident.USE_TOOL_CALLING",
        False,
    )
    @patch(
        "graph.nodes.interpret_incident.SKIP_LLM",
        False,
    )
    @patch(
        "graph.nodes.interpret_incident._run_no_tools",
        return_value=("free-form unsupported markdown", [], []),
    )
    def test_interpret_node_abstains_on_non_json_model_output(
        self,
        _run,
    ):
        result = interpret_incident(_state())
        self.assertEqual(
            result["interpretation_structured"]["status"],
            "abstained",
        )
        self.assertTrue(result["interpretation_quality"]["abstained"])
        self.assertIn(
            "No supported root cause yet",
            result["interpretation"],
        )

    @patch(
        "graph.nodes.interpret_incident.USE_TOOL_CALLING",
        False,
    )
    @patch(
        "graph.nodes.interpret_incident.SKIP_LLM",
        False,
    )
    @patch(
        "graph.nodes.interpret_incident._run_no_tools",
    )
    def test_interpret_node_renders_only_validated_structure(
        self,
        _run_no_tools,
    ):
        _run_no_tools.return_value = (
            json.dumps(_payload()),
            [],
            [],
        )
        result = interpret_incident(_state())
        self.assertEqual(
            result["interpretation_structured"]["status"],
            "supported",
        )
        self.assertTrue(result["claim_grounding"]["passed"])
        self.assertIn(
            "Database connection pool exhausted",
            result["interpretation"],
        )
        self.assertNotIn(
            "Invented root cause title",
            result["interpretation"],
        )


if __name__ == "__main__":
    unittest.main()
