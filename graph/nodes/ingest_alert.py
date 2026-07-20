from utils.incident_window import (
    build_incident_window
)


def ingest_alert(state):

    alert = state["alert"]

    return {
        "incident_id":
        alert["incident_id"],
        "incident_window":
        build_incident_window(alert)
    }
