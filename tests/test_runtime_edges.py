"""Tests for network boundaries around job orchestration and worker metrics."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from utils import egress
from webhook import job_handler, metrics_server


class _Reader:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def readuntil(self, marker):
        if self.error:
            raise self.error
        return self.payload


class _Writer:
    def __init__(self):
        self.payload = b""
        self.closed = False

    def write(self, data):
        self.payload += data

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class EgressPolicyTests(unittest.TestCase):
    def test_secure_modes_require_https_and_an_allowlisted_host(self):
        with patch.object(egress, "ENVIRONMENT", "production"), patch.object(
            egress, "EGRESS_ALLOWED_HOSTS", {"api.example.test", "*.amazonaws.com"}
        ):
            self.assertEqual(
                egress.assert_egress_url("https://api.example.test/v1", source="model"),
                "https://api.example.test/v1",
            )
            self.assertEqual(
                egress.assert_egress_url("https://logs.eu.amazonaws.com/query"),
                "https://logs.eu.amazonaws.com/query",
            )
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                egress.assert_egress_url("http://api.example.test")
            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                egress.assert_egress_url("https://untrusted.example.test")

    def test_local_mode_preserves_development_urls(self):
        with patch.object(egress, "ENVIRONMENT", "local"):
            self.assertEqual(egress.assert_egress_url("http://127.0.0.1:1234/v1"), "http://127.0.0.1:1234/v1")


class MetricsServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_request_requires_token_and_emits_prometheus_body(self):
        with patch.object(metrics_server, "METRICS_BEARER_TOKEN", "token"), patch.object(
            metrics_server, "_body", new=AsyncMock(return_value=b"metric 1\n")
        ):
            unauthorized = _Writer()
            await metrics_server._handle(_Reader(b"GET /metrics HTTP/1.1\r\n\r\n"), unauthorized)
            self.assertIn(b"401 Unauthorized", unauthorized.payload)

            authorized = _Writer()
            await metrics_server._handle(
                _Reader(b"GET /metrics HTTP/1.1\r\nAuthorization: Bearer token\r\n\r\n"),
                authorized,
            )
        self.assertIn(b"200 OK", authorized.payload)
        self.assertIn(b"metric 1", authorized.payload)
        self.assertTrue(authorized.closed)

    async def test_metrics_server_handles_invalid_requests_and_disconnects(self):
        with patch.object(metrics_server, "METRICS_BEARER_TOKEN", ""):
            writer = _Writer()
            await metrics_server._handle(_Reader(b"POST /metrics HTTP/1.1\r\n\r\n"), writer)
            self.assertIn(b"404 Not Found", writer.payload)

            disconnected = _Writer()
            await metrics_server._handle(
                _Reader(error=asyncio.IncompleteReadError(b"", None)), disconnected
            )
        self.assertEqual(disconnected.payload, b"")
        self.assertTrue(disconnected.closed)


class JobHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalized_alert_starts_lifecycle_syncs_state_and_awaits_review(self):
        normalized = {"incident_id": "INC-NORMALIZED", "alertname": "Latency"}
        state = {"pending_review": {"status": "awaiting_review"}}
        with (
            patch.object(job_handler.registry, "get_lifecycle", return_value=None),
            patch.object(job_handler.registry, "transition_lifecycle") as transition,
            patch.object(job_handler.graph, "ainvoke", new=AsyncMock(return_value=state)) as invoke,
            patch.object(job_handler, "sync_registry") as sync,
            patch.object(job_handler, "is_awaiting_review", return_value=True),
            patch.object(job_handler, "emit_log_event"),
        ):
            result = await job_handler.run_normalized_alert(
                normalized,
                analysis_revision=4,
                latest_event_id=11,
                run_context={"prompt_version": "v3"},
            )

        self.assertEqual(result["status"], "awaiting_review")
        self.assertEqual(transition.call_args_list[0].args[1], "received")
        self.assertEqual(transition.call_args_list[-1].args[1], "awaiting_analysis_review")
        self.assertEqual(invoke.call_args.kwargs["config"]["configurable"]["thread_id"], "INC-NORMALIZED")
        self.assertEqual(sync.call_args.args[3:5], (4, 11))

    async def test_resolved_job_creates_revision_and_skips_workflow(self):
        job = {
            "incident_id": "INC-RESOLVED",
            "kind": "analyze",
            "event_id": 3,
            "payload": {"incident_id": "INC-RESOLVED", "status": "resolved"},
        }
        with (
            patch.object(job_handler, "create_revision", return_value=4),
            patch.object(job_handler.registry, "resolve_incident", return_value={"status": "resolved"}),
            patch.object(job_handler, "run_normalized_alert", new=AsyncMock()) as run,
        ):
            result = await job_handler.run_incident_job(job)
        self.assertEqual(result["revision"], 4)
        run.assert_not_awaited()

    async def test_new_alert_creates_revision_and_passes_reprocessing_context(self):
        job = {
            "incident_id": "INC-NEW",
            "kind": "reprocess",
            "event_id": 8,
            "payload": {"incident_id": "INC-NEW", "alertname": "Latency"},
            "run_context": {"prompt_version": "v2"},
        }
        with (
            patch.object(job_handler, "create_revision", return_value=5) as create,
            patch.object(
                job_handler,
                "run_normalized_alert",
                new=AsyncMock(return_value={"status": "completed"}),
            ) as run,
        ):
            result = await job_handler.run_incident_job(job)
        self.assertEqual(result, {"status": "completed", "revision": 5})
        self.assertIn("reprocessing stored event", create.call_args.args)
        self.assertEqual(run.call_args.kwargs["run_context"], {"prompt_version": "v2"})
