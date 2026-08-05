"""Label-free peer baselines for completed operation durations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import json
from statistics import median


OPERATION_DURATION_FEATURE_VERSION = (
    "operation-duration-feature/v1"
)
PEER_DURATION_BASELINE_VERSION = (
    "peer-duration-baseline/v1"
)


DEFAULT_DURATION_POLICY = {
    "minimum_peer_count": 20,
    "minimum_percentile_rank": 95.0,
    "minimum_duration_ratio": 1.25,
    "minimum_robust_z": 3.5,
}


def _parse(value):
    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    return parsed


def _duration(operation):
    start = _parse(operation["started_at"])
    end = _parse(operation["completed_at"])
    if end < start:
        return None
    return (end - start).total_seconds()


def _baseline_id(operation):
    identity = {
        "operation_name":
        operation.get("operation_name"),
        "cohort_dimensions":
        operation.get(
            "cohort_dimensions", {}
        ),
        "schema_version":
        PEER_DURATION_BASELINE_VERSION,
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "baseline-" + hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()[:16]


def build_peer_duration_features(
    operations,
    policy=None,
):
    """Compute leave-one-out duration features without labels or truth."""
    policy = {
        **DEFAULT_DURATION_POLICY,
        **(policy or {}),
    }
    prepared = []
    cohorts = defaultdict(list)
    for operation in operations or []:
        duration = _duration(operation)
        if duration is None:
            continue
        row = {
            **operation,
            "_duration_seconds": duration,
        }
        prepared.append(row)
        cohorts[
            operation.get("cohort_key")
        ].append(duration)

    features = {}
    for operation in prepared:
        duration = operation[
            "_duration_seconds"
        ]
        peers = list(
            cohorts[
                operation.get("cohort_key")
            ]
        )
        peers.remove(duration)
        peer_count = len(peers)
        center = (
            median(peers)
            if peers
            else None
        )
        deviations = (
            [
                abs(peer - center)
                for peer in peers
            ]
            if center is not None
            else []
        )
        mad = (
            median(deviations)
            if deviations
            else None
        )
        ratio = (
            duration / center
            if center is not None
            and center > 0
            else None
        )
        percentile = (
            100.0
            * sum(
                peer <= duration
                for peer in peers
            )
            / peer_count
            if peer_count
            else None
        )
        robust_z = (
            0.6745
            * (duration - center)
            / mad
            if center is not None
            and mad is not None
            and mad > 0
            else None
        )
        sufficient = (
            peer_count
            >= policy[
                "minimum_peer_count"
            ]
            and center is not None
            and mad is not None
            and mad > 0
        )
        deviates = bool(
            sufficient
            and percentile
            >= policy[
                "minimum_percentile_rank"
            ]
            and ratio
            >= policy[
                "minimum_duration_ratio"
            ]
            and robust_z
            >= policy[
                "minimum_robust_z"
            ]
        )
        status = (
            "deviation_observed"
            if deviates
            else "within_peer_baseline"
            if sufficient
            else "insufficient_baseline"
        )
        identifier = operation.get(
            "operation_id"
        )
        features[identifier] = {
            "schema_version":
            OPERATION_DURATION_FEATURE_VERSION,
            "feature_name":
            "operation_latency_deviation",
            "operation_name":
            operation.get(
                "operation_name",
                "unknown",
            ),
            "status": status,
            "duration_seconds": round(
                duration, 3
            ),
            "baseline": {
                "schema_version":
                PEER_DURATION_BASELINE_VERSION,
                "baseline_id":
                _baseline_id(operation),
                "cohort_dimensions":
                operation.get(
                    "cohort_dimensions",
                    {},
                ),
                "peer_count": peer_count,
                "peer_median_seconds": (
                    round(center, 3)
                    if center is not None
                    else None
                ),
                "peer_mad_seconds": (
                    round(mad, 3)
                    if mad is not None
                    else None
                ),
                "duration_ratio": (
                    round(ratio, 4)
                    if ratio is not None
                    else None
                ),
                "percentile_rank": (
                    round(percentile, 2)
                    if percentile is not None
                    else None
                ),
                "robust_z": (
                    round(robust_z, 3)
                    if robust_z is not None
                    else None
                ),
                "leave_one_out": True,
                "labels_used": False,
                "source_provenance":
                operation.get(
                    "source_provenance",
                    {},
                ),
            },
            "decision_policy": {
                "method":
                "peer_relative_percentile_ratio_and_mad",
                **policy,
                "fixed_seconds_threshold":
                None,
            },
            "limitations": [
                (
                    "The feature establishes a peer-relative "
                    "latency deviation, not its root cause."
                )
            ],
        }
    return features
