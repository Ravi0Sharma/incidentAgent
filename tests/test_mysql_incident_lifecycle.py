import hashlib
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from webhook import registry
from webhook import rate_limit
from webhook.incident_store import (
    claim_next_job,
    complete_job,
    create_revision,
    enqueue_reprocessing,
    fail_job,
    list_dead_letters,
    list_events,
    record_event,
    record_event_and_enqueue,
    replay_dead_letter,
)


class MySQLIncidentLifecycleTests(unittest.TestCase):
    """Integration coverage for the durable Area 2 incident records."""

    def setUp(self):
        self.incident_id = "INC-TEST-" + uuid.uuid4().hex[:16]

    def tearDown(self):
        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM incident_dead_letters WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_jobs WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM pending_reviews WHERE thread_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_lifecycle WHERE thread_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_revisions WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_revision_heads WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_events WHERE incident_id=%s", (self.incident_id,))
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
