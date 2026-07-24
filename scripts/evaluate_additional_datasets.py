"""Evaluate local HDFS_v1 and OpenStack corpora without an LLM."""

import argparse
import json
import os
import sys


_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.hdfs_v1_dataset import (
    evaluate_hdfs_v1,
)
from evaluation.openstack_dataset import (
    evaluate_openstack,
)


def _write(path, report):
    target = os.path.abspath(path)
    os.makedirs(
        os.path.dirname(target),
        exist_ok=True,
    )
    with open(
        target,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            report,
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hdfs-path",
        default=os.path.abspath(
            os.path.join(
                _ROOT, "..", "HDFS_v1"
            )
        ),
    )
    parser.add_argument(
        "--openstack-path",
        default=os.path.abspath(
            os.path.join(
                _ROOT, "..", "OpenStack"
            )
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(
            _ROOT, "output"
        ),
    )
    parser.add_argument(
        "--hdfs-cases-per-truth",
        type=int,
        default=250,
    )
    parser.add_argument(
        "--hdfs-sample-limit",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--openstack-file-sample-limit",
        type=int,
        default=1000,
    )
    args = parser.parse_args()

    hdfs = evaluate_hdfs_v1(
        os.path.abspath(
            args.hdfs_path
        ),
        cases_per_truth=max(
            args.hdfs_cases_per_truth,
            1,
        ),
        sample_limit=max(
            args.hdfs_sample_limit, 1
        ),
    )
    openstack = evaluate_openstack(
        os.path.abspath(
            args.openstack_path
        ),
        file_sample_limit=max(
            args.openstack_file_sample_limit,
            1,
        ),
    )
    hdfs_path = _write(
        os.path.join(
            args.output_dir,
            "hdfs-v1-evaluation.json",
        ),
        hdfs,
    )
    openstack_path = _write(
        os.path.join(
            args.output_dir,
            "openstack-evaluation.json",
        ),
        openstack,
    )
    summary = {
        "hdfs_v1": {
            "source_trace_rows":
            hdfs["source_trace_rows"],
            "truth_counts":
            hdfs["truth_counts"],
            "evaluation_cases":
            hdfs["evaluation_cases"],
            "gates": hdfs["gates"],
            "quality_gate_passed":
            hdfs[
                "quality_gate_passed"
            ],
            "output": hdfs_path,
        },
        "openstack": {
            "anomaly_truth_entities":
            openstack[
                "anomaly_truth_entities"
            ],
            "anomaly_entities_found":
            openstack[
                "anomaly_entities_found"
            ],
            "anomaly_observable_coverage":
            openstack[
                "anomaly_observable_coverage"
            ],
            "gates": openstack["gates"],
            "quality_gate_passed":
            openstack[
                "quality_gate_passed"
            ],
            "output": openstack_path,
        },
    }
    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )
    return (
        0
        if (
            hdfs["quality_gate_passed"]
            and openstack[
                "quality_gate_passed"
            ]
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
