import hashlib
import json
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pymysql

from webhook import registry
from webhook import rate_limit
from webhook import incident_store
from webhook.incident_store import (
    QueueCapacityError,
    claim_next_job,
    complete_job,
    create_revision,
    enqueue_reprocessing,
    fail_job,
    list_dead_letters,
    list_events,
    record_event,
    record_event_and_enqueue,
    record_worker_heartbeat,
    renew_job_lease,
    replay_dead_letter,
    worker_runtime_status,
)


class MySQLIncidentLifecycleTests(unittest.TestCase):
    """Integration coverage for the durable Area 2 incident records."""

    def setUp(self):
        self.incident_id = "INC-TEST-" + uuid.uuid4().hex[:16]
        self.other_incident_id = "INC-TEST-" + uuid.uuid4().hex[:16]
        self.worker_id = "worker-test-" + uuid.uuid4().hex[:16]

    def tearDown(self):
        with registry._connection() as conn, conn.cursor() as cur:
            for incident_id in (self.incident_id, self.other_incident_id):
                cur.execute("DELETE FROM incident_job_locks WHERE incident_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_dead_letters WHERE incident_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_jobs WHERE incident_id=%s", (incident_id,))
                cur.execute("DELETE FROM pending_reviews WHERE thread_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_lifecycle WHERE thread_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_revisions WHERE incident_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_revision_heads WHERE incident_id=%s", (incident_id,))
                cur.execute("DELETE FROM incident_events WHERE incident_id=%s", (incident_id,))
            cur.execute("DELETE FROM incident_workers WHERE worker_id=%s", (self.worker_id,))
            conn.commit()

    def test_event_idempotency_revision_and_lifecycle_are_durable(self):
        payload = {"alertname": "HighLatency", "service": "checkout"}
        key = hashlib.sha256(self.incident_id.encode("utf-8")).hexdigest()
        inserted = record_event(self.incident_id, key, "firing", payload)
        duplicate = record_event(self.incident_id, key, "firing", payload)
        self.assertTrue(inserted["inserted"])
        self.assertFalse(duplicate["inserted"])

        self.assertEqual(create_revision(self.incident_id, "new observation"), 1)
        self.assertEqual(registry.transition_lifecycle(self.incident_id, "received")["version"], 1)
        state = registry.transition_lifecycle(self.incident_id, "collecting", expected_version=1)
        self.assertEqual(state["status"], "collecting")
        self.assertEqual(registry.get_lifecycle(self.incident_id)["version"], 2)

    def test_job_claim_retries_a_transient_mysql_deadlock(self):
        expected = {"job_id": 17, "incident_id": self.incident_id}
        deadlock = pymysql.err.OperationalError(1213, "deadlock")
        with patch.object(
            incident_store,
            "_claim_next_job_once",
            side_effect=[deadlock, expected],
        ) as claim_once, patch.object(incident_store.time, "sleep") as sleep:
            self.assertEqual(claim_next_job("retry-worker"), expected)
        self.assertEqual(claim_once.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_stale_writer_cannot_overwrite_pending_review_or_lifecycle(self):
        pending = registry.add_pending(self.incident_id, {"alertname": "HighLatency"})
        with self.assertRaises(registry.RevisionConflictError):
            registry.add_pending(
                self.incident_id,
                {"alertname": "stale write"},
                expected_version=pending["pending_revision"] - 1,
            )

        registry.transition_lifecycle(self.incident_id, "received")
        with self.assertRaises(registry.RevisionConflictError):
            registry.transition_lifecycle(
                self.incident_id,
                "collecting",
                expected_version=0,
            )

    def test_event_before_ack_queue_lease_and_timeline_order(self):
        late = record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "late").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
            event_time="2026-07-21T11:00:00+00:00",
            source_time="2026-07-21T11:00:00+00:00",
            clock_quality="source_timestamp_present",
        )
        early = record_event(
            self.incident_id,
            hashlib.sha256((self.incident_id + "early").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
            event_time="2026-07-21T10:00:00+00:00",
            source_time="2026-07-21T10:00:00+00:00",
            clock_quality="source_timestamp_present",
        )
        self.assertTrue(late["queued"])
        self.assertTrue(early["inserted"])
        self.assertEqual([item["event_id"] for item in list_events(self.incident_id)], [early["event_id"], late["event_id"]])

        job = claim_next_job("test-worker")
        self.assertEqual(job["event_id"], late["event_id"])
        complete_job(job["job_id"], "test-worker")

    def test_alertmanager_zulu_timestamp_is_persisted_as_utc_datetime(self):
        event = record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "zulu").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
            event_time="2026-07-14T10:03:12.000Z",
            source_time="2026-07-14T12:03:12.000+02:00",
            clock_quality="source_timestamp_present",
        )

        stored = next(
            item
            for item in list_events(self.incident_id)
            if item["event_id"] == event["event_id"]
        )
        self.assertEqual(stored["event_time"], "2026-07-14T10:03:12")
        self.assertEqual(stored["source_time"], "2026-07-14T10:03:12")

    def test_exhausted_job_is_dead_lettered_and_can_be_replayed(self):
        event = record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "dead").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency", "token": "secret"},
        )
        job = claim_next_job("test-worker")
        self.assertEqual(fail_job(job, "test-worker", RuntimeError("test failure token=secret"), max_attempts=1), "dead_letter")
        dead = list_dead_letters(self.incident_id)
        self.assertEqual(len(dead), 1)
        self.assertNotIn("secret", str(dead[0]))
        self.assertTrue(replay_dead_letter(event["job_id"])["replayed"])

    def test_queue_capacity_rejects_before_event_or_job_is_committed(self):
        with self.assertRaisesRegex(QueueCapacityError, "admission is disabled"):
            record_event_and_enqueue(
                self.incident_id,
                hashlib.sha256((self.incident_id + "capacity").encode()).hexdigest(),
                "firing",
                {"alertname": "HighLatency"},
                max_pending_jobs=0,
            )
        self.assertEqual(list_events(self.incident_id), [])

    def test_reprocessing_uses_the_same_queue_capacity_gate(self):
        record_event(
            self.incident_id,
            hashlib.sha256((self.incident_id + "stored").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
        )
        with self.assertRaisesRegex(QueueCapacityError, "admission is disabled"):
            enqueue_reprocessing(self.incident_id, max_pending_jobs=0)

    def test_worker_liveness_requires_a_running_recent_heartbeat(self):
        record_worker_heartbeat(self.worker_id, "running")
        self.assertEqual(worker_runtime_status(15)["status"], "ready")
        record_worker_heartbeat(self.worker_id, "stopped")
        status = worker_runtime_status(15)
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["active_workers"], 0)

    def test_incident_lock_blocks_parallel_job_and_expired_lease_recovers(self):
        first = record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "first-job").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
        )
        record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "second-job").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatencyUpdated"},
        )
        claimed = claim_next_job("worker-a", lease_seconds=120)
        self.assertEqual(claimed["job_id"], first["job_id"])
        self.assertIsNone(claim_next_job("worker-b", lease_seconds=120))

        renewed_until = renew_job_lease(first["job_id"], "worker-a", 180)
        self.assertTrue(renewed_until)
        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE incident_jobs SET leased_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND "
                "WHERE job_id=%s",
                (first["job_id"],),
            )
            cur.execute(
                "UPDATE incident_job_locks SET leased_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND "
                "WHERE incident_id=%s",
                (self.incident_id,),
            )
            conn.commit()

        recovered = claim_next_job("worker-b", lease_seconds=120)
        self.assertEqual(recovered["job_id"], first["job_id"])
        self.assertEqual(recovered["attempt_count"], 2)
        with self.assertRaisesRegex(ValueError, "job lease is not owned"):
            complete_job(first["job_id"], "worker-a")
        complete_job(recovered["job_id"], "worker-b")

        next_job = claim_next_job("worker-b", lease_seconds=120)
        self.assertEqual(next_job["incident_id"], self.incident_id)
        complete_job(next_job["job_id"], "worker-b")

    def test_reprocessing_records_selected_versions_without_new_event(self):
        original = record_event(
            self.incident_id,
            hashlib.sha256((self.incident_id + "reprocess").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
        )
        context = {"code_version": "build-17", "prompt_version": "prompt-4", "model_version": "model-x"}
        replay = enqueue_reprocessing(self.incident_id, context)
        self.assertEqual(replay["event_id"], original["event_id"])
        job = claim_next_job("test-worker")
        self.assertEqual(job["kind"], "reprocess")
        for key, value in context.items():
            self.assertEqual(job["run_context"][key], value)
        self.assertEqual(
            job["run_context"]["pipeline_config"]["schema_version"],
            "pipeline-config-manifest/v1",
        )
        complete_job(job["job_id"], "test-worker")

    def test_runtime_rate_limit_is_shared_in_mysql(self):
        key = "test-rate-" + uuid.uuid4().hex
        self.assertEqual(rate_limit.allow(key, 1, 60), (True, 0))
        allowed, retry_after = rate_limit.allow(key, 1, 60)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)

    def test_resolution_is_idempotent_and_reopen_is_a_versioned_path(self):
        registry.transition_lifecycle(self.incident_id, "received")
        registry.transition_lifecycle(self.incident_id, "collecting")
        registry.transition_lifecycle(self.incident_id, "analyzing")
        resolved = registry.resolve_incident(self.incident_id)
        duplicate = registry.resolve_incident(self.incident_id)
        self.assertEqual(resolved["status"], "resolved")
        self.assertFalse(resolved["idempotent"])
        self.assertTrue(duplicate["idempotent"])

        reopened = registry.reopen_incident(self.incident_id)
        self.assertEqual(reopened["status"], "analyzing")
        self.assertTrue(reopened["reopened"])
        self.assertEqual(
            [entry["to"] for entry in reopened["history"][-4:]],
            ["resolved", "received", "collecting", "analyzing"],
        )
        with self.assertRaisesRegex(
            registry.RevisionConflictError,
            "only a resolved incident",
        ):
            registry.reopen_incident(self.incident_id)

    def test_concurrent_revision_writers_receive_unique_monotonic_versions(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            revisions = list(pool.map(
                lambda index: create_revision(
                    self.incident_id,
                    f"concurrent observation {index}",
                ),
                range(4),
            ))
        self.assertEqual(sorted(revisions), [1, 2, 3, 4])

    def test_retried_job_reuses_revision_and_persists_completion_result(self):
        event = record_event_and_enqueue(
            self.incident_id,
            hashlib.sha256((self.incident_id + "idempotent-job").encode()).hexdigest(),
            "firing",
            {"alertname": "HighLatency"},
        )
        first_claim = claim_next_job("worker-crashed", lease_seconds=120)
        first_revision = create_revision(
            self.incident_id,
            "new alert observation",
            job_id=first_claim["job_id"],
        )

        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE incident_jobs SET leased_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND "
                "WHERE job_id=%s",
                (event["job_id"],),
            )
            cur.execute(
                "UPDATE incident_job_locks SET leased_until=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND "
                "WHERE incident_id=%s",
                (self.incident_id,),
            )
            conn.commit()

        recovered = claim_next_job("worker-recovery", lease_seconds=120)
        recovered_revision = create_revision(
            self.incident_id,
            "new alert observation",
            job_id=recovered["job_id"],
        )
        self.assertEqual(recovered_revision, first_revision)
        complete_job(
            recovered["job_id"],
            "worker-recovery",
            {"revision": recovered_revision, "status": "completed"},
        )

        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status,attempt_count,result,completed_at FROM incident_jobs "
                "WHERE job_id=%s",
                (event["job_id"],),
            )
            status, attempts, result, completed_at = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) FROM incident_revisions WHERE job_id=%s",
                (event["job_id"],),
            )
            revision_count = cur.fetchone()[0]

        self.assertEqual(status, "completed")
        self.assertEqual(attempts, 2)
        self.assertEqual(revision_count, 1)
        decoded_result = result if isinstance(result, dict) else json.loads(result)
        self.assertEqual(decoded_result["revision"], first_revision)
        self.assertIsNotNone(completed_at)
