import json

from langgraph.types import (
    Command
)

from graph.workflow import (
    graph
)


with open(
    "fixtures/"
    "grafana_alertmanager_payload"
    ".json"
) as f:
    payload = json.load(f)


def normalize(alert):

    labels = alert.get(
        "labels", {}
    )
    annotations = alert.get(
        "annotations", {}
    )

    return {
        "incident_id": (
            alert.get("fingerprint")
            or labels.get(
                "alertname",
                "unknown"
            )
        ),
        "service": (
            labels.get("service")
            or labels.get("job")
            or "unknown"
        ),
        "severity": labels.get(
            "severity", "unknown"
        ),
        "alertname": labels.get(
            "alertname", "unknown"
        ),
        "message": (
            annotations.get("summary")
            or annotations.get(
                "description", ""
            )
        ),
        "labels": labels,
        "annotations": annotations,
        "started_at": alert.get(
            "startsAt"
        ),
        "generator_url": alert.get(
            "generatorURL"
        ),
        "fingerprint": alert.get(
            "fingerprint"
        )
    }


firing = [
    normalize(a)
    for a in payload["alerts"]
    if a.get("status") == "firing"
]


CHOSEN_HYPOTHESIS = 1


for alert in firing:

    thread_id = alert[
        "incident_id"
    ]

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    print("=" * 60)
    print(
        f"INCOMING ALERT "
        f"[{alert['alertname']}] "
        f"service={alert['service']} "
        f"severity="
        f"{alert['severity']}"
    )
    print("=" * 60)

    state = graph.invoke(
        {
            "alert": alert,
            "execution_log": []
        },
        config=config
    )

    print()
    print("=" * 60)
    print(
        "LOG GROUPS "
        "(aggregated by labels)"
    )
    print("=" * 60)

    for g in state.get(
        "log_groups", []
    ):
        print(
            f"[{g['count']:>4}] "
            f"{g['labels']}  "
            f"{g['first_seen']} "
            f"-> {g['last_seen']}"
        )

    print()
    print("=" * 60)
    print(
        "LLM RANKED HYPOTHESES "
        "(for reviewer)"
    )
    print("=" * 60)
    print(
        state.get(
            "interpretation", ""
        )
    )

    print()
    print("=" * 60)
    print(
        f"Auto-approving "
        f"Hypothesis "
        f"{CHOSEN_HYPOTHESIS} "
        f"for demo."
    )
    print("=" * 60)

    state = graph.invoke(
        Command(
            resume={
                "status": "approved",
                "chosen_hypothesis":
                CHOSEN_HYPOTHESIS
            }
        ),
        config=config
    )

    print()
    print("=" * 60)
    print(
        "FINAL POSTMORTEM "
        f"(based on Hypothesis "
        f"{CHOSEN_HYPOTHESIS})"
    )
    print("=" * 60)
    print(
        state.get(
            "postmortem_draft", ""
        )
    )

    if state.get("postmortem_url"):
        print()
        print(
            "GitHub issue: "
            f"{state['postmortem_url']}"
        )
