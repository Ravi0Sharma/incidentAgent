#!/usr/bin/env python3
"""Evaluate HDFS_v1 or OpenStack through the typed impact boundary."""

import argparse
import html
import json
import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.distributed_log_datasets import (
    evaluate_distributed_dataset,
)


def _render_index(report):
    metrics = report.get("metrics", {})
    metric_items = "".join(
        "<li><strong>"
        + html.escape(str(key))
        + ":</strong> "
        + html.escape(str(value))
        + "</li>"
        for key, value in metrics.items()
    )
    rows = []
    for case in report.get("cases", []):
        review = case.get("review_html")
        case_id = html.escape(
            str(case.get("case_id"))
        )
        link = (
            f'<a href="{html.escape(review)}">'
            + case_id
            + "</a>"
            if review
            else case_id
        )
        rows.append(
            "<tr>"
            f"<td>{link}</td>"
            f"<td>{html.escape(str(case.get('truth')))}</td>"
            f"<td>{case.get('source_records', 0)}</td>"
            f"<td>{html.escape(str(case.get('raw_signal_families', {})))}</td>"
            f"<td>{html.escape(str(case.get('observed_signal_families', {})))}</td>"
            f"<td>{html.escape(str(case.get('observation_pattern_families', {})))}</td>"
            f"<td>{html.escape(str(case.get('impact_status_counts', {})))}</td>"
            f"<td>{html.escape(str(case.get('review_status')))}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(report.get('dataset', 'dataset'))} impact generalization</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:2rem;background:#f6f8fa;color:#17202a}}
main{{max-width:1300px;margin:auto;background:white;padding:2rem;border-radius:14px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}
th,td{{border:1px solid #d8dee4;padding:.55rem;text-align:left}}
th{{background:#eef3f7}}li{{margin:.25rem 0}}
</style></head><body><main>
<h1>{html.escape(report.get('dataset', 'dataset'))} impact generalization</h1>
<p>Dataset truth was joined only after pipeline, grounding, and case review.
The labels do not contain a root-cause class.</p>
<ul>{metric_items}</ul>
<table><thead><tr><th>Case</th><th>Post-review label</th><th>Records</th>
<th>Catalog signals</th><th>Fault observations</th>
<th>Correlated patterns</th><th>Impact</th><th>Review</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        choices=(
            "hdfs_v1",
            "hdfs_v3",
            "openstack",
            "bgl",
            "zookeeper",
        ),
        required=True,
    )
    parser.add_argument("--path")
    parser.add_argument(
        "--sample-limit", type=int, default=200
    )
    parser.add_argument(
        "--cases-per-label", type=int, default=8
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--html-dir")
    args = parser.parse_args()
    defaults = {
        "hdfs_v1": "HDFS_v1",
        "hdfs_v3": "HDFS_v3_TraceBench",
        "openstack": "OpenStack",
        "bgl": "BGL",
        "zookeeper": "Zookeeper.log",
    }
    default_path = os.path.abspath(
        os.path.join(
            _ROOT,
            "..",
            defaults[args.dataset],
        )
    )
    report = evaluate_distributed_dataset(
        dataset=args.dataset,
        root=os.path.abspath(
            args.path or default_path
        ),
        sample_limit=max(args.sample_limit, 1),
        cases_per_label=max(
            args.cases_per_label, 1
        ),
        html_dir=args.html_dir,
    )
    output = os.path.abspath(args.output)
    os.makedirs(
        os.path.dirname(output) or ".",
        exist_ok=True,
    )
    with open(
        output, "w", encoding="utf-8"
    ) as handle:
        json.dump(
            report,
            handle,
            indent=2,
            sort_keys=True,
        )
    if args.html_dir:
        os.makedirs(args.html_dir, exist_ok=True)
        with open(
            os.path.join(
                args.html_dir, "index.html"
            ),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(_render_index(report))
    metrics = report["metrics"]
    print(
        f"dataset={args.dataset} "
        f"cases={metrics['cases']} "
        f"observed={metrics['observed_signals_total']} "
        f"grounding={metrics['grounding_pass_rate']:.2%} "
        f"impact_contract={metrics['impact_contract_pass_rate']:.2%} "
        f"gate={report['contract_gate_passed']}"
    )
    print("output: " + output)
    return 0 if report["contract_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
