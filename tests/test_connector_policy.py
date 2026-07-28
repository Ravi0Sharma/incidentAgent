import unittest
from unittest.mock import patch

import httpx

from utils import resilience


class _Response:
    def raise_for_status(self):
        return None


class ConnectorPolicyTests(unittest.TestCase):
    def setUp(self):
        resilience._STATE.clear()

    def tearDown(self):
        resilience._STATE.clear()

    def test_source_policy_sets_the_default_timeout(self):
        policy = {
            "timeout_seconds": 7.5,
            "retry_attempts": 1,
            "retry_backoff_seconds": 0,
            "circuit_open_seconds": 9,
        }
        with (
            patch.dict(
                resilience.SOURCE_REQUEST_POLICIES,
                {"test-source": policy},
                clear=False,
            ),
            patch.object(
                resilience.httpx,
                "request",
                return_value=_Response(),
            ) as send,
        ):
            resilience.request("test-source", "GET", "https://example.test")

        self.assertEqual(send.call_args.kwargs["timeout"], 7.5)

    def test_source_policy_controls_retry_attempts(self):
        policy = {
            "timeout_seconds": 1,
            "retry_attempts": 3,
            "retry_backoff_seconds": 0,
            "circuit_open_seconds": 9,
        }
        with (
            patch.dict(
                resilience.SOURCE_REQUEST_POLICIES,
                {"retry-source": policy},
                clear=False,
            ),
            patch.object(
                resilience.httpx,
                "request",
                side_effect=httpx.ConnectError("offline"),
            ) as send,
            patch.object(resilience.time, "sleep") as sleep,
        ):
            with self.assertRaises(resilience.SourceUnavailable) as caught:
                resilience.request("retry-source", "GET", "https://example.test")

        self.assertEqual(send.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("after 3 attempts", str(caught.exception))

    def test_explicit_timeout_overrides_source_default(self):
        policy = {
            "timeout_seconds": 7.5,
            "retry_attempts": 1,
            "retry_backoff_seconds": 0,
            "circuit_open_seconds": 9,
        }
        with (
            patch.dict(
                resilience.SOURCE_REQUEST_POLICIES,
                {"override-source": policy},
                clear=False,
            ),
            patch.object(
                resilience.httpx,
                "request",
                return_value=_Response(),
            ) as send,
        ):
            resilience.request(
                "override-source",
                "GET",
                "https://example.test",
                timeout=2,
            )

        self.assertEqual(send.call_args.kwargs["timeout"], 2)

    def test_source_policy_controls_circuit_open_duration(self):
        policy = {
            "timeout_seconds": 1,
            "retry_attempts": 1,
            "retry_backoff_seconds": 0,
            "circuit_open_seconds": 17,
        }
        with (
            patch.dict(
                resilience.SOURCE_REQUEST_POLICIES,
                {"circuit-source": policy},
                clear=False,
            ),
            patch.object(
                resilience.httpx,
                "request",
                side_effect=httpx.ConnectError("offline"),
            ),
            patch.object(resilience.time, "monotonic", return_value=100),
        ):
            for _ in range(3):
                with self.assertRaises(resilience.SourceUnavailable):
                    resilience.request(
                        "circuit-source",
                        "GET",
                        "https://example.test",
                    )

        self.assertEqual(
            resilience._STATE["circuit-source"]["open_until"],
            117,
        )
