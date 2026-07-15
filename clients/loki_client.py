from datetime import datetime, timedelta, timezone

import json
import re

from settings import (
    LOKI_URL,
    LOKI_USER,
    LOKI_API_KEY,
    LOG_QUERY_LIMIT,
    LOG_TOOL_QUERY_LIMIT,
)

from utils.incident_window import parse_window
from utils.resilience import request
from utils.signal_catalog import (
    detect_signals,
    signal_key,
)


LABEL_FORWARDING_KEYS = (
    "namespace",
    "cluster",
    "env",
    "environment"
)

HIGH_SIGNAL_PATTERN = (
    r"(?i)(error|exception|fatal|panic|timeout|"
    r"failed|failure|lost|unreachable|refused|"
    r"exhausted|oomkilled|servfail|nxdomain|"
    r"no space left|disk full|connection reset|"
    r"exit code|killed)"
)


def _high_signal_shape(log):
    """Group volatile variants while preserving operational distinctions."""
    labels = log.get(
        "labels", {}
    ) or {}
    level = str(
        labels.get("level", "")
    ).lower()
    message = str(
        log.get("message", "")
    ).lower()
    protected = {}

    def protect_semantic(match, label):
        token = (
            "__samplingcode"
            + chr(ord("a") + len(protected))
            + "__"
        )
        protected[token] = f"{label}={match.group(1)}"
        return token

    semantic_patterns = (
        (
            r"\bsqlstate\s*[\[\(:= ]\s*([0-9a-z]{5})\]?",
            "sqlstate",
        ),
        (
            r"\b(?:http(?:\s+status)?|status(?:_code)?)"
            r"[=:\s]+([1-5][0-9]{2})\b",
            "http_status",
        ),
        (
            r"\b(?:errno|error_code)"
            r"[=:\s\[]+([0-9a-z_-]{2,16})\]?",
            "error_code",
        ),
    )
    for pattern, name in semantic_patterns:
        message = re.sub(
            pattern,
            lambda match, label=name: protect_semantic(
                match, label
            ),
            message,
            flags=re.IGNORECASE,
        )
    message = re.sub(
        r"trace[_-]?id[=:\s\"]+[a-z0-9-]+",
        "trace_id=?",
        message,
    )
    message = re.sub(
        r"(?:req(?:uest)?[_-]?id|x-request-id)"
        r"[=:\s\"]+[a-z0-9-]+",
        "request_id=?",
        message,
    )
    message = re.sub(
        r"user[_-]?id[=:\s\"]+[a-z0-9-]+",
        "user_id=?",
        message,
    )
    message = re.sub(
        r"^\[(?:req-\[uuid\]|-)[^\]]*\]\s*",
        "[request_context] ",
        message,
    )
    message = re.sub(
        r"\b(peer|host|node|pod|instance|container)"
        r"(?:[_-]?id)?[=:]+[a-z0-9._-]+",
        lambda match: match.group(1) + "=?",
        message,
    )
    message = re.sub(
        r"\b0x[0-9a-f]+\b",
        "<hex>",
        message,
    )
    message = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b",
        "<uuid>",
        message,
    )
    message = re.sub(
        r"\b(?=[0-9a-f]{7,40}\b)"
        r"(?=[0-9a-f]*[a-f])[0-9a-f]+\b",
        "<hex>",
        message,
    )
    message = re.sub(
        r"\d+(?:\.\d+)?",
        "<num>",
        message,
    )
    message = re.sub(
        r"\s+", " ", message
    ).strip()
    for token, value in protected.items():
        message = message.replace(token, value)
    if len(message) > 180:
        message = message[:120] + " … " + message[-56:]
    return (
        str(labels.get("service", "")),
        level,
        str(labels.get("error_type", "")),
        str(labels.get("event_name", "")),
        str(labels.get("status_code", "")),
        message,
    )


def _log_key(log):
    return (
        str(log.get("timestamp")),
        str(log.get("message")),
        json.dumps(
            log.get("labels", {}),
            sort_keys=True,
            default=str,
        ),
    )


def _sorted_unique(logs):
    unique = {}
    for log in logs or []:
        unique[_log_key(log)] = log
    return sorted(
        unique.values(),
        key=lambda item: str(
            item.get("timestamp", "")
        ),
    )


def _even_sample(logs, limit):
    rows = _sorted_unique(logs)
    limit = max(int(limit or 1), 1)
    if len(rows) <= limit:
        return rows
    if limit == 1:
        return [rows[0]]
    indexes = {
        round(
            index
            * (len(rows) - 1)
            / (limit - 1)
        )
        for index in range(limit)
    }
    return [
        rows[index]
        for index in sorted(indexes)
    ]


def representative_sample(logs, limit):
    """Keep boundaries, high signals and bounded general event-shape coverage."""
    rows = _sorted_unique(logs)
    limit = max(int(limit or 1), 1)
    if len(rows) <= limit:
        return rows

    selected = []
    selected_keys = set()

    def add(values):
        for log in values:
            if len(selected) >= limit:
                break
            key = _log_key(log)
            if key in selected_keys:
                continue
            selected.append(log)
            selected_keys.add(key)

    # Boundary events protect time coverage and terminal events near the end.
    add([rows[0], rows[-1]])

    # Reserve first/last representatives for each semantic signal shape.
    signal_buckets = {}
    for log in rows:
        for signal in detect_signals(
            log
        ):
            signal_buckets.setdefault(
                signal_key(signal),
                [],
            ).append(log)
    semantic_budget = min(
        max(limit // 4, 2),
        limit - len(selected),
    )
    semantic = []
    for key in sorted(
        signal_buckets,
        key=str,
    ):
        values = signal_buckets[key]
        semantic.extend(
            [values[0], values[-1]]
        )
    add(
        _even_sample(
            semantic,
            semantic_budget,
        )
    )

    high_signal_buckets = {}
    for log in rows:
        labels = log.get(
            "labels", {}
        ) or {}
        level = str(
            labels.get("level", "")
        ).lower()
        message = str(
            log.get("message", "")
        )
        if (
            level in {
                "error",
                "fatal",
                "warn",
                "warning",
                "critical",
            }
            or re.search(
                HIGH_SIGNAL_PATTERN,
                message,
            )
        ):
            high_signal_buckets.setdefault(
                _high_signal_shape(log),
                [],
            ).append(log)

    high_signal = []
    for key in sorted(
        high_signal_buckets,
        key=str,
    ):
        values = high_signal_buckets[
            key
        ]
        high_signal.extend(
            [values[0], values[-1]]
        )
    signal_limit = min(
        len(high_signal),
        max(1, limit // 3),
        limit - len(selected),
    )
    add(
        _even_sample(
            high_signal,
            signal_limit,
        )
    )

    # Time-only fill can omit uncommon informational event shapes. Reserve one
    # representative per general shape before using the remaining time sample.
    # The budget keeps this bounded when a source has high shape cardinality.
    general_shape_buckets = {}
    for log in rows:
        general_shape_buckets.setdefault(
            _high_signal_shape(log),
            [],
        ).append(log)
    general_representatives = [
        values[0]
        for _, values in sorted(
            general_shape_buckets.items(),
            key=lambda item: str(item[0]),
        )
    ]
    general_shape_limit = min(
        len(general_representatives),
        max(4, limit // 3),
        limit - len(selected),
    )
    add(
        _even_sample(
            general_representatives,
            general_shape_limit,
        )
    )

    remaining = [
        log
        for log in rows
        if _log_key(log)
        not in selected_keys
    ]
    remaining_slots = (
        limit - len(selected)
    )
    if remaining_slots > 0:
        add(
            _even_sample(
                remaining,
                remaining_slots,
            )
        )
    return _sorted_unique(selected)[
        :limit
    ]


def _time_slices(start, end, count):
    count = max(int(count or 1), 1)
    width = (end - start) / count
    return [
        (
            start + width * index,
            (
                end
                if index == count - 1
                else start
                + width * (index + 1)
            ),
        )
        for index in range(count)
    ]


def _quotas(total, count):
    count = max(int(count or 1), 1)
    base, remainder = divmod(
        max(int(total or 0), 0),
        count,
    )
    return [
        base + (1 if index < remainder else 0)
        for index in range(count)
    ]


def _build_logql(
    service,
    alert_labels,
    extra_labels=None,
):

    selectors = []

    def quoted(value):
        # JSON quoting prevents labels from breaking out of the selector.
        return json.dumps(str(value))

    if service:
        selectors.append(
            f"service={quoted(service)}"
        )

    if alert_labels:
        for k in (
            LABEL_FORWARDING_KEYS
        ):
            v = alert_labels.get(k)
            if v:
                selectors.append(
                    f"{k}={quoted(v)}"
                )

    for key, value in (extra_labels or {}).items():
        if value:
            selectors.append(
                f"{key}={quoted(value)}"
            )

    if not selectors:
        selectors.append(
            'service=~".+"'
        )

    return (
        "{"
        + ",".join(selectors)
        + "}"
    )


def _line_filter(pattern):
    if not pattern:
        return ""
    # Literal matching is deliberate. The LLM must not be able to submit
    # arbitrary LogQL regular expressions or pipeline expressions.
    return " |= " + json.dumps(str(pattern))


def _range_params(
    query,
    start,
    end,
    limit,
    direction="backward",
):
    return {
        "query": query,
        "start": int(start.timestamp() * 1e9),
        "end": int(end.timestamp() * 1e9),
        "limit": limit,
        "direction": direction,
    }


def _as_log(stream_labels, value):
    ts_ns, line = value
    return {
        "timestamp": datetime.fromtimestamp(
            int(ts_ns) / 1e9,
            tz=timezone.utc,
        ).isoformat(),
        "message": line,
        "labels": stream_labels,
    }


def _within_filters(
    log,
    pattern=None,
    service=None,
    level=None
):

    labels = log.get(
        "labels", {}
    ) or {}

    if (
        service
        and labels.get("service")
        != service
    ):
        return False

    if (
        level
        and labels.get("level")
        != level
    ):
        return False

    if pattern:
        return (
            pattern.lower()
            in (log.get("message", "") or "")
            .lower()
        )

    return True


class RealLokiClient:

    sampling_strategy = (
        "time_stratified_with_high_signal"
    )

    def __init__(
        self,
        base_url,
        user,
        api_key
    ):
        self.base_url = (
            base_url.rstrip("/")
        )
        self.auth = (
            (user, api_key)
            if user and api_key
            else None
        )

    def query_logs(
        self,
        service,
        alert_labels=None,
        window=None,
        limit=LOG_QUERY_LIMIT,
    ):

        query = _build_logql(
            service,
            alert_labels
        )

        start, end = parse_window(window)
        bounded_limit = min(
            max(int(limit or 1), 1),
            LOG_QUERY_LIMIT,
        )
        general_budget = max(
            1,
            bounded_limit * 3 // 4,
        )
        signal_budget = (
            bounded_limit - general_budget
        )
        slice_count = min(
            4,
            max(1, general_budget // 2),
        )
        slices = _time_slices(
            start,
            end,
            slice_count,
        )
        logs = []

        for (
            slice_start,
            slice_end,
        ), quota in zip(
            slices,
            _quotas(
                general_budget,
                slice_count,
            ),
        ):
            if quota <= 0:
                continue
            forward = (
                quota
                if quota == 1
                else (quota + 1) // 2
            )
            backward = quota - forward
            logs.extend(
                self._query_range(
                    query,
                    slice_start,
                    slice_end,
                    forward,
                    "forward",
                )
            )
            if backward:
                logs.extend(
                    self._query_range(
                        query,
                        slice_start,
                        slice_end,
                        backward,
                        "backward",
                    )
                )

        if signal_budget:
            signal_query = (
                query
                + " |~ "
                + json.dumps(
                    HIGH_SIGNAL_PATTERN
                )
            )
            for (
                slice_start,
                slice_end,
            ), quota in zip(
                slices,
                _quotas(
                    signal_budget,
                    slice_count,
                ),
            ):
                if quota <= 0:
                    continue
                logs.extend(
                    self._query_range(
                        signal_query,
                        slice_start,
                        slice_end,
                        quota,
                        "forward",
                    )
                )

        sampled = _sorted_unique(logs)
        if len(sampled) < bounded_limit:
            sampled.extend(
                self._query_range(
                    query,
                    start,
                    end,
                    bounded_limit
                    - len(sampled),
                    "backward",
                )
            )
        return _sorted_unique(
            sampled
        )[:bounded_limit]

    def _query_range(
        self,
        query,
        start,
        end,
        limit,
        direction,
    ):
        if limit <= 0:
            return []
        resp = request(
            "loki",
            "GET",
            (
                f"{self.base_url}"
                "/loki/api/v1"
                "/query_range"
            ),
            params=_range_params(
                query,
                start,
                end,
                limit,
                direction,
            ),
            auth=self.auth,
        )
        data = resp.json()
        logs = []
        for stream in (
            data.get(
                "data", {}
            ).get(
                "result", []
            )
        ):
            labels = stream.get(
                "stream", {}
            )
            for value in stream.get(
                "values", []
            ):
                logs.append(
                    _as_log(
                        labels,
                        value,
                    )
                )
        return logs

    def _count(self, query, start, end):
        seconds = max(int((end - start).total_seconds()), 1)
        count_query = (
            "sum(count_over_time("
            f"{query}[{seconds}s]))"
        )
        resp = request(
            "loki", "GET",
            f"{self.base_url}/loki/api/v1/query",
            params={
                "query": count_query,
                "time": end.timestamp(),
            },
            auth=self.auth,
        )
        rows = (
            resp.json().get("data", {}).get("result", [])
        )
        if not rows:
            return 0
        return int(float(rows[0].get("value", [0, "0"])[1]))

    def get_log_stats(
        self,
        service=None,
        alert_labels=None,
        window=None,
        pattern=None,
        level=None,
    ):
        start, end = parse_window(window)
        query = _build_logql(
            service,
            alert_labels,
            extra_labels={"level": level},
        ) + _line_filter(pattern)
        try:
            total = self._count(query, start, end)
            return {
                "total_count": total,
                "count_is_exact": True,
                "query_kind": "loki_count_over_time",
            }
        except Exception as exc:
            return {
                "total_count": None,
                "count_is_exact": False,
                "count_error": str(exc),
            }

    def query_logs_by_pattern(
        self,
        service=None,
        alert_labels=None,
        pattern=None,
        level=None,
        limit=LOG_TOOL_QUERY_LIMIT,
        window=None,
    ):

        query = _build_logql(
            service,
            alert_labels,
            extra_labels={"level": level},
        ) + _line_filter(pattern)
        start, end = parse_window(window)
        params = _range_params(
            query,
            start,
            end,
            min(max(int(limit or 50), 1), 250),
        )

        resp = request(
            "loki", "GET",
            (
                f"{self.base_url}"
                "/loki/api/v1"
                "/query_range"
            ),
            params=params,
            auth=self.auth,
        )
        data = resp.json()

        out = []

        for stream in (
            data
            .get("data", {})
            .get("result", [])
        ):
            stream_labels = (
                stream.get(
                    "stream", {}
                )
            )
            for value in (
                stream.get(
                    "values", []
                )
            ):
                log = _as_log(stream_labels, value)
                if not _within_filters(
                    log,
                    pattern=pattern,
                    service=service,
                    level=level
                ):
                    continue
                if len(out) < 25:
                    out.append(log)

        stats = self.get_log_stats(
            service=service,
            alert_labels=alert_labels,
            window=window,
            pattern=pattern,
            level=level,
        )

        return {
            "total_matched": stats.get("total_count"),
            "count_is_exact": stats.get("count_is_exact", False),
            "count_error": stats.get("count_error"),
            "sample_count": len(out),
            "sample": out
        }

    def discover_services(
        self,
        alert_labels=None,
        limit=250,
        window=None,
    ):

        result = self.query_logs_by_pattern(
            service=None,
            alert_labels=alert_labels,
            limit=limit,
            window=window,
        )

        counts = {}
        levels = {}

        for log in result.get("sample", []):
            labels = log.get(
                "labels", {}
            ) or {}
            service = labels.get(
                "service"
            )
            if not service:
                continue
            counts[service] = (
                counts.get(service, 0)
                + 1
            )
            level = labels.get("level")
            if level:
                levels.setdefault(
                    service, set()
                ).add(level)

        services = [
            {
                "service": service,
                "sampled_count": count,
                "levels": sorted(
                    levels.get(
                        service,
                        set()
                    )
                )
            }
            for service, count in (
                sorted(
                    counts.items(),
                    key=lambda item:
                    item[1],
                    reverse=True
                )
            )
        ]

        return services[:limit]


class MockLokiClient:

    sampling_strategy = (
        "time_stratified_with_high_signal"
    )

    def _logs_for_service(self, service, window=None):
        """Create a synthetic, trace-linked database-pool incident.

        The local demo deliberately models one causal chain: a payments pool
        exhaustion followed by checkout failures carrying the same trace IDs.
        It is not production data and must stay free of real customer content.
        """
        _start, end = parse_window(window)
        base = end.replace(
            second=0,
            microsecond=0,
        ) - timedelta(minutes=6)

        def ts(minutes, seconds):
            return (
                base + timedelta(
                    minutes=minutes,
                    seconds=seconds,
                )
            ).isoformat().replace("+00:00", "Z")

        logs = []

        if service == "payments":
            for i in range(72):
                m = 2 + i // 36
                s = (i * 3) % 60
                logs.append({
                    "timestamp": ts(m, s),
                    "message": (
                        "pool timeout: connection pool exhausted after 5000ms "
                        "trace_id="
                        f"paydb{i % 12:03d} "
                        "SQLSTATE[53300]"
                    ),
                    "labels": {
                        "service": "payments",
                        "level": "error",
                        "error_type": "db_timeout",
                        "pod": f"payments-{(i % 3) + 1}",
                    }
                })
            for i in range(12):
                logs.append({
                    "timestamp": ts(5, (i * 4) % 60),
                    "message": (
                        "request processed after connection pool recovery "
                        f"request_id=payment-r{i:03d}"
                    ),
                    "labels": {
                        "service": "payments",
                        "level": "info",
                        "error_type": "ok",
                    }
                })

        elif service == "checkout":
            for i in range(24):
                logs.append({
                    "timestamp": ts(3 + i // 18, (i * 3) % 60),
                    "message": (
                        "payment authorization failed because payments could not "
                        "acquire a database connection trace_id="
                        f"paydb{i % 12:03d}"
                    ),
                    "labels": {
                        "service": "checkout",
                        "level": "error",
                        "error_type": "payments_dependency_failure",
                    }
                })

        elif service == "auth":
            for i in range(8):
                logs.append({
                    "timestamp": ts(2, (i * 7) % 60),
                    "message": (
                        "token introspection completed normally "
                        f"request_id=auth-r{i:03d}"
                    ),
                    "labels": {
                        "service": "auth",
                        "level": "info",
                        "error_type": "ok",
                    }
                })

        else:
            for i in range(6):
                logs.append({
                    "timestamp": ts(2, (i * 8) % 60),
                    "message": f"background task completed request_id=other-r{i:03d}",
                    "labels": {
                        "service": service,
                        "level": "info",
                        "error_type": "ok",
                    }
                })

        return logs

    def query_logs(
        self,
        service,
        alert_labels=None,
        window=None,
        limit=LOG_QUERY_LIMIT,
    ):

        return representative_sample(
            self._logs_for_service(
                service,
                window=window,
            ),
            limit,
        )

    def get_log_stats(
        self,
        service=None,
        alert_labels=None,
        window=None,
        pattern=None,
        level=None,
    ):
        result = self.query_logs_by_pattern(
            service=service,
            alert_labels=alert_labels,
            pattern=pattern,
            level=level,
            window=window,
        )
        return {
            "total_count": result.get("total_matched", 0),
            "count_is_exact": True,
            "query_kind": "mock_exact",
        }

    def query_logs_by_pattern(
        self,
        service=None,
        alert_labels=None,
        pattern=None,
        level=None,
        limit=LOG_TOOL_QUERY_LIMIT,
        window=None,
    ):

        services = (
            [service]
            if service
            else [
                "payments",
                "checkout",
                "auth",
                "catalog"
            ]
        )

        matches = []
        total = 0

        for svc in services:
            for log in self._logs_for_service(
                svc,
                window=window,
            ):
                if not _within_filters(
                    log,
                    pattern=pattern,
                    service=service,
                    level=level
                ):
                    continue
                total += 1
                if len(matches) < min(
                    int(limit or 50),
                    25
                ):
                    matches.append(log)

        return {
            "total_matched": total,
            "count_is_exact": True,
            "sample_count": len(matches),
            "sample": matches
        }

    def discover_services(
        self,
        alert_labels=None,
        limit=20,
        window=None,
    ):

        services = []

        for service in (
            "payments",
            "checkout",
            "auth",
            "catalog"
        ):
            logs = self._logs_for_service(
                service
            )
            levels = sorted({
                (
                    log.get("labels", {})
                    .get("level")
                )
                for log in logs
                if log.get("labels", {})
                .get("level")
            })
            services.append({
                "service": service,
                "sampled_count":
                len(logs),
                "levels": levels
            })

        return services[:limit]


def _make_client():

    if LOKI_URL:
        return RealLokiClient(
            LOKI_URL,
            LOKI_USER,
            LOKI_API_KEY
        )

    print(
        "[loki_client] LOKI_URL "
        "not set, using mock"
    )
    return MockLokiClient()


loki = _make_client()
