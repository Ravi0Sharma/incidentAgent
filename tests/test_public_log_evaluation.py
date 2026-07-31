import csv
import os
import tempfile
import unittest

from evaluation.public_log_dataset import (
    evaluate_loghub_hdfs,
    load_loghub_hdfs_csv,
    load_loghub_spark_csv,
    parse_loghub_spark_raw,
    sanitize_spark_message,
    spark_record_signature,
)
from graph.nodes.aggregate_by_labels import (
    _fingerprint,
)


class PublicLogEvaluationTests(
    unittest.TestCase
):
    def _fixture(self):
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            newline="",
            delete=False,
            encoding="utf-8",
        )
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "LineId",
                "Date",
                "Time",
                "Pid",
                "Level",
                "Component",
                "Content",
                "EventId",
                "EventTemplate",
            ],
        )
        writer.writeheader()
        writer.writerows([
            {
                "LineId": "1",
                "Date": "081109",
                "Time": "203615",
                "Pid": "148",
                "Level": "INFO",
                "Component": "DataNode",
                "Content": (
                    "Received blk_123 from "
                    "10.1.2.3 /user/alice/job"
                ),
                "EventId": "E1",
                "EventTemplate":
                "Received <*>",
            },
            {
                "LineId": "2",
                "Date": "081109",
                "Time": "203616",
                "Pid": "149",
                "Level": "WARN",
                "Component": "DataNode",
                "Content": (
                    "Failed blk_-987 from "
                    "10.1.2.4 /user/bob/job"
                ),
                "EventId": "E2",
                "EventTemplate":
                "Failed <*>",
            },
        ])
        handle.close()
        self.addCleanup(
            lambda: os.unlink(handle.name)
        )
        return handle.name

    def test_loader_minimizes_dataset_specific_identifiers(
        self,
    ):
        records, _ = load_loghub_hdfs_csv(
            self._fixture()
        )
        text = " ".join(
            record["message"]
            for record in records
        )
        self.assertNotIn(
            "10.1.2.3", text
        )
        self.assertNotIn(
            "blk_123", text
        )
        self.assertNotIn(
            "/user/alice", text
        )

    def test_public_report_stays_within_robustness_scope(
        self,
    ):
        report = evaluate_loghub_hdfs(
            self._fixture(),
            sample_limit=2,
        )
        self.assertEqual(
            report["source_rows"], 2
        )
        self.assertTrue(
            report[
                "timestamps_valid_utc"
            ]
        )
        self.assertTrue(
            report[
                "dataset_specific_minimization"
            ]
        )
        self.assertTrue(
            report[
                "order_invariant_groups"
            ]
        )
        self.assertTrue(
            report[
                "quality_gate_passed"
            ]
        )
        self.assertIn(
            "robustness only",
            report["scope"],
        )

    def test_fingerprint_removes_embedded_volatile_numbers(
        self,
    ):
        first = _fingerprint(
            "allocate task_000742 "
            "subdir51 blk_[ID]"
        )
        second = _fingerprint(
            "allocate task_000590 "
            "subdir5 blk_[ID] blk_[ID]"
        )
        self.assertEqual(first, second)

    def test_fingerprint_normalizes_signed_measurements_and_units(
        self,
    ):
        first = _fingerprint(
            "Times: total = 900 ms, boot = -4 ms"
        )
        second = _fingerprint(
            "Times: total = 2 seconds, boot = 8 ms"
        )
        self.assertEqual(first, second)
        self.assertEqual(
            _fingerprint(
                "Block x estimated size 900 B"
            ),
            _fingerprint(
                "Block x estimated size 5.2 KB"
            ),
        )

    def test_fingerprint_normalizes_embedded_human_timestamps(self):
        self.assertEqual(
            _fingerprint(
                "connection from [IP] at Sat Nov 25 23:10:12 2006"
            ),
            _fingerprint(
                "connection from [IP] at Tue Jun 9 06:06:20 2004"
            ),
        )

    def test_spark_raw_and_structured_adapters_are_label_blind(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            structured = os.path.join(
                root, "Spark.csv"
            )
            raw = os.path.join(
                root, "Spark.log"
            )
            with open(
                structured,
                "w",
                newline="",
                encoding="utf-8",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "LineId",
                        "Date",
                        "Time",
                        "Level",
                        "Component",
                        "Content",
                        "EventId",
                        "EventTemplate",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "LineId": "1",
                    "Date": "17/06/09",
                    "Time": "20:10:40",
                    "Level": "INFO",
                    "Component":
                    "executor.Executor",
                    "Content": (
                        "Connecting to hdfs://10.1.2.3:9000/"
                        "alice/job application_123_45 on "
                        "mesos-slave-07 "
                        "70293f72-844a-4b39-9ad6-fb0ad7e364e4"
                    ),
                    "EventId": "E-secret",
                    "EventTemplate":
                    "Connecting to <*>",
                })
            with open(
                raw,
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "17/06/09 20:10:40 INFO executor.Executor: "
                    "Connecting to hdfs://10.1.2.3:9000/alice/job "
                    "application_123_45 on mesos-slave-07 "
                    "70293f72-844a-4b39-9ad6-fb0ad7e364e4\n"
                )
            structured_records, source_rows = (
                load_loghub_spark_csv(
                    structured
                )
            )
            raw_records, unparsed = (
                parse_loghub_spark_raw(raw)
            )
        self.assertEqual(unparsed, [])
        self.assertEqual(
            spark_record_signature(
                structured_records[0]
            ),
            spark_record_signature(
                raw_records[0]
            ),
        )
        self.assertNotIn(
            "EventId",
            repr(structured_records[0]),
        )
        self.assertEqual(
            source_rows[0]["event_id"],
            "E-secret",
        )
        minimized = (
            structured_records[0][
                "message"
            ]
        )
        for secret in (
            "10.1.2.3",
            "/alice/",
            "application_123_45",
            "mesos-slave-07",
            "70293f72-844a-4b39-9ad6-fb0ad7e364e4",
        ):
            self.assertNotIn(
                secret,
                minimized,
            )

    def test_spark_raw_adapter_retains_untimed_exception_event(self):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".log",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(
                "17/03/23 14:01:54 INFO Proxy: Opening proxy\n"
                'Exception in thread "ContainerLauncher-0" '
                "java.lang.Error: org.apache.spark.SparkException: "
                "Exception while starting container container_123 "
                "on host mesos-slave-16\n"
                "java.io.IOException: Cannot run program /private/tool\n"
            )
            path = handle.name
        self.addCleanup(lambda: os.unlink(path))

        records, unparsed = parse_loghub_spark_raw(path)

        self.assertEqual(unparsed, [])
        self.assertEqual(len(records), 3)
        exception = records[1]
        self.assertEqual(
            exception["labels"]["level"],
            "error",
        )
        self.assertEqual(
            exception["labels"]["source_component"],
            "unattributed_exception",
        )
        self.assertEqual(
            exception["connector_metadata"]["timestamp_quality"],
            "inferred_from_previous_event",
        )
        self.assertEqual(
            exception["connector_metadata"][
                "timestamp_ordering_scope"
            ],
            "source_relative",
        )
        self.assertEqual(
            exception["timestamp"],
            records[0]["timestamp"],
        )
        self.assertNotIn(
            "mesos-slave-16",
            exception["message"],
        )
        self.assertIn(
            "Cannot run program",
            records[2]["message"],
        )
        self.assertEqual(
            records[2]["labels"]["level"],
            "error",
        )

    def test_spark_acl_values_are_minimized(
        self,
    ):
        self.assertEqual(
            sanitize_spark_message(
                "Changing view acls to: yarn,curi"
            ),
            "Changing view acls to: [USER_SET]",
        )


if __name__ == "__main__":
    unittest.main()
