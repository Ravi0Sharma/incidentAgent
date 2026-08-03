import os
import re
import sqlite3

from settings import (
    HTML_OUTPUT_DIR,
    INCIDENT_STORE_PATH,
)


_INCIDENT_RE = re.compile(
    r"^INC-(\d+)\.html$"
)


def next_incident_id(
    output_dir,
    prefix="INC",
    width=6,
    start=100001
):
    os.makedirs(
        output_dir,
        exist_ok=True
    )

    counter_path = os.path.join(
        output_dir,
        ".incident_counter"
    )

    highest = start - 1

    try:
        with open(counter_path) as f:
            highest = max(
                highest,
                int(f.read().strip())
            )
    except (
        FileNotFoundError,
        ValueError
    ):
        pass

    for name in os.listdir(output_dir):
        match = _INCIDENT_RE.match(name)
        if not match:
            continue
        highest = max(
            highest,
            int(match.group(1))
        )

    next_value = highest + 1

    with open(counter_path, "w") as f:
        f.write(str(next_value))

    return (
        f"{prefix}-"
        f"{next_value:0{width}d}"
    )


def get_or_create_incident_id(alert):
    """Allocate one six-digit ID per Alertmanager occurrence.

    Alertmanager retries reuse fingerprint + startsAt. A later firing gets a
    new ID, so it cannot resume an old completed LangGraph thread.
    """
    alert = alert or {}
    supplied = str(alert.get("incident_id", ""))
    if re.fullmatch(r"INC-\d{6,}", supplied):
        return supplied

    fingerprint = (
        alert.get("fingerprint")
        or alert.get("upstream_incident_id")
        or alert.get("alertname", "unknown")
    )
    key = "|".join([
        str(fingerprint),
        str(alert.get("service", "unknown")),
        str(alert.get("started_at", "unknown")),
    ])
    os.makedirs(
        os.path.dirname(INCIDENT_STORE_PATH) or ".",
        exist_ok=True,
    )
    with sqlite3.connect(INCIDENT_STORE_PATH) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS incident_id_map "
            "(incident_key TEXT PRIMARY KEY, incident_id TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT incident_id FROM incident_id_map WHERE incident_key = ?",
            (key,),
        ).fetchone()
        if row:
            return row[0]
        incident_id = next_incident_id(HTML_OUTPUT_DIR)
        conn.execute(
            "INSERT INTO incident_id_map VALUES (?, ?)",
            (key, incident_id),
        )
        return incident_id
