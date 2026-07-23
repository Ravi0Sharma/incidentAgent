#!/usr/bin/env python3
"""Audit OpenStack duration confounders and HDFS ordered outcomes."""

import argparse
import html
import json
import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.distributed_feature_audit import (
    audit_hdfs_event_traces,
    audit_openstack_durations,
)


def _render(report):
    openstack = report["openstack"]
    hdfs = report["hdfs_v1"]
    anomaly_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['case_id'])}</td>"
        f"<td>{row['duration_seconds']}</td>"
        f"<td>{row['cohort_features']['peer_median_seconds']}</td>"
        f"<td>{row['cohort_features']['duration_ratio']}</td>"
        f"<td>{row['cohort_features']['percentile_rank']}</td>"
        f"<td>{row['cohort_features']['robust_z']}</td>"
        "</tr>"
        for row in openstack[
            "labeled_anomaly_cases"
        ]
    )
    hdfs_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['event_id']))}</td>"
        f"<td>{html.escape(str(row['typed_storage_family']))}</td>"
        f"<td>{row['support']}</td>"
        f"<td>{row['failure_precision']}</td>"
        f"<td>{row['failure_recall']}</td>"
        "</tr>"
        for row in hdfs[
            "typed_storage_event_associations"
        ]
    )
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Distributed feature audit</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;margin:2rem;background:#f6f8fa;color:#17202a}}
main{{max-width:1200px;margin:auto;background:white;padding:2rem;border-radius:14px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #d8dee4;padding:.55rem;text-align:left}}
th{{background:#eef3f7}}pre{{white-space:pre-wrap;background:#f3f5f7;padding:1rem}}
</style></head><body><main>
<h1>Label-last distributed feature audit</h1>
<h2>OpenStack duration confounder check</h2>
<pre>{html.escape(json.dumps(openstack['cohort_summaries'], indent=2))}</pre>
<table><thead><tr><th>Case</th><th>Duration</th><th>Peer median</th>
<th>Ratio</th><th>Percentile</th><th>Robust z</th></tr></thead>
<tbody>{anomaly_rows}</tbody></table>
<h2>HDFS ordered outcome feasibility</h2>
<pre>{html.escape(json.dumps(hdfs['feature_cross_tabs'], indent=2))}</pre>
<h3>Combined typed-storage association</h3>
<pre>{html.escape(json.dumps(hdfs['typed_storage_combined_association'], indent=2))}</pre>
<table><thead><tr><th>Event</th><th>Family</th><th>Support</th>
<th>Failure precision</th><th>Failure recall</th></tr></thead>
<tbody>{hdfs_rows}</tbody></table>
<h3>What follows the final typed-storage marker</h3>
<pre>{html.escape(json.dumps(hdfs['typed_storage_followups'], indent=2))}</pre>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openstack-path",
        default=os.path.abspath(
            os.path.join(
                _ROOT, "..", "OpenStack"
            )
        ),
    )
    parser.add_argument(
        "--hdfs-path",
        default=os.path.abspath(
            os.path.join(
                _ROOT, "..", "HDFS_v1"
            )
        ),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT,
            "output",
            "distributed-feature-audit.json",
        ),
    )
    parser.add_argument(
        "--html",
        default=os.path.join(
            _ROOT,
            "output",
            "distributed-feature-audit.html",
        ),
    )
    args = parser.parse_args()
    report = {
        "audit":
        "distributed-feature-decision/v2",
        "openstack":
        audit_openstack_durations(
            args.openstack_path
        ),
        "hdfs_v1":
        audit_hdfs_event_traces(
            args.hdfs_path
        ),
    }
    os.makedirs(
        os.path.dirname(
            os.path.abspath(args.output)
        ),
        exist_ok=True,
    )
    with open(
        args.output,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            report,
            handle,
            indent=2,
            sort_keys=True,
        )
    with open(
        args.html,
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(_render(report))
    print(
        "openstack_complete_traces="
        + str(
            report["openstack"][
                "complete_spawn_traces"
            ]
        )
        + " hdfs_traces="
        + str(
            report["hdfs_v1"]["traces"]
        )
    )
    print("JSON: " + args.output)
    print("HTML: " + args.html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
