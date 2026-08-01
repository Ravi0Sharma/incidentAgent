import os
import re

import yaml


_CONFIG_PATH = os.getenv(
    "CODE_MAP_PATH",
    os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.abspath(__file__)
            )
        ),
        "config",
        "code_map.yaml"
    )
)


def _load():

    if not os.path.exists(
        _CONFIG_PATH
    ):
        return {
            "codes": {},
            "patterns": []
        }

    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


_CONFIG = _load()

_CODES = _CONFIG.get(
    "codes", {}
) or {}

_PATTERNS = [
    {
        **p,
        "_compiled": re.compile(
            p["regex"]
        )
    }
    for p in (
        _CONFIG.get("patterns", [])
        or []
    )
]


def decode(message):

    if not message:
        return []

    found = []

    for p in _PATTERNS:

        m = p["_compiled"].search(
            message
        )

        if not m:
            continue

        code = m.group(1)
        table = _CODES.get(
            p["lookup"], {}
        )
        meaning = table.get(code)

        if meaning:
            found.append({
                "label": p["label"],
                "code": code,
                "meaning": meaning
            })

    return found


def decorate(message):

    hits = decode(message)

    if not hits:
        return message

    parts = [
        f"[{h['label']} {h['code']}: "
        f"{h['meaning']}]"
        for h in hits
    ]

    return (
        message
        + "  "
        + " ".join(parts)
    )
