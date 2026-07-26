import argparse
import json
import os
import sys


parser = argparse.ArgumentParser(
    description=(
        "Run the incident-agent "
        "graph against a fixture."
    )
)
parser.add_argument(
    "--no-llm",
    action="store_true",
    help=(
        "Skip all LLM calls; use "
        "deterministic stubs for "
        "interpretation / RCA / "
        "postmortem. Full pipeline "
        "still runs."
    )
)
parser.add_argument(
    "--fixture",
    default=(
        "fixtures/latency_alert.json"
    ),
    help=(
        "Path to alert fixture "
        "JSON (default: "
        "fixtures/latency_alert.json)"
    )
)
parser.add_argument(
    "--keep-incident-id",
    action="store_true",
    help=(
        "Use the incident_id from "
        "the fixture instead of "
        "allocating a fresh "
        "six-digit demo ID."
    )
)
parser.add_argument(
    "--stop-at-review",
    action="store_true",
    help=(
        "Stop at the human-review gate. "
        "Do not auto-approve, generate "
        "RCA/postmortem, or publish."
    ),
)

args, _ = parser.parse_known_args()

if args.no_llm:
    os.environ["SKIP_LLM"] = "true"

_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from langgraph.types import (
    Command
)

from graph.workflow import (
    graph
)

from settings import (
    HTML_OUTPUT_DIR
)

from utils.incident_ids import (
    next_incident_id
)


with open(args.fixture) as f:
    alert = json.load(f)

if not args.keep_incident_id:
    original_incident_id = alert.get(
        "incident_id"
    )
    alert["incident_id"] = next_incident_id(
        HTML_OUTPUT_DIR
    )
    print(
        "[run_fixture] allocated "
        f"{alert['incident_id']} "
        f"(fixture had "
        f"{original_incident_id})"
    )


config = {
    "configurable": {
        "thread_id": alert["incident_id"]
    }
}


state = graph.invoke(
    {
        "alert": alert,
        "execution_log": []
    },
    config=config
)


def hr(title):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


hr("TRIAGE")
print(
    f"Severity: {state.get('severity')} "
    f"— {state.get('severity_reason')}"
)
print(
    "Business context: "
    f"{state.get('business_context')}"
)


hr("ANCHOR EVENT")
print(state.get("anchor_event"))


hr("FREQUENCY HEATMAP")
print(
    state.get(
        "frequency_heatmap_ascii",
        ""
    )
)


hr("TIMELINE (with offsets)")
for e in state.get("timeline", []):
    marker = (
        " *ANCHOR*"
        if e.get("is_anchor")
        else ""
    )
    print(
        f"{e.get('offset', 'T?')}"
        f"{marker}  "
        f"[{e.get('type')}] "
        f"{e.get('timestamp')}  "
        f"{e.get('labels') or e.get('commit') or ''}"
    )


hr("DETECTION RULES MATCHED")
for d in state.get(
    "detections", []
):
    print(
        f"[{d.get('level')}] "
        f"{d.get('title')} "
        f"({d.get('category')})  "
        f"on {d.get('group_labels')} "
        f"count={d.get('group_count')}"
    )


hr("LOG GROUPS (post-suppression)")
for g in state["log_groups"]:
    dets = ", ".join(
        d["id"]
        for d in g.get(
            "detections", []
        )
    ) or "-"
    print(
        f"[{g['count']:>4}] "
        f"{g['labels']}  "
        f"owner={g.get('owner')} "
        f"detections=[{dets}]"
    )
    print(
        f"       msg: "
        f"{g.get('example_message_decoded')}"
    )


hr("SUPPRESSED GROUPS")
for g in state.get(
    "suppressed_groups", []
):
    print(
        f"  [{g.get('count')}] "
        f"{g.get('labels')} "
        f"suppressed_by="
        f"{g.get('suppressed_by')}"
    )


hr("PIVOT KEYWORDS")
for k, values in (
    state.get("pivots", {}).items()
):
    print(f"  {k}: {values}")


hr("LLM INTERPRETATION (for reviewer)")
print(state["interpretation"])

traces = state.get(
    "interpretation_tool_trace", []
)
if traces:
    print()
    print(
        "Tool calls made during "
        "interpretation:"
    )
    for t in traces:
        print(f"  - {t}")

if args.stop_at_review:
    hr("STOPPED AT HUMAN REVIEW")
    print(
        "No review approval, RCA, "
        "postmortem, or publication "
        "was performed."
    )
    sys.exit(0)


hr(
    "Auto-approving Hypothesis 1 for demo."
)
state = graph.invoke(
    Command(
        resume={
            "status": "approved",
            "chosen_hypothesis": 1
        }
    ),
    config=config
)


hr("5-WHYS DRILLDOWN")
print(state.get("rca_chain"))


hr("FINAL POSTMORTEM")
print(state["postmortem_draft"])


hr("PUBLISHED")
print(
    "Postmortem URL: "
    f"{state.get('postmortem_url')}"
)
print(
    "HTML report: "
    f"{state.get('postmortem_html_path')}"
)
