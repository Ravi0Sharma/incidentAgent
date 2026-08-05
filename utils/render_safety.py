"""Small fail-closed helpers for report paths and oversized text rendering."""

import hashlib
import os
import re
from pathlib import Path


MAX_RENDER_TEXT_CHARS = 100_000


def bounded_text(value, limit=MAX_RENDER_TEXT_CHARS):
    text = str(value if value is not None else "")
    maximum = max(int(limit), 64)
    if len(text) <= maximum:
        return text
    omitted = len(text) - maximum
    return text[:maximum] + f"\n[render truncated: {omitted} characters omitted]"


def safe_report_filename(incident_id, suffix=".html"):
    raw = str(incident_id or "unknown")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._") or "unknown"
    if cleaned != raw or raw in {".", ".."}:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        cleaned = cleaned[:80] + "-" + digest
    return cleaned[:128] + str(suffix)


def safe_report_path(directory, incident_id, suffix=".html"):
    """Return a filename inside directory even for an attacker-controlled ID."""
    filename = safe_report_filename(incident_id, suffix)
    root = Path(directory).resolve()
    candidate = (root / filename).resolve()
    if os.path.commonpath([str(root), str(candidate)]) != str(root):
        raise ValueError("report path escaped the configured output directory")
    return str(candidate)
