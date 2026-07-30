import csv
import os
import tempfile
import unittest

from evaluation.loghub2_windows import (
    evaluate_template_grouping,
    load_loghub2_zookeeper_cases,
    load_linux_syslog_records,
    load_spark_explicit_window,
    load_spark_signal_cases,
)


class LogHub2WindowTests(unittest.TestCase):
    def _structured(self, root, rows):
        path = os.path.join(root, "structured.csv")
        with open(
            path,
            "w",
            newline="",
            encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "LineId",
                    "Content",
                    "EventId",
                    "EventTemplate",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_spark_selection_is_label_blind_and_retains_untimed_error(self):
        with tempfile.TemporaryDirectory() as root:
            raw = os.path.join(root, "Spark.log")
            lines = [
                "17/03/23 14:01:50 INFO Driver: Starting\n",
                "17/03/23 14:01:51 INFO Worker: Registered\n",
                "17/03/23 14:01:52 ERROR Worker: Container failed\n",
                "java.io.IOException: Cannot run program /private/tool\n",
                "17/03/23 14:01:53 INFO Worker: Retrying\n",
            ]
            with open(raw, "w", encoding="utf-8") as handle:
                handle.writelines(lines)
            structured = self._structured(
                root,
                [
                    {
                        "LineId": str(index),
                        "Content": line.strip(),
                        "EventId": f"E{index}",
                        "EventTemplate": f"template-{index}",
                    }
                    for index, line in enumerate(lines, 1)
                ],
            )

            cases, stats = load_spark_signal_cases(
                raw,
                case_limit=2,
                radius=1,
            )
            report = evaluate_template_grouping(
                cases,
                structured,
                dataset="fixture",
                sample_limit=20,
            )

        self.assertEqual(stats.get("unparsed_lines", 0), 0)
        self.assertEqual(stats["untimed_exception"], 1)
        self.assertTrue(cases)
        records = [
            record
            for spec in cases.values()
            for record in spec["records"]
        ]
        self.assertTrue(any(
            record["connector_metadata"]["timestamp_quality"]
            == "inferred_from_previous_event"
            for record in records
        ))
        self.assertNotIn("EventId", repr(cases))
        self.assertFalse(report["selection_used_template_truth"])
        self.assertTrue(
            report["template_truth_joined_after_selection"]
        )
        self.assertEqual(report["missing_template_truth_rows"], 0)

    def test_explicit_spark_window_keeps_previous_time_for_first_error(self):
        with tempfile.TemporaryDirectory() as root:
            raw = os.path.join(root, "Spark.log")
            with open(raw, "w", encoding="utf-8") as handle:
                handle.write(
                    "17/03/23 14:01:50 INFO Driver: Starting\n"
                    "java.io.IOException: failed to start\n"
                    "17/03/23 14:01:51 INFO Driver: Retrying\n"
                )

            records, stats = load_spark_explicit_window(
                raw,
                start_line=2,
                end_line=3,
            )

        self.assertEqual(stats["records"], 2)
        self.assertEqual(
            records[0]["connector_metadata"]["timestamp_quality"],
            "inferred_from_previous_event",
        )
        self.assertEqual(
            records[0]["connector_metadata"][
                "timestamp_ordering_scope"
            ],
            "source_relative",
        )
        self.assertEqual(
            records[0]["timestamp"],
            "2017-03-23T14:01:50+00:00",
        )

    def test_zookeeper_nested_threads_join_template_truth_after_selection(self):
        with tempfile.TemporaryDirectory() as root:
            raw = os.path.join(root, "Zookeeper.log")
            lines = [
                "2015-07-29 17:41:41,714 - INFO  "
                "[QuorumPeer[myid=1]/0:0:0:0:2181:QuorumPeer@670] - "
                "LOOKING\n",
                "2015-07-29 17:41:41,733 - WARN  "
                "[WorkerSender[myid=1]:QuorumCnxManager@368] - "
                "Cannot open channel\n",
                "2015-07-29 18:01:41,714 - INFO  "
                "[main:QuorumPeer@670] - FOLLOWING\n",
            ]
            with open(raw, "w", encoding="utf-8") as handle:
                handle.writelines(lines)
            structured = self._structured(
                root,
                [
                    {
                        "LineId": str(index),
                        "Content": line.strip(),
                        "EventId": f"Z{index}",
                        "EventTemplate": f"template-{index}",
                    }
                    for index, line in enumerate(lines, 1)
                ],
            )

            cases, stats = load_loghub2_zookeeper_cases(
                raw,
                per_cohort=1,
            )
            report = evaluate_template_grouping(
                cases,
                structured,
                dataset="fixture-zookeeper",
                sample_limit=20,
            )

        self.assertEqual(stats["parsed_events"], 3)
        self.assertEqual(report["missing_template_truth_rows"], 0)
        self.assertFalse(report["selection_used_template_truth"])
        self.assertNotIn("EventId", repr(cases))

    def test_linux_syslog_marks_missing_year_not_comparable(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".log",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(
                "Jun  9 06:06:20 combo kernel: "
                "Connection refused by 10.0.0.1\n"
            )
            path = handle.name
        self.addCleanup(lambda: os.unlink(path))

        records, stats = load_linux_syslog_records(path)

        self.assertEqual(stats["parsed_events"], 1)
        self.assertEqual(records[0]["labels"]["level"], "unknown")
        metadata = records[0]["connector_metadata"]
        self.assertEqual(metadata["timestamp_quality"], "year_missing")
        self.assertEqual(
            metadata["timestamp_ordering_scope"],
            "not_comparable",
        )
        self.assertNotIn("10.0.0.1", records[0]["message"])


if __name__ == "__main__":
    unittest.main()
