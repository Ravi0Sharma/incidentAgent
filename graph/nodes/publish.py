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
