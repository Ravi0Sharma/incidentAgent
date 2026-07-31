import importlib
import os
import tempfile
import unittest
import zlib
from unittest.mock import patch

from utils.review_gate import analysis_review_state
from utils.tool_budget import (
    ToolSession,
    compact_result,
    remote_cost,
    validate_tool_request,
)


log_store = importlib.import_module("utils.log_store")
redaction = importlib.import_module("utils.redaction")
tool_budget = importlib.import_module("utils.tool_budget")


class LogStoreBoundaryTests(unittest.TestCase):
    def test_encode_enforces_uncompressed_and_compressed_limits(self):
        with patch.object(log_store, "MAX_STORED_LOG_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "uncompressed byte limit"):
                log_store._encode_logs([{"message": "too large"}])

        with patch.object(
            log_store,
            "MAX_STORED_LOG_BYTES",
            10_000,
        ), patch.object(log_store, "MAX_COMPRESSED_LOG_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "compressed byte limit"):
                log_store._encode_logs([{"message": "small"}])

    def test_decode_rejects_type_size_framing_and_non_list_json(self):
        with self.assertRaisesRegex(ValueError, "not binary"):
            log_store._decode_logs("not-bytes")

        with patch.object(log_store, "MAX_COMPRESSED_LOG_BYTES", 2):
            with self.assertRaisesRegex(ValueError, "compressed byte limit"):
                log_store._decode_logs(b"123")

        invalid_payloads = [
            zlib.compress(b"[]") + b"trailing-data",
            zlib.compress(b"[]")[:-1],
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "invalid compressed framing"):
                    log_store._decode_logs(payload)

        with self.assertRaisesRegex(ValueError, "decode to a list"):
            log_store._decode_logs(zlib.compress(b'{"message":"not a list"}'))

    def test_sqlite_round_trip_redacts_before_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "incident-logs.sqlite3")
            with patch.object(log_store, "INCIDENT_STORE_PATH", path):
                log_store.put_logs("", [{"message": "ignored"}])
                self.assertEqual(log_store.get_logs(""), [])
                self.assertEqual(log_store.get_logs("missing"), [])

                log_store.put_logs("INC-1", [{
                    "message": "authorization=secret-value",
                    "labels": {"api_key": "sensitive", "service": "checkout"},
                }])
                restored = log_store.get_logs("INC-1")

        self.assertEqual(restored[0]["message"], "authorization=[REDACTED]")
        self.assertEqual(restored[0]["labels"]["service"], "checkout")
        self.assertTrue(restored[0]["labels"]["api_key"].startswith("redacted-"))


class RedactionBoundaryTests(unittest.TestCase):
    def test_disabled_redaction_preserves_values_for_each_public_entrypoint(self):
        payload = {"token": "visible", "nested": ["email=a@example.test"]}
        with patch.object(redaction, "PII_REDACTION_ENABLED", False):
            self.assertEqual(redaction.redact_message("token=visible"), "token=visible")
            self.assertEqual(
                redaction.redact_labels({"email": "a@example.test"}),
                {"email": "a@example.test"},
            )
            self.assertIs(redaction.redact_data(payload), payload)

    def test_recursive_redaction_handles_labels_tuples_and_log_defaults(self):
        labels = redaction.redact_labels({
            "user_email": "a@example.test",
            "service": "checkout",
        })
        self.assertTrue(labels["user_email"].startswith("redacted-"))
        self.assertEqual(labels["service"], "checkout")

        value = redaction.redact_data((
            "contact a@example.test",
            {"nested_access_token": "secret", "count": 3},
        ))
        self.assertIsInstance(value, tuple)
        self.assertEqual(value[0], "contact [EMAIL_REDACTED]")
        self.assertTrue(value[1]["nested_access_token"].startswith("redacted-"))
        self.assertEqual(value[1]["count"], 3)

        empty_log = redaction.redact_log(None)
        self.assertEqual(empty_log["message"], "")
        self.assertEqual(empty_log["labels"], {})

    def test_syslog_identity_fields_and_reverse_dns_are_redacted(self):
        rendered = redaction.redact_message(
            "authentication failure; logname=alice ruser=bob "
            "rhost=host.example.test user=root; connection from "
            "10.0.0.1 (host.example.test)"
        )
        for value in (
            "alice",
            "bob",
            "host.example.test",
            "root",
            "10.0.0.1",
        ):
            self.assertNotIn(value, rendered)
        self.assertIn("user=[USER_REDACTED]", rendered)
        self.assertIn("rhost=[HOST_REDACTED]", rendered)


class ReviewGateDecisionTests(unittest.TestCase):
    @staticmethod
    def _base_state():
        return {
            "interpretation": "Grounded hypothesis",
            "interpretation_quality": {"passed": True, "abstained": False},
            "claim_grounding": {"passed": True},
            "deterministic_assessment": {"candidates": [{"rank": 1}]},
        }

    def test_review_gate_exposes_each_fail_closed_reason(self):
        scenarios = [
            ({"interpretation": ""}, {"hypotheses": [{"rank": 1}]}, "analysis_unavailable"),
            (
                {"interpretation_quality": {"passed": True, "abstained": True}},
                {"hypotheses": [{"rank": 1}]},
                "analysis_abstained",
            ),
            ({}, {"hypotheses": []}, "no_hypothesis"),
            ({}, {"hypotheses": [{"rank": 2}]}, "hypothesis_not_in_saved_candidates"),
            (
                {"interpretation_quality": {"passed": False, "abstained": False}},
                {"hypotheses": [{"rank": 1}]},
                "interpretation_quality_failed",
            ),
            (
                {"claim_grounding": {"passed": False}},
                {"hypotheses": [{"rank": 1}]},
                "claim_grounding_failed",
            ),
            ({}, {"hypotheses": [{"rank": 1}]}, "approvable"),
        ]

        for overrides, parsed, expected_reason in scenarios:
            with self.subTest(reason=expected_reason):
                state = self._base_state()
                state.update(overrides)
                result = analysis_review_state(state, parsed)
                self.assertEqual(result["reason"], expected_reason)
                self.assertEqual(result["can_approve"], expected_reason == "approvable")

    def test_review_gate_ignores_malformed_and_out_of_range_ranks(self):
        state = self._base_state()
        state["deterministic_assessment"] = {
            "candidates": [None, {"rank": "invalid"}, {"rank": 4}, {"rank": "1"}]
        }
        parsed = {
            "hypotheses": ["invalid", {"rank": None}, {"rank": 4}, {"rank": 1}]
        }

        result = analysis_review_state(state, parsed)

        self.assertTrue(result["can_approve"])
        self.assertEqual(result["approvable_ranks"], [1])

    def test_degraded_or_structurally_abstained_output_fails_closed(self):
        degraded = self._base_state()
        degraded["interpretation_tool_trace"] = [{"status": "degraded"}]
        degraded["claim_grounding"] = {"passed": False}
        self.assertEqual(
            analysis_review_state(degraded, {"hypotheses": [{"rank": 1}]})["reason"],
            "analysis_unavailable",
        )

        state = self._base_state()
        result = analysis_review_state(state, {
            "status": "abstained",
            "hypotheses": [{"rank": 1}],
        })
        self.assertEqual(result["reason"], "analysis_abstained")


class ToolBudgetBoundaryTests(unittest.TestCase):
    @staticmethod
    def _state(**budget_overrides):
        budget = {
            "max_remote_units": 3,
            "used_remote_units": 0,
            "tool_cache": {},
            "tool_history": [],
            "expansion_loop": {
                "max_services": 2,
                "max_result_bytes": 20_000,
                "max_elapsed_seconds": 300,
            },
        }
        budget.update(budget_overrides)
        return {
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments", "checkout", "catalog"],
            },
            "investigation_budget": budget,
        }

    def test_tool_policy_handles_non_object_none_and_empty_policy(self):
        self.assertEqual(
            validate_tool_request("search_logs", ["not", "an", "object"])[1],
            "tool arguments must be an object",
        )
        normalized, error = validate_tool_request(
            "search_logs",
            {"pattern": None, "service": "payments"},
        )
        self.assertIsNone(error)
        self.assertEqual(normalized, {"service": "payments"})
        self.assertEqual(validate_tool_request("discover_related_services", {}), ({}, None))

    def test_remote_cost_reflects_scope_and_tool_type(self):
        state = self._state()
        self.assertEqual(remote_cost(state, "discover_related_services", {}), 0)
        self.assertEqual(remote_cost(state, "get_log_context", {}), 0)
        self.assertEqual(remote_cost(state, "get_service_dependencies", {}), 0)
        self.assertEqual(remote_cost(state, "get_trace", {}), 2)
        self.assertEqual(remote_cost(state, "search_logs", {}), 0)
        self.assertEqual(remote_cost(state, "search_logs", {"service": "payments"}), 0)
        self.assertEqual(remote_cost(state, "search_logs", {"service": "checkout"}), 1)
        self.assertEqual(remote_cost(state, "unknown", {}), 1)

    def test_compaction_bounds_samples_and_preserves_provenance(self):
        raw = {
            "total_matched": 4,
            "provenance": {"source": "loki"},
            "sample": [{
                "timestamp": f"t-{index}",
                "labels": {"service": "payments"},
                "message": "x" * 300,
            } for index in range(5)],
            "raw_samples": list(range(8)),
            "services_checked": [{
                "service": f"service-{index}",
                "total_matched": index,
                "provenance": {"source": "loki"},
                "sample": [{"message": "m", "labels": {}} for _ in range(4)],
            } for index in range(5)],
        }

        result = compact_result(raw)

        self.assertEqual(len(result["sample"]), 3)
        self.assertEqual(len(result["sample"][0]["message"]), 240)
        self.assertEqual(result["sample"][0]["connector_metadata"], {"source": "loki"})
        self.assertEqual(result["raw_samples"], [0, 1, 2])
        self.assertEqual(len(result["services_checked"]), 3)
        self.assertEqual(len(result["services_checked"][0]["sample"]), 2)
        self.assertEqual(compact_result("plain"), {"result": "plain"})

    def test_deadline_and_stopped_loop_block_dispatch(self):
        calls = []
        deadline_state = self._state()
        deadline_state["analysis_deadline"] = {"deadline_at": "past"}
        with patch.object(tool_budget, "remaining_deadline_seconds", return_value=0):
            result = ToolSession(deadline_state).run(
                "search_logs",
                {"service": "payments"},
                lambda state, name, args: calls.append(args),
            )
        self.assertIn("deadline exhausted", result["error"])

        stopped_state = self._state()
        stopped_state["investigation_budget"]["expansion_loop"].update({
            "round": 1,
            "stop_reason": "sufficient_evidence",
        })
        result = ToolSession(stopped_state).run(
            "search_logs",
            {"service": "payments"},
            lambda state, name, args: calls.append(args),
        )
        self.assertEqual(result["stop_reason"], "sufficient_evidence")
        self.assertEqual(calls, [])

    def test_scope_is_truncated_and_history_is_bounded(self):
        session = ToolSession(self._state())
        result = session.run(
            "search_logs",
            {"service": "catalog"},
            lambda state, name, args: {"total_matched": 1},
        )
        self.assertIn("outside", result["error"])

        session.budget["tool_history"] = [{"status": "old"}] * 20
        session.run(
            "search_logs",
            {"service": "payments"},
            lambda state, name, args: {"total_matched": 0},
        )
        self.assertEqual(len(session.snapshot()["tool_history"]), 20)


if __name__ == "__main__":
    unittest.main()
