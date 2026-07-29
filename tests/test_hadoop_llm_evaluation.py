import os
import tempfile
import unittest

from evaluation.hadoop_llm import (
    InterpreterResult,
    ModelInterpretation,
    evaluate_hadoop_llm,
    known_evidence_ids,
    select_stratified_cases,
    validate_interpretation,
)


class HadoopLLMEvaluationTests(
    unittest.TestCase
):
    def _dataset(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = temp.name
        labels = """### WordCount
Normal:
+ application_1_0001

Machine down:
+ application_1_0002

Network disconnection:
+ application_1_0003

Disk full:
+ application_1_0004
"""
        with open(
            os.path.join(
                root,
                "abnormal_label.txt",
            ),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(labels)
        messages = {
            "application_1_0001":
            "job completed successfully",
            "application_1_0002":
            "worker host unavailable",
            "application_1_0003":
            "network peer unreachable",
            "application_1_0004":
            "no space left on device",
        }
        for index, (
            application_id,
            message,
        ) in enumerate(
            messages.items(),
            start=1,
        ):
            directory = os.path.join(
                root,
                application_id,
            )
            os.makedirs(directory)
            with open(
                os.path.join(
                    directory,
                    "container.log",
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "2015-10-17 21:48:"
                    + f"{index:02d}"
                    + ",337 INFO [main] "
                    + "component: "
                    + message
                    + "\n"
                )
        return root

    def test_selection_balances_outcomes(
        self,
    ):
        labels = {
            f"application_{index}": {
                "workload": (
                    "A"
                    if index % 2
                    else "B"
                ),
                "outcome": outcome,
            }
            for index, outcome in enumerate(
                [
                    "normal",
                    "machine_down",
                    "network_disconnection",
                    "disk_full",
                    "normal",
                    "machine_down",
                    "network_disconnection",
                    "disk_full",
                ],
                start=1,
            )
        }
        selected = select_stratified_cases(
            labels,
            limit=8,
        )
        counts = {
            outcome: sum(
                item["outcome"]
                == outcome
                for item in selected
            )
            for outcome in {
                item["outcome"]
                for item in selected
            }
        }
        self.assertEqual(
            set(counts.values()),
            {2},
        )

    def test_unknown_citation_is_rejected(
        self,
    ):
        result = validate_interpretation(
            ModelInterpretation(
                classification=
                "machine_down",
                confidence="high",
                summary="Host unavailable.",
                evidence_ids=[
                    "invented-id"
                ],
            ),
            frozenset({"log-known"}),
        )
        self.assertFalse(
            result["citation_valid"]
        )
        self.assertFalse(
            result[
                "claim_contract_valid"
            ]
        )

    def test_visible_observation_pattern_is_a_valid_evidence_id(self):
        pattern_id = "observation-pattern-0123456789abcdef"
        state = {
            "deterministic_assessment": {
                "observation_patterns": [{
                    "pattern_id": pattern_id,
                }],
            },
        }
        known_ids = known_evidence_ids(state)
        result = validate_interpretation(
            ModelInterpretation(
                classification="network_disconnection",
                confidence="high",
                summary="Repeated unreachable-peer observations.",
                evidence_ids=[pattern_id],
            ),
            known_ids,
        )

        self.assertIn(pattern_id, known_ids)
        self.assertTrue(result["citation_valid"])
        self.assertTrue(result["claim_contract_valid"])

    def test_truth_is_not_exposed_to_interpreter(
        self,
    ):
        seen = []

        def interpreter(model_input):
            seen.append(model_input)
            return InterpreterResult(
                interpretation=(
                    ModelInterpretation(
                        classification=
                        "insufficient_evidence",
                        confidence="low",
                        summary=(
                            "The pack is not "
                            "discriminating."
                        ),
                        evidence_ids=[],
                        missing_evidence=[
                            "Direct failure evidence"
                        ],
                        timeline=[],
                    )
                ),
                model="fake",
                latency_ms=1,
                usage={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
                response_status="completed",
            )

        report = evaluate_hadoop_llm(
            self._dataset(),
            interpreter,
            case_limit=4,
            sample_limit=10,
        )
        self.assertEqual(
            len(seen), 4
        )
        self.assertTrue(
            report[
                "contract_gate_passed"
            ]
        )
        self.assertFalse(
            report[
                "truth_exposed_to_model"
            ]
        )
        self.assertEqual(
            report["metrics"][
                "unsupported_answer_rate"
            ],
            0.0,
        )
        self.assertIn(
            "recoverable_selective_accuracy",
            report["metrics"],
        )
        for model_input in seen:
            self.assertFalse(
                hasattr(
                    model_input, "truth"
                )
            )
            self.assertFalse(
                hasattr(
                    model_input,
                    "application_id",
                )
            )

    def test_prior_development_cases_can_be_excluded(
        self,
    ):
        def interpreter(model_input):
            return InterpreterResult(
                interpretation=(
                    ModelInterpretation(
                        classification=
                        "insufficient_evidence",
                        confidence="low",
                        summary="Not enough.",
                        missing_evidence=[
                            "Direct evidence"
                        ],
                    )
                ),
                model="fake",
                latency_ms=1,
                usage={},
                response_status="completed",
            )

        report = evaluate_hadoop_llm(
            self._dataset(),
            interpreter,
            case_limit=3,
            sample_limit=10,
            excluded_application_ids={
                "application_1_0001"
            },
        )
        self.assertEqual(
            report[
                "cases_requested"
            ],
            3,
        )
        self.assertEqual(
            report[
                "excluded_application_ids"
            ],
            ["application_1_0001"],
        )


if __name__ == "__main__":
    unittest.main()
