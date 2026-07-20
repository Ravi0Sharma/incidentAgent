from utils.log_normalizer import (
    normalize_logs as _normalize
)


def normalize_logs(state):

    raw = state.get("logs", []) or []

    normalized = _normalize(raw)

    return {"logs": normalized}
