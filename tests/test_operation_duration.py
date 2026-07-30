import unittest

from utils.operation_duration import (
    build_peer_duration_features,
)


class OperationDurationTests(unittest.TestCase):
    def test_peer_outlier_is_label_free_and_has_baseline_provenance(self):
        operations = []
        for index, duration in enumerate(
            [
                40,
                19,
                20,
                21,
                19,
                20,
                21,
                19,
                20,
                21,
                19,
                20,
                21,
                19,
                20,
                21,
                19,
                20,
                21,
                19,
                20,
            ]
        ):
            operations.append({
                "operation_id":
                "operation-" + str(index),
                "operation_name": "spawn",
                "started_at":
                "2026-07-29T10:00:00Z",
                "completed_at":
                (
                    "2026-07-29T10:00:"
                    + f"{duration:02d}Z"
                ),
                "cohort_key":
                ("service-a", "spawn", "10"),
                "cohort_dimensions": {
                    "service": "service-a",
                    "operation": "spawn",
                    "hour": "10",
                },
                "source_provenance": {
                    "source_schema_id":
                    "test-operation/v1",
                },
            })
        features = (
            build_peer_duration_features(
                operations
            )
        )
        outlier = features[
            "operation-0"
        ]
        baseline = outlier["baseline"]
        self.assertEqual(
            outlier["status"],
            "deviation_observed",
        )
        self.assertEqual(
            baseline["peer_count"], 20
        )
        self.assertFalse(
            baseline["labels_used"]
        )
        self.assertTrue(
            baseline["leave_one_out"]
        )
        self.assertIsNone(
            outlier["decision_policy"][
                "fixed_seconds_threshold"
            ]
        )
        self.assertGreater(
            baseline["duration_ratio"],
            1.25,
        )

    def test_small_cohort_abstains(self):
        features = (
            build_peer_duration_features([
                {
                    "operation_id": "one",
                    "operation_name":
                    "request",
                    "started_at":
                    "2026-07-29T10:00:00Z",
                    "completed_at":
                    "2026-07-29T10:00:30Z",
                    "cohort_key": "tiny",
                },
                {
                    "operation_id": "two",
                    "operation_name":
                    "request",
                    "started_at":
                    "2026-07-29T10:00:00Z",
                    "completed_at":
                    "2026-07-29T10:00:10Z",
                    "cohort_key": "tiny",
                },
            ])
        )
        self.assertEqual(
            features["one"]["status"],
            "insufficient_baseline",
        )


if __name__ == "__main__":
    unittest.main()
