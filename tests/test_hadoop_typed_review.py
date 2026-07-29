import unittest

from scripts.evaluate_hadoop_typed_review import (
    _case_id,
    _cause_prediction,
    _classification_prediction,
    _observed_outcome,
)


class HadoopTypedReviewTests(unittest.TestCase):
    def test_case_ids_do_not_collide_on_shared_numeric_suffix(self):
        first = _case_id("application_cluster_a_0011")
        second = _case_id("application_cluster_b_0011")

        self.assertNotEqual(first, second)

    def test_tied_candidates_remain_insufficient_evidence(self):
        state = {
            "deterministic_assessment": {
                "abstain": True,
                "candidates": [{
                    "category": "network_disconnection",
                }],
            },
        }

        self.assertEqual(
            _cause_prediction(state),
            "insufficient_evidence",
        )

    def test_success_is_separate_from_cause_prediction(self):
        signals = {
            "statuses": {
                "job_lifecycle:succeeded": 1,
            },
        }

        observed = _observed_outcome(signals)

        self.assertEqual(observed, "succeeded")
        self.assertEqual(
            _classification_prediction(
                "insufficient_evidence",
                observed,
            ),
            "normal",
        )


if __name__ == "__main__":
    unittest.main()
