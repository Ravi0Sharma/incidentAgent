import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from graph.nodes.integrate_targeted_evidence import (
    integrate_targeted_evidence,
)
from utils.investigation_loop import (
    complete_round,
    expansion_router,
)
from utils.tool_budget import ToolSession


NOW = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)


def _budget(**loop_overrides):
    loop = {
        "max_rounds": 2,
        "max_services": 3,
        "max_result_bytes": 100000,
        "max_elapsed_seconds": 120,
    }
    loop.update(loop_overrides)
    return {
        "mode": "targeted_verification",
        "max_remote_units": 2,
        "used_remote_units": 0,
        "tool_cache": {},
        "tool_history": [],
        "expansion_loop": loop,
    }


class InvestigationLoopTests(unittest.TestCase):
    @patch(
        "graph.nodes.integrate_targeted_evidence.get_logs",
        return_value=[],
    )
    def test_service_a_to_b_evidence_changes_ranking_and_is_revisioned(
        self,
        _get_logs,
    ):
        state = {
            "incident_id": "LOOP-A-B",
            "alert": {
                "incident_id": "LOOP-A-B",
                "service": "payments",
                "started_at": "2026-07-22T10:05:00Z",
                "labels": {"service": "payments"},
            },
            "incident_window": {
                "start": "2026-07-22T09:55:00Z",
                "end": "2026-07-22T10:05:00Z",
            },
            "metrics": [],
            "deploys": [],
            "deterministic_assessment": {
                "expansion_recommended": True,
                "candidates": [],
            },
            "incident_features": {"source_failures": []},
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments", "orders"],
            },
            "investigation_budget": _budget(),
            "semantic_correlation_tool_trace": [{
                "tool": "search_logs",
                "args": {
                    "service": "orders",
                    "pattern": "connection pool",
                },
                "result_summary": "matched=1 samples=1",
                "result": {
                    "provenance": {"query_id": "qry-orders-1"},
                    "sample": [{
                        "timestamp": "2026-07-22T10:02:00Z",
                        "message": "connection pool exhausted",
                        "labels": {
                            "service": "orders",
                            "level": "error",
                            "error_type": "db_timeout",
                        },
                    }],
                },
            }],
        }

        result = integrate_targeted_evidence(state)

        top = result["deterministic_assessment"]["candidates"][0]
        self.assertEqual(top["title"], "Database connection pool exhausted")
        self.assertEqual(result["targeted_evidence"]["integrated_records"], 1)
        self.assertEqual(
            result["investigation_revisions"][0]["query_ids"],
            ["qry-orders-1"],
        )
        self.assertEqual(
            result["investigation_loop"]["stop_reason"],
            "enough_evidence",
        )
        self.assertEqual(expansion_router(result), "interpret_incident")

    def test_source_down_has_explicit_stop_reason(self):
        state = {
            "investigation_budget": _budget(),
            "incident_features": {"source_failures": []},
            "deterministic_assessment": {
                "expansion_recommended": True,
                "candidates": [],
            },
            "semantic_correlation_tool_trace": [{
                "tool": "search_logs",
                "result": {"error": "Loki unavailable"},
                "result_summary": "error: Loki unavailable",
            }],
        }
        result = complete_round(
            state,
            targeted_evidence={"integrated_records": 0},
            query_ids=[],
            now=NOW,
        )
        self.assertEqual(
            result["investigation_loop"]["stop_reason"],
            "source_unavailable",
        )
        self.assertEqual(expansion_router(result), "interpret_incident")

    def test_no_new_evidence_stops_with_safe_abstention(self):
        state = {
            "investigation_budget": _budget(),
            "incident_features": {"source_failures": []},
            "deterministic_assessment": {
                "expansion_recommended": True,
                "abstain": True,
                "candidates": [],
            },
            "semantic_correlation_tool_trace": [],
        }
        result = complete_round(
            state,
            targeted_evidence={
                "integrated_records": 0,
                "reason": "no discriminating records found",
            },
            query_ids=[],
            now=NOW,
        )
        self.assertEqual(
            result["investigation_loop"]["stop_reason"],
            "safe_abstention",
        )

    def test_remote_budget_exhaustion_wins_over_generic_source_error(self):
        budget = _budget()
        budget["max_remote_units"] = 1
        budget["used_remote_units"] = 1
        state = {
            "investigation_budget": budget,
            "incident_features": {"source_failures": []},
            "deterministic_assessment": {
                "expansion_recommended": True,
            },
            "semantic_correlation_tool_trace": [{
                "tool": "search_logs",
                "result": {"error": "remote query budget exhausted"},
            }],
        }
        result = complete_round(
            state,
            targeted_evidence={"integrated_records": 0},
            query_ids=[],
            now=NOW,
        )
        self.assertEqual(
            result["investigation_loop"]["stop_reason"],
            "remote_query_budget_exhausted",
        )

    def test_round_limit_stops_an_otherwise_continuable_expansion(self):
        state = {
            "investigation_budget": _budget(max_rounds=1),
            "incident_features": {"source_failures": []},
            "deterministic_assessment": {
                "expansion_recommended": True,
                "candidates": [{"id": "candidate-a", "score": 50}],
            },
            "semantic_correlation_tool_trace": [],
        }
        result = complete_round(
            state,
            targeted_evidence={"integrated_records": 2},
            query_ids=["qry-1"],
            now=NOW,
        )
        self.assertEqual(
            result["investigation_loop"]["stop_reason"],
            "round_budget_exhausted",
        )

    def test_new_ambiguous_evidence_allows_one_more_bounded_round(self):
        state = {
            "investigation_budget": _budget(),
            "incident_features": {"source_failures": []},
            "deterministic_assessment": {
                "expansion_recommended": True,
                "candidates": [{"id": "candidate-a", "score": 50}],
            },
            "semantic_correlation_tool_trace": [],
        }
        result = complete_round(
            state,
            targeted_evidence={"integrated_records": 2},
            query_ids=["qry-1"],
            now=NOW,
        )
        self.assertTrue(
            result["investigation_loop"]["continue_expansion"]
        )
        self.assertIsNone(
            result["investigation_loop"]["stop_reason"]
        )
        self.assertEqual(expansion_router(result), "semantic_correlate")

    def test_tool_result_byte_limit_blocks_oversized_result(self):
        budget = _budget(max_result_bytes=1)
        session = ToolSession({
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments"],
            },
            "investigation_budget": budget,
        })
        result = session.run(
            "search_logs",
            {"service": "payments", "pattern": "timeout"},
            lambda state, name, args: {
                "total_matched": 1,
                "sample": [{
                    "timestamp": "2026-07-28T10:00:00Z",
                    "message": "timeout",
                    "labels": {"service": "payments"},
                }],
            },
        )
        self.assertEqual(result["error"], "result byte budget exhausted")
        self.assertEqual(
            session.snapshot()["expansion_loop"]["used_result_bytes"],
            1,
        )

    def test_elapsed_limit_blocks_tool_before_dispatch(self):
        calls = []
        budget = _budget(
            max_elapsed_seconds=1,
            started_at="2000-01-01T00:00:00Z",
        )
        session = ToolSession({
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments"],
            },
            "investigation_budget": budget,
        })
        result = session.run(
            "search_logs",
            {"service": "payments", "pattern": "timeout"},
            lambda state, name, args: calls.append(args),
        )
        self.assertEqual(
            result["error"],
            "elapsed investigation budget exhausted",
        )
        self.assertEqual(calls, [])

    def test_tool_session_blocks_out_of_scope_service_without_dispatch(self):
        calls = []
        session = ToolSession({
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments", "orders"],
            },
            "investigation_budget": _budget(),
        })
        result = session.run(
            "search_logs",
            {"service": "catalog", "pattern": "timeout"},
            lambda state, name, args: calls.append(args),
        )
        self.assertIn("outside", result["error"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
