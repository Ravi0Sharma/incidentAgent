from datetime import datetime, timedelta

from settings import (
    GITHUB_TOKEN,
    GITHUB_REPO,
    DEPLOY_LOOKBACK_HOURS
)

from utils.incident_window import parse_window
from utils.resilience import request
from utils.redaction import redact_message


API_ROOT = "https://api.github.com"


def _headers():
    return {
        "Authorization":
        f"Bearer {GITHUB_TOKEN}",
        "Accept":
        "application/vnd."
        "github+json",
        "X-GitHub-Api-Version":
        "2022-11-28"
    }


class RealGithubClient:

    def __init__(self, repo):
        self.repo = repo

    def get_recent_deploys(
        self,
        service=None,
        window=None,
    ):

        url = (
            f"{API_ROOT}/repos/"
            f"{self.repo}/deployments"
        )

        params = {
            "per_page": 30
        }

        if service:
            params["environment"] = (
                service
            )

        resp = request(
            "github", "GET",
            url,
            params=params,
            headers=_headers(),
        )

        _, window_end = parse_window(window)
        cutoff = window_end - timedelta(
            hours=DEPLOY_LOOKBACK_HOURS
        )

        deploys = []

        for d in resp.json():

            created_at = (
                datetime.fromisoformat(
                    d["created_at"]
                    .replace(
                        "Z", "+00:00"
                    )
                )
            )

            if created_at < cutoff:
                continue

            deploys.append({
                "time":
                d["created_at"],
                "commit":
                d["sha"][:7],
                "environment":
                d.get(
                    "environment", ""
                ),
                "ref": d.get("ref", ""),
                "description":
                d.get(
                    "description", ""
                )
            })

        return deploys

    def create_postmortem(
        self,
        title,
        body
    ):

        title = redact_message(title)
        body = redact_message(body)

        url = (
            f"{API_ROOT}/repos/"
            f"{self.repo}/issues"
        )

        resp = request(
            "github", "POST",
            url,
            json={
                "title": title,
                "body": body,
                "labels": [
                    "postmortem",
                    "incident"
                ]
            },
            headers=_headers(),
        )

        return resp.json().get(
            "html_url"
        )


class MockGithubClient:

    def get_recent_deploys(
        self,
        service=None,
        window=None,
    ):
        _, end = parse_window(window)
        return [
            {
                "time": (
                    end - timedelta(minutes=8)
                ).isoformat().replace("+00:00", "Z"),
                "commit": "poolcfg1",
                "environment":
                service or "payments",
                "ref": "main",
                "description":
                "synthetic pool configuration rollout"
            }
        ]

    def create_postmortem(
        self,
        title,
        body
    ):
        title = redact_message(title)
        body = redact_message(body)
        print(
            "[MOCK GITHUB] would "
            f"create issue: {title}"
        )
        print(body[:200] + "...")
        return None


def _make_client():

    if GITHUB_TOKEN and GITHUB_REPO:
        return RealGithubClient(
            GITHUB_REPO
        )

    print(
        "[github_client] GITHUB_TOKEN "
        "or GITHUB_REPO not set, "
        "using mock"
    )
    return MockGithubClient()


github = _make_client()
