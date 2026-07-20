import os

from langgraph.types import (
    interrupt
)

from settings import (
    HTML_OUTPUT_DIR
)

from utils.html_report import (
    render_review
)
from utils.render_safety import safe_report_path


def _write_review_html(state):
    os.makedirs(
        HTML_OUTPUT_DIR,
        exist_ok=True
    )

    incident_id = state.get(
        "incident_id", "unknown"
    )
    path = safe_report_path(
        HTML_OUTPUT_DIR, incident_id, "-review.html"
    )

    with open(path, "w") as f:
        f.write(
            render_review(state)
        )

    print(
        "[human_review] wrote "
        f"review screen -> {path}"
    )

    return path


def human_review(state):

    review_html_path = (
        _write_review_html(state)
    )

    result = interrupt(
        {
            "interpretation":
            state["interpretation"],

            "review_html_path":
            review_html_path,

            "evidence_pack":
            state.get("evidence_pack", ""),

            "semantic_correlation":
            state.get(
                "semantic_correlation", {}
            ),

            "semantic_correlation_tool_trace":
            state.get(
                "semantic_correlation_tool_trace",
                []
            ),

            "metrics":
            state.get("metrics", [])[:5],

            "deploys":
            state.get("deploys", [])[:3],

            "attempt": state.get(
                "interpretation_attempts",
                1
            ),

            "instructions": (
                "Resume with: "
                "{'status': 'approved', "
                "'chosen_hypothesis': "
                "1|2|3} OR "
                "{'status': 'rejected', "
                "'feedback': '...'} OR "
                "{'status': 'request_more_evidence', "
                "'feedback': 'exact evidence needed'}"
            )
        }
    )

    status = result.get("status", "rejected")
    if status not in (
        "approved", "rejected", "request_more_evidence"
    ):
        status = "rejected"
    try:
        chosen = int(result.get("chosen_hypothesis", 1))
    except (TypeError, ValueError):
        chosen = 1
    chosen = chosen if chosen in (1, 2, 3) else 1

    return {
        "review_status":
        status,
        "review_feedback":
        result.get("feedback", ""),
        "chosen_hypothesis":
        chosen
    }
