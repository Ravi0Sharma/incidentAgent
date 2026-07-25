"""Score current production grouping against curated BGL/OpenStack pairs."""

import argparse
import json
import os
import sys


_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from evaluation.real_log_pair_benchmark import evaluate_real_log_pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates",
        default=os.path.join(
            _ROOT, "output", "real-log-pair-candidates.json"
        ),
    )
    parser.add_argument(
        "--annotations",
        default=os.path.join(
            _ROOT, "fixtures", "real_log_pair_annotations.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            _ROOT, "output", "real-log-pair-benchmark.json"
        ),
    )
    args = parser.parse_args()
    report = evaluate_real_log_pairs(
        os.path.abspath(args.candidates),
        os.path.abspath(args.annotations),
    )
    output = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "output": output,
        "evaluated_pairs": report["evaluated_pairs"],
        "confusion": report["confusion"],
        "metrics": report["metrics"],
        "quality_gate_passed": report["quality_gate_passed"],
    }, indent=2, sort_keys=True))
    return 0 if report["quality_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

