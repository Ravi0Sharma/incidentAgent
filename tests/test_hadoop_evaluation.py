import os
import tempfile
import unittest

from evaluation.hadoop_dataset import (
    evaluate_hadoop,
    load_hadoop_labels,
    parse_hadoop_log_file,
)
from utils.detection_rules import (
    match_group,
)


class HadoopEvaluationTests(
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
        rows = {
            "application_1_0001": [
                (
                    "2015-10-17 21:48:16,337 "
                    "INFO [main] component: "
                    "job completed"
                ),
            ],
            "application_1_0002": [
                (
                    "2015-10-17 21:49:16,337 "
                    "WARN [main] component: "
                    "container_1_0002_01 "
                    "failed on msra-sa-41"
                ),
                (
                    "java.io.IOException: "
                    "connection reset"
                ),
            ],
        }
        for application_id, lines in (
            rows.items()
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
                    "\n".join(lines)
                    + "\n"
                )
        return root

    def test_labels_are_loaded_as_holdout_truth(
        self,
    ):
        labels = load_hadoop_labels(
            self._dataset()
        )
        self.assertEqual(
            labels[
                "application_1_0002"
            ]["outcome"],
            "machine_down",
        )

    def test_parser_attaches_stack_trace_and_minimizes_ids(
        self,
    ):
        root = self._dataset()
        path = os.path.join(
            root,
            "application_1_0002",
            "container.log",
        )
        records = parse_hadoop_log_file(
            path,
            "application_1_0002",
        )
        self.assertEqual(len(records), 1)
        message = records[0]["message"]
        self.assertIn(
            "java.io.IOException",
            message,
        )
        self.assertNotIn(
            "container_1_0002_01",
            message,
        )
        self.assertNotIn(
            "msra-sa-41",
            message,
        )
        self.assertRegex(
            records[0]["labels"][
                "workload_id"
            ],
            r"^workload-[0-9a-f]{12}$",
        )
        self.assertRegex(
            records[0]["labels"][
                "execution_id"
            ],
            r"^execution-[0-9a-f]{12}$",
        )
        self.assertNotIn(
            "application_1_0002",
            records[0]["labels"][
                "workload_id"
            ],
        )

    def test_end_to_end_report_keeps_truth_out_of_pipeline(
        self,
    ):
        report = evaluate_hadoop(
            self._dataset(),
            sample_limit=10,
        )
        self.assertEqual(
            report[
                "applications_total"
            ],
            2,
        )
        self.assertFalse(
            report[
                "truth_exposed_to_pipeline"
            ]
        )
        self.assertTrue(
            report[
                "quality_gate_passed"
            ]
        )

    def test_applicationmaster_exit_137_is_not_claimed_as_oom(
        self,
    ):
        group = {
            "labels": {
                "service": "hadoop",
                "level": "info",
            },
            "example_message": (
                "Container killed by the "
                "ApplicationMaster. Exit "
                "code is 137."
            ),
        }
        ids = {
            item["id"]
            for item in match_group(group)
        }
        self.assertNotIn(
            "oom-killed", ids
        )

    def test_explicit_oom_evidence_still_matches(
        self,
    ):
        group = {
            "labels": {
                "service": "payments",
                "level": "error",
            },
            "example_message": (
                "Memory cgroup out of "
                "memory: process killed "
                "by the kernel"
            ),
        }
        ids = {
            item["id"]
            for item in match_group(group)
        }
        self.assertIn(
            "oom-killed", ids
        )

    def test_glued_job_id_is_minimized(
        self,
    ):
        from evaluation.hadoop_dataset import (
            sanitize_hadoop_message,
        )

        value = sanitize_hadoop_message(
            "job_1445062781478_0011Job "
            "Transitioned from COMMITTING "
            "to SUCCEEDED"
        )
        self.assertNotIn(
            "1445062781478", value
        )
        self.assertIn(
            "job_[ID]Job", value
        )


if __name__ == "__main__":
    unittest.main()
