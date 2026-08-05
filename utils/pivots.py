import re


PIVOT_FIELDS = (
    "trace_id",
    "user_id",
    "request_id",
    "commit_sha",
    "pod",
    "host"
)


_MESSAGE_PATTERNS = [
    ("trace_id", re.compile(
        r"trace[_-]?id[=:\s\"]+"
        r"([a-f0-9-]{8,})",
        re.IGNORECASE
    )),
    ("request_id", re.compile(
        r"(?:req(?:uest)?[_-]?id|"
        r"x-request-id)"
        r"[=:\s\"]+([A-Za-z0-9-]{6,})",
        re.IGNORECASE
    )),
    ("user_id", re.compile(
        r"user[_-]?id[=:\s\"]+"
        r"([A-Za-z0-9-]{3,})",
        re.IGNORECASE
    )),
    ("commit_sha", re.compile(
        r"\b([0-9a-f]{7,40})\b"
    ))
]


_MAX_PER_KEY = 20


def _add(bucket, key, value):

    if not value:
        return

    v = str(value).strip()

    if not v:
        return

    if v in bucket[key]:
        return

    if len(bucket[key]) >= (
        _MAX_PER_KEY
    ):
        return

    bucket[key].append(v)


def extract_from_group(group):

    bucket = {
        k: []
        for k in PIVOT_FIELDS
    }

    labels = group.get(
        "labels", {}
    ) or {}

    for k in PIVOT_FIELDS:
        if k in labels:
            _add(
                bucket,
                k,
                labels[k]
            )

    messages = [
        group.get("example_message", "") or "",
        *(group.get("sample_messages", []) or []),
        *[
            sample.get("message", "")
            for sample in (
                group.get("representative_samples", [])
                or []
            )
        ],
    ]

    for msg in messages:
        for key, rx in _MESSAGE_PATTERNS:
            for m in rx.finditer(msg):
                _add(bucket, key, m.group(1))

    return {
        k: v
        for k, v in bucket.items()
        if v
    }


def extract_all(groups, top_n=10):

    merged = {
        k: []
        for k in PIVOT_FIELDS
    }

    for g in groups[:top_n]:

        pivots = extract_from_group(g)

        for k, values in (
            pivots.items()
        ):
            for v in values:
                _add(merged, k, v)

    return {
        k: v
        for k, v in merged.items()
        if v
    }
