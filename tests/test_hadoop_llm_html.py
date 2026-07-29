import unittest

from utils.hadoop_llm_html import (
    render_hadoop_llm_review,
)


class HadoopLLMHTMLTests(
    unittest.TestCase
):
    def test_review_separates_truth_and_escapes_model_text(
        self,
    ):
        report = {
            "prompt_version": "test/v1",
            "cases_requested": 1,
            "cases_successful": 1,
            "contract_gate_passed": True,
            "diagnostic_gate_passed": False,
            "provider_failures": [],
            "metrics": {
                "citation_valid_rate": 1,
                "coverage": 0,
                "selective_accuracy": 0,
            },
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
            },
            "cases": [{
                "case_id": "case-1",
                "prediction":
                "insufficient_evidence",
                "truth": "normal",
                "answered": False,
                "correct": False,
                "confidence": "high",
                "summary":
                "<script>alert(1)</script>",
                "evidence_ids": [],
                "missing_evidence": [
                    "job status"
                ],
                "timeline": [],
                "validation": {
                    "citation_valid": True,
                    "claim_contract_valid":
                    True,
                },
                "usage": {},
                "model": "fake",
            }],
        }
        rendered = (
            render_hadoop_llm_review(
                report
            )
        )
        self.assertIn(
            "Ground truth and workload "
            "were attached only after",
            rendered,
        )
        self.assertNotIn(
            "<script>alert(1)</script>",
            rendered,
        )
        self.assertIn(
            "&lt;script&gt;alert(1)"
            "&lt;/script&gt;",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
