import os

from clients.slack_client import (
    slack
)

from clients.github_client import (
    github
)

from utils.html_report import (
    render as render_html
)

from settings import (
    HTML_OUTPUT_DIR,
    PUBLISH_EXTERNAL,
)
from utils.redaction import redact_data, redact_message
from utils.render_safety import safe_report_path
from webhook.incident_store import (
    begin_publication,
    complete_publication,
    mark_publication_uncertain,
)


def _alertname(alert):

    return (
        alert
        .get("labels", {})
        .get("alertname")
        or alert.get("alertname")
        or "Incident"
    )


def _write_html(state, title):

    heatmap = state.get(
        "frequency_heatmap_ascii", ""
    )

    html = render_html(
        redact_data(state), heatmap
    )

    os.makedirs(
        HTML_OUTPUT_DIR,
        exist_ok=True
    )

    incident_id = state.get(
        "incident_id", "unknown"
    )

    path = safe_report_path(
        HTML_OUTPUT_DIR, incident_id, ".html"
    )

    with open(path, "w") as f:
        f.write(html)

    print(
        "[publish] wrote HTML "
        f"report -> {path}"
    )

    return path


def publish(state):

    alert = state["alert"]
    draft = redact_message(state["postmortem_draft"])

    incident_id = state.get(
        "incident_id",
        "unknown"
    )

    severity = state.get(
        "severity", "SEV?"
    )

    title = redact_message(
        f"[{incident_id}] "
        f"[{severity}] "
        f"{_alertname(alert)}"
    )

    html_path = _write_html(
        state, title
    )

    issue_url = None
    if PUBLISH_EXTERNAL:
        publication = begin_publication(incident_id, draft)
        if publication["status"] == "completed":
            issue_url = publication.get("issue_url") or None
        else:
            try:
                slack.publish(
                    draft
                    + "\n\n"
                    + "_HTML report: "
                    + f"{html_path}_",
                    title=title
                )
                issue_url = github.create_postmortem(
                    title,
                    draft
                )
                complete_publication(
                    publication["publication_key"],
                    publication["attempt_token"],
                    issue_url,
                )
            except Exception as exc:
                mark_publication_uncertain(
                    publication["publication_key"],
                    publication["attempt_token"],
                    exc,
                )
                raise
    else:
        print(
            "[publish] external publishing disabled; "
            "wrote local draft only"
        )

    return {
        "postmortem_url":
        issue_url or "",
        "postmortem_html_path":
        html_path
    }
