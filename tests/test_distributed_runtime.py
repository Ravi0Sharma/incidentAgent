"""Real process boundaries for checkpoint and multi-worker recovery."""

import unittest

from scripts.verify_distributed_runtime import run_probe


class DistributedRuntimeTests(unittest.TestCase):
    def test_multiple_processes_share_checkpoints_and_jobs(self):
        report = run_probe(jobs=12, workers=3)

        self.assertTrue(report["checkpoint"]["writer_pid_boundary"])
        self.assertEqual(report["multi_worker"]["jobs"], 13)
        self.assertGreaterEqual(
            report["multi_worker"]["distinct_worker_owners"],
            2,
        )
        self.assertEqual(report["multi_worker"]["recovered_jobs"], 1)
        self.assertEqual(report["multi_worker"]["revisions"], 13)
