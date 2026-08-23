from typing import Annotated
from typing import TypedDict
from typing import List
from typing import Dict
from typing import Any
from typing import Optional


def _merge_status(left, right):
    return {**(left or {}), **(right or {})}


class IncidentState(TypedDict, total=False):

    alert: Dict[str, Any]

    incident_id: str

    severity: str
    severity_reason: str
    business_context: Dict[str, Any]
    impact: Dict[str, Any]

    logs: List[dict]
    raw_log_count: int
    log_query: Dict[str, Any]
    log_groups: List[dict]
    suppressed_groups: List[dict]
    metrics: List[dict]
    deploys: List[dict]

    detections: List[dict]
    pivots: Dict[str, List[str]]

    timeline: List[dict]
    anchor_event: Optional[Dict[str, Any]]
    frequency_histogram: List[dict]
    frequency_heatmap_ascii: str
    incident_window: Dict[str, Any]
    source_status: Annotated[Dict[str, Any], _merge_status]
    data_quality: Dict[str, Any]
    collection_plan: Dict[str, Any]
    incident_features: Dict[str, Any]
    deterministic_assessment: Dict[str, Any]
    decision_brief: Dict[str, Any]
    investigation_budget: Dict[str, Any]
    investigation_loop: Dict[str, Any]
    investigation_revisions: List[dict]
    analysis_deadline: Dict[str, Any]
    model_usage_ledger: Dict[str, Any]
    skill_policy_profiles: Dict[str, List[str]]
    evidence_graph: Dict[str, Any]
    scope_expansion: Dict[str, Any]
    evidence_pack: str

    labels: List[str]

    semantic_correlation: Dict[str, Any]
    semantic_correlation_tool_trace: List[dict]
    targeted_evidence: Dict[str, Any]

    interpretation: str
    interpretation_structured: Dict[str, Any]
    claim_grounding: Dict[str, Any]
    interpretation_attempts: int
    interpretation_tool_trace: List[dict]
    interpretation_quality: Dict[str, Any]

    review_status: str
    review_feedback: str
    investigation_request: str
    chosen_hypothesis: int

    rca_chain: str

    postmortem_draft: str
    publish_review_status: str
    publish_review_feedback: str
    approved_draft_sha256: str
    postmortem_url: str
    postmortem_html_path: str

    execution_log: List[dict]
