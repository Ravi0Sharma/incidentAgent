import csv
import os
import tempfile
import unittest

from evaluation.distributed_feature_audit import (
    _has_later_success,
    _peer_features,
    audit_hdfs_event_traces,
)


class DistributedFeatureAuditTests(unittest.TestCase):
    def test_peer_features_compare_only_with_supplied_peers(self):
        result = _peer_features(
            30.0,
            [19.0, 20.0, 21.0],
        )
        self.assertEqual(
            result["peer_count"], 3
        )
        self.assertEqual(
            result["peer_median_seconds"],
            20.0,
        )
        self.assertEqual(
            result["duration_ratio"], 1.5
        )
        self.assertEqual(
            result["percentile_rank"],
            100.0,
        )

    def test_later_success_requires_order(self):
        self.assertTrue(
            _has_later_success(
                ["E7", "E1", "E2"],
                0,
            )
        )
        self.assertFalse(
            _has_later_success(
                ["E2", "E7"],
                1,
            )
        )

    def test_hdfs_truth_is_joined_after_order_features(self):
        with tempfile.TemporaryDirectory() as root:
            preprocessed = os.path.join(
                root, "preprocessed"
            )
            os.makedirs(preprocessed)
            path = os.path.join(
                preprocessed,
                "Event_traces.csv",
            )
            with open(
                path,
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Features",
                        "Latency",
                        "Label",
                    ],
                )
                writer.writeheader()
                writer.writerows([
                    {
                        "Features": "E1 E7",
                        "Latency": "10",
                        "Label": "Fail",
                    },
                    {
                        "Features": "E20 E2",
                        "Latency": "12",
                        "Label": "Success",
                    },
                    {
                        "Features": "E1 E2",
                        "Latency": "9",
                        "Label": "Success",
                    },
                ])
            report = audit_hdfs_event_traces(
                root
            )
        self.assertFalse(
            report[
                "labels_used_during_feature_extraction"
            ]
        )
        self.assertEqual(
            report[
                "typed_storage_combined_association"
            ]["support"],
            2,
        )
        self.assertEqual(
            report["feature_cross_tabs"][
                "typed_marker_terminal"
            ]["fail:true"],
            1,
        )
        followups = report[
            "typed_storage_followups"
        ]
        e20_success = next(
            item
            for item in followups
            if item["last_typed_event"]
            == "E20"
        )
        self.assertEqual(
            e20_success[
                "top_next_events"
            ][0],
            {
                "event_id": "E2",
                "count": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
