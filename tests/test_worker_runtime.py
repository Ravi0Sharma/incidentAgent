"""Worker execution, lease loss, and graceful-stop behavior."""

import asyncio
import unittest
from unittest.mock import patch

from webhook import worker


class WorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.job = {
            "job_id": 41,
            "incident_id": "INC-WORKER-1",
            "kind": "analyze",
        }

    async def test_empty_queue_is_reported_without_starting_a_handler(self):
        with patch.object(worker, "claim_next_job", return_value=None):
            result = await worker.process_one(lambda job: None, "worker-a")
        self.assertEqual(result, {"status": "empty"})

    async def test_completed_job_is_committed_by_its_lease_owner(self):
        async def handler(job):
            self.assertEqual(job, self.job)
            return {"revision": 7}

        with (
            patch.object(worker, "claim_next_job", return_value=self.job),
            patch.object(worker, "complete_job") as complete,
            patch.object(worker, "emit_log_event"),
        ):
            result = await worker.process_one(handler, "worker-a")

        self.assertEqual(result["status"], "completed")
        complete.assert_called_once_with(41, "worker-a")

    async def test_handler_failure_uses_the_durable_failure_path(self):
        async def handler(job):
            raise RuntimeError("temporary source outage")

        with (
            patch.object(worker, "claim_next_job", return_value=self.job),
            patch.object(worker, "fail_job", return_value="retry") as fail,
            patch.object(worker, "emit_log_event"),
        ):
            result = await worker.process_one(handler, "worker-a")

        self.assertEqual(result["status"], "retry")
        self.assertEqual(fail.call_args.args[0], self.job)
        self.assertEqual(fail.call_args.args[1], "worker-a")
        self.assertEqual(fail.call_args.args[3], 3)

    async def test_lost_lease_cancels_the_handler_without_committing(self):
        async def handler(job):
            await asyncio.Event().wait()

        async def lose_lease(job, worker_id, stop):
            raise worker.LeaseLostError("lease disappeared")

        with (
            patch.object(worker, "claim_next_job", return_value=self.job),
            patch.object(worker, "_maintain_lease", side_effect=lose_lease),
            patch.object(worker, "complete_job") as complete,
            patch.object(worker, "emit_log_event"),
        ):
            result = await worker.process_one(handler, "worker-a")

        self.assertEqual(result["status"], "lease_lost")
        complete.assert_not_called()

    async def test_run_forever_records_start_and_stop_heartbeats(self):
        stop = asyncio.Event()

        async def one_job(handler, worker_id):
            stop.set()
            return {"status": "empty"}

        with (
            patch.object(worker, "ensure_schema") as ensure,
            patch.object(worker, "record_worker_heartbeat") as heartbeat,
            patch.object(worker, "process_one", side_effect=one_job),
            patch.object(worker, "emit_log_event"),
        ):
            await worker.run_forever(lambda job: None, worker_id="worker-a", stop_event=stop)

        ensure.assert_called_once_with()
        self.assertEqual(heartbeat.call_args_list[0].args, ("worker-a", "running", None))
        self.assertEqual(heartbeat.call_args_list[-1].args, ("worker-a", "stopped", None))
