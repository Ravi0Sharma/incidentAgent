# Jira output through Atlassian Rovo MCP

Jira is an optional publication destination. It receives only the redacted,
human-approved postmortem draft and is disabled by default. Analysis approval
does not call Jira: a second decision must approve the exact draft digest.

## Supported path

The client uses Atlassian Rovo MCP's Streamable HTTP endpoint and the
`createJiraIssue` tool. Headless authentication uses an Atlassian account or
service-account email plus a scoped Rovo MCP API token. The token is converted
to HTTP Basic Auth in memory and is never placed in graph state, reports or
publisher arguments.

Official references:

- [Atlassian Rovo MCP setup](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/)
- [API-token authentication](https://community.atlassian.com/forums/Atlassian-Remote-MCP-Server/Announcing-authentication-via-API-token-for-Atlassian-Rovo-MCP/ba-p/3197014)
- [supported Rovo MCP tools](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/supported-tools/)

An Atlassian organization administrator must permit API-token authentication.
Use a scoped token with only the Jira permissions needed for the target
project. Do not use a personal all-access token for a deployed worker.

## Local sandbox setup

Use a disposable Jira project first. Copy the relevant values from
`.env.example` into the ignored `.env` file:

```dotenv
JIRA_MCP_EMAIL=service-account@example.com
JIRA_MCP_API_TOKEN=replace-with-scoped-rovo-mcp-token
JIRA_MCP_CLOUD_ID=https://example.atlassian.net
JIRA_MCP_PROJECT_KEY=OPS
JIRA_MCP_ISSUE_TYPE=Task
```

Start the opt-in override:

```bash
docker compose -f compose.yaml -f compose.jira-mcp.yaml up --build --wait
```

The override enables Jira only; Slack and GitHub publishing stay disabled.
Approve the analysis, inspect the generated draft, and then approve that exact
draft in the publication review. A successful response becomes the state's
`postmortem_url`.

## Deployment configuration

| Variable | Required value |
| --- | --- |
| `PUBLISH_EXTERNAL` | `true` master switch |
| `PUBLISH_JIRA_MCP` | `true` Jira destination switch |
| `PUBLISH_SLACK`, `PUBLISH_GITHUB` | Set independently; both may be `false` |
| `JIRA_MCP_URL` | `https://mcp.atlassian.com/v1/mcp` for API-token auth |
| `JIRA_MCP_EMAIL` | Token owner/service-account email |
| `JIRA_MCP_API_TOKEN` | Scoped secret from the deployment secret manager |
| `JIRA_MCP_CLOUD_ID` | Full site URL, for example `https://example.atlassian.net` |
| `JIRA_MCP_PROJECT_KEY` | Deployment-owned Jira project key |
| `JIRA_MCP_ISSUE_TYPE` | Existing issue type; defaults to `Task` |
| `JIRA_MCP_TIMEOUT_SECONDS` | `1..120`; defaults to `30` |

Secure runtimes must also allowlist `mcp.atlassian.com` in
`EGRESS_ALLOWED_HOSTS`. The endpoint, project and issue type come only from
deployment configuration. The MCP tool is fixed in code to `createJiraIssue`;
alerts and model output cannot select a tool or destination.

## Failure and verification boundary

- The call is covered by the existing durable publication claim.
- A completed claim is not published twice.
- A timeout, transport loss or unparseable success response is marked
  uncertain and blocks automatic retry until an operator reconciles Jira.
- Only an HTTPS result on the configured Atlassian site is accepted as the
  returned issue URL.
- Public tests use an in-process fake MCP result. This repository contains no
  Atlassian token, private site name or proof of a live Jira write.

Before connecting a real target, complete
[PRODUCTION_READINESS.md](PRODUCTION_READINESS.md), including least privilege,
secret rotation, audit, egress and partial-publication recovery.
