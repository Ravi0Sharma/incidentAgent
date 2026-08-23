#!/usr/bin/env python3
"""Fail when a repository Markdown link points at a missing local file."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", ".langgraph_api", ".phoenix_data", "output"}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "data:")


def _markdown_files():
    for path in ROOT.rglob("*.md"):
        if not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts):
            yield path


def _target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", 1)[0])


def broken_links():
    broken = []
    for source in _markdown_files():
        for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
            for match in LINK_PATTERN.finditer(line):
                target = _target(match.group(1))
                if not target or target.startswith(EXTERNAL_PREFIXES):
                    continue
                destination = (source.parent / target).resolve()
                try:
                    destination.relative_to(ROOT)
                except ValueError:
                    broken.append((source, line_number, target, "outside repository"))
                    continue
                if not destination.exists():
                    broken.append((source, line_number, target, "missing"))
    return broken


def main():
    failures = broken_links()
    if failures:
        for source, line_number, target, reason in failures:
            print(f"{source.relative_to(ROOT)}:{line_number}: {target} ({reason})")
        print(f"Markdown link check failed: {len(failures)} broken link(s)", file=sys.stderr)
        return 1
    print("Markdown link check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
