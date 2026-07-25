"""Run deterministic ingest/reduction/correlation evaluation before any LLM."""

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


from clients.loki_client import (
    representative_sample,
)
from evaluation.synthetic_scenarios import (
    scenarios,
)
from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels,
)
from graph.nodes.apply_detection_rules import (
    apply_detection_rules,
)
from graph.nodes.correlate import correlate
from graph.nodes.enrich_groups import (
    enrich_groups,
)
from graph.nodes.normalize_logs import (
    normalize_logs,
)
from utils.candidate_scoring import (
    score_candidates,
)
from utils.incident_features import (
    build_features,
)
from utils.incident_window import (
    build_incident_window,
)


def _run_pipeline(scenario):
    raw_logs = scenario.get(
        "logs", []
    )
    sample_limit = scenario.get(
        "sample_limit"
    )
    logs = (
        representative_sample(
            raw_logs,
            sample_limit,
        )
        if sample_limit
        else list(raw_logs)
    )
    truncated = len(logs) < len(
        raw_logs
    )
    state = {
        "alert": scenario["alert"],
        "incident_window":
        build_incident_window(
            scenario["alert"]
        ),
        "logs": logs,
        "log_query": {
            "total_count": len(
                raw_logs
            ),
            "count_is_exact": True,
            "fetched_count": len(logs),
            "sample_limit": (
                sample_limit
                or len(logs)
            ),
            "possibly_truncated":
            truncated,
            "sampling_strategy": (
                "time_stratified_with_high_signal"
            ),
        },
        "metrics": list(
            scenario.get(
                "metrics", []
            )
        ),
        "deploys": list(
            scenario.get(
                "deploys", []
            )
        ),
    }
    state.update(
        normalize_logs(state)
    )
    state.update(
        aggregate_by_labels(state)
    )
    state.update(
        apply_detection_rules(state)
    )
    state.update(
        enrich_groups(state)
    )
    state["incident_features"] = (
        build_features(state)
    )
    state.update(correlate(state))
    state[
        "deterministic_assessment"
    ] = score_candidates(state)
    return state


def _contains_text(state, text):
    lowered = text.lower()
    return any(
        lowered
        in str(
            group.get(
                "example_message", ""
            )
        ).lower()
        for group in state.get(
            "log_groups", []
        )
    )


def _evaluate(scenario, state):
    expected = scenario.get(
        "expect", {}
    )
    failures = []
    detections = {
        item.get("id")
        for item in state.get(
            "detections", []
        )
    }
    required = set(
        expected.get(
            "detection_ids", []
        )
    )
    missing = required - detections
    if missing:
        failures.append(
            "missing detections: "
            + ", ".join(sorted(missing))
        )
    forbidden = set(
        expected.get(
            "forbidden_detection_ids",
            [],
        )
    ) & detections
    if forbidden:
        failures.append(
            "forbidden detections: "
            + ", ".join(
                sorted(forbidden)
            )
        )

    assessment = state.get(
        "deterministic_assessment", {}
    )
    candidates = assessment.get(
        "candidates", []
    )
    if (
        "top_candidate" in expected
        and (
            not candidates
            or candidates[0].get("title")
            != expected["top_candidate"]
        )
    ):
        failures.append(
            "unexpected top candidate"
        )
    if (
        "abstain" in expected
        and bool(
            assessment.get("abstain")
        )
        != expected["abstain"]
    ):
        failures.append(
            "unexpected abstention state"
        )

    groups = state.get(
        "log_groups", []
    )
    if (
        "group_count" in expected
        and len(groups)
        != expected["group_count"]
    ):
        failures.append(
            "unexpected group count: "
            f"{len(groups)}"
        )
    signatures = [
        str(
            group.get(
                "labels", {}
            ).get(
                "event_signature", ""
            )
        )
        for group in groups
    ]
    for value in expected.get(
        "signatures", []
    ):
        if not any(
            value in signature
            for signature in signatures
        ):
            failures.append(
                "missing signature: "
                + value
            )
    for value in expected.get(
        "retained_text", []
    ):
        if not _contains_text(
            state, value
        ):
            failures.append(
                "sample lost signal: "
                + value
            )

    if groups:
        first = min(
            (
                group.get("first_seen")
                for group in groups
                if group.get("first_seen")
            ),
            default=None,
        )
        last = max(
            (
                group.get("last_seen")
                for group in groups
                if group.get("last_seen")
            ),
            default=None,
        )
        if (
            expected.get("first_seen")
            and first
            != expected["first_seen"]
        ):
            failures.append(
                "unexpected first_seen: "
                + str(first)
            )
        if (
            expected.get("last_seen")
            and last
            != expected["last_seen"]
        ):
            failures.append(
                "unexpected last_seen: "
                + str(last)
            )

    if (
        "related_deploy_count"
        in expected
    ):
        actual = sum(
            len(
                group.get(
                    "related_deploys", []
                )
            )
            for group in groups
        )
        if actual != expected[
            "related_deploy_count"
        ]:
            failures.append(
                "unexpected related deploy count"
            )

    relationships = {
        link.get("relationship")
        for link in (
            state.get(
                "evidence_graph", {}
            ).get(
                "factual_links", []
            )
        )
    }
    for value in expected.get(
        "temporal_relationships", []
    ):
        if value not in relationships:
            failures.append(
                "missing temporal relation: "
                + value
            )

    services = {
        (
            group.get("labels", {})
            or {}
        ).get("service")
        for group in groups
    }
    for value in expected.get(
        "services", []
    ):
        if value not in services:
            failures.append(
                "missing service: "
                + value
            )
    pivot_values = {
        str(value)
        for values in (
            state.get("pivots", {})
            or {}
        ).values()
        for value in values
    }
    for value in expected.get(
        "pivot_values", []
    ):
        if value not in pivot_values:
            failures.append(
                "missing pivot: "
                + value
            )

    log_quality = (
        state.get(
            "data_quality", {}
        ).get(
            "logs", {}
        )
    )
    for field, actual in (
        (
            "truncated",
            log_quality.get(
                "possibly_truncated"
            ),
        ),
        (
            "group_counts_exact",
            log_quality.get(
                "group_counts_are_exact"
            ),
        ),
        (
            "raw_log_count",
            state.get("raw_log_count"),
        ),
    ):
        if (
            field in expected
            and actual
            != expected[field]
        ):
            failures.append(
                f"unexpected {field}: "
                f"{actual}"
            )

    if (
        expected.get(
            "contradiction"
        )
        and not assessment.get(
            "contradictions"
        )
    ):
        failures.append(
            "expected contradiction missing"
        )

    return {
        "id": scenario["id"],
        "passed": not failures,
        "failures": failures,
        "raw_logs": len(
            scenario.get("logs", [])
        ),
        "sampled_logs": (
            log_quality.get(
                "fetched_count"
            )
        ),
        "groups": len(groups),
        "detections": sorted(
            value
            for value in detections
            if value
        ),
        "top_candidate": (
            candidates[0].get("title")
            if candidates
            else None
        ),
        "abstained": bool(
            assessment.get("abstain")
        ),
    }


def run():
    results = []
    for scenario in scenarios():
        state = _run_pipeline(
            scenario
        )
        results.append(
            _evaluate(
                scenario,
                state,
            )
        )
    return {
        "suite": (
            "pre-review-synthetic/v1"
        ),
        "scenario_count": len(
            results
        ),
        "passed": sum(
            1
            for result in results
            if result["passed"]
        ),
        "failed": sum(
            1
            for result in results
            if not result["passed"]
        ),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full JSON report.",
    )
    args = parser.parse_args()
    report = run()
    if args.json:
        print(
            json.dumps(
                report,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for result in report[
            "results"
        ]:
            marker = (
                "PASS"
                if result["passed"]
                else "FAIL"
            )
            print(
                f"{marker} {result['id']}: "
                f"raw={result['raw_logs']} "
                f"sample={result['sampled_logs']} "
                f"groups={result['groups']} "
                f"top={result['top_candidate']}"
            )
            for failure in result[
                "failures"
            ]:
                print(
                    "  - " + failure
                )
        print(
            "summary: "
            f"{report['passed']}/"
            f"{report['scenario_count']} "
            "passed"
        )
    return 1 if report[
        "failed"
    ] else 0


if __name__ == "__main__":
    sys.exit(main())
