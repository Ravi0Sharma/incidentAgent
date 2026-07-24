"""Scan versionable repository files without ever printing secret values."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".langgraph_api",
    ".phoenix_data",
    "__pycache__",
    "data",
    "output",
    "var",
}
EXCLUDED_NAMES = {".env", ".DS_Store"}
TEXT_SUFFIXES = {
    ".css", ".html", ".ini", ".json", ".md", ".py", ".sh", ".svg",
    ".toml", ".txt", ".yaml", ".yml",
}
PATTERNS = {
    "openai_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    "slack_token": re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{16,}\b", re.I),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
}
PLACEHOLDER_FRAGMENTS = {
    "example", "placeholder", "replace", "dummy", "fake", "012345", "xxxxx"
}


def _candidate_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in EXCLUDED_NAMES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            ".gitignore", ".python-version",
        }:
            continue
        yield path


def scan_root(root: Path):
    findings = []
    for path in _candidate_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, 1):
            if "nosecret" in line.lower():
                continue
            for detector, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    candidate = match.group(0).lower()
                    if any(item in candidate for item in PLACEHOLDER_FRAGMENTS):
                        continue
                    findings.append({
                        "path": str(path.relative_to(root)),
                        "line": line_number,
                        "detector": detector,
                    })
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan_root(root)
    if findings:
        print(f"secret scan failed: {len(findings)} potential finding(s)")
        for finding in findings:
            print(
                f"{finding['path']}:{finding['line']}: "
                f"{finding['detector']} (value suppressed)"
            )
        return 1
    print("secret scan passed: no credential patterns in versionable files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

