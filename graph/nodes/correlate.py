from datetime import (
    datetime,
    timezone
)

from utils.histogram import (
    build as build_histogram,
    render_ascii
)


EDGE_SCHEMA_VERSION = (
    "incident-edge/v1"
)


def _service(event):
    event = event or {}
    labels = event.get(
        "labels", {}
    ) or {}
    return (
        event.get("service")
        or labels.get("service")
        or "unknown"
    )


def _source_lineage(event):
    event = event or {}
    lineage = (
        event.get(
            "lineage", {}
        )
        or {}
    )
    metadata = (
        event.get(
            "connector_metadata",
            {},
        )
        or {}
    )
    query_ids = set(
        lineage.get(
            "source_query_ids",
            [],
        )
        or []
    )
    for value in (
        event.get(
            "source_query_id"
        ),
        metadata.get(
            "query_id"
        ),
    ):
        if value:
            query_ids.add(
                str(value)
            )
    schema_ids = set(
        lineage.get(
            "source_schema_ids",
            [],
        )
        or []
    )
    if metadata.get(
        "source_schema_id"
    ):
        schema_ids.add(
            str(
                metadata[
                    "source_schema_id"
                ]
            )
        )
    sources = set(
        lineage.get("sources", [])
        or []
    )
    for value in (
        event.get("source"),
        metadata.get("source"),
    ):
        if value:
            sources.add(str(value))
    connector_versions = set(
        lineage.get("connector_versions", [])
        or []
    )
    if metadata.get("connector_version"):
        connector_versions.add(
            str(metadata["connector_version"])
        )
    return {
        "sources": sorted(sources),
        "source_query_ids":
        sorted(query_ids),
        "source_schema_ids":
        sorted(schema_ids),
        "connector_versions":
        sorted(connector_versions),
    }


def _typed_link(
    *,
    source,
    target,
    relationship,
    relation_type,
    method,
    confidence,
    provenance=(
        "deterministic_derived"
    ),
    offset=None,
    alternative_explanation=None,
):
    return {
        "edge_schema_version":
        EDGE_SCHEMA_VERSION,
        "from": source,
        "to": target,
        "relationship":
        relationship,
        "relation_type":
        relation_type,
        "provenance": provenance,
        "method": method,
        "supporting_event_ids": [
            value
            for value in (
                source,
                target,
            )
            if value
        ],
        "direction":
        "from_to",
        "confidence":
        confidence,
        "causal_status":
        "not_established",
        "alternative_explanation": (
            alternative_explanation
            or (
                "The relation may be "
                "coincidental or reflect "
                "a shared downstream effect."
            )
        ),
        **(
            {"offset": offset}
            if offset is not None
            else {}
        ),
    }


def _parse_ts(ts):

    if not ts:
        return None

    if isinstance(ts, datetime):
        return (
            ts
            if ts.tzinfo
            else ts.replace(
                tzinfo=timezone.utc
            )
        )

    if not isinstance(ts, str):
        return None

    try:

        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")
        )

    except ValueError:

        return None


def _format_offset(delta_seconds):

    if delta_seconds is None:
        return "T?"

    sign = (
        "+"
        if delta_seconds >= 0
        else "-"
    )

    seconds = abs(int(delta_seconds))
    minutes, seconds = divmod(
        seconds, 60
    )
    hours, minutes = divmod(
        minutes, 60
    )

    if hours:
        return (
            f"T{sign}{hours}h"
            f"{minutes:02d}m"
        )

    return (
        f"T{sign}{minutes}m"
        f"{seconds:02d}s"
    )


def _pick_anchor(events):

    alerts = [
        event for event in events
        if event["type"] == "alert"
        and event.get("_dt") is not None
    ]
    if alerts:
        alerts.sort(key=lambda event: event["_dt"])
        return alerts[0]

    log_events = [
        e for e in events
        if e["type"] == "log_group"
        and (
            e.get("labels", {})
            .get("level")
            in ("error", "warn")
        )
        and e.get("_dt") is not None
    ]

    if log_events:
        log_events.sort(
            key=lambda e: e["_dt"]
        )
        return log_events[0]

    dated = [
        e for e in events
        if e.get("_dt") is not None
    ]

    if dated:
        dated.sort(
            key=lambda e: e["_dt"]
        )
        return dated[0]

    return None


def _temporal_links(
    timeline,
    anchor,
):
    if not anchor:
        return []
    anchor_id = anchor.get(
        "event_id"
    )
    anchor_dt = _parse_ts(
        anchor.get("timestamp")
    )
    if not anchor_id:
        return []

    links = []
    for event in timeline:
        event_id = event.get(
            "event_id"
        )
        if (
            not event_id
            or event_id == anchor_id
        ):
            continue
        event_dt = _parse_ts(
            event.get("timestamp")
        )
        if (
            event_dt is None
            or anchor_dt is None
        ):
            relationship = (
                "temporal_relation_unknown"
            )
        elif event_dt < anchor_dt:
            relationship = (
                "precedes_anchor"
            )
        elif event_dt > anchor_dt:
            relationship = (
                "follows_anchor"
            )
        else:
            relationship = (
                "coincides_with_anchor"
            )
        links.append(
            _typed_link(
                source=event_id,
                target=anchor_id,
                relationship=(
                    relationship
                ),
                relation_type="temporal",
                method=(
                    "timestamp_compare_"
                    "to_anchor_v1"
                ),
                confidence=(
                    95
                    if relationship
                    != (
                        "temporal_"
                        "relation_unknown"
                    )
                    else 20
                ),
                offset=event.get(
                    "offset"
                ),
                alternative_explanation=(
                    "Temporal proximity does "
                    "not establish causality."
                ),
            )
        )
    return links


def _entity_links(
    timeline,
    anchor,
):
    if not anchor:
        return []
    anchor_id = anchor.get(
        "event_id"
    )
    anchor_service = _service(
        anchor
    )
    if (
        not anchor_id
        or anchor_service == "unknown"
    ):
        return []
    links = []
    for event in timeline:
        event_id = event.get(
            "event_id"
        )
        if (
            not event_id
            or event_id == anchor_id
            or _service(event)
            != anchor_service
        ):
            continue
        links.append(
            _typed_link(
                source=event_id,
                target=anchor_id,
                relationship=(
                    "same_service"
                ),
                relation_type=(
                    "entity_service"
                ),
                method=(
                    "normalized_service_"
                    "equality_v1"
                ),
                confidence=95,
                alternative_explanation=(
                    "Events in one service "
                    "can still be unrelated."
                ),
            )
        )
    return links


def _change_links(timeline):
    deploys = [
        event
        for event in timeline
        if event.get("type") == "deploy"
    ]
    signals = [
        event
        for event in timeline
        if event.get("type")
        == "log_group"
    ]
    links = []
    for deploy in deploys:
        deploy_time = _parse_ts(
            deploy.get("timestamp")
        )
        for signal in signals:
            signal_time = _parse_ts(
                signal.get("timestamp")
            )
            if (
                not deploy_time
                or not signal_time
                or deploy_time
                > signal_time
                or _service(deploy)
                == "unknown"
                or _service(deploy)
                != _service(signal)
            ):
                continue
            links.append(
                _typed_link(
                    source=deploy.get(
                        "event_id"
                    ),
                    target=signal.get(
                        "event_id"
                    ),
                    relationship=(
                        "precedes_same_"
                        "service_signal"
                    ),
                    relation_type=(
                        "change_deploy"
                    ),
                    method=(
                        "same_service_"
                        "precedence_v1"
                    ),
                    confidence=70,
                    alternative_explanation=(
                        "The deploy may be "
                        "unrelated to the "
                        "later signal."
                    ),
                )
            )
    return links


def _topology_links(
    timeline,
    anchor,
    state,
):
    if not anchor:
        return []
    context = state.get(
        "business_context", {}
    ) or {}
    dependencies = set(
        context.get(
            "dependencies", []
        )
        or []
    )
    if not dependencies:
        return []
    links = []
    for event in timeline:
        event_id = event.get(
            "event_id"
        )
        if (
            not event_id
            or _service(event)
            not in dependencies
        ):
            continue
        links.append(
            _typed_link(
                source=event_id,
                target=anchor.get(
                    "event_id"
                ),
                relationship=(
                    "configured_dependency_"
                    "of_alert_service"
                ),
                relation_type=(
                    "topology_dependency"
                ),
                method=(
                    "business_context_"
                    "dependency_v1"
                ),
                confidence=90,
                provenance="observed",
                alternative_explanation=(
                    "Dependency membership "
                    "does not establish that "
                    "the dependency caused "
                    "this incident."
                ),
            )
        )
    return links


def correlate(state):

    events = []

    alert = state.get("alert", {}) or {}
    window = state.get("incident_window", {}) or {}
    anchor_time = (
        alert.get("started_at")
        or window.get("anchor_time")
    )
    if anchor_time:
        events.append({
            "event_id": "alert-1",
            "type": "alert",
            "timestamp": anchor_time,
            "_dt": _parse_ts(anchor_time),
            "alertname": alert.get("alertname"),
            "service": alert.get("service"),
            "labels": alert.get("labels", {}),
            "message": alert.get("message", ""),
        })

    deploys = []
    for idx, deploy in enumerate(
        state.get("deploys", []),
        start=1
    ):
        deploy = {
            "event_id":
            deploy.get("event_id")
            or (
                f"deploy-{deploy.get('commit', 'unknown')}-"
                f"{str(deploy.get('time', 'unknown'))[:16]}"
            ),
            **deploy
        }
        deploys.append(deploy)
        ts = deploy.get("time")
        events.append({
            "type": "deploy",
            "timestamp": ts,
            "_dt": _parse_ts(ts),
            **deploy
        })

    for group in state.get(
        "log_groups", []
    ):
        ts = group.get("first_seen")
        events.append({
            "type": "log_group",
            "timestamp": ts,
            "_dt": _parse_ts(ts),
            **group
        })

    metrics = []
    for idx, metric in enumerate(
        state.get("metrics", []),
        start=1
    ):
        metric = {
            "event_id":
            metric.get("event_id")
            or (
                f"metric-{metric.get('metric', idx)}-"
                f"{str(metric.get('timestamp', 'unknown'))[:16]}"
            ),
            **metric
        }
        metrics.append(metric)
        ts = metric.get("timestamp")
        events.append({
            "type": "metric",
            "timestamp": ts,
            "_dt": _parse_ts(ts),
            **metric
        })

    events.sort(
        key=lambda x: (
            x["_dt"] or datetime.max
            .replace(
                tzinfo=timezone.utc
            )
        )
    )

    anchor = _pick_anchor(events)
    anchor_dt = (
        anchor["_dt"]
        if anchor
        else None
    )

    timeline = []

    for e in events:

        if (
            anchor_dt is not None
            and e.get("_dt") is not None
        ):
            delta = (
                e["_dt"] - anchor_dt
            ).total_seconds()
            offset = _format_offset(
                delta
            )
        else:
            offset = "T?"

        clean = {
            k: v
            for k, v in e.items()
            if k != "_dt"
        }
        clean["offset"] = offset
        clean["is_anchor"] = (
            anchor is not None
            and e is anchor
        )

        timeline.append(clean)

    anchor_summary = None
    if anchor is not None:
        anchor_summary = {
            "event_id":
            anchor.get("event_id"),
            "type": anchor["type"],
            "timestamp":
            anchor.get("timestamp"),
            "labels":
            anchor.get("labels"),
            "example_message":
            anchor.get(
                "example_message"
            ),
            "message": anchor.get("message"),
            "service": _service(
                anchor
            ),
        }

    histogram = build_histogram(
        state.get("log_groups", []),
        bucket_minutes=1
    )

    heatmap_ascii = render_ascii(
        histogram,
        width=40
    )

    temporal_links = (
        _temporal_links(
            timeline,
            anchor_summary,
        )
    )
    typed_links = [
        *temporal_links,
        *_entity_links(
            timeline,
            anchor_summary,
        ),
        *_topology_links(
            timeline,
            anchor_summary,
            state,
        ),
        *_change_links(timeline),
    ]

    return {
        "metrics": metrics,
        "deploys": deploys,
        "timeline": timeline,
        "anchor_event":
        anchor_summary,
        "frequency_histogram":
        histogram,
        "frequency_heatmap_ascii":
        heatmap_ascii,
        "evidence_graph": {
            "nodes": [
                {
                    "event_id": event.get("event_id"),
                    "type": event.get("type"),
                    "timestamp": event.get("timestamp"),
                    "service":
                    _service(event),
                    "provenance":
                    "observed",
                    "source_lineage":
                    _source_lineage(
                        event
                    ),
                }
                for event in timeline
                if event.get("event_id")
            ],
            "factual_links":
            temporal_links,
            "typed_links":
            typed_links,
            "edge_schema_version":
            EDGE_SCHEMA_VERSION,
            "window": window,
        }
    }
