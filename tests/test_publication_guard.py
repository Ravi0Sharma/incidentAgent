"""Final publication review and durable external-effect guardrails."""

import asyncio
import hashlib
import json
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from graph.nodes import publish as publish_node
from graph.nodes import publish_review
from utils.mysql import connection as mysql_connection
from webhook.incident_store import (
    PublicationStateUncertainError,
    begin_publication,
    complete_publication,
    mark_publication_uncertain,
    operational_snapshot,
)
from webhook import api


class PublicationLedgerTests(unittest.TestCase):
    def setUp(self):
        self.incident_id = "INC-PUBLICATION-" + uuid.uuid4().hex[:16]

    def tearDown(self):
        with mysql_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM incident_publications WHERE incident_id=%s",
                (self.incident_id,),
            )
            connection.commit()

    def test_completed_publication_is_deduplicated_without_a_second_claim(self):
        first = begin_publication(self.incident_id, "reviewed draft")
        complete_publication(
            first["publication_key"],
            first["attempt_token"],
            "https://example.invalid/issues/1",
        )

        duplicate = begin_publication(self.incident_id, "reviewed draft")

        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(duplicate["status"], "completed")
        self.assertEqual(
            duplicate["issue_url"],
            "https://example.invalid/issues/1",
        )

    def test_uncertain_publication_fails_closed_instead_of_repeating_effects(self):
        first = begin_publication(self.incident_id, "reviewed draft")
        mark_publication_uncertain(
            first["publication_key"],
            first["attempt_token"],
            RuntimeError("provider response lost"),
        )

        with self.assertRaisesRegex(
            PublicationStateUncertainError,
            "reconcile providers",
        ):
            begin_publication(self.incident_id, "reviewed draft")
        self.assertGreaterEqual(operational_snapshot()["publication_uncertain"], 1)


class PublicationNodeTests(unittest.TestCase):
    def _state(self):
        return {
            "incident_id": "INC-PUBLISH-NODE",
            "severity": "SEV2",
            "alert": {"alertname": "Latency"},
            "postmortem_draft": "reviewed draft",
        }

    def test_final_review_requires_an_explicit_publication_decision(self):
        state = self._state()
        draft_sha256 = hashlib.sha256(
            state["postmortem_draft"].encode("utf-8")
        ).hexdigest()
        with patch.object(
            publish_review,
            "interrupt",
            return_value={"status": "approved", "draft_sha256": draft_sha256},
        ):
            approved = publish_review.publish_review(state)
        self.assertEqual(approved["publish_review_status"], "approved")
        self.assertEqual(
            publish_review.publish_review_router(approved),
            "publish",
        )
        self.assertEqual(
            publish_review.publish_review_router(
                {"publish_review_status": "rejected"}
            ),
            "end",
        )
        with patch.object(
            publish_review,
            "interrupt",
            return_value={"status": "approved", "draft_sha256": "0" * 64},
        ):
            with self.assertRaisesRegex(ValueError, "does not match"):
                publish_review.publish_review(state)

    def test_external_publish_completes_one_durable_claim(self):
        claim = {
            "publication_key": "key",
            "attempt_token": "token",
            "status": "started",
            "deduplicated": False,
        }
        with (
            patch.object(publish_node, "PUBLISH_EXTERNAL", True),
            patch.object(publish_node, "_write_html", return_value="report.html"),
            patch.object(publish_node, "begin_publication", return_value=claim),
            patch.object(publish_node.slack, "publish") as slack,
            patch.object(
                publish_node.github,
                "create_postmortem",
                return_value="https://example.invalid/1",
            ) as github,
            patch.object(publish_node, "complete_publication") as complete,
        ):
            result = publish_node.publish(self._state())

        slack.assert_called_once()
        github.assert_called_once()
        complete.assert_called_once_with(
            "key",
            "token",
            "https://example.invalid/1",
        )
        self.assertEqual(result["postmortem_url"], "https://example.invalid/1")

    def test_completed_claim_skips_all_provider_calls(self):
        claim = {
            "publication_key": "key",
            "attempt_token": None,
            "status": "completed",
            "deduplicated": True,
            "issue_url": "https://example.invalid/1",
        }
        with (
            patch.object(publish_node, "PUBLISH_EXTERNAL", True),
            patch.object(publish_node, "_write_html", return_value="report.html"),
            patch.object(publish_node, "begin_publication", return_value=claim),
            patch.object(publish_node.slack, "publish") as slack,
            patch.object(publish_node.github, "create_postmortem") as github,
        ):
            result = publish_node.publish(self._state())

        slack.assert_not_called()
        github.assert_not_called()
        self.assertEqual(result["postmortem_url"], "https://example.invalid/1")

    def test_jira_can_be_the_only_external_destination(self):
        claim = {
            "publication_key": "key",
            "attempt_token": "token",
            "status": "started",
            "deduplicated": False,
        }
        jira_url = "https://example.atlassian.net/browse/OPS-42"
        with (
            patch.object(publish_node, "PUBLISH_EXTERNAL", True),
            patch.object(publish_node, "PUBLISH_SLACK", False),
            patch.object(publish_node, "PUBLISH_GITHUB", False),
            patch.object(publish_node, "PUBLISH_JIRA_MCP", True),
            patch.object(publish_node, "_write_html", return_value="report.html"),
            patch.object(publish_node, "begin_publication", return_value=claim),
            patch.object(publish_node.slack, "publish") as slack,
            patch.object(publish_node.github, "create_postmortem") as github,
            patch.object(
                publish_node.jira,
                "create_postmortem",
                return_value=jira_url,
            ) as jira,
            patch.object(publish_node, "complete_publication") as complete,
        ):
            result = publish_node.publish(self._state())

        slack.assert_not_called()
        github.assert_not_called()
        jira.assert_called_once_with(
            "[INC-PUBLISH-NODE] [SEV2] Latency",
            "reviewed draft",
        )
        complete.assert_called_once_with("key", "token", jira_url)
        self.assertEqual(result["postmortem_url"], jira_url)


class PublicationEndpointTests(unittest.TestCase):
    def test_operator_approval_resumes_the_final_interrupt_and_completes_lifecycle(self):
        pending = {
            "review_stage": "publish",
            "pending_revision": 7,
            "alertname": "Latency",
            "service": "checkout",
            "severity": "SEV2",
            "message": "latency elevated",
            "postmortem_draft": "reviewed draft",
        }
        request = Mock(headers={"x-request-id": "request-1"})
        state = {
            "postmortem_draft": "reviewed draft",
            "postmortem_url": "https://example.invalid/1",
        }
        with (
            patch.object(api.registry, "get_pending", return_value=pending),
            patch.object(
                api.registry,
                "get_lifecycle",
                return_value={"version": 4},
            ),
            patch.object(api.registry, "transition_lifecycle") as transition,
            patch.object(api.graph, "ainvoke", new=AsyncMock(return_value=state)) as invoke,
            patch.object(api, "sync_registry") as sync,
            patch.object(api, "append_event"),
            patch.object(api, "record_audit_event"),
            patch.object(api, "_reviewer_identity", return_value="oidc:operator"),
        ):
            result = asyncio.run(
                api.publish_review_decision(
                    "INC-PUBLISH-ENDPOINT",
                    {"pending_revision": 7, "status": "approved"},
                    request,
                )
            )

        self.assertEqual(result["publication_status"], "approved")
        self.assertEqual(transition.call_args.args[1], "completed")
        self.assertEqual(sync.call_args.kwargs["expected_pending_version"], 7)
        self.assertEqual(
            invoke.call_args.args[0].resume,
            {
                "status": "approved",
                "feedback": "",
                "draft_sha256": hashlib.sha256(b"reviewed draft").hexdigest(),
            },
        )

    def test_publication_rejection_requires_a_reason(self):
        request = Mock(headers={})
        with patch.object(api.registry, "get_pending", return_value={
            "review_stage": "publish",
            "pending_revision": 2,
        }):
            response = asyncio.run(
                api.publish_review_decision(
                    "INC-PUBLISH-ENDPOINT",
                    {"pending_revision": 2, "status": "rejected"},
                    request,
                )
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("requires a reason", json.loads(response.body)["error"])
