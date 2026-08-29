"""Jira Rovo MCP publisher contract tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.jira_mcp_client import (
    JiraMcpError,
    RealJiraMcpClient,
    _issue_url,
)


class JiraMcpClientTests(unittest.TestCase):
    def _client(self):
        return RealJiraMcpClient(
            "https://mcp.atlassian.com/v1/mcp",
            "service-account@example.test",
            "scoped-test-token",
            "https://example.atlassian.net",
            "OPS",
            issue_type="Task",
            timeout=15,
        )

    def test_create_uses_the_bounded_official_tool_contract(self):
        result = SimpleNamespace(
            isError=False,
            structuredContent={"issue": {"key": "OPS-42"}},
            content=[],
        )
        call = AsyncMock(return_value=result)
        with patch("clients.jira_mcp_client._call_tool", new=call):
            issue_url = self._client().create_postmortem(
                "[INC-1] [SEV2] Latency",
                "approved postmortem",
            )

        self.assertEqual(
            issue_url,
            "https://example.atlassian.net/browse/OPS-42",
        )
        args = call.await_args.args
        self.assertEqual(args[0], "https://mcp.atlassian.com/v1/mcp")
        self.assertEqual(
            args[3],
            {
                "cloudId": "https://example.atlassian.net",
                "projectKey": "OPS",
                "issueTypeName": "Task",
                "summary": "[INC-1] [SEV2] Latency",
                "description": "approved postmortem",
            },
        )
        self.assertEqual(args[4], 15)

    def test_provider_error_is_sanitized_and_not_retried(self):
        call = AsyncMock(
            side_effect=RuntimeError("api_token=do-not-leak-this-token")
        )
        with patch("clients.jira_mcp_client._call_tool", new=call):
            with self.assertRaisesRegex(
                JiraMcpError,
                "Jira MCP request failed: RuntimeError",
            ) as raised:
                self._client().create_postmortem("title", "body")

        self.assertNotIn("do-not-leak", str(raised.exception))
        self.assertEqual(call.await_count, 1)

    def test_untrusted_response_url_is_rejected(self):
        result = SimpleNamespace(
            structuredContent={"url": "https://attacker.example/OPS-42"},
            content=[],
        )
        with self.assertRaisesRegex(JiraMcpError, "trusted issue key or URL"):
            _issue_url(result, "https://example.atlassian.net")

    def test_tool_error_does_not_become_a_successful_publication(self):
        result = SimpleNamespace(
            isError=True,
            structuredContent=None,
            content=[SimpleNamespace(text="permission denied")],
        )
        with patch(
            "clients.jira_mcp_client._call_tool",
            new=AsyncMock(return_value=result),
        ):
            with self.assertRaisesRegex(JiraMcpError, "permission denied"):
                self._client().create_postmortem("title", "body")


if __name__ == "__main__":
    unittest.main()
