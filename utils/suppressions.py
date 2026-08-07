import os
import re

import yaml


_CONFIG_PATH = os.getenv(
    "SUPPRESSIONS_PATH",
    os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "config",
        "suppressions.yaml"
    )
)


def _load():

    if not os.path.exists(
        _CONFIG_PATH
    ):
        return []

    with open(_CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}

    rules = (
        data.get("suppressions", [])
        or []
    )

    for r in rules:
        if "message_regex" in r:
            r["_regex"] = re.compile(
                r["message_regex"],
                re.IGNORECASE
            )

    return rules


_RULES = _load()


def _matches(group, rule):

    labels = group.get(
        "labels", {}
    ) or {}

    if "service" in rule:
        if labels.get(
            "service"
        ) != rule["service"]:
            return False

    if "level" in rule:
        if labels.get(
            "level"
        ) != rule["level"]:
            return False

    if "error_type" in rule:
        if labels.get(
            "error_type"
        ) != rule["error_type"]:
            return False

    if "_regex" in rule:
        msg = group.get(
            "example_message", ""
        ) or ""
        if not rule["_regex"].search(
            msg
        ):
            return False

    if "min_count" in rule:
        if (
            group.get("count", 0)
            < rule["min_count"]
        ):
            return False

    return True


def filter_groups(groups):

    kept = []
    suppressed = []

    for g in groups:

        matched = None

        for rule in _RULES:
            if _matches(g, rule):
                matched = rule
                break

        if matched:
            suppressed.append({
                **g,
                "suppressed_by":
                matched.get("id"),
                "suppress_reason":
                matched.get("reason")
            })
        else:
            kept.append(g)

    return kept, suppressed
