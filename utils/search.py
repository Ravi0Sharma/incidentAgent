import re


def _compile_pattern(pattern):

    if not pattern:
        return None

    return re.compile(
        re.escape(str(pattern)),
        re.IGNORECASE
    )


def search_logs(
    logs,
    pattern=None,
    service=None,
    level=None,
    max_results=25
):

    if not logs:
        return []

    rx = _compile_pattern(pattern)

    out = []

    for log in logs:

        labels = log.get(
            "labels", {}
        ) or {}

        if (
            service
            and labels.get("service")
            != service
        ):
            continue

        if (
            level
            and labels.get("level")
            != level
        ):
            continue

        if rx:
            msg = log.get(
                "message", ""
            ) or ""
            if not rx.search(msg):
                continue

        out.append({
            "timestamp":
            log.get("timestamp"),
            "labels": labels,
            "message":
            log.get("message")
        })

        if len(out) >= max_results:
            break

    return out


def count_logs(
    logs,
    pattern=None,
    service=None,
    level=None
):

    if not logs:
        return 0

    rx = _compile_pattern(pattern)

    total = 0

    for log in logs:

        labels = log.get(
            "labels", {}
        ) or {}

        if (
            service
            and labels.get("service")
            != service
        ):
            continue

        if (
            level
            and labels.get("level")
            != level
        ):
            continue

        if rx:
            msg = log.get(
                "message", ""
            ) or ""
            if not rx.search(msg):
                continue

        total += 1

    return total


def search_summary(logs, **kwargs):

    matches = search_logs(
        logs, **kwargs
    )
    total = count_logs(
        logs, **kwargs
    )

    return {
        "total_matched":
        total,
        "sample_count":
        len(matches),
        "sample": matches[:10],
        "query": {
            k: v
            for k, v in kwargs.items()
            if v is not None
        }
    }
