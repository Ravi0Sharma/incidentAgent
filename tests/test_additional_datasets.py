import csv
import os
from pathlib import Path
import tempfile
import unittest

from evaluation.hdfs_v1_dataset import (
    evaluate_hdfs_v1,
    parse_event_sequence,
)
from evaluation.openstack_dataset import (
    evaluate_openstack,
    parse_openstack_file,
)


class AdditionalDatasetTests(
    unittest.TestCase
):
    def test_hdfs_event_sequence_parser(self):
        self.assertEqual(
            parse_event_sequence(
                "[E1,E29,E4]"
            ),
            ["E1", "E29", "E4"],
        )

    def test_hdfs_truth_is_held_out_from_sampler(self):
        with tempfile.TemporaryDirectory() as root:
            pre = Path(root) / "preprocessed"
            pre.mkdir()
            (pre / "HDFS.log_templates.csv").write_text(
                "EventId,EventTemplate\n"
                "E1,Receiving block [*]\n"
                "E4,Got exception serving [*]\n",
                encoding="utf-8",
            )
            (pre / "anomaly_label.csv").write_text(
                "BlockId,Label\n"
                "blk_1,Normal\n"
                "blk_2,Anomaly\n",
                encoding="utf-8",
            )
            with (
                pre / "Event_traces.csv"
            ).open(
                "w",
                newline="",
                encoding="utf-8",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "BlockId",
                        "Label",
                        "Type",
                        "Features",
                        "TimeInterval",
                        "Latency",
                    ],
                )
                writer.writeheader()
                writer.writerows([
                    {
                        "BlockId": "blk_1",
                        "Label": "Success",
                        "Features": "[E1]",
                    },
                    {
                        "BlockId": "blk_2",
                        "Label": "Fail",
                        "Features": "[E1,E4]",
                    },
                ])
            report = evaluate_hdfs_v1(
                root,
                cases_per_truth=1,
                sample_limit=2,
            )
            self.assertTrue(
                report[
                    "truth_isolation"
                ][
                    "truth_exposed_to_sampler"
                ]
                is False
            )
            self.assertEqual(
                report[
                    "source_trace_rows"
                ],
                2,
            )
            self.assertTrue(
                report[
                    "quality_gate_passed"
                ]
            )

    def _openstack_fixture(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        vm = (
            "544fd51c-4edc-4780-"
            "baae-ba1d80a0acfc"
        )
        request = (
            "req-5a2050e7-b381-4ae9-"
            "92d2-8b08e9f9f4c0"
        )
        line = (
            "nova-compute.log.1 "
            "2017-05-14 19:39:02.007 "
            "2931 INFO nova.compute.manager "
            f"[{request} - - - - -] "
            f"[instance: {vm}] VM Resumed\n"
        )
        for name in (
            "openstack_abnormal.log",
            "openstack_normal1.log",
            "openstack_normal2.log",
        ):
            Path(root.name, name).write_text(
                line,
                encoding="utf-8",
            )
        Path(
            root.name,
            "anomaly_labels.txt",
        ).write_text(
            vm + "\n",
            encoding="utf-8",
        )
        return root.name, vm

    def test_openstack_parser_minimizes_identifiers(self):
        root, vm = self._openstack_fixture()
        records, stats = parse_openstack_file(
            os.path.join(
                root,
                "openstack_abnormal.log",
            )
        )
        self.assertEqual(
            stats["primary_records"], 1
        )
        self.assertNotIn(
            vm, records[0]["message"]
        )
        self.assertNotIn(
            vm,
            str(records[0]["labels"]),
        )

    def test_openstack_report_does_not_turn_label_into_rca(
        self,
    ):
        root, _ = self._openstack_fixture()
        report = evaluate_openstack(
            root,
            file_sample_limit=1,
            entity_sample_limit=1,
        )
        self.assertTrue(
            report[
                "quality_gate_passed"
            ]
        )
        self.assertEqual(
            report[
                "anomaly_truth_entities"
            ],
            1,
        )
        self.assertEqual(
            report[
                "anomaly_entities_with_catalog_signal"
            ],
            0,
        )
        self.assertIn(
            "not automatically observable",
            report["data_limit"],
        )


if __name__ == "__main__":
    unittest.main()
