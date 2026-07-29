import unittest

from evaluation.hadoop_llm import (
    prediction_supported_by_signals,
)


class HadoopReportTests(
    unittest.TestCase
):
    def test_alternative_observed_fault_is_grounded_even_when_label_differs(
        self,
    ):
        summary = {
            "statuses": {
                "machine_availability:"
                "unavailable": 3,
            }
        }
        self.assertTrue(
            prediction_supported_by_signals(
                "machine_down",
                summary,
            )
        )
        self.assertFalse(
            prediction_supported_by_signals(
                "disk_full",
                summary,
            )
        )


if __name__ == "__main__":
    unittest.main()
