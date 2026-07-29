import unittest
import os
import json
import tempfile

from evaluation.grouping_quality import (
    evaluate_controlled_grouping,
    evaluate_grouping_rows,
)
from evaluation.real_log_pair_benchmark import (
    evaluate_real_log_pairs,
)


def _record(line_id, message, *, level="error", service="api"):
    return {
        "timestamp": "2026-07-29T10:00:00Z",
        "message": message,
        "labels": {
            "service": service,
            "level": level,
        },
        "connector_metadata": {
            "source": "test",
            "source_line_id": line_id,
        },
    }


class GroupingQualityTests(unittest.TestCase):
    def test_real_pair_benchmark_recomputes_current_groups(self):
        candidates = {
            "schema_version": "real-log-pair-candidates/v1",
            "candidates": [
                {
                    "pair_id": "same",
                    "dataset": "test",
                    "left": {
                        "message": "timeout request 10",
                        "labels": {"service": "api", "level": "error"},
                    },
                    "right": {
                        "message": "timeout request 20",
                        "labels": {"service": "api", "level": "error"},
                    },
                },
                {
                    "pair_id": "different",
                    "dataset": "test",
                    "left": {
                        "message": "instance spawned",
                        "labels": {"service": "api", "level": "info"},
                    },
                    "right": {
                        "message": "instance destroyed",
                        "labels": {"service": "api", "level": "info"},
                    },
                },
            ],
        }
        annotations = {
            "schema_version": "real-log-pair-annotations/v1",
            "annotations": [
                {
                    "pair_id": "same",
                    "expected_relation": "same_event_shape",
                },
                {
                    "pair_id": "different",
                    "expected_relation": "different_event_shape",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as root:
            candidate_path = os.path.join(root, "candidates.json")
            annotation_path = os.path.join(root, "annotations.json")
            with open(candidate_path, "w", encoding="utf-8") as handle:
                json.dump(candidates, handle)
            with open(annotation_path, "w", encoding="utf-8") as handle:
                json.dump(annotations, handle)
            report = evaluate_real_log_pairs(
                candidate_path, annotation_path
            )
        self.assertTrue(report["quality_gate_passed"])
        self.assertEqual(report["evaluated_pairs"], 2)

    def test_pair_metrics_detect_overmerge_and_fragmentation(self):
        rows = [
            ("case", _record("1", "failure code 10"), "event-a"),
            ("case", _record("2", "failure code 11"), "event-a"),
            ("case", _record("3", "failure code 12"), "event-b"),
            ("case", _record("4", "different failure"), "event-a"),
        ]
        report = evaluate_grouping_rows(
            rows,
            dataset="contract",
            truth_kind="reviewed",
            sample_limit=10,
            truth_limitations="none",
        )
        self.assertEqual(report["collision_group_count"], 1)
        self.assertEqual(report["fragmented_source_label_count"], 1)
        self.assertEqual(report["pairwise"]["false_positive_pairs"], 2)
        self.assertEqual(report["pairwise"]["false_negative_pairs"], 2)

    def test_service_boundary_prevents_cross_service_merge(self):
        rows = [
            (
                "case",
                _record("1", "timeout request 10", service="checkout"),
                "checkout-timeout",
            ),
            (
                "case",
                _record("2", "timeout request 11", service="payments"),
                "payments-timeout",
            ),
        ]
        report = evaluate_grouping_rows(
            rows,
            dataset="contract",
            truth_kind="reviewed",
            sample_limit=10,
            truth_limitations="none",
        )
        self.assertEqual(report["collision_group_count"], 0)
        self.assertEqual(report["pairwise"]["precision"], 1.0)

    def test_controlled_fixture_is_loadable(self):
        report = evaluate_controlled_grouping(
            os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "fixtures",
                "grouping_contract_cases.json",
            )
        )
        self.assertEqual(
            report["fixture_schema_version"],
            "grouping-contract/v1",
        )
        self.assertEqual(report["source_rows"], 32)
        self.assertTrue(report["quality_gate_passed"])
        self.assertEqual(report["collision_group_count"], 0)
        self.assertEqual(report["fragmented_source_label_count"], 0)


if __name__ == "__main__":
    unittest.main()
