import json
import unittest
import uuid

from webhook import registry
from webhook.incident_store import (
    EvidenceIntegrityError,
    get_analysis_revision_diff,
    get_analysis_revision,
    list_evidence_records,
    list_postmortem_drafts,
    record_analysis_revision,
    record_postmortem_draft,
    record_review_decision,
    create_revision,
    validate_analysis_evidence,
)
from webhook.knowledge_store import (
    create_knowledge_record,
    delete_knowledge_record,
    retrieve_knowledge,
)
from webhook.state_sync import sync_registry


class MemoryAndReviewPersistenceTests(unittest.TestCase):
    """Integration tests for Area 7/8 records in the configured MySQL database."""

    def setUp(self):
        self.incident_id = "INC-MEM-" + uuid.uuid4().hex[:16]
        self.tenant = "tenant-" + uuid.uuid4().hex[:10]
        self.created_knowledge = []

    def tearDown(self):
        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM pending_reviews WHERE thread_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_review_decisions WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_postmortem_drafts WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_analysis_evidence WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_evidence_records WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_analysis_revisions WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_revisions WHERE incident_id=%s", (self.incident_id,))
            cur.execute("DELETE FROM incident_revision_heads WHERE incident_id=%s", (self.incident_id,))
            for identifier in self.created_knowledge:
                cur.execute("DELETE FROM curated_knowledge WHERE knowledge_id=%s", (identifier,))
            conn.commit()

    def test_pending_review_decision_has_one_atomic_winner(self):
        pending = registry.add_pending(self.incident_id, {
            "interpretation": "saved review",
        })
        first = record_review_decision(
            self.incident_id,
            pending["pending_revision"],
            "rejected",
            "basic:reviewer",
            "ranking is not supported",
            request_id="req-atomic-1",
            enforce_pending=True,
        )
        self.assertFalse(first["deduplicated"])
        duplicate = record_review_decision(
            self.incident_id,
            pending["pending_revision"],
            "rejected",
            "basic:reviewer",
            "ranking is not supported",
            request_id="req-atomic-1",
            enforce_pending=True,
        )
        self.assertTrue(duplicate["deduplicated"])
        with self.assertRaisesRegex(ValueError, "already decided"):
            record_review_decision(
                self.incident_id,
                pending["pending_revision"],
                "rejected",
                "basic:other-reviewer",
                "different decision payload",
                request_id="req-atomic-2",
                enforce_pending=True,
            )

    def test_analysis_snapshot_and_review_decision_are_immutable_and_grounded(self):
        state = {
            "evidence_graph": {"nodes": [{"event_id": "alert-1"}, {"event_id": "log-db"}]},
            "deterministic_assessment": {"candidates": [
                {"id": "candidate-log-db", "rank": 1, "title": "DB saturation", "event_ids": ["log-db"]}
            ]},
            "incident_window": {"start": "2026-07-22T10:00:00+00:00"},
            "evidence_pack": "compact redacted evidence only",
            "source_status": {"logs": {"status": "ok"}},
            "data_quality": {},
            "interpretation_quality": {"passed": True},
        }
        snapshot = record_analysis_revision(self.incident_id, 1, state, event_id=42)
        self.assertEqual(snapshot["evidence_ids"], ["alert-1", "log-db"])
        self.assertEqual(snapshot["candidates"][0]["rank"], 1)
        self.assertEqual(get_analysis_revision(self.incident_id, 1)["event_id"], 42)

        decision = record_review_decision(
            self.incident_id, 3, "approved", "basic:reviewer", "evidence confirms it",
            request_id="req-7", selected_hypothesis=1, analysis_revision=1,
        )
        self.assertEqual(decision["displayed_evidence_ids"], ["alert-1", "log-db"])
        with self.assertRaisesRegex(ValueError, "selected hypothesis"):
            record_review_decision(
                self.incident_id, 4, "approved", "basic:reviewer", selected_hypothesis=2,
                analysis_revision=1,
            )
        requested = record_review_decision(
            self.incident_id,
            5,
            "request_more_evidence",
            "basic:reviewer",
            "Check database metrics before the first timeout.",
            analysis_revision=1,
        )
        self.assertEqual(requested["decision"], "request_more_evidence")
        with self.assertRaisesRegex(ValueError, "requires rationale"):
            record_review_decision(
                self.incident_id,
                6,
                "request_more_evidence",
                "basic:reviewer",
                "",
                analysis_revision=1,
            )

    def test_generated_and_edited_drafts_keep_versions(self):
        generated = record_postmortem_draft(self.incident_id, "## Executive Summary\nGenerated.", 1)
        duplicate = record_postmortem_draft(self.incident_id, "## Executive Summary\nGenerated.", 1)
        edited = record_postmortem_draft(
            self.incident_id, "## Executive Summary\nEdited by reviewer.", 1,
            source="edited", editor_identity="basic:reviewer",
        )
        self.assertEqual(generated["version"], 1)
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(edited["version"], 2)
        drafts = list_postmortem_drafts(self.incident_id)
        self.assertEqual([item["source"] for item in drafts], ["generated", "edited"])
        self.assertEqual(drafts[1]["supersedes_draft_id"], drafts[0]["draft_id"])

    def test_late_evidence_appends_and_preserves_the_reviewed_revision(self):
        first_state = {
            "evidence_graph": {"nodes": [{"event_id": "log-db", "type": "log_group"}]},
            "timeline": [{
                "event_id": "log-db", "type": "log_group",
                "timestamp": "2026-07-22T10:05:00+00:00", "count": 4,
                "offset": "T+5m", "is_anchor": True,
            }],
            "deterministic_assessment": {"candidates": [{
                "id": "candidate-db", "rank": 1, "title": "DB saturation",
                "event_ids": ["log-db"],
            }]},
            "evidence_pack": "first compact pack",
        }
        second_state = {
            "evidence_graph": {"nodes": [
                {"event_id": "metric-cpu", "type": "metric"},
                {"event_id": "log-db", "type": "log_group"},
            ]},
            "timeline": [
                {
                    "event_id": "metric-cpu", "type": "metric",
                    "timestamp": "2026-07-22T10:02:00+00:00", "value": 0.96,
                    "offset": "T-3m", "is_anchor": False,
                },
                {
                    "event_id": "log-db", "type": "log_group",
                    "timestamp": "2026-07-22T10:05:00+00:00", "count": 4,
                    "offset": "T+3m", "is_anchor": True,
                },
            ],
            "deterministic_assessment": {"candidates": [
                {
                    "id": "candidate-cpu", "rank": 1, "title": "CPU saturation",
                    "event_ids": ["metric-cpu"],
                },
                {
                    "id": "candidate-db", "rank": 2, "title": "DB saturation",
                    "event_ids": ["log-db"],
                },
            ]},
            "evidence_pack": "second compact pack",
        }
        record_analysis_revision(self.incident_id, 1, first_state, event_id=1)
        original = list_evidence_records(self.incident_id, 1)
        record_analysis_revision(self.incident_id, 2, second_state, event_id=2)

        reviewed = list_evidence_records(self.incident_id, 1)
        latest = list_evidence_records(self.incident_id, 2)
        self.assertEqual(reviewed, original)
        self.assertEqual(
            [item["evidence_id"] for item in reviewed],
            ["log-db"],
        )
        self.assertEqual(
            [item["evidence_id"] for item in latest],
            ["log-db", "metric-cpu"],
        )
        self.assertEqual(
            reviewed[0]["evidence_record_id"],
            latest[0]["evidence_record_id"],
        )
        diff = get_analysis_revision_diff(self.incident_id, 2)
        self.assertEqual(diff["evidence"]["added"], ["metric-cpu"])
        self.assertEqual(diff["evidence"]["changed"], [])
        self.assertEqual(diff["evidence"]["removed"], [])
        self.assertEqual(diff["evidence"]["unchanged"], ["log-db"])
        self.assertGreaterEqual(len(diff["candidate_changes"]), 2)

    def test_corrected_evidence_creates_a_superseding_version(self):
        def state(message):
            return {
                "evidence_graph": {"nodes": [{"event_id": "log-db", "type": "log_group"}]},
                "timeline": [{
                    "event_id": "log-db", "type": "log_group",
                    "timestamp": "2026-07-22T10:05:00+00:00", "message": message,
                }],
                "deterministic_assessment": {"candidates": []},
                "evidence_pack": message,
            }

        record_analysis_revision(self.incident_id, 1, state("original"), event_id=1)
        record_analysis_revision(self.incident_id, 2, state("corrected"), event_id=2)
        versions = list_evidence_records(self.incident_id)
        self.assertEqual([item["version"] for item in versions], [1, 2])
        self.assertEqual(
            versions[1]["supersedes_record_id"],
            versions[0]["evidence_record_id"],
        )
        self.assertEqual(
            get_analysis_revision_diff(self.incident_id, 2)["evidence"]["changed"],
            ["log-db"],
        )

    def test_allocated_revision_chain_survives_out_of_order_worker_completion(self):
        self.assertEqual(create_revision(self.incident_id, "first event"), 1)
        self.assertEqual(create_revision(self.incident_id, "second event"), 2)

        def state(event_id):
            return {
                "evidence_graph": {"nodes": [{"event_id": event_id}]},
                "timeline": [{"event_id": event_id, "type": "log_group"}],
                "deterministic_assessment": {"candidates": []},
                "evidence_pack": event_id,
            }

        # The later worker finishes first, but its parent is still revision 1.
        second = record_analysis_revision(
            self.incident_id, 2, state("log-second"), event_id=2
        )
        first = record_analysis_revision(
            self.incident_id, 1, state("log-first"), event_id=1
        )
        self.assertIsNone(first["previous_revision"])
        self.assertEqual(second["previous_revision"], 1)
        diff = get_analysis_revision_diff(self.incident_id, 2)
        self.assertEqual(diff["previous_revision"], 1)
        self.assertEqual(diff["evidence"]["added"], ["log-second"])
        self.assertEqual(diff["evidence"]["removed"], ["log-first"])

    def test_state_sync_carries_new_connector_evidence_into_review_diff(self):
        normalized = {
            "alertname": "HighLatency",
            "service": "checkout",
            "severity": "warning",
        }

        def state(nodes, candidates):
            return {
                "__interrupt__": [{"value": "review"}],
                "evidence_graph": {"nodes": nodes},
                "timeline": nodes,
                "deterministic_assessment": {"candidates": candidates},
                "interpretation": "Grounded analysis",
                "interpretation_quality": {"passed": True},
                "claim_grounding": {"passed": True},
                "evidence_pack": "bounded evidence",
            }

        first_revision = create_revision(self.incident_id, "alert observation")
        sync_registry(
            self.incident_id,
            normalized,
            state(
                [{
                    "event_id": "log-timeout", "type": "log_group",
                    "timestamp": "2026-07-22T10:05:00+00:00",
                }],
                [{
                    "id": "candidate-timeout", "rank": 1,
                    "title": "Timeout", "event_ids": ["log-timeout"],
                }],
            ),
            analysis_revision=first_revision,
            latest_event_id=10,
        )
        first_pending = registry.get_pending(self.incident_id)

        second_revision = create_revision(self.incident_id, "metric observation")
        sync_registry(
            self.incident_id,
            normalized,
            state(
                [
                    {
                        "event_id": "metric-latency", "type": "metric",
                        "timestamp": "2026-07-22T10:03:00+00:00",
                    },
                    {
                        "event_id": "log-timeout", "type": "log_group",
                        "timestamp": "2026-07-22T10:05:00+00:00",
                    },
                ],
                [{
                    "id": "candidate-timeout", "rank": 1,
                    "title": "Timeout", "event_ids": ["log-timeout", "metric-latency"],
                }],
            ),
            analysis_revision=second_revision,
            latest_event_id=11,
            expected_pending_version=first_pending["pending_revision"],
        )
        latest_pending = registry.get_pending(self.incident_id)
        self.assertEqual(latest_pending["analysis_revision"], 2)
        self.assertEqual(
            latest_pending["revision_diff"]["evidence"]["added"],
            ["metric-latency"],
        )
        self.assertEqual(
            latest_pending["revision_diff"]["evidence"]["unchanged"],
            ["log-timeout"],
        )
        self.assertEqual(
            [item["evidence_id"] for item in list_evidence_records(self.incident_id, 1)],
            ["log-timeout"],
        )

    def test_tampered_evidence_is_detected_and_blocks_review(self):
        state = {
            "evidence_graph": {"nodes": [{"event_id": "log-db", "type": "log_group"}]},
            "timeline": [{
                "event_id": "log-db", "type": "log_group", "message": "original",
            }],
            "deterministic_assessment": {"candidates": [{
                "id": "candidate-db", "rank": 1, "title": "DB issue",
                "event_ids": ["log-db"],
            }]},
            "evidence_pack": "original",
        }
        record_analysis_revision(self.incident_id, 1, state, event_id=1)
        self.assertTrue(
            validate_analysis_evidence(self.incident_id, 1)["passed"]
        )
        with registry._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE incident_evidence_records SET payload=%s "
                "WHERE incident_id=%s AND evidence_id='log-db'",
                (json.dumps({
                    "event_id": "log-db", "type": "log_group",
                    "message": "tampered",
                }), self.incident_id),
            )
            conn.commit()

        self.assertFalse(
            list_evidence_records(self.incident_id, 1)[0]["integrity_valid"]
        )
        with self.assertRaises(EvidenceIntegrityError):
            get_analysis_revision_diff(self.incident_id, 1)
        with self.assertRaises(EvidenceIntegrityError):
            record_review_decision(
                self.incident_id,
                1,
                "approved",
                "basic:reviewer",
                selected_hypothesis=1,
                analysis_revision=1,
            )
        rejected = record_review_decision(
            self.incident_id,
            1,
            "rejected",
            "basic:reviewer",
            rationale="stored evidence failed integrity validation",
            analysis_revision=1,
        )
        self.assertEqual(rejected["decision"], "rejected")

    def test_knowledge_requires_approval_filters_before_ranking_and_honors_supersession(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            create_knowledge_record(
                source_type="reviewed_postmortem", source_link="local://pm", approval_identity="",
                approval_reference="review-1", tenant=self.tenant, summary="database pool saturation",
                security_class="internal", service="checkout", environment="production",
            )
        first = create_knowledge_record(
            source_type="reviewed_postmortem", source_link="local://pm/1", approval_identity="basic:reviewer",
            approval_reference="decision-1", tenant=self.tenant, summary="Checkout database pool saturation after deploy.",
            security_class="internal", service="checkout", environment="production",
            metadata={"incident_type": "latency"},
        )
        self.created_knowledge.append(first["knowledge_id"])
        hits = retrieve_knowledge(
            tenant=self.tenant, allowed_security_classes=["internal"], service="checkout",
            environment="production", query="database saturation", limit=1,
        )
        self.assertEqual([hit["knowledge_id"] for hit in hits], [first["knowledge_id"]])
        self.assertEqual(
            retrieve_knowledge(
                tenant=self.tenant, allowed_security_classes=["internal"], service="payments",
                environment="production", query="database", limit=5,
            ),
            [],
        )
        replacement = create_knowledge_record(
            source_type="reviewed_runbook", source_link="local://runbook/2", approval_identity="basic:reviewer",
            approval_reference="review-2", tenant=self.tenant, summary="Checkout pool saturation mitigation uses bounded connections.",
            security_class="internal", service="checkout", environment="production",
            supersedes_knowledge_id=first["knowledge_id"],
        )
        self.created_knowledge.append(replacement["knowledge_id"])
        current = retrieve_knowledge(
            tenant=self.tenant, allowed_security_classes=["internal"], service="checkout",
            environment="production", query="pool saturation", limit=5,
        )
        self.assertEqual([hit["knowledge_id"] for hit in current], [replacement["knowledge_id"]])
        self.assertEqual(delete_knowledge_record(replacement["knowledge_id"], "basic:reviewer", "runbook retired")["status"], "deleted")
