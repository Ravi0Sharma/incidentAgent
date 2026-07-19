from utils.evidence_pack import (
    build_evidence_pack as _build
)


def build_evidence_pack(state):
    return {
        "evidence_pack": _build(state),
        "data_quality": {
            **(state.get("data_quality", {}) or {}),
            "sources": state.get("source_status", {}) or {},
        },
    }
