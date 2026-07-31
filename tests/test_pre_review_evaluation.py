import unittest
from datetime import timedelta

from clients.loki_client import (
    representative_sample,
)
from evaluation.synthetic_scenarios import (
    BASE,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.correlate import correlate
from graph.nodes.integrate_targeted_evidence import (
    integrate_targeted_evidence,
)
from scripts.evaluate_pre_review import (
    run as run_pre_review_evaluation,
)
from utils.log_normalizer import (
    normalize_log,
)


class PreReviewEvaluationTests(
    unittest.TestCase
):
    def test_high_signal_sampling_keeps_rare_error_and_time_coverage(self):
        logs = [
            {
                "timestamp": (
                    BASE.isoformat()
                ),
                "message": (
                    f"normal request {index}"
                ),
                "labels": {
                    "service": "payments",
                    "level": "info",
                },
            }
            for index in range(1_000)
        ]
        logs[537] = {
            "timestamp": (
                BASE.isoformat()
            ),
            "message": (
                "connection pool exhausted"
            ),
            "labels": {
                "service": "payments",
                "level": "error",
            },
        }

        sampled = representative_sample(
            logs, 30
        )
        self.assertEqual(
            len(sampled), 30
        )
        self.assertTrue(
            any(
                "pool exhausted"
                in log["message"]
                for log in sampled
            )
        )

    def test_sampling_reserves_an_uncommon_informational_shape(self):
        logs = [
            {
                "timestamp": (
                    BASE
                    + timedelta(seconds=index)
                ).isoformat(),
                "message": f"routine heartbeat node={index}",
                "labels": {
                    "service": "hdfs",
                    "level": "info",
                },
            }
            for index in range(500)
        ]
        logs[251] = {
            **logs[251],
            "message": "metadata checkpoint completed",
        }
        sampled = representative_sample(logs, 30)
        self.assertTrue(any(
            row["message"] == "metadata checkpoint completed"
            for row in sampled
        ))

    def test_normalizer_promotes_canonical_utc_event_time(self):
        normalized = normalize_log({
            "timestamp": (
                "2026-07-22T12:00:00+02:00"
            ),
            "message": "timeout",
            "labels": {
                "service": "payments",
                "level": "error",
            },
        })
        self.assertEqual(
            normalized["timestamp"],
            "2026-07-22T10:00:00Z",
        )
        self.assertEqual(
            normalized[
                "original_timestamp"
            ],
            "2026-07-22T12:00:00+02:00",
        )

    def test_source_timestamp_scope_reaches_log_group(self):
        normalized = normalize_log({
            "timestamp":
            "2026-07-22T12:00:00Z",
            "message":
            "IOException: OP_READ_BLOCK",
            "labels": {
                "service": "hdfs",
                "level": "error",
            },
            "connector_metadata": {
                "source_dataset":
                "tracebench",
                "timestamp_quality":
                "coarse_trace_first_seen",
                "timestamp_ordering_scope":
                "trace_only",
            },
        })
        result = aggregate_by_labels({
            "logs": [normalized],
            "log_query": {
                "total_count": 1,
                "possibly_truncated":
                False,
            },
        })
        quality = result[
            "log_groups"
        ][0]["time_quality"]
        self.assertEqual(
            quality[
                "ordering_scopes"
            ],
            ["trace_only"],
        )
        self.assertFalse(
            quality[
                "globally_comparable"
            ]
        )

    def test_semantic_error_codes_do_not_overmerge(self):
        result = aggregate_by_labels({
            "logs": [
                {
                    "timestamp": (
                        "2026-07-22T10:00:00Z"
                    ),
                    "message": (
                        "database failed "
                        "SQLSTATE[53300]"
                    ),
                    "labels": {
                        "service": "payments",
                        "level": "error",
                        "error_type": (
                            "database_error"
                        ),
                    },
                },
                {
                    "timestamp": (
                        "2026-07-22T10:01:00Z"
                    ),
                    "message": (
                        "database failed "
                        "SQLSTATE[08006]"
                    ),
                    "labels": {
                        "service": "payments",
                        "level": "error",
                        "error_type": (
                            "database_error"
                        ),
                    },
                },
            ],
            "log_query": {
                "total_count": 2,
                "possibly_truncated": False,
            },
        })
        self.assertEqual(
            len(result["log_groups"]),
            2,
        )

    def test_evidence_graph_records_actual_relation_to_anchor(self):
        state = {
            "alert": {
                "started_at": (
                    "2026-07-22T10:05:00Z"
                ),
                "message": "alert",
            },
            "incident_window": {},
            "log_groups": [
                {
                    "event_id": "log-before",
                    "first_seen": (
                        "2026-07-22T10:02:00Z"
                    ),
                    "labels": {
                        "level": "error"
                    },
                    "time_buckets": [],
                }
            ],
            "deploys": [
                {
                    "event_id": (
                        "deploy-before"
                    ),
                    "time": (
                        "2026-07-22T10:00:00Z"
                    ),
                }
            ],
            "metrics": [
                {
                    "event_id": (
                        "metric-after"
                    ),
                    "metric": "error_rate",
                    "value": 0.2,
                    "timestamp": (
                        "2026-07-22T10:06:00Z"
                    ),
                }
            ],
        }
        result = correlate(state)
        by_event = {
            link["from"]:
            link["relationship"]
            for link in result[
                "evidence_graph"
            ]["factual_links"]
        }
        self.assertEqual(
            by_event["deploy-before"],
            "precedes_anchor",
        )
        self.assertEqual(
            by_event["log-before"],
            "precedes_anchor",
        )
        self.assertEqual(
            by_event["metric-after"],
            "follows_anchor",
        )
        graph = result[
            "evidence_graph"
        ]
        self.assertEqual(
            graph[
                "edge_schema_version"
            ],
            "incident-edge/v1",
        )
        for link in graph[
            "typed_links"
        ]:
            self.assertIn(
                link["provenance"],
                {
                    "observed",
                    "deterministic_derived",
                    "model_inferred",
                },
            )
            self.assertEqual(
                link["causal_status"],
                "not_established",
            )

    def test_targeted_tool_evidence_is_reprocessed_and_rescored(self):
        result = integrate_targeted_evidence({
            "alert": {
                "incident_id": (
                    "EVAL-TARGETED"
                ),
                "service": "payments",
                "started_at": (
                    "2026-07-22T10:05:00Z"
                ),
                "labels": {
                    "service": "payments"
                },
            },
            "incident_window": {
                "start": (
                    "2026-07-22T09:55:00Z"
                ),
                "end": (
                    "2026-07-22T10:05:00Z"
                ),
            },
            "metrics": [],
            "deploys": [],
            "investigation_budget": {
                "mode": (
                    "targeted_verification"
                ),
                "max_remote_units": 2,
                "used_remote_units": 1,
            },
            "semantic_correlation_tool_trace": [
                {
                    "tool": "search_logs",
                    "result": {
                        "sample": [
                            {
                                "timestamp": (
                                    "2026-07-22T10:02:00Z"
                                ),
                                "message": (
                                    "connection pool exhausted"
                                ),
                                "labels": {
                                    "service": "payments",
                                    "level": "error",
                                    "error_type": (
                                        "db_timeout"
                                    ),
                                },
                            }
                        ]
                    },
                }
            ],
        })
        self.assertTrue(
            result[
                "targeted_evidence"
            ]["rescored"]
        )
        self.assertIn(
            "db-connection-pool-exhausted",
            {
                item["id"]
                for item in result[
                    "detections"
                ]
            },
        )
        self.assertEqual(
            result[
                "deterministic_assessment"
            ]["candidates"][0]["title"],
            (
                "Database connection pool "
                "exhausted"
            ),
        )

    def test_complete_synthetic_pre_review_suite_passes(self):
        report = (
            run_pre_review_evaluation()
        )
        self.assertEqual(
            report["failed"], 0
        )
        self.assertEqual(
            report["passed"],
            report["scenario_count"],
        )


if __name__ == "__main__":
    unittest.main()
