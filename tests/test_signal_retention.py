import unittest

from clients.loki_client import (
    representative_sample,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from utils.evidence_pack import (
    build_evidence_pack,
)
from utils.candidate_scoring import (
    score_candidates,
)
from utils.signal_catalog import (
    detect_signals,
)


def _log(index, message, level="info"):
    return {
        "timestamp": (
            "2026-07-28T10:"
            + f"{index // 60:02d}:"
            + f"{index % 60:02d}Z"
        ),
        "message": message,
        "labels": {
            "service": "hadoop",
            "level": level,
        },
    }


class SignalRetentionTests(
    unittest.TestCase
):
    def test_unclassified_error_is_observed_but_never_promoted(self):
        signals = detect_signals({
            "message":
            "opaque subsystem code XQ-19",
            "labels": {
                "service": "system",
                "level": "error",
            },
        })
        self.assertEqual(
            signals[0]["signal_family"],
            "unclassified_error",
        )
        self.assertTrue(
            signals[0]["observation_only"]
        )
        assessment = score_candidates({
            "log_groups": [{
                "event_id":
                "log-unclassified",
                "first_seen":
                "2026-07-29T10:00:00Z",
                "last_seen":
                "2026-07-29T10:00:00Z",
                "count": 1,
                "example_message":
                "opaque subsystem code XQ-19",
                "signals": signals,
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        observation = assessment[
            "observed_signals"
        ][0]
        self.assertEqual(
            observation[
                "impact_assessment"
            ]["impact_status"],
            "not_established",
        )
        self.assertFalse(
            observation[
                "cause_candidate_eligible"
            ]
        )
        self.assertEqual(
            assessment["candidates"], []
        )
        self.assertTrue(
            assessment["abstain"]
        )

    def test_specific_system_signals_replace_generic_error_fallback(self):
        cases = {
            "IOException: Got error for "
            "OP_READ_BLOCK":
            "storage_io",
            "Lustre mount FAILED":
            "storage_availability",
            "machine check interrupt":
            "machine_hardware",
            "Connection broken for peer":
            "network_transport",
            "caught end of stream exception":
            "connection_lifecycle",
        }
        for message, family in (
            cases.items()
        ):
            with self.subTest(
                message=message
            ):
                signals = detect_signals({
                    "message": message,
                    "labels": {
                        "service": "system",
                        "level": "error",
                    },
                })
                self.assertEqual(
                    signals[0][
                        "signal_family"
                    ],
                    family,
                )
                self.assertNotIn(
                    "unclassified_error",
                    {
                        signal[
                            "signal_family"
                        ]
                        for signal in signals
                    },
                )

    def test_new_system_observations_do_not_enter_candidate_whitelist(self):
        signals = detect_signals(
            "Lustre mount FAILED"
        )
        assessment = score_candidates({
            "log_groups": [{
                "event_id":
                "log-mount-failed",
                "first_seen":
                "2026-07-29T10:00:00Z",
                "last_seen":
                "2026-07-29T10:00:00Z",
                "count": 3,
                "example_message":
                "Lustre mount FAILED",
                "signals": signals,
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        self.assertEqual(
            len(
                assessment[
                    "observed_signals"
                ]
            ),
            1,
        )
        self.assertEqual(
            assessment["candidates"], []
        )
        self.assertTrue(
            assessment["abstain"]
        )

    def test_trace_only_timestamps_cannot_link_lifecycle_impact(self):
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id":
                    "log-unclassified",
                    "first_seen":
                    "2026-07-29T10:00:00Z",
                    "last_seen":
                    "2026-07-29T10:00:00Z",
                    "count": 1,
                    "example_message":
                    "opaque subsystem error",
                    "dimensions": {
                        "execution_id": {
                            "top": [{
                                "value": "trace-a",
                            }],
                        },
                    },
                    "time_quality": {
                        "ordering_scopes": [
                            "trace_only"
                        ],
                        "source_datasets": [
                            "tracebench"
                        ],
                    },
                    "signals": [{
                        "rule_id":
                        "source-level-unclassified-error",
                        "signal_family":
                        "unclassified_error",
                        "directness":
                        "direct",
                        "status":
                        "error_logged",
                    }],
                },
                {
                    "event_id":
                    "log-job-failed",
                    "first_seen":
                    "2026-07-29T10:00:01Z",
                    "last_seen":
                    "2026-07-29T10:00:01Z",
                    "count": 1,
                    "dimensions": {
                        "execution_id": {
                            "top": [{
                                "value": "trace-a",
                            }],
                        },
                    },
                    "time_quality": {
                        "ordering_scopes": [
                            "trace_only"
                        ],
                        "source_datasets": [
                            "tracebench"
                        ],
                    },
                    "signals": [{
                        "rule_id":
                        "job-state-failed",
                        "signal_family":
                        "job_lifecycle",
                        "directness":
                        "direct",
                        "status": "failed",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        impact = assessment[
            "observed_signals"
        ][0]["impact_assessment"]
        self.assertEqual(
            impact["time_relation"],
            "unknown",
        )
        self.assertEqual(
            impact["impact_status"],
            "not_established",
        )
        self.assertEqual(
            assessment["candidates"], []
        )
        pattern = assessment[
            "observation_patterns"
        ][0]
        self.assertEqual(
            pattern["time_span_status"],
            "not_comparable",
        )
        self.assertIsNone(
            pattern["first_seen"]
        )
        self.assertIsNone(
            pattern["last_seen"]
        )

    def test_impact_linked_catalog_signal_becomes_label_blind_candidate(
        self,
    ):
        assessment = score_candidates({
            "log_groups": [{
                "event_id": "log-node-lost",
                "count": 3,
                "example_message": (
                    "Container released on a "
                    "*lost* node"
                ),
                "signals": [{
                    "rule_id": "machine-lost-node",
                    "signal_family": "machine_availability",
                    "directness": "direct",
                    "status": "unavailable",
                }],
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        self.assertEqual(
            assessment["candidates"][0]["category"],
            "machine_down",
        )
        self.assertEqual(
            assessment["candidates"][0]["event_ids"],
            ["log-node-lost"],
        )
        self.assertFalse(
            assessment["abstain"]
        )
        self.assertEqual(
            assessment[
                "observed_signals"
            ][0]["impact_status"],
            "operation_effect_observed",
        )

    def test_unlinked_direct_signal_remains_observation_not_cause(
        self,
    ):
        assessment = score_candidates({
            "log_groups": [{
                "event_id": "log-host-down",
                "count": 1,
                "example_message": (
                    "worker host unavailable"
                ),
                "signals": [{
                    "rule_id":
                    "machine-lost-node",
                    "signal_family":
                    "machine_availability",
                    "directness": "direct",
                    "status": "unavailable",
                }],
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })

        self.assertEqual(
            assessment["candidates"],
            [],
        )
        self.assertEqual(
            len(
                assessment[
                    "observed_signals"
                ]
            ),
            1,
        )
        self.assertTrue(
            assessment["abstain"]
        )
        self.assertIn(
            "incident-impact link",
            " ".join(
                assessment[
                    "abstain_reasons"
                ]
            ),
        )

    def test_indirect_signal_does_not_become_cause_candidate(
        self,
    ):
        assessment = score_candidates({
            "log_groups": [{
                "event_id": "log-network-slow",
                "count": 8,
                "signals": [{
                    "rule_id": "network-latency",
                    "signal_family": "network_transport",
                    "directness": "indirect",
                    "status": "slow",
                }],
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        self.assertEqual(
            assessment["candidates"],
            [],
        )
        self.assertTrue(
            assessment["abstain"]
        )

    def test_catalog_distinguishes_direct_and_indirect_network_signals(
        self,
    ):
        direct = detect_signals(
            "java.net.NoRouteToHostException"
        )
        indirect = detect_signals(
            "Slow ReadProcessor took 40000ms"
        )
        self.assertEqual(
            direct[0]["directness"],
            "direct",
        )
        self.assertEqual(
            indirect[0]["directness"],
            "indirect",
        )

    def test_catalog_retains_hdfs_storage_observations_without_claiming_cause(
        self,
    ):
        read_failed = detect_signals(
            "WriteBlock received exception "
            "java.io.IOException: Could not read from stream"
        )
        metadata = detect_signals(
            "Unexpected error trying to delete block. "
            "BlockInfo not found in volumeMap."
        )
        self.assertEqual(
            read_failed[0]["signal_family"],
            "storage_io",
        )
        self.assertEqual(
            read_failed[0]["directness"],
            "direct",
        )
        self.assertEqual(
            metadata[0]["signal_family"],
            "storage_metadata",
        )

    def test_hdfs_explicit_read_failure_establishes_operation_not_cause(
        self,
    ):
        signals = detect_signals(
            "WriteBlock received exception: "
            "Could not read from stream"
        )
        assessment = score_candidates({
            "log_groups": [{
                "event_id":
                "log-block-read-failed",
                "first_seen":
                "2026-07-29T10:00:00Z",
                "last_seen":
                "2026-07-29T10:00:00Z",
                "count": 1,
                "example_message":
                "WriteBlock received exception: "
                "Could not read from stream",
                "dimensions": {
                    "execution_id": {
                        "top": [{
                            "value":
                            "block-scope-a",
                        }],
                    },
                },
                "signals": signals,
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        observation = assessment[
            "observed_signals"
        ][0]
        impact = observation[
            "impact_assessment"
        ]
        self.assertEqual(
            impact["impact_status"],
            "established",
        )
        self.assertEqual(
            impact["links"][0][
                "impact_kind"
            ],
            "block_operation_failed",
        )
        self.assertFalse(
            impact[
                "cause_candidate_eligible"
            ]
        )
        self.assertEqual(
            assessment["candidates"], []
        )

    def test_latency_deviation_survives_success_without_becoming_cause(
        self,
    ):
        feature = {
            "schema_version":
            "operation-duration-feature/v1",
            "feature_name":
            "operation_latency_deviation",
            "operation_name": "spawn",
            "status":
            "deviation_observed",
            "duration_seconds": 40,
            "baseline": {
                "schema_version":
                "peer-duration-baseline/v1",
                "baseline_id":
                "baseline-test",
                "peer_count": 20,
                "peer_median_seconds": 20,
                "peer_mad_seconds": 1,
                "duration_ratio": 2,
                "percentile_rank": 100,
                "robust_z": 13.49,
                "labels_used": False,
            },
        }
        grouped = aggregate_by_labels({
            "logs": [
                {
                    "timestamp":
                    "2026-07-29T10:00:40Z",
                    "message":
                    "Instance spawned successfully.",
                    "labels": {
                        "service": "openstack",
                        "level": "info",
                        "workload_id":
                        "instance-a",
                        "execution_id":
                        "instance-a",
                    },
                    "operation_feature":
                    feature,
                },
                {
                    "timestamp":
                    "2026-07-29T10:01:00Z",
                    "message":
                    "VM Resumed "
                    "(Lifecycle Event)",
                    "labels": {
                        "service": "openstack",
                        "level": "info",
                        "workload_id":
                        "instance-a",
                        "execution_id":
                        "instance-a",
                    },
                },
            ],
            "log_query": {
                "total_count": 2,
                "count_is_exact": True,
                "possibly_truncated":
                False,
            },
        })
        assessment = score_candidates({
            **grouped,
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        observation = assessment[
            "observed_signals"
        ][0]
        impact = observation[
            "impact_assessment"
        ]
        self.assertEqual(
            observation["signal_family"],
            "operation_latency",
        )
        self.assertEqual(
            impact["impact_status"],
            "established",
        )
        self.assertFalse(
            impact[
                "cause_candidate_eligible"
            ]
        )
        self.assertIn(
            "successful_completion_does_not_contradict"
            "_latency_deviation",
            impact["reason_codes"],
        )
        self.assertIn(
            "lifecycle_recovery_does_not_contradict"
            "_completed_latency_measurement",
            impact["reason_codes"],
        )
        self.assertFalse(
            observation[
                "recovery_observed"
            ]
        )
        self.assertTrue(
            observation[
                "successful_completion_observed"
            ]
        )
        state = {
            **grouped,
            "alert": {},
            "deterministic_assessment":
            assessment,
        }
        pack = build_evidence_pack(state)
        self.assertIn(
            "baseline-test", pack
        )
        self.assertIn(
            "labels_used=False", pack
        )
        self.assertIn(
            "successful_completion=True",
            pack,
        )

    def test_workload_lifecycle_is_outcome_context_not_fault_observation(
        self,
    ):
        lifecycle = detect_signals(
            "Instance spawned successfully."
        )
        self.assertEqual(
            lifecycle[0]["signal_family"],
            "workload_lifecycle",
        )
        assessment = score_candidates({
            "log_groups": [{
                "event_id": "log-spawned",
                "count": 1,
                "signals": lifecycle,
            }],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        self.assertEqual(
            assessment["observed_signals"],
            [],
        )
        self.assertEqual(
            assessment["candidates"],
            [],
        )

    def test_neutral_pause_context_is_not_recovery_or_adverse_impact(
        self,
    ):
        dimensions = {
            "execution_id": {
                "top": [{"value": "execution-a"}],
            },
        }
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id": "log-machine",
                    "first_seen": "2026-07-28T10:00:00Z",
                    "last_seen": "2026-07-28T10:00:00Z",
                    "count": 1,
                    "example_message": "worker host unavailable",
                    "dimensions": dimensions,
                    "signals": [{
                        "rule_id": "machine-lost-node",
                        "signal_family": "machine_availability",
                        "directness": "direct",
                        "status": "unavailable",
                    }],
                },
                {
                    "event_id": "log-paused",
                    "first_seen": "2026-07-28T10:01:00Z",
                    "last_seen": "2026-07-28T10:01:00Z",
                    "count": 1,
                    "dimensions": dimensions,
                    "signals": [{
                        "rule_id": "workload-state-paused",
                        "signal_family": "workload_lifecycle",
                        "directness": "direct",
                        "status": "paused",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {"source_failures": []},
        })
        impact = assessment["observed_signals"][0][
            "impact_assessment"
        ]
        self.assertEqual(impact["impact_status"], "not_established")
        self.assertEqual(impact["recovery_event_ids"], [])
        self.assertEqual(impact["outcome_event_ids"], ["log-paused"])
        self.assertFalse(impact["cause_candidate_eligible"])

    def test_job_lifecycle_does_not_treat_task_attempt_as_job_status(
        self,
    ):
        task = detect_signals(
            "attempt_1 TaskAttempt "
            "Transitioned from RUNNING "
            "to SUCCEEDED"
        )
        job = detect_signals(
            "job_[ID]Job Transitioned "
            "from COMMITTING to SUCCEEDED"
        )
        self.assertFalse(
            any(
                item["signal_family"]
                == "job_lifecycle"
                for item in task
            )
        )
        self.assertEqual(
            job[0]["scope"], "job"
        )

    def test_sampler_keeps_terminal_and_lost_node_signals(
        self,
    ):
        logs = [
            _log(
                index,
                f"task progress {index}",
            )
            for index in range(120)
        ]
        logs[70] = _log(
            70,
            "Container released on a "
            "*lost* node",
            "info",
        )
        logs[118] = _log(
            118,
            "job_1 transitioned from "
            "COMMITTING to SUCCEEDED",
            "info",
        )
        sampled = (
            representative_sample(
                logs, 20
            )
        )
        text = "\n".join(
            item["message"]
            for item in sampled
        )
        self.assertIn(
            "lost* node", text
        )
        self.assertIn(
            "SUCCEEDED", text
        )
        self.assertEqual(
            len(sampled), 20
        )

    def test_sampler_keeps_info_level_killed_event(
        self,
    ):
        logs = [
            _log(
                index,
                f"task progress {index}",
            )
            for index in range(240)
        ]
        logs[121] = _log(
            121,
            "Container killed by the "
            "ApplicationMaster; exit code 137",
            "info",
        )
        sampled = (
            representative_sample(
                logs, 30
            )
        )
        self.assertTrue(
            any(
                "exit code 137"
                in item["message"]
                for item in sampled
            )
        )

    def test_sampler_reserves_distinct_high_signal_shapes(
        self,
    ):
        logs = [
            _log(
                index,
                f"routine message {index}",
            )
            for index in range(30)
        ]
        logs.extend([
            _log(
                60,
                "connection refused by peer 123",
                "error",
            ),
            _log(
                61,
                "unexpected checksum mismatch 456",
                "error",
            ),
            _log(
                62,
                "replication queue is delayed",
                "warning",
            ),
        ])
        sampled = representative_sample(
            logs, 12
        )
        messages = {
            row["message"]
            for row in sampled
        }
        self.assertIn(
            "connection refused by peer 123",
            messages,
        )
        self.assertIn(
            "unexpected checksum mismatch 456",
            messages,
        )
        self.assertIn(
            "replication queue is delayed",
            messages,
        )

    def test_signal_group_is_visible_in_evidence_pack(
        self,
    ):
        groups = aggregate_by_labels({
            "logs": [
                _log(
                    1,
                    "normal progress",
                ),
                _log(
                    2,
                    "java.net."
                    "NoRouteToHostException",
                    "warn",
                ),
            ],
            "log_query": {
                "total_count": 2,
                "count_is_exact": True,
                "possibly_truncated":
                False,
            },
        })
        state = {
            **groups,
            "alert": {},
            "deterministic_assessment":
            {},
        }
        pack = build_evidence_pack(
            state
        )
        network = next(
            group
            for group in groups[
                "log_groups"
            ]
            if "network_transport"
            in group["signal_families"]
        )
        self.assertIn(
            network["event_id"],
            pack,
        )
        self.assertIn(
            "Signal Family Evidence",
            pack,
        )

    def test_repeated_shape_has_collapsed_burst_summary(
        self,
    ):
        groups = aggregate_by_labels({
            "logs": [
                _log(
                    index,
                    "Failed to connect to peer",
                    "error",
                )
                for index in range(5)
            ],
            "log_query": {
                "total_count": 5,
                "count_is_exact": True,
                "possibly_truncated":
                False,
            },
        })
        group = groups["log_groups"][0]

        self.assertTrue(
            group["burst"][
                "collapsed_repetition"
            ]
        )
        self.assertEqual(
            group["burst"][
                "repetitions"
            ],
            5,
        )

    def test_shared_scope_distinguishes_successful_completion_from_recovery(
        self,
    ):
        common = {
            "service": "hadoop",
            "level": "info",
            "workload_id":
            "workload-123456789abc",
            "execution_id":
            "execution-123456789abc",
        }
        grouped = aggregate_by_labels({
            "logs": [
                {
                    "timestamp":
                    "2026-07-28T10:00:00Z",
                    "message": (
                        "Container released on "
                        "a *lost* node"
                    ),
                    "labels": common,
                },
                {
                    "timestamp":
                    "2026-07-28T10:01:00Z",
                    "message": (
                        "job_[ID]Job Transitioned "
                        "from COMMITTING to "
                        "SUCCEEDED"
                    ),
                    "labels": common,
                },
            ],
            "log_query": {
                "total_count": 2,
                "count_is_exact": True,
                "possibly_truncated":
                False,
            },
        })
        assessment = score_candidates({
            **grouped,
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        observation = assessment[
            "observed_signals"
        ][0]

        self.assertFalse(
            observation[
                "recovery_observed"
            ]
        )
        self.assertTrue(
            observation[
                "successful_completion_observed"
            ]
        )
        self.assertTrue(
            any(
                link["impact_kind"]
                == "successful_completion_context"
                for link in observation[
                    "impact_links"
                ]
            )
        )
        self.assertEqual(
            observation["entities"][
                "execution_id"
            ],
            ["execution-123456789abc"],
        )

    def test_competing_observed_categories_force_abstention(
        self,
    ):
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id": "log-machine",
                    "count": 1,
                    "example_message": (
                        "Container released on "
                        "a *lost* node"
                    ),
                    "signals": [{
                        "rule_id":
                        "machine-lost-node",
                        "signal_family":
                        "machine_availability",
                        "directness": "direct",
                        "status": "unavailable",
                    }],
                },
                {
                    "event_id": "log-network",
                    "count": 1,
                    "example_message":
                    "NoRouteToHostException",
                    "signals": [{
                        "rule_id":
                        "network-no-route",
                        "signal_family":
                        "network_transport",
                        "directness": "direct",
                        "status": "unreachable",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })

        self.assertTrue(
            assessment["abstain"]
        )
        self.assertIn(
            (
                "direct observations span "
                "competing failure categories"
            ),
            assessment["abstain_reasons"],
        )

    def test_mismatched_execution_cannot_supply_adverse_impact(
        self,
    ):
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id": "log-machine",
                    "first_seen": "2026-07-28T10:00:00Z",
                    "last_seen": "2026-07-28T10:00:00Z",
                    "count": 1,
                    "example_message": "worker host unavailable",
                    "dimensions": {
                        "workload_id": {
                            "top": [{"value": "workload-a"}],
                        },
                        "execution_id": {
                            "top": [{"value": "execution-a"}],
                        },
                    },
                    "signals": [{
                        "rule_id": "machine-lost-node",
                        "signal_family": "machine_availability",
                        "directness": "direct",
                        "status": "unavailable",
                    }],
                },
                {
                    "event_id": "log-failed",
                    "first_seen": "2026-07-28T10:01:00Z",
                    "last_seen": "2026-07-28T10:01:00Z",
                    "count": 1,
                    "dimensions": {
                        "workload_id": {
                            "top": [{"value": "workload-a"}],
                        },
                        "execution_id": {
                            "top": [{"value": "execution-b"}],
                        },
                    },
                    "signals": [{
                        "rule_id": "job-failed",
                        "signal_family": "job_lifecycle",
                        "directness": "direct",
                        "status": "failed",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {"source_failures": []},
        })
        impact = assessment["observed_signals"][0][
            "impact_assessment"
        ]
        self.assertEqual(impact["entity_match"], "workload_only")
        self.assertEqual(impact["impact_status"], "not_established")
        self.assertEqual(impact["outcome_event_ids"], [])
        self.assertFalse(impact["cause_candidate_eligible"])
        self.assertEqual(assessment["candidates"], [])

    def test_outcome_before_signal_cannot_supply_adverse_impact(
        self,
    ):
        common_dimensions = {
            "execution_id": {
                "top": [{"value": "execution-a"}],
            },
        }
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id": "log-machine",
                    "first_seen": "2026-07-28T10:02:00Z",
                    "last_seen": "2026-07-28T10:02:00Z",
                    "count": 1,
                    "example_message": "worker host unavailable",
                    "dimensions": common_dimensions,
                    "signals": [{
                        "rule_id": "machine-lost-node",
                        "signal_family": "machine_availability",
                        "directness": "direct",
                        "status": "unavailable",
                    }],
                },
                {
                    "event_id": "log-failed",
                    "first_seen": "2026-07-28T10:01:00Z",
                    "last_seen": "2026-07-28T10:01:00Z",
                    "count": 1,
                    "dimensions": common_dimensions,
                    "signals": [{
                        "rule_id": "job-failed",
                        "signal_family": "job_lifecycle",
                        "directness": "direct",
                        "status": "failed",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {"source_failures": []},
        })
        impact = assessment["observed_signals"][0][
            "impact_assessment"
        ]
        self.assertEqual(impact["time_relation"], "before")
        self.assertEqual(impact["impact_status"], "not_established")
        self.assertEqual(impact["outcome_event_ids"], [])
        self.assertFalse(impact["cause_candidate_eligible"])

    def test_same_execution_later_failure_establishes_impact_not_cause(
        self,
    ):
        common_dimensions = {
            "execution_id": {
                "top": [{"value": "execution-a"}],
            },
        }
        assessment = score_candidates({
            "log_groups": [
                {
                    "event_id": "log-machine",
                    "first_seen": "2026-07-28T10:00:00Z",
                    "last_seen": "2026-07-28T10:00:00Z",
                    "count": 1,
                    "example_message": "worker host unavailable",
                    "dimensions": common_dimensions,
                    "signals": [{
                        "rule_id": "machine-lost-node",
                        "signal_family": "machine_availability",
                        "directness": "direct",
                        "status": "unavailable",
                    }],
                },
                {
                    "event_id": "log-failed",
                    "first_seen": "2026-07-28T10:01:00Z",
                    "last_seen": "2026-07-28T10:01:00Z",
                    "count": 1,
                    "dimensions": common_dimensions,
                    "signals": [{
                        "rule_id": "job-failed",
                        "signal_family": "job_lifecycle",
                        "directness": "direct",
                        "status": "failed",
                    }],
                },
            ],
            "detections": [],
            "incident_features": {"source_failures": []},
        })
        impact = assessment["observed_signals"][0][
            "impact_assessment"
        ]
        self.assertEqual(impact["entity_match"], "exact")
        self.assertEqual(impact["time_relation"], "after")
        self.assertEqual(impact["impact_status"], "established")
        self.assertEqual(
            impact["adverse_outcome_event_ids"],
            ["log-failed"],
        )
        self.assertTrue(impact["cause_candidate_eligible"])
        self.assertEqual(
            assessment["candidates"][0]["root_cause_status"],
            "not_established",
        )

    def test_repeated_observations_form_one_stable_review_pattern(
        self,
    ):
        groups = [
            {
                "event_id":
                f"log-opaque-{index:02d}",
                "first_seen":
                "2026-07-28T10:"
                + f"{index:02d}:00Z",
                "last_seen":
                "2026-07-28T10:"
                + f"{index:02d}:30Z",
                "count": index + 1,
                "example_message":
                f"opaque subsystem error {index}",
                "labels": {
                    "service": "compute",
                    "level": "error",
                },
                "dimensions": {
                    "host": {
                        "top": [{
                            "value":
                            f"host-{index % 4}",
                        }],
                    },
                },
                "time_quality": {
                    "source_timestamp_qualities": [
                        "timezone_assumed_utc"
                    ],
                    "ordering_scopes": [
                        "source_relative"
                    ],
                    "source_datasets": [
                        "bgl"
                    ],
                },
                "signals": [{
                    "rule_id":
                    "source-level-unclassified-error",
                    "signal_family":
                    "unclassified_error",
                    "directness": "direct",
                    "status": "error_logged",
                    "scope": "source_event",
                }],
            }
            for index in range(25)
        ]
        first = score_candidates({
            "log_groups": groups,
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        reversed_result = score_candidates({
            "log_groups": list(
                reversed(groups)
            ),
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })

        self.assertEqual(
            len(first["observed_signals"]),
            25,
        )
        self.assertEqual(
            first["observation_patterns"],
            reversed_result[
                "observation_patterns"
            ],
        )
        self.assertEqual(
            len(
                first[
                    "observation_patterns"
                ]
            ),
            1,
        )
        pattern = first[
            "observation_patterns"
        ][0]
        self.assertEqual(
            pattern["event_group_count"],
            25,
        )
        self.assertEqual(
            pattern["occurrence_count"],
            sum(range(1, 26)),
        )
        self.assertEqual(
            pattern[
                "omitted_event_group_count"
            ],
            5,
        )
        self.assertEqual(
            pattern["causal_status"],
            "not_established",
        )
        self.assertEqual(
            pattern["entities"]["host"][
                "unique"
            ],
            4,
        )
        self.assertEqual(
            first["candidates"], []
        )

        pack = build_evidence_pack({
            "alert": {},
            "log_groups": groups,
            "deterministic_assessment":
            first,
        })
        self.assertIn(
            "Correlated Observation Patterns",
            pack,
        )
        self.assertIn(
            "groups=25; occurrences=325",
            pack,
        )
        self.assertIn(
            "log-opaque-24",
            pack,
        )

    def test_observation_patterns_do_not_cross_service_or_impact_boundaries(
        self,
    ):
        groups = [
            {
                "event_id": "log-a",
                "count": 2,
                "labels": {
                    "service": "service-a",
                },
                "signals": [{
                    "rule_id": "opaque-a",
                    "signal_family":
                    "unclassified_error",
                    "directness": "direct",
                    "status": "error_logged",
                }],
            },
            {
                "event_id": "log-b",
                "count": 3,
                "labels": {
                    "service": "service-b",
                },
                "signals": [{
                    "rule_id": "opaque-b",
                    "signal_family":
                    "unclassified_error",
                    "directness": "direct",
                    "status": "error_logged",
                }],
            },
            {
                "event_id": "log-network",
                "count": 1,
                "example_message":
                "connection refused by peer",
                "labels": {
                    "service": "service-a",
                },
                "signals": [{
                    "rule_id":
                    "network-connection-refused",
                    "signal_family":
                    "network_transport",
                    "directness": "direct",
                    "status": "unreachable",
                }],
            },
        ]
        assessment = score_candidates({
            "log_groups": groups,
            "detections": [],
            "incident_features": {
                "source_failures": []
            },
        })
        patterns = assessment[
            "observation_patterns"
        ]
        self.assertEqual(
            len(patterns), 3
        )
        self.assertEqual(
            {
                (
                    item["service"],
                    item["signal_family"],
                    item["impact_status"],
                )
                for item in patterns
            },
            {
                (
                    "service-a",
                    "unclassified_error",
                    "not_established",
                ),
                (
                    "service-b",
                    "unclassified_error",
                    "not_established",
                ),
                (
                    "service-a",
                    "network_transport",
                    "established",
                ),
            },
        )
        self.assertEqual(
            [
                item["category"]
                for item in assessment[
                    "candidates"
                ]
            ],
            ["network_disconnection"],
        )


if __name__ == "__main__":
    unittest.main()
