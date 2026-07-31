import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from unittest.mock import patch

from langgraph.graph import END, StateGraph

from graph.checkpointer import SQLiteSaver
from graph.nodes.plan_collection import plan_collection
from graph.nodes.aggregate_by_labels import aggregate_by_labels
from graph.nodes.enrich_groups import enrich_groups
from graph.nodes.apply_detection_rules import apply_detection_rules
from clients.github_client import MockGithubClient
from clients.loki_client import MockLokiClient
from utils.candidate_scoring import score_candidates
from utils.incident_features import build_features
from utils.llm_context import (
    build_decision_brief,
    build_investigation_budget,
    build_policy_profiles,
)
from utils.histogram import build
from utils.incident_window import build_incident_window
from utils.semantic_report import validate_semantic_report
from utils.tool_budget import ToolSession
from graph.nodes.reinvestigate_feedback import reinvestigate_feedback
from webhook.timeline import timeline_items
from utils import correlation_tools


class _CounterState(TypedDict):
    value: int


class ProductionFlowTests(unittest.TestCase):
    def test_synthetic_demo_has_a_decisive_trace_linked_causal_chain(self):
        window = {
            "start": "2026-07-22T11:51:00Z",
            "end": "2026-07-22T12:01:00Z",
        }
        client = MockLokiClient()
        logs = client.query_logs("payments", window=window, limit=300)
        aggregated = aggregate_by_labels({
            "incident_id": "INC-SYNTHETIC-DEMO",
            "logs": logs,
            "log_query": {"total_count": len(logs)},
        })["log_groups"]
        deploys = MockGithubClient().get_recent_deploys(
            "payments", window=window
        )
        detected = apply_detection_rules({
            "log_groups": aggregated,
            "deploys": deploys,
        })
        enriched = enrich_groups({
            "log_groups": detected["log_groups"],
            "deploys": deploys,
        })["log_groups"]
        state = {
            "incident_id": "INC-SYNTHETIC-DEMO",
            "log_groups": enriched,
            "detections": detected["detections"],
            "anchor_event": {"timestamp": window["end"]},
            "incident_features": build_features({
                "log_groups": enriched,
                "metrics": [],
                "source_status": {},
            }),
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments", "checkout", "auth"],
                "window": window,
            },
        }
        assessment = score_candidates(state)

        self.assertFalse(assessment["abstain"])
        self.assertEqual(
            assessment["candidates"][0]["title"],
            "Database connection pool exhausted",
        )
        self.assertGreaterEqual(assessment["candidates"][0]["score"], 70)

        with patch.object(correlation_tools, "loki", client):
            trace = correlation_tools.get_trace(state, "paydb000")
        by_service = {
            item["service"]: item.get("total_matched")
            for item in trace["services_checked"]
        }
        self.assertTrue(trace["count_is_exact"])
        self.assertGreater(by_service["payments"], 0)
        self.assertGreater(by_service["checkout"], 0)

    def test_reviewer_retry_gets_a_fresh_bounded_tool_budget(self):
        result = reinvestigate_feedback({
            "review_feedback": "Verify the database trace.",
            "investigation_budget": {
                "max_remote_units": 2,
                "used_remote_units": 2,
                "tool_cache": {"old": {"result": {}}},
                "tool_history": [{"status": "executed"}],
            },
        })
        budget = result["investigation_budget"]
        self.assertEqual(budget["max_remote_units"], 2)
        self.assertEqual(budget["used_remote_units"], 0)
        self.assertEqual(budget["tool_cache"], {})
        self.assertEqual(budget["tool_history"], [])

    def test_incident_window_uses_alert_timestamps(self):
        window = build_incident_window({
            "started_at": "2026-07-14T10:00:00Z",
            "received_at": "2026-07-14T10:07:00Z",
        })
        self.assertEqual(
            window["anchor_time"],
            "2026-07-14T10:00:00+00:00",
        )
        self.assertEqual(
            window["start"],
            "2026-07-14T09:50:00+00:00",
        )
        self.assertEqual(
            window["end"],
            "2026-07-14T10:07:00+00:00",
        )

    def test_high_volume_group_is_one_event_with_actual_buckets(self):
        base = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        logs = []
        for index in range(1_200):
            timestamp = base + timedelta(seconds=index % 180)
            logs.append({
                "timestamp": timestamp.isoformat(),
                "message": (
                    "payment dependency timeout "
                    f"trace_id=abcdef{index:06d}"
                ),
                "labels": {
                    "service": "payments",
                    "level": "error",
                    "error_type": "dependency_timeout",
                    "pod": f"payments-{index % 4}",
                    "route": "/checkout",
                },
            })

        state = {
            "incident_id": "TEST-HIGH-VOLUME",
            "logs": logs,
            "log_query": {
                "total_count": 1_200,
                "count_is_exact": True,
                "possibly_truncated": False,
            },
            "incident_window": {},
        }
        output = aggregate_by_labels(state)
        self.assertEqual(len(output["log_groups"]), 1)
        group = output["log_groups"][0]
        self.assertEqual(group["count"], 1_200)
        self.assertTrue(group["count_is_exact"])
        self.assertEqual(group["dimensions"]["pod"]["unique"], 4)
        self.assertEqual(
            sum(item["count"] for item in group["time_buckets"]),
            1_200,
        )
        self.assertEqual(
            sum(item["count"] for item in build([group])),
            1_200,
        )

    def test_truncated_fetch_is_never_claimed_as_exact_group_count(self):
        state = {
            "incident_id": "TEST-TRUNCATED",
            "logs": [{
                "timestamp": "2026-07-14T10:00:00Z",
                "message": "timeout trace_id=abcdef123",
                "labels": {
                    "service": "payments",
                    "level": "error",
                    "error_type": "timeout",
                },
            }],
            "log_query": {
                "total_count": 50_000,
                "count_is_exact": True,
                "possibly_truncated": True,
            },
            "incident_window": {},
        }
        output = aggregate_by_labels(state)
        group = output["log_groups"][0]
        self.assertFalse(group["count_is_exact"])
        self.assertEqual(group["count_scope"], "fetched_log_sample")
        self.assertEqual(output["raw_log_count"], 50_000)

    def test_semantic_report_discards_unknown_event_reference(self):
        state = {
            "evidence_graph": {
                "nodes": [
                    {"event_id": "alert-1"},
                    {"event_id": "log-known"},
                ]
            },
            "source_status": {},
            "data_quality": {"logs": {}},
        }
        report = validate_semantic_report({
            "primary_chain": [{
                "cause_event": "invented-event",
                "effect_event": "log-known",
                "relationship": "likely_causes",
                "confidence": 99,
                "evidence": ["not grounded"],
            }],
        }, state, [])
        self.assertEqual(report["primary_chain"], [])
        self.assertTrue(report["validation"]["warnings"])

    def test_valid_semantic_link_is_marked_model_inferred(
        self,
    ):
        state = {
            "evidence_graph": {
                "nodes": [
                    {"event_id": "log-a"},
                    {"event_id": "log-b"},
                ]
            },
            "source_status": {},
            "data_quality": {
                "logs": {}
            },
        }
        report = validate_semantic_report({
            "primary_chain": [{
                "cause_event": "log-a",
                "effect_event": "log-b",
                "relationship":
                "likely_causes",
                "confidence": 75,
                "evidence": [
                    "shared trace"
                ],
            }],
        }, state, [])
        link = report[
            "primary_chain"
        ][0]
        self.assertEqual(
            link["provenance"],
            "model_inferred",
        )
        self.assertEqual(
            link["causal_status"],
            "not_established",
        )

    def test_review_timeline_has_anchor_and_valid_log_ranges(self):
        items, groups = timeline_items([
            {
                "type": "alert",
                "timestamp": "2026-07-14T10:03:12Z",
                "message": "latency alert",
            },
            {
                "type": "log_group",
                "timestamp": "2026-07-14T10:03:00Z",
                "first_seen": "2026-07-14T10:03:00Z",
                "last_seen": "2026-07-14T10:04:00Z",
                "count": 42,
                "labels": {"error_type": "db_timeout"},
            },
            {
                "type": "log_group",
                "timestamp": "2026-07-14T10:05:00Z",
                "first_seen": "2026-07-14T10:05:00Z",
                "last_seen": "2026-07-14T10:05:00Z",
                "count": 1,
                "labels": {"error_type": "retry"},
            },
        ])
        self.assertEqual(groups[0]["id"], "alert")
        self.assertEqual(items[0]["content"], "alert")
        self.assertEqual(items[1]["type"], "range")
        self.assertEqual(items[2]["type"], "point")

    def test_initial_collection_is_bounded_and_mock_respects_limit(self):
        plan = plan_collection({
            "severity": "SEV3",
            "alert": {"service": "payments"},
            "business_context": {"service": "payments"},
        })["collection_plan"]
        self.assertLess(plan["log_fetch_limit"], 1_000)
        logs = MockLokiClient().query_logs(
            "payments",
            window={
                "start": "2026-07-14T10:00:00Z",
                "end": "2026-07-14T10:06:00Z",
            },
            limit=7,
        )
        self.assertEqual(len(logs), 7)

    def test_deterministic_candidate_is_grounded_and_flags_close_ranking(self):
        groups = [{
            "event_id": "log-db",
            "count": 42,
            "first_seen": "2026-07-14T10:03:00Z",
            "labels": {
                "level": "error",
                "error_type": "db_timeout",
                "event_signature": "pool exhausted",
            },
            "related_deploys": [{
                "commit": "abc1234",
                "minutes_before_first_error": 8,
            }],
            "dimensions": {"pod": {"unique": 3}},
            "time_buckets": [{
                "bucket": "2026-07-14T10:03:00Z",
                "count": 42,
            }],
        }]
        state = {
            "log_groups": groups,
            "metrics": [],
            "pivots": {},
            "source_status": {},
            "anchor_event": {
                "timestamp": "2026-07-14T10:03:12Z",
            },
            "detections": [
                {
                    "id": "pool-exhausted",
                    "title": "Pool exhausted",
                    "level": "high",
                    "category": "resource_exhaustion",
                    "event_id": "log-db",
                    "group_count": 42,
                },
                {
                    "id": "deploy-regression",
                    "title": "Deploy regression",
                    "level": "high",
                    "category": "deploy_regression",
                    "event_id": "log-db",
                    "group_count": 42,
                },
            ],
        }
        state["incident_features"] = build_features(state)
        assessment = score_candidates(state)
        top = assessment["candidates"][0]
        self.assertEqual(len(assessment["candidates"]), 1)
        self.assertGreaterEqual(top["score"], 70)
        self.assertTrue(top["evidence"])
        self.assertTrue(top["verification"])

    def test_strong_assessment_skips_remote_llm_tools_and_has_compact_policy(self):
        state = {
            "severity": "SEV2",
            "deterministic_assessment": {
                "expansion_recommended": False,
                "candidates": [{
                    "title": "Pool exhausted",
                    "score": 82,
                    "event_ids": ["log-db"],
                    "evidence": ["count=42"],
                    "weaknesses": [],
                    "verification": "Inspect trace.",
                }],
            },
            "incident_features": {"source_failures": []},
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments"],
                "configured_dependencies": [],
            },
            "anchor_event": {"event_id": "alert-1"},
            "data_quality": {"logs": {}},
            "alert": {"service": "payments"},
        }
        budget = build_investigation_budget(state)
        self.assertEqual(budget["mode"], "deterministic_explanation")
        self.assertEqual(budget["max_remote_units"], 0)
        brief = build_decision_brief(state, budget)
        self.assertEqual(brief["candidate_ranking"][0]["event_ids"], ["log-db"])
        profiles = build_policy_profiles(state)
        self.assertLessEqual(len(profiles["semantic"]), 4)

    def test_shared_tool_budget_caches_and_blocks_second_remote_query(self):
        calls = []

        def dispatch(state, name, args):
            calls.append((name, args))
            return {"total_matched": 1, "sample": []}

        state = {
            "scope_expansion": {
                "alert_service": "payments",
                "services": ["payments", "orders"],
            },
            "investigation_budget": {
                "max_remote_units": 1,
                "used_remote_units": 0,
                "tool_cache": {},
                "tool_history": [],
            },
        }
        session = ToolSession(state)
        args = {"service": "orders", "pattern": "timeout"}
        self.assertEqual(
            session.run("search_logs", args, dispatch)["total_matched"], 1
        )
        self.assertEqual(
            session.run("search_logs", args, dispatch)["total_matched"], 1
        )
        blocked = session.run(
            "search_logs",
            {"service": "catalog", "pattern": "timeout"},
            dispatch,
        )
        self.assertEqual(blocked["error"], "remote query budget exhausted")
        self.assertEqual(len(calls), 1)

    def test_sqlite_checkpoint_survives_new_saver(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "checkpoints.sqlite3")
            builder = StateGraph(_CounterState)
            builder.add_node(
                "increment",
                lambda state: {"value": state["value"] + 1},
            )
            builder.set_entry_point("increment")
            builder.add_edge("increment", END)
            graph = builder.compile(checkpointer=SQLiteSaver(path))
            config = {"configurable": {"thread_id": "persisted"}}
            self.assertEqual(graph.invoke({"value": 1}, config)["value"], 2)

            restored = SQLiteSaver(path)
            self.assertIsNotNone(restored.get_tuple(config))


if __name__ == "__main__":
    unittest.main()
