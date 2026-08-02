from datetime import (
    datetime,
    timezone
)


def _parse(ts):

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


def _bucket_start(dt, minutes):

    epoch_min = int(
        dt.timestamp() // 60
    )
    aligned = (
        epoch_min
        - (epoch_min % minutes)
    ) * 60

    return datetime.fromtimestamp(
        aligned,
        tz=timezone.utc
    )


def build(
    log_groups,
    bucket_minutes=1,
    only_levels=("error", "warn")
):

    counts = {}

    for g in log_groups:

        level = (
            g.get("labels", {})
            .get("level")
        )

        if (
            only_levels
            and level not in only_levels
        ):
            continue

        buckets = g.get("time_buckets", []) or []
        if buckets:
            for item in buckets:
                timestamp = _parse(item.get("bucket"))
                if timestamp is None:
                    continue
                key = _bucket_start(
                    timestamp, bucket_minutes
                ).isoformat()
                counts[key] = counts.get(key, 0) + int(
                    item.get("count", 0) or 0
                )
            continue

        # Legacy groups do not have event buckets. Do not fabricate an
        # even distribution; show their first observation only.
        first = _parse(g.get("first_seen"))
        if first is not None:
            key = _bucket_start(first, bucket_minutes).isoformat()
            counts[key] = counts.get(key, 0) + int(
                g.get("count", 0) or 0
            )

    return sorted(
        [
            {
                "bucket": k,
                "count": v
            }
            for k, v in counts.items()
        ],
        key=lambda x: x["bucket"]
    )


def render_ascii(
    histogram,
    width=40
):

    if not histogram:
        return "(no data)"

    max_count = max(
        h["count"]
        for h in histogram
    ) or 1

    lines = []

    for h in histogram:

        bar_len = int(
            (h["count"] / max_count)
            * width
        )
        bar = "█" * bar_len

        ts = h["bucket"][11:16]

        lines.append(
            f"{ts}  {bar} "
            f"({h['count']})"
        )

    return "\n".join(lines)
