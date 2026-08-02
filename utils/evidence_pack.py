EVIDENCE_PACK_VERSION = (
    "evidence-pack/v3"
)


def _short(value, limit=70):
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _compact_labels(labels):
    labels = labels or {}
    keep = (
        "service",
        "level",
        "error_type",
        "status_code",
    )
    return {
        k: labels.get(k)
        for k in keep
        if labels.get(k)
    }


def _line_items(items, formatter, limit):
    out = []
    for item in (items or [])[:limit]:
        out.append(formatter(item))
    return out


def _format_log_group(group):
    labels = group.get("labels", {})
    dets = [
        d.get("id")
        for d in group.get("detections", [])
        if d.get("id")
    ]
    parts = [
        f"id={group.get('event_id')}",
        f"labels={_compact_labels(labels)}",
        f"count={group.get('count')}",
        f"count_scope={group.get('count_scope', 'unknown')}",
        f"first={group.get('first_seen')}",
        f"last={group.get('last_seen')}",
        f"example={_short(group.get('example_message_decoded') or group.get('example_message'))}"
    ]
    if dets:
        parts.append(
            "rules=" + ",".join(dets)
        )
    families = group.get(
        "signal_families", []
    ) or []
    if families:
        parts.append(
            "signal_families="
            + ",".join(families)
        )
    if group.get("owner"):
        parts.append(
            f"owner={group.get('owner')}"
        )
    dimensions = group.get("dimensions", {}) or {}
    if dimensions:
        parts.append(
            "spread=" + ",".join(
                f"{key}:{value.get('unique', 0)}"
                for key, value in dimensions.items()
            )
        )
    query_ids = (
        group.get(
            "lineage", {}
        )
        or {}
    ).get(
        "source_query_ids", []
    )
    if query_ids:
        parts.append(
            "source_queries="
            + ",".join(
                query_ids[:2]
            )
        )
    time_quality = (
        group.get("time_quality", {})
        or {}
    )
    if time_quality:
        parts.append(
            "time_quality="
            + ",".join(
                time_quality.get(
                    "source_timestamp_qualities",
                    [],
                )
                or time_quality.get(
                    "clock_qualities",
                    [],
                )
            )
            + ";ordering="
            + ",".join(
                time_quality.get(
                    "ordering_scopes",
                    [],
                )
            )
        )
    return "- " + "; ".join(parts)


def _format_service_summary(item):
    return (
        "- "
        f"service={item.get('service')}; "
        f"owner={item.get('owner')}; "
        f"tier={item.get('tier')}; "
        f"dependencies="
        + ",".join(
            item.get("dependencies", [])
        )
    )


def _groups_by_service(groups, per_service=2):
    buckets = {}
    for group in groups or []:
        service = (
            group.get("labels", {})
            .get("service", "unknown")
        )
        buckets.setdefault(
            service, []
        ).append(group)

    rows = []
    for service in sorted(buckets):
        rows.append(
            f"- service={service}"
        )
        for group in buckets[service][
            :per_service
        ]:
            rows.append(
                "  "
                + _format_log_group(
                    group
                )
            )

    return rows


def _rare_high_signal_groups(groups, exclude_ids=None):
    candidates = []
    exclude_ids = set(exclude_ids or [])

    for group in groups or []:
        if group.get("event_id") in exclude_ids:
            continue
        labels = group.get(
            "labels", {}
        ) or {}
        if (
            labels.get("level")
            in (
                "error",
                "fatal",
                "warn",
                "warning",
            )
            or group.get("detections")
        ):
            candidates.append(group)

    candidates.sort(
        key=lambda g: (
            g.get("count", 0),
            g.get("first_seen") or ""
        )
    )

    return candidates[:3]


def _signal_family_groups(groups, limit=5):
    """Prefer one direct representative for every observable family."""
    selected = []
    seen = set()
    candidates = sorted(
        groups or [],
        key=lambda group: (
            not any(
                signal.get("directness")
                == "direct"
                for signal in (
                    group.get(
                        "signals", []
                    )
                    or []
                )
            ),
            group.get("first_seen")
            or "",
        ),
    )
    for group in candidates:
        families = group.get(
            "signal_families", []
        ) or []
        if not families:
            continue
        unseen = [
            family
            for family in families
            if family not in seen
        ]
        if not unseen:
            continue
        selected.append(group)
        seen.update(unseen)
        if len(selected) >= limit:
            break
    return selected


def _format_signal_group(group):
    signals = group.get(
        "signals", []
    ) or []
    descriptors = sorted({
        "{}:{}:{}:{}".format(
            signal.get(
                "signal_family"
            ),
            signal.get(
                "status"
            ),
            signal.get(
                "directness"
            ),
            signal.get(
                "scope", "unknown"
            ),
        )
        for signal in signals
    })
    return (
        "- id={}; signals={}; count={}; "
        "count_scope={}; first={}; last={}; "
        "time_quality={}; ordering={}; "
        "example={}"
    ).format(
        group.get("event_id"),
        ",".join(descriptors),
        group.get("count"),
        group.get(
            "count_scope", "unknown"
        ),
        group.get("first_seen"),
        group.get("last_seen"),
        ",".join(
            (
                group.get(
                    "time_quality", {}
                )
                or {}
            ).get(
                "source_timestamp_qualities",
                [],
            )
            or (
                group.get(
                    "time_quality", {}
                )
                or {}
            ).get(
                "clock_qualities",
                [],
            )
        ),
        ",".join(
            (
                group.get(
                    "time_quality", {}
                )
                or {}
            ).get(
                "ordering_scopes", []
            )
        ),
        _short(
            group.get(
                "example_message_decoded"
            )
            or group.get(
                "example_message"
            ),
            220,
        ),
    )


def _format_observed_signal(observation):
    burst = observation.get("burst", {}) or {}
    entities = observation.get("entities", {}) or {}
    impact = observation.get(
        "impact_assessment", {}
    ) or {}
    entity_text = ",".join(
        f"{name}={','.join(values[:2])}"
        for name, values in entities.items()
    ) or "none"
    feature_evidence = (
        observation.get(
            "feature_evidence", []
        )
        or []
    )
    feature_text = ""
    if feature_evidence:
        feature = feature_evidence[0]
        baseline = (
            feature.get("baseline", {})
            or {}
        )
        feature_text = (
            "; duration={}s; baseline_id={}; "
            "peers={}; peer_median={}s; "
            "peer_mad={}s; ratio={}; "
            "percentile={}; robust_z={}; "
            "labels_used={}"
        ).format(
            feature.get(
                "duration_seconds"
            ),
            baseline.get("baseline_id"),
            baseline.get("peer_count"),
            baseline.get(
                "peer_median_seconds"
            ),
            baseline.get(
                "peer_mad_seconds"
            ),
            baseline.get(
                "duration_ratio"
            ),
            baseline.get(
                "percentile_rank"
            ),
            baseline.get("robust_z"),
            baseline.get(
                "labels_used"
            ),
        )
    return (
        "- event={}; signal={}:{}; "
        "impact={}; entity_match={}; time_relation={}; "
        "recovery={}; successful_completion={}; entities={}; "
        "burst={} events/{} buckets/peak {}; "
        "cause_candidate_eligible={}{}"
    ).format(
        observation.get("event_id"),
        observation.get("signal_family"),
        observation.get("status"),
        impact.get(
            "impact_status",
            observation.get("impact_status"),
        ),
        impact.get("entity_match", "unknown"),
        impact.get("time_relation", "unknown"),
        observation.get("recovery_observed", False),
        observation.get(
            "successful_completion_observed",
            False,
        ),
        entity_text,
        burst.get(
            "repetitions",
            observation.get("count", 0),
        ),
        burst.get("distinct_time_buckets", 0),
        burst.get("peak_count", 0),
        observation.get(
            "cause_candidate_eligible",
            False,
        ),
        feature_text,
    )


def _format_observation_pattern(pattern):
    entity_text = ",".join(
        "{}={}:{}".format(
            name,
            summary.get("unique", 0),
            ",".join(
                summary.get("sample", [])[
                    :2
                ]
            ),
        )
        for name, summary in (
            pattern.get("entities", {})
            or {}
        ).items()
    ) or "none"
    time_quality = (
        pattern.get("time_quality", {})
        or {}
    )
    representatives = []
    for item in (
        pattern.get(
            "representative_evidence", []
        )
        or []
    )[:3]:
        representatives.append(
            "{}({}):{}".format(
                item.get("event_id"),
                item.get("count", 0),
                _short(
                    item.get("example_message"),
                    100,
                ),
            )
        )
    omitted = pattern.get(
        "omitted_event_group_count", 0
    )
    return (
        "- id={}; service={}; signal={}:{}; "
        "scope={}; impact={}; causal_status={}; "
        "groups={}; occurrences={}; time_span={}; "
        "first={}; last={}; "
        "entities={}; time_quality={}; ordering={}; "
        "representatives={}{}"
    ).format(
        pattern.get("pattern_id"),
        pattern.get("service"),
        pattern.get("signal_family"),
        pattern.get("status"),
        pattern.get("scope"),
        pattern.get("impact_status"),
        pattern.get(
            "causal_status",
            "not_established",
        ),
        pattern.get(
            "event_group_count", 0
        ),
        pattern.get(
            "occurrence_count", 0
        ),
        pattern.get(
            "time_span_status",
            "not_comparable",
        ),
        pattern.get("first_seen"),
        pattern.get("last_seen"),
        entity_text,
        ",".join(
            time_quality.get(
                "source_timestamp_qualities",
                [],
            )
        ),
        ",".join(
            time_quality.get(
                "ordering_scopes", []
            )
        ),
        " | ".join(representatives)
        or "none",
        (
            "; omitted_groups={}"
            .format(omitted)
            if omitted
            else ""
        ),
    )


def _review_observations(observations):
    """Keep details only when the pattern summary cannot replace them."""
    return [
        observation
        for observation in observations or []
        if (
            observation.get(
                "cause_candidate_eligible",
                False,
            )
            or observation.get(
                "feature_evidence"
            )
        )
    ]


def _lifecycle_rows(groups, limit=3):
    rows = []
    for group in groups or []:
        signals = [
            signal
            for signal in (
                group.get(
                    "signals", []
                )
                or []
            )
            if signal.get(
                "signal_family"
            ) == "job_lifecycle"
        ]
        if not signals:
            continue
        statuses = sorted({
            signal.get(
                "status", "unknown"
            )
            for signal in signals
        })
        scopes = sorted({
            signal.get(
                "scope", "unknown"
            )
            for signal in signals
        })
        rows.append(
            "- id={}; scope={}; statuses={}; "
            "first={}; last={}; count={}; "
            "count_scope={}; example={}".format(
                group.get("event_id"),
                ",".join(scopes),
                ",".join(statuses),
                group.get("first_seen"),
                group.get("last_seen"),
                group.get("count"),
                group.get(
                    "count_scope",
                    "unknown",
                ),
                _short(
                    group.get(
                        "example_message_decoded"
                    )
                    or group.get(
                        "example_message"
                    ),
                    180,
                ),
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _format_detection(det):
    group_labels = _compact_labels(
        det.get("group_labels", {})
    )
    return (
        "- "
        f"id={det.get('id')}; "
        f"event={det.get('event_id')}; "
        f"level={det.get('level')}; "
        f"category={det.get('category')}; "
        f"group={group_labels}; "
        f"count={det.get('group_count')}; "
        f"title={det.get('title')}"
    )


def _format_timeline(event):
    label = (
        event.get("labels")
        or event.get("commit")
        or event.get("metric")
        or ""
    )
    marker = " anchor" if event.get("is_anchor") else ""
    burst = event.get("burst", {}) or {}
    burst_text = (
        "; burst={} events/{} buckets/peak {}"
        .format(
            burst.get("repetitions", 0),
            burst.get(
                "distinct_time_buckets",
                0,
            ),
            burst.get("peak_count", 0),
        )
        if burst.get("collapsed_repetition")
        else ""
    )
    return (
        "- "
        f"{event.get('offset', 'T?')}{marker}: "
        f"id={event.get('event_id')}; "
        f"{event.get('type')} "
        f"{event.get('timestamp')} "
        f"{_compact_labels(label) if isinstance(label, dict) else label}"
        f"{burst_text}"
    )


def _format_metric(metric):
    return (
        "- "
        f"id={metric.get('event_id')}; "
        f"{metric.get('metric')}="
        f"{metric.get('value')}"
        + (
            f" at {metric.get('timestamp')}"
            if metric.get("timestamp")
            else ""
        )
        + (
            f"; peak={metric.get('peak_value')}"
            f" at {metric.get('peak_timestamp')}"
            if metric.get("peak_value") is not None
            else ""
        )
        + (
            f"; trend={metric.get('trend')}"
            if metric.get("trend")
            else ""
        )
    )


def _format_deploy(deploy):
    return (
        "- "
        f"id={deploy.get('event_id')}; "
        f"commit={deploy.get('commit')}; "
        f"time={deploy.get('time')}; "
        f"env={deploy.get('environment') or deploy.get('service')}"
    )


def _format_pivots(pivots):
    rows = []
    for key, values in (pivots or {}).items():
        rows.append(
            "- "
            f"{key}: "
            + ", ".join(
                str(v)
                for v in values[:2]
            )
        )
    return rows


def _format_source(name, status):
    status = status or {}
    source_provenance = (
        status.get(
            "provenance", {}
        )
        or {}
    )
    quality = (
        status.get(
            "data_quality", {}
        )
        or {}
    )
    pieces = [
        f"source={name}",
        f"status={status.get('status', 'unknown')}",
        (
            "schema="
            + str(
                source_provenance.get(
                    "source_schema_id",
                    "unknown",
                )
            )
        ),
        (
            "query_id="
            + str(
                source_provenance.get(
                    "query_id",
                    "unknown",
                )
            )
        ),
    ]
    if status.get("error"):
        pieces.append(f"error={_short(status.get('error'), 120)}")
    if status.get("total_count") is not None:
        pieces.append(
            f"total_count={status.get('total_count')}"
        )
    if source_provenance:
        pieces.append(
            "fetched="
            + str(
                source_provenance.get(
                    "fetched_count", 0
                )
            )
        )
        pieces.append(
            "reduced="
            + str(
                source_provenance.get(
                    "reduced_count", 0
                )
            )
        )
        pieces.append(
            "truncated="
            + str(
                source_provenance.get(
                    "truncated", False
                )
            )
        )
    if quality:
        pieces.append(
            "quarantined="
            + str(
                quality.get(
                    "quarantined_records",
                    0,
                )
            )
        )
        pieces.append(
            "duplicates="
            + str(
                quality.get(
                    "duplicate_records", 0
                )
            )
        )
        pieces.append(
            "freshness_seconds="
            + str(
                quality.get(
                    "freshness_seconds"
                )
            )
        )
    return "- " + "; ".join(pieces)


def _format_candidate(candidate):
    return (
        "- rank_score={}; title={}; category={}; events={}; "
        "impact_events={}; outcome_events={}; contradicting_events={}; "
        "evidence={}; weaknesses={}; verification={}"
    ).format(
        candidate.get("score"),
        candidate.get("title"),
        candidate.get("category"),
        ",".join(candidate.get("event_ids", [])),
        ",".join(
            candidate.get("impact_event_ids", [])
        ) or "none",
        ",".join(
            candidate.get("outcome_event_ids", [])
        ) or "none",
        ",".join(
            candidate.get("contradicting_event_ids", [])
        ) or "none",
        " | ".join(candidate.get("evidence", [])[:2]),
        " | ".join(candidate.get("weaknesses", [])[:1]) or "none",
        candidate.get("verification", "none"),
    )


def _top_group_ids_by_service(groups):
    seen = set()
    for group in groups or []:
        service = (
            group.get("labels", {})
            .get("service", "unknown")
        )
        if service in seen:
            continue
        seen.add(service)
        yield group.get("event_id")


def _format_anchor(anchor):
    anchor = anchor or {}
    return (
        "- id=" + str(anchor.get("event_id"))
        + "; type=" + str(anchor.get("type"))
        + "; time=" + str(anchor.get("timestamp"))
    )


def build_evidence_pack(state):
    alert = state.get("alert", {}) or {}
    bctx = state.get("business_context", {}) or {}
    raw_log_count = state.get(
        "raw_log_count",
        len(state.get("logs", []) or [])
    )
    groups = state.get("log_groups", []) or []
    detections = state.get("detections", []) or []
    timeline = state.get("timeline", []) or []
    metrics = state.get("metrics", []) or []
    deploys = state.get("deploys", []) or []
    suppressed = state.get("suppressed_groups", []) or []
    scope = state.get("scope_expansion", {}) or {}
    window = state.get("incident_window", {}) or {}
    source_status = state.get("source_status", {}) or {}
    quality = state.get("data_quality", {}) or {}
    assessment = state.get("deterministic_assessment", {}) or {}

    sections = [
        "# Evidence Pack",
        "",
        "## Incident",
        (
            f"- id={state.get('incident_id', alert.get('incident_id', 'unknown'))}; "
            f"service={bctx.get('service', alert.get('service', 'unknown'))}; "
            f"severity={state.get('severity', 'unknown')} "
            f"({state.get('severity_reason', '')}); "
            f"tier={bctx.get('tier', '?')}; "
            f"customer_facing={bctx.get('customer_facing', False)}; "
            f"owner={bctx.get('owner', 'unknown')}"
        ),
        f"- alert_message={_short(alert.get('message') or alert)}",
        (
            "- investigation_window="
            f"{window.get('start')}..{window.get('end')}; "
            f"anchor={window.get('anchor_time')} "
            f"({window.get('anchor_source')}); "
            f"window_truncated={window.get('truncated', False)}"
        ),
    ]

    sections.append(
        "- pack_version="
        f"{EVIDENCE_PACK_VERSION}; "
        "policy=traceable facts; explicit unknowns; "
        "approval before destructive action"
    )

    sections.extend([
        "",
        "## Scope Expansion",
        (
            "- alert_service="
            f"{scope.get('alert_service', 'unknown')}; "
            "services="
            + ",".join(
                scope.get("services", [])
            )
        ),
        *(
            _line_items(
                scope.get(
                    "service_summaries", []
                ),
                _format_service_summary,
                1
            )
            or ["- none"]
        ),
        "",
        "## Anchor",
        _format_anchor(state.get("anchor_event")),
        "",
        "## Correlated Observation Patterns",
        *(
            _line_items(
                assessment.get(
                    "observation_patterns",
                    [],
                ),
                _format_observation_pattern,
                5,
            )
            or ["- none"]
        ),
        "",
        "## Candidate/Feature Direct Signals",
        *(
            _line_items(
                _review_observations(
                    assessment.get(
                        "observed_signals",
                        [],
                    )
                ),
                _format_observed_signal,
                3,
            )
            or ["- none"]
        ),
        "",
        "## Deterministic Candidate Ranking",
        "- method={}; expansion_recommended={}; reason={}".format(
            assessment.get("method", "not_run"),
            assessment.get("expansion_recommended", False),
            assessment.get("expansion_reason", "not_run"),
        ),
        *(
            _line_items(
                assessment.get("candidates", []),
                _format_candidate,
                3,
            )
            or ["- no deterministic candidate"]
        ),
        "",
        "## Top Detection Rules",
        *(
            _line_items(
                detections,
                _format_detection,
                2
            )
            or ["- none"]
        ),
        "",
        "## Job Lifecycle",
        *(
            _lifecycle_rows(groups)
            or [
                "- no terminal or lifecycle "
                "signal in supplied evidence"
            ]
        ),
        "",
        "## Signal Family Evidence",
        *(
            _line_items(
                _signal_family_groups(
                    groups
                ),
                _format_signal_group,
                5,
            )
            or [
                "- no classified signal "
                "family in supplied evidence"
            ]
        ),
        "",
        "## Log Groups By Service",
        *(
            _groups_by_service(
                groups,
                per_service=1
            )
            or ["- none"]
        ),
        "",
        "## Rare Or High-Severity Signals",
        *(
            _line_items(
                _rare_high_signal_groups(
                    groups,
                    exclude_ids=_top_group_ids_by_service(
                        groups
                    ),
                ),
                _format_log_group,
                1
            )
            or ["- none"]
        ),
        "",
        "## Metrics",
        *(
            _line_items(
                metrics,
                _format_metric,
                2
            )
            or ["- none"]
        ),
        "",
        "## Recent Deploys",
        *(
            _line_items(
                deploys,
                _format_deploy,
                2
            )
            or ["- none"]
        ),
        "",
        "## Timeline",
        *(
            _line_items(
                timeline,
                _format_timeline,
                3
            )
            or ["- none"]
        ),
        "",
        "## Pivots",
        *(
            _format_pivots(
                {
                    key: values[:1]
                    for key, values in (
                        state.get("pivots", {}) or {}
                    ).items()
                }
            )
            or ["- none"]
        ),
        "",
        "## Frequency",
        state.get(
            "frequency_heatmap_ascii",
            ""
        ) or "- none",
        "",
        "## Omitted From LLM Context",
        f"- raw_logs={raw_log_count} available only via search_logs tool",
        f"- log_groups_omitted_from_service_summaries={max(len(groups) - 4, 0)}",
        f"- timeline_events_omitted={max(len(timeline) - 4, 0)}",
        f"- suppressed_groups={len(suppressed)}",
        (
            "- group_counts_are_exact="
            f"{quality.get('logs', {}).get('group_counts_are_exact', False)}"
        ),
        (
            "- sampling_bias="
            + _short(
                quality.get("logs", {}).get("sampling_bias", {}),
                300,
            )
        ),
        "",
        "## Source Coverage",
        *(
            [
                _format_source(name, status)
                for name, status in source_status.items()
            ]
            or ["- no source status recorded"]
        ),
    ])

    return "\n".join(sections)
