#!/usr/bin/env python3
"""Run LogHub 2.0 Linux through parser and label-last grouping only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from evaluation.loghub2_windows import (
    evaluate_template_grouping,
    load_linux_syslog_records,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=REPO_ROOT.parent / "Loghub-2.0" / "extracted",
    )
    parser.add_argument("--sample-limit", type=int, default=200)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "output" / "loghub2-linux.json",
    )
    args = parser.parse_args()

    root = args.dataset_root / "Linux" / "Linux"
    raw_path = root / "Linux_full.log"
    structured_path = root / "Linux_full.log_structured.csv"
    for path in (raw_path, structured_path):
        if not path.is_file():
            parser.error(f"required LogHub 2.0 file missing: {path}")
    records, source_stats = load_linux_syslog_records(str(raw_path))
    grouping = evaluate_template_grouping(
        {"linux-syslog": {
            "truth": "unlabeled",
            "selection_cohort": "full_parser_corpus",
            "records": records,
        }},
        str(structured_path),
        dataset="loghub2_linux_syslog",
        sample_limit=max(args.sample_limit, 1),
    )
    structural_gate = all((
        source_stats.get("unparsed_lines", 0) == 0,
        grouping["missing_template_truth_rows"] == 0,
        grouping["selection_used_template_truth"] is False,
    ))
    report = {
        "suite": "loghub2-linux-syslog-parser-grouping/v1",
        "model_called": False,
        "pre_review_eligible": False,
        "pre_review_eligibility_reason": (
            "source omits year and severity; timestamps are schema-only and "
            "marked not_comparable, so this corpus cannot validate incident "
            "timeline, impact, correlation, or OpenAI interpretation"
        ),
        "structural_gate_passed": structural_gate,
        "source_stats": source_stats,
        "grouping": grouping,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(args.output.resolve()),
        "structural_gate_passed": structural_gate,
        "source_stats": source_stats,
        "pairwise": grouping["pairwise"],
        "source_event_labels": grouping["source_event_labels"],
        "pre_review_eligible": False,
    }, indent=2, sort_keys=True))
    return 0 if structural_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
