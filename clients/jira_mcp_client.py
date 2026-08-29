"""Publish an approved postmortem as a Jira issue through Atlassian Rovo MCP."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from settings import (
    JIRA_MCP_API_TOKEN,
    JIRA_MCP_CLOUD_ID,
    JIRA_MCP_EMAIL,
    JIRA_MCP_ISSUE_TYPE,
    JIRA_MCP_PROJECT_KEY,
    JIRA_MCP_TIMEOUT_SECONDS,
    JIRA_MCP_URL,
    PUBLISH_JIRA_MCP,
)
from utils.egress import assert_egress_url
from utils.redaction import redact_message


_ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9_]+-\d+\b")
_URL = re.compile(r"https://[^\s<>\"]+")
_CREATE_TOOL = "createJiraIssue"


class JiraMcpError(RuntimeError):
    """A sanitized Jira MCP publication failure."""


async def _call_tool(endpoint, email, token, arguments, timeout):
    """Make one non-retried MCP tool call.

    Publication is deliberately not retried here: a lost acknowledgement may
    mean Jira created the issue even though this worker did not receive it.
    """

    read_timeout = timedelta(seconds=float(timeout))
    async with streamablehttp_client(
        endpoint,
        auth=httpx.BasicAuth(email, token),
        timeout=float(timeout),
        sse_read_timeout=float(timeout),
    ) as (read_stream, write_stream, _):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=read_timeout,
        ) as session:
            await session.initialize()
            return await session.call_tool(
                _CREATE_TOOL,
                arguments=arguments,
                read_timeout_seconds=read_timeout,
            )


def _content_text(result):
    parts = []
    for item in getattr(result, "content", ()) or ():
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _find_named_value(value, names):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in names and isinstance(item, str):
                return item
        for item in value.values():
            found = _find_named_value(item, names)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_named_value(item, names)
            if found:
                return found
    return None


def _structured_result(result):
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    text = _content_text(result).strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _issue_url(result, cloud_id):
    structured = _structured_result(result)
    key = _find_named_value(structured, {"key", "issuekey", "issue_key"})
    text = _content_text(result)
    if not key:
        match = _ISSUE_KEY.search(text)
        key = match.group(0) if match else None

    cloud_url = str(cloud_id).rstrip("/")
    cloud = urlparse(cloud_url)
    if key and cloud.scheme == "https" and cloud.hostname:
        return f"{cloud_url}/browse/{key}"

    candidate = _find_named_value(
        structured,
        {"url", "browseurl", "weburl", "self"},
    )
    if not candidate:
        match = _URL.search(text)
        candidate = match.group(0).rstrip(".,)") if match else None
    parsed = urlparse(str(candidate or ""))
    if (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.hostname == cloud.hostname
    ):
        return str(candidate)
    raise JiraMcpError(
        "Jira MCP returned success without a trusted issue key or URL"
    )


class RealJiraMcpClient:
    def __init__(
        self,
        endpoint,
        email,
        token,
        cloud_id,
        project_key,
        issue_type="Task",
        timeout=30,
    ):
        self.endpoint = endpoint
        self.email = email
        self.token = token
        self.cloud_id = cloud_id
        self.project_key = project_key
        self.issue_type = issue_type
        self.timeout = timeout

    def create_postmortem(self, title, body):
        assert_egress_url(self.endpoint, source="jira_mcp")
        arguments = {
            "cloudId": self.cloud_id,
            "projectKey": self.project_key,
            "issueTypeName": self.issue_type,
            "summary": redact_message(title),
            "description": redact_message(body),
        }
        try:
            result = asyncio.run(
                _call_tool(
                    self.endpoint,
                    self.email,
                    self.token,
                    arguments,
                    self.timeout,
                )
            )
        except Exception as exc:
            raise JiraMcpError(
                "Jira MCP request failed: " + type(exc).__name__
            ) from exc
        if getattr(result, "isError", False):
            diagnostic = redact_message(_content_text(result))[:300]
            raise JiraMcpError(
                "Jira MCP rejected createJiraIssue"
                + (f": {diagnostic}" if diagnostic else "")
            )
        return _issue_url(result, self.cloud_id)


class DisabledJiraMcpClient:
    def create_postmortem(self, title, body):
        del title, body
        raise JiraMcpError(
            "Jira MCP publishing is enabled but its credentials or target are incomplete"
        )


class MockJiraMcpClient:
    def create_postmortem(self, title, body):
        del body
        print(f"[MOCK JIRA MCP] would create issue: {redact_message(title)}")
        return None


def _make_client():
    required = (
        JIRA_MCP_URL,
        JIRA_MCP_EMAIL,
        JIRA_MCP_API_TOKEN,
        JIRA_MCP_CLOUD_ID,
        JIRA_MCP_PROJECT_KEY,
    )
    if all(required):
        return RealJiraMcpClient(
            JIRA_MCP_URL,
            JIRA_MCP_EMAIL,
            JIRA_MCP_API_TOKEN,
            JIRA_MCP_CLOUD_ID,
            JIRA_MCP_PROJECT_KEY,
            issue_type=JIRA_MCP_ISSUE_TYPE,
            timeout=JIRA_MCP_TIMEOUT_SECONDS,
        )
    if PUBLISH_JIRA_MCP:
        return DisabledJiraMcpClient()
    return MockJiraMcpClient()


jira = _make_client()
