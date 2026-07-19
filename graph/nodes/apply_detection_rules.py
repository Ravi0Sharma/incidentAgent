from utils.detection_rules import (
    apply_rules
)


def apply_detection_rules(state):

    groups = state.get(
        "log_groups", []
    )
    deploys = state.get(
        "deploys", []
    )

    tagged, matches = apply_rules(
        groups,
        deploys=deploys
    )

    return {
        "log_groups": tagged,
        "detections": matches
    }
