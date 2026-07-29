import os
import tempfile
import unittest

from evaluation.distributed_log_datasets import (
    _load_openstack_operation_features,
    _sanitize_openstack,
    load_bgl_cases,
    load_hdfs_v1_cases,
    load_hdfs_v3_cases,
    load_openstack_cases,
    load_zookeeper_cases,
)
from scripts.evaluate_distributed_openai import (
    _unsupported_numeric_claims,
)


class DistributedLogDatasetTests(unittest.TestCase):
    def test_openstack_minimizes_uuid_before_underscore_suffix(self):
        identifier = (
            "d9e8cd9a-6202-4dbf-a7ec-138c0249f026"
        )
        sanitized = _sanitize_openstack(
            "/var/lib/nova/instances/"
            + identifier
            + "_del"
        )
        self.assertNotIn(
            identifier, sanitized
        )
        self.assertIn(
            "[UUID]_del", sanitized
        )

    def test_percentage_claim_requires_evidence_or_sample_fraction(self):
        payload = {
            "evidence_gaps": [
                "Only 7.21% was sampled."
            ]
        }
        self.assertEqual(
            _unsupported_numeric_claims(
                payload
            ),
            ["7.21%"],
        )
        self.assertEqual(
            _unsupported_numeric_claims(
                payload,
                "sampling_bias={'sampled_fraction': "
                "0.0721}",
            ),
            [],
        )

    def test_zookeeper_adapter_handles_continuations_without_truth(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(
                root, "Zookeeper.log"
            )
            with open(
                path, "w", encoding="utf-8"
            ) as handle:
                handle.write(
                    "2015-07-29 17:41:41,536 - INFO  "
                    "[main:QuorumPeerConfig@101] - "
                    "Reading configuration\n"
                    "continuation detail\n"
                    "2015-07-29 17:51:41,536 - ERROR "
                    "[main:QuorumPeer@9] - "
                    "Connection refused by 10.0.0.1\n"
                )
            cases, stats = (
                load_zookeeper_cases(
                    path,
                    per_cohort=1,
                )
            )
        self.assertEqual(
            stats["parsed_events"], 2
        )
        self.assertEqual(
            stats["continuation_lines"], 1
        )
        self.assertTrue(cases)
        self.assertTrue(all(
            spec["truth"] == "unlabeled"
            for spec in cases.values()
        ))
        messages = " ".join(
            record["message"]
            for spec in cases.values()
            for record in spec["records"]
        )
        self.assertNotIn(
            "10.0.0.1", messages
        )

    def test_zookeeper_adapter_parses_nested_thread_brackets(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "Zookeeper.log")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "2015-07-29 17:41:41,714 - INFO  "
                    "[QuorumPeer[myid=1]/0:0:0:0:0:0:0:0:2181:"
                    "QuorumPeer@670] - LOOKING\n"
                    "2015-07-29 17:41:41,733 - WARN  "
                    "[WorkerSender[myid=1]:QuorumCnxManager@368] - "
                    "Cannot open channel\n"
                )

            cases, stats = load_zookeeper_cases(
                path,
                per_cohort=1,
            )

        self.assertEqual(stats["parsed_events"], 2)
        self.assertEqual(stats.get("continuation_lines", 0), 0)
        components = {
            record["labels"]["source_component"]
            for spec in cases.values()
            for record in spec["records"]
        }
        self.assertEqual(
            components,
            {"QuorumPeer", "QuorumCnxManager"},
        )

    def test_bgl_adapter_holds_out_alert_tag(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(
                root, "BGL.log"
            )
            with open(
                path, "w", encoding="utf-8"
            ) as handle:
                handle.write(
                    "- 1 2005.06.03 NODE-A "
                    "2005-06-03-15.42.50.000001 "
                    "NODE-A RAS KERNEL INFO corrected\n"
                    "KERNDTLB 2 2005.06.03 NODE-B "
                    "2005-06-03-15.52.50.000001 "
                    "NODE-B RAS KERNEL FATAL failed\n"
                )
            cases, stats = load_bgl_cases(
                path, per_label=1
            )
        self.assertEqual(
            stats["unparsed_lines"], 0
        )
        self.assertEqual(
            {
                spec["truth"]
                for spec in cases.values()
            },
            {"alert", "non_alert"},
        )
        evidence_text = " ".join(
            record["message"]
            + " "
            + str(record["labels"])
            for spec in cases.values()
            for record in spec["records"]
        )
        self.assertNotIn(
            "KERNDTLB", evidence_text
        )
        self.assertNotIn(
            "NODE-A", evidence_text
        )

    def test_tracebench_adapter_holds_out_fault_directory(self):
        with tempfile.TemporaryDirectory() as root:
            trace_root = os.path.join(
                root, "tracebench"
            )
            for directory in (
                "AN_Net_disconnectDN_r_fixture",
                "NM_CL_fixture",
            ):
                path = os.path.join(
                    trace_root, directory
                )
                os.makedirs(path)
                with open(
                    os.path.join(
                        path, "trace.csv"
                    ),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        "TaskID,Title,NumReports,"
                        "NumEdges,FirstSeen,LastUpdated,"
                        "StartTime,EndTime\n"
                        "TASK-1,read,1,0,"
                        "2013-11-04 13:54:35,"
                        "2013-11-04 13:54:36,1,2\n"
                    )
                with open(
                    os.path.join(
                        path, "event.csv"
                    ),
                    "w",
                    encoding="utf-8",
                ) as handle:
                    handle.write(
                        "TaskID,TID,OpName,StartTime,"
                        "EndTime,HostAddress,HostName,"
                        "Agent,Description\n"
                        "TASK-1,T1,readBlock,1,2,"
                        "10.0.0.1,node,DataNode,"
                        + (
                            "connection refused by 10.0.0.1\n"
                            if directory.startswith(
                                "AN_"
                            )
                            else "Success: checksumOk\n"
                        )
                    )
            cases, stats = (
                load_hdfs_v3_cases(
                    root, per_cohort=1
                )
            )
        self.assertEqual(
            stats["fault_metadata_exposed"], 0
        )
        self.assertEqual(len(cases), 2)
        self.assertEqual(
            {
                spec["truth"]
                for spec in cases.values()
            },
            {"failure", "normal"},
        )
        for spec in cases.values():
            record = spec["records"][0]
            self.assertNotIn(
                "TASK-1", record["message"]
            )
            self.assertNotIn(
                "10.0.0.1", record["message"]
            )
            self.assertEqual(
                record[
                    "connector_metadata"
                ][
                    "timestamp_quality"
                ],
                "coarse_trace_first_seen",
            )
        normal = next(
            spec
            for spec in cases.values()
            if spec["truth"] == "normal"
        )
        self.assertEqual(
            normal["records"][0][
                "labels"
            ]["level"],
            "info",
        )

    def test_hdfs_adapter_holds_out_labels_and_minimizes_block_scope(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(
                os.path.join(root, "preprocessed")
            )
            with open(
                os.path.join(
                    root,
                    "preprocessed",
                    "anomaly_label.csv",
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "BlockId,Label\n"
                    "blk_-1,Anomaly\n"
                    "blk_2,Normal\n"
                )
            with open(
                os.path.join(root, "HDFS.log"),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "081109 203518 143 WARN dfs.DataNode: "
                    "Could not read from stream for blk_-1 "
                    "at 10.0.0.1\n"
                    "081109 203519 143 INFO dfs.DataNode: "
                    "Received block blk_2 from 10.0.0.2\n"
                )
            cases, _ = load_hdfs_v1_cases(
                root, per_label=1
            )
            self.assertEqual(len(cases), 2)
            anomaly = cases["blk_-1"]
            self.assertEqual(
                anomaly["truth"], "anomaly"
            )
            record = anomaly["records"][0]
            self.assertNotIn(
                "blk_-1", record["message"]
            )
            self.assertNotIn(
                "10.0.0.1", record["message"]
            )
            self.assertTrue(
                record["labels"][
                    "execution_id"
                ].startswith("block-")
            )

    def test_openstack_adapter_deduplicates_selected_instances(self):
        anomaly_id = (
            "11111111-1111-1111-1111-111111111111"
        )
        normal_a = (
            "22222222-2222-2222-2222-222222222222"
        )
        normal_b = (
            "33333333-3333-3333-3333-333333333333"
        )
        prefix = (
            "nova-compute.log "
            "2017-05-16 00:00:00.008 "
            "1 INFO nova.compute.manager "
        )
        with tempfile.TemporaryDirectory() as root:
            with open(
                os.path.join(
                    root, "anomaly_labels.txt"
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(anomaly_id + "\n")
            with open(
                os.path.join(
                    root, "openstack_abnormal.log"
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    prefix
                    + "[instance: "
                    + anomaly_id
                    + "] Instance spawned successfully.\n"
                )
            with open(
                os.path.join(
                    root, "openstack_normal1.log"
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    prefix
                    + "[instance: "
                    + normal_a
                    + "] Instance spawned successfully.\n"
                )
                handle.write(
                    prefix
                    + "[instance: "
                    + normal_a
                    + "] VM Resumed (Lifecycle Event)\n"
                )
            with open(
                os.path.join(
                    root, "openstack_normal2.log"
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    prefix
                    + "[instance: "
                    + normal_b
                    + "] Instance spawned successfully.\n"
                )
            cases, _ = load_openstack_cases(
                root, normal_limit=2
            )
            self.assertEqual(len(cases), 3)
            self.assertEqual(
                sum(
                    spec["truth"] == "normal"
                    for spec in cases.values()
                ),
                2,
            )
            for identifier, spec in cases.items():
                for record in spec["records"]:
                    self.assertNotIn(
                        identifier,
                        record["message"],
                    )

    def test_openstack_duration_feature_is_built_without_label_file(self):
        with tempfile.TemporaryDirectory() as root:
            outlier_id = (
                "00000000-0000-0000-0000-"
                "000000000000"
            )
            with open(
                os.path.join(
                    root,
                    "openstack_abnormal.log",
                ),
                "w",
                encoding="utf-8",
            ) as handle:
                for index in range(21):
                    identifier = (
                        "00000000-0000-0000-0000-"
                        + f"{index:012d}"
                    )
                    duration = (
                        40
                        if index == 0
                        else 19
                        + index % 3
                    )
                    prefix = (
                        "nova-compute.log "
                        "2017-05-16 "
                    )
                    handle.write(
                        prefix
                        + "10:00:00.000 "
                        + f"{index} INFO "
                        + "nova.compute.manager "
                        + "[instance: "
                        + identifier
                        + "] Attempting claim\n"
                    )
                    handle.write(
                        prefix
                        + "10:00:"
                        + f"{duration:02d}.000 "
                        + f"{index} INFO "
                        + "nova.compute.manager "
                        + "[instance: "
                        + identifier
                        + "] Instance spawned "
                        + "successfully.\n"
                    )
            for name in (
                "openstack_normal1.log",
                "openstack_normal2.log",
            ):
                with open(
                    os.path.join(root, name),
                    "w",
                    encoding="utf-8",
                ):
                    pass
            features, stats = (
                _load_openstack_operation_features(
                    root
                )
            )
        self.assertEqual(
            stats[
                "complete_spawn_operations"
            ],
            21,
        )
        self.assertFalse(
            stats["baseline_labels_used"]
        )
        self.assertEqual(
            features[outlier_id]["status"],
            "deviation_observed",
        )


if __name__ == "__main__":
    unittest.main()
