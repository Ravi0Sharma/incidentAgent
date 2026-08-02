import os
import re

import yaml


_RULES_DIR = os.getenv(
    "DETECTION_RULES_DIR",
    os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "rules"
    )
)


def _parse_rule_file(path):

    with open(path) as f:
        raw = f.read()

    if path.endswith(".md"):
        rule, body = _parse_frontmatter(
            raw
        )
        if body and not rule.get("hint"):
            rule["hint"] = body
        return rule

    return yaml.safe_load(raw) or {}


def _parse_frontmatter(raw):

    stripped = raw.lstrip()

    if not stripped.startswith("---"):
        return {}, raw.strip()

    parts = stripped.split(
        "---", 2
    )

    if len(parts) < 3:
        return {}, raw.strip()

    meta = yaml.safe_load(
        parts[1]
    ) or {}

    body = parts[2].strip()

    body = re.sub(
        r"^#\s+.*\n+",
        "",
        body,
        count=1
    )

    return meta, body.strip()


def _load_rules():

    rules = []

    if not os.path.isdir(
        _RULES_DIR
    ):
        return rules

    for fname in sorted(
        os.listdir(_RULES_DIR)
    ):

        if not fname.endswith(
            (".md", ".yaml", ".yml")
        ):
            continue

        path = os.path.join(
            _RULES_DIR, fname
        )

        rule = _parse_rule_file(path)

        sel = rule.get(
            "selection", {}
        ) or {}

        if "message_regex" in sel:
            rule["_regex"] = (
                re.compile(
                    sel[
                        "message_regex"
                    ],
                    re.IGNORECASE
                )
            )

        rules.append(rule)

    return rules


_RULES = _load_rules()


_LEVEL_RANK = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "informational": 0
}


def _match_static(rule, group):

    sel = rule.get(
        "selection", {}
    ) or {}

    labels = group.get(
        "labels", {}
    ) or {}

    if "level" in sel:

        allowed = sel["level"]

        if isinstance(allowed, str):
            allowed = [allowed]

        if labels.get(
            "level"
        ) not in allowed:
            return False

    if "_regex" in rule:

        msg = group.get(
            "example_message", ""
        ) or ""

        if not rule[
            "_regex"
        ].search(msg):
            return False

    return True


def _match_deploy_window(
    rule,
    group,
    deploys
):

    sel = rule.get(
        "selection", {}
    ) or {}

    window_min = sel.get(
        "first_seen_within_"
        "minutes_after_deploy"
    )

    if window_min is None:
        return True

    from datetime import (
        datetime,
        timedelta
    )

    def _parse(ts):
        if not ts:
            return None
        try:
            return (
                datetime.fromisoformat(
                    ts.replace(
                        "Z", "+00:00"
                    )
                )
            )
        except (
            ValueError,
            AttributeError
        ):
            return None

    first_seen = _parse(
        group.get("first_seen")
    )

    if first_seen is None:
        return False

    group_service = (
        group.get("labels", {})
        .get("service")
    )

    for d in deploys or []:

        deploy_service = (
            d.get("environment")
            or d.get("service")
        )

        if (
            group_service
            and deploy_service
            and deploy_service
            != group_service
        ):
            continue

        d_time = _parse(
            d.get("time")
        )

        if d_time is None:
            continue

        delta = (
            first_seen - d_time
        )

        if (
            timedelta(0)
            <= delta
            <= timedelta(
                minutes=window_min
            )
        ):
            return True

    return False


def match_group(
    group,
    deploys=None
):

    matches = []

    for rule in _RULES:

        if not _match_static(
            rule, group
        ):
            continue

        if not _match_deploy_window(
            rule, group, deploys
        ):
            continue

        matches.append({
            "id": rule.get("id"),
            "title": rule.get("title"),
            "level": rule.get("level"),
            "category": rule.get(
                "category"
            ),
            "tags": rule.get(
                "tags", []
            ),
            "hint": rule.get("hint"),
            "runbook": rule.get(
                "runbook"
            )
        })

    return matches


def apply_rules(
    groups,
    deploys=None
):

    tagged = []
    all_matches = []

    for g in groups:

        matches = match_group(
            g, deploys=deploys
        )

        tagged.append({
            **g,
            "detections": matches
        })

        for m in matches:
            all_matches.append({
                "event_id":
                g.get("event_id"),
                "group_labels":
                g.get("labels"),
                "group_count":
                g.get("count"),
                **m
            })

    all_matches.sort(
        key=lambda m: (
            -_LEVEL_RANK.get(
                m.get("level"), 0
            ),
            -(
                m.get(
                    "group_count", 0
                ) or 0
            )
        )
    )

    return tagged, all_matches
