"""Versioned, label-agnostic observable signal families for log evidence."""

import re


SIGNAL_CATALOG_VERSION = (
    "incident-signals/v4"
)


_RULES = (
    {
        "id": "job-state-succeeded",
        "family": "job_lifecycle",
        "directness": "direct",
        "status": "succeeded",
        "scope": "job",
        "pattern": re.compile(
            r"(?i)(?:(?:\bjob"
            r"(?:_[^\s]+)?(?:job)?)"
            r".{0,8}transitioned\s+from"
            r".{0,80}\s+to\s+succeeded|"
            r"\bjob\b.{0,40}"
            r"(?:final\s+status.{0,20}"
            r"succeeded|completed"
            r"\s+successfully))"
        ),
    },
    {
        "id": "job-state-failed",
        "family": "job_lifecycle",
        "directness": "direct",
        "status": "failed",
        "scope": "job",
        "pattern": re.compile(
            r"(?i)(?:(?:\bjob"
            r"(?:_[^\s]+)?(?:job)?)"
            r".{0,8}transitioned\s+from"
            r".{0,80}\s+to\s+(?:failed|"
            r"killed)|\bjob\b.{0,40}"
            r"(?:final\s+status"
            r".{0,20}(?:failed|killed)|"
            r"failed))"
        ),
    },
    {
        "id": "job-finished-event",
        "family": "job_lifecycle",
        "directness": "indirect",
        "status": "finished_event",
        "scope": "job",
        "pattern": re.compile(
            r"(?i)(?:JobFinishedEvent|"
            r"\bJOB_FINISHED\b)"
        ),
    },
    {
        "id": "machine-lost-node",
        "family": "machine_availability",
        "directness": "direct",
        "status": "unavailable",
        "scope": "node",
        "pattern": re.compile(
            r"(?i)(?:released\s+on\s+a"
            r"\s+\*?lost\*?\s+node|"
            r"(?:node|worker|host)"
            r".{0,40}(?:unavailable|"
            r"\blost\b|\bdown\b)|"
            r"(?:unavailable|\blost\b|"
            r"\bdown\b).{0,40}"
            r"(?:node|worker|host))"
        ),
    },
    {
        "id": "network-no-route",
        "family": "network_transport",
        "directness": "direct",
        "status": "unreachable",
        "scope": "network_peer",
        "pattern": re.compile(
            r"(?i)(?:NoRouteToHost"
            r"(?:Exception)?|"
            r"no\s+route\s+to\s+host|"
            r"network\s+is\s+unreachable)"
        ),
    },
    {
        "id": "network-disconnect",
        "family": "network_transport",
        "directness": "direct",
        "status": "disconnected",
        "scope": "network_peer",
        "pattern": re.compile(
            r"(?i)(?:connection\s+"
            r"(?:reset|refused|timed\s*out)|"
            r"network\s+disconnect(?:ed|ion)?|"
            r"unreachable\s+peer)"
        ),
    },
    {
        "id": "network-latency",
        "family": "network_transport",
        "directness": "indirect",
        "status": "slow",
        "scope": "transport",
        "pattern": re.compile(
            r"(?i)(?:slow\s+(?:read|"
            r"write|connection)|"
            r"socket\s+timeout)"
        ),
    },
    {
        "id": "storage-capacity",
        "family": "storage_capacity",
        "directness": "direct",
        "status": "exhausted",
        "scope": "storage",
        "pattern": re.compile(
            r"(?i)(?:no\s+space\s+left"
            r"(?:\s+on\s+device)?|"
            r"\bdisk\s+full\b|\bENOSPC\b|"
            r"quota\s+exceeded|"
            r"storage\s+capacity"
            r".{0,30}exhaust)"
        ),
    },
    {
        "id": "storage-read-only",
        "family": "storage_write",
        "directness": "direct",
        "status": "write_blocked",
        "scope": "storage",
        "pattern": re.compile(
            r"(?i)(?:read-only\s+file"
            r"\s+system|write\s+failed"
            r".{0,40}(?:space|capacity))"
        ),
    },
    {
        "id": "storage-stream-read-failed",
        "family": "storage_io",
        "directness": "direct",
        "status": "read_failed",
        "scope": "storage_block",
        "pattern": re.compile(
            r"(?i)(?:could\s+not\s+read"
            r"\s+from\s+stream|"
            r"failed\s+to\s+read"
            r"\s+from\s+stream)"
        ),
    },
    {
        "id": "storage-block-metadata-inconsistent",
        "family": "storage_metadata",
        "directness": "direct",
        "status": "inconsistent",
        "scope": "storage_block",
        "pattern": re.compile(
            r"(?i)(?:blockinfo\s+not\s+found"
            r"\s+in\s+volumemap|"
            r"block.{0,60}does\s+not\s+"
            r"belong\s+to\s+any\s+file)"
        ),
    },
    {
        "id": "storage-block-serve-exception",
        "family": "storage_io",
        "directness": "indirect",
        "status": "serve_exception",
        "scope": "storage_block",
        "pattern": re.compile(
            r"(?i)got\s+exception\s+while"
            r"\s+serving\s+(?:block|blk_)"
        ),
    },
    {
        "id": "storage-block-operation-failed",
        "family": "storage_io",
        "directness": "direct",
        "status": "block_operation_failed",
        "scope": "storage_block",
        "pattern": re.compile(
            r"(?i)(?:OP_READ_BLOCK|"
            r"OP_STATUS_ERROR|"
            r"could\s+not\s+(?:create\s+)?"
            r"BlockSender|"
            r"no\s+live\s+nodes\s+contain"
            r"\s+current\s+block|"
            r"could\s+not\s+obtain\s+block)"
        ),
    },
    {
        "id": "storage-integrity-corruption",
        "family": "storage_integrity",
        "directness": "direct",
        "status": "corruption_detected",
        "scope": "storage",
        "pattern": re.compile(
            r"(?i)(?:checksum\s+error|"
            r"corrupt(?:ed|ion)?"
            r".{0,40}(?:block|segment)|"
            r"(?:block|segment)"
            r".{0,40}corrupt(?:ed|ion)?)"
        ),
    },
    {
        "id": "storage-mount-failed",
        "family": "storage_availability",
        "directness": "direct",
        "status": "mount_failed",
        "scope": "storage",
        "pattern": re.compile(
            r"(?i)(?:(?:lustre|filesystem|"
            r"file\s+system|volume)"
            r".{0,50}\bmount\s+failed\b|"
            r"\bmount\s+failed\b)"
        ),
    },
    {
        "id": "connection-broken",
        "family": "network_transport",
        "directness": "direct",
        "status": "interrupted",
        "scope": "network_peer",
        "pattern": re.compile(
            r"(?i)\bconnection\s+broken\b"
        ),
    },
    {
        "id": "connection-stream-ended",
        "family": "connection_lifecycle",
        "directness": "direct",
        "status": "stream_ended",
        "scope": "connection",
        "pattern": re.compile(
            r"(?i)(?:caught\s+end\s+of"
            r"\s+stream\s+exception|"
            r"unexpected\s+end\s+of"
            r"\s+stream)"
        ),
    },
    {
        "id": "machine-hardware-fault",
        "family": "machine_hardware",
        "directness": "direct",
        "status": "fault_observed",
        "scope": "node",
        "pattern": re.compile(
            r"(?i)(?:machine\s+check"
            r"\s+interrupt|"
            r"(?:instruction|data|l[123])"
            r".{0,30}(?:cache|unit)?"
            r".{0,30}parity\s+error|"
            r"\bhardware\s+(?:fault|error)\b)"
        ),
    },
    {
        "id": "process-failure",
        "family": "process_failure",
        "directness": "direct",
        "status": "terminated",
        "scope": "process",
        "pattern": re.compile(
            r"(?i)(?:segmentation\s+fault|"
            r"\bsegfault\b|kernel\s+panic|"
            r"fatal\s+signal|"
            r"process.{0,40}"
            r"(?:terminated\s+unexpectedly|"
            r"\bkilled\b))"
        ),
    },
    {
        "id": "workload-state-succeeded",
        "family": "workload_lifecycle",
        "directness": "direct",
        "status": "succeeded",
        "scope": "workload",
        "pattern": re.compile(
            r"(?i)(?:instance\s+spawned"
            r"\s+successfully|claim\s+successful)"
        ),
    },
    {
        "id": "workload-state-resumed",
        "family": "workload_lifecycle",
        "directness": "direct",
        "status": "resumed",
        "scope": "workload",
        "pattern": re.compile(
            r"(?i)\bVM\s+Resumed"
            r"\s+\(Lifecycle\s+Event\)"
        ),
    },
    {
        "id": "workload-state-paused",
        "family": "workload_lifecycle",
        "directness": "direct",
        "status": "paused",
        "scope": "workload",
        "pattern": re.compile(
            r"(?i)\bVM\s+Paused"
            r"\s+\(Lifecycle\s+Event\)"
        ),
    },
)


def detect_signals(value):
    """Return observable matches without consulting incident truth."""
    if isinstance(value, dict):
        messages = [
            value.get("message"),
            value.get("example_message"),
            value.get(
                "example_message_decoded"
            ),
            *(
                value.get(
                    "sample_messages", []
                )
                or []
            ),
        ]
        text = "\n".join(
            str(message)
            for message in messages
            if message
        )
    else:
        text = str(value or "")
    matches = []
    operation_features = (
        value.get(
            "operation_features", []
        )
        or [
            value.get(
                "operation_feature"
            )
        ]
        if isinstance(value, dict)
        else []
    )
    operation_features = [
        feature
        for feature in operation_features
        if isinstance(feature, dict)
    ]
    for feature in operation_features:
        if (
            feature.get("schema_version")
            != "operation-duration-feature/v1"
            or feature.get("feature_name")
            != "operation_latency_deviation"
            or feature.get("status")
            != "deviation_observed"
        ):
            continue
        matches.append({
            "catalog_version":
            SIGNAL_CATALOG_VERSION,
            "rule_id":
            "operation-peer-latency-deviation",
            "signal_family":
            "operation_latency",
            "directness": "direct",
            "status":
            "slow_relative_to_peers",
            "scope": "workload",
            "match_method":
            "versioned_structured_feature",
            "feature_schema_version":
            feature.get(
                "schema_version"
            ),
            "baseline_id":
            (
                feature.get(
                    "baseline", {}
                )
                or {}
            ).get("baseline_id"),
        })
    for rule in _RULES:
        if not rule["pattern"].search(
            text
        ):
            continue
        matches.append({
            "catalog_version":
            SIGNAL_CATALOG_VERSION,
            "rule_id": rule["id"],
            "signal_family":
            rule["family"],
            "directness":
            rule["directness"],
            "status": rule["status"],
            "scope": rule["scope"],
            "match_method":
            "versioned_regex",
        })
    if isinstance(value, dict):
        labels = value.get(
            "labels", {}
        ) or {}
        level = str(
            labels.get(
                "level", ""
            )
        ).lower()
        if (
            level
            in {
                "error",
                "fatal",
                "critical",
            }
            and not matches
        ):
            matches.append({
                "catalog_version":
                SIGNAL_CATALOG_VERSION,
                "rule_id":
                "source-level-unclassified-error",
                "signal_family":
                "unclassified_error",
                "directness": "direct",
                "status":
                "error_logged",
                "scope": "service",
                "match_method":
                "structured_source_level",
                "observation_only": True,
            })
    return matches


def signal_key(signal):
    return (
        signal.get("signal_family"),
        signal.get("directness"),
        signal.get("status"),
    )


def has_priority_signal(value):
    """Whether a record deserves a reserved sampling slot."""
    return bool(
        detect_signals(value)
    )
