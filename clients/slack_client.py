from settings import (
    SLACK_WEBHOOK_URL,
    SLACK_CHANNEL
)

from utils.resilience import request
from utils.redaction import redact_message


class RealSlackClient:

    def __init__(
        self,
        webhook_url,
        channel
    ):
        self.webhook_url = webhook_url
        self.channel = channel

    def publish(
        self,
        text,
        title=None
    ):

        text = redact_message(text)
        title = redact_message(title) if title else None

        blocks = []

        if title:
            blocks.append({
                "type": "header",
                "text": {
                    "type":
                    "plain_text",
                    "text": title
                }
            })

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text
            }
        })

        payload = {
            "channel": self.channel,
            "text":
            title or "Incident update",
            "blocks": blocks
        }

        request(
            "slack", "POST",
            self.webhook_url,
            json=payload,
        )


class MockSlackClient:

    def publish(
        self,
        text,
        title=None
    ):
        text = redact_message(text)
        title = redact_message(title) if title else None
        if title:
            print(
                f"[MOCK SLACK] "
                f"{title}"
            )
        print(text)


def _make_client():

    if SLACK_WEBHOOK_URL:
        return RealSlackClient(
            SLACK_WEBHOOK_URL,
            SLACK_CHANNEL
        )

    print(
        "[slack_client] "
        "SLACK_WEBHOOK_URL not set, "
        "using mock"
    )
    return MockSlackClient()


slack = _make_client()
