from langgraph.graph import (
    StateGraph,
    END
)

from utils.observability import (
    init_tracing
)

init_tracing()

from graph.checkpointer import (
    build_checkpointer
)

from graph.state import (
    IncidentState
)

from graph.nodes.ingest_alert import (
    ingest_alert
)

from graph.nodes.classify_severity import (
    classify_severity
)

from graph.nodes.plan_collection import (
    plan_collection
)

from graph.nodes.gather_logs import (
    gather_logs
)

from graph.nodes.gather_metrics import (
    gather_metrics
)

from graph.nodes.gather_deploys import (
    gather_deploys
)

from graph.nodes.normalize_logs import (
    normalize_logs
)

from graph.nodes.aggregate_by_labels import (
    aggregate_by_labels
)

from graph.nodes.extract_features import (
    extract_features
)

from graph.nodes.apply_detection_rules import (
    apply_detection_rules
)

from graph.nodes.enrich_groups import (
    enrich_groups
)

from graph.nodes.correlate import (
    correlate
)

from graph.nodes.reassess_severity import (
    reassess_severity
)

from graph.nodes.scope_expansion import (
    scope_expansion
)

from graph.nodes.score_candidates import (
    score_candidates
)

from graph.nodes.build_llm_context import (
    build_llm_context
)

from graph.nodes.build_evidence_pack import (
    build_evidence_pack
)

from graph.nodes.semantic_correlate import (
    semantic_correlate
)

from graph.nodes.integrate_targeted_evidence import (
    integrate_targeted_evidence
)

from graph.nodes.reinvestigate_feedback import (
    reinvestigate_feedback
)

from graph.nodes.interpret_incident import (
    interpret_incident
)

from graph.nodes.human_review import (
    human_review
)

from graph.nodes.deep_rca import (
    deep_rca
)

from graph.nodes.draft_postmortem import (
    draft_postmortem
)

from graph.nodes.publish import (
    publish
)
from graph.nodes.publish_review import (
    publish_review,
    publish_review_router,
)

from graph.routing import (
    review_router
)
from utils.investigation_loop import (
    expansion_router,
)


builder = StateGraph(
    IncidentState
)

builder.add_node(
    "ingest_alert", ingest_alert
)
builder.add_node(
    "classify_severity",
    classify_severity
)
builder.add_node(
    "plan_collection",
    plan_collection
)
builder.add_node(
    "gather_logs", gather_logs
)
builder.add_node(
    "gather_metrics", gather_metrics
)
builder.add_node(
    "gather_deploys", gather_deploys
)
builder.add_node(
    "normalize_logs", normalize_logs
)
builder.add_node(
    "aggregate_by_labels",
    aggregate_by_labels,
    defer=True
)
builder.add_node(
    "extract_features",
    extract_features
)
builder.add_node(
    "apply_detection_rules",
    apply_detection_rules
)
builder.add_node(
    "enrich_groups", enrich_groups
)
builder.add_node(
    "correlate", correlate
)
builder.add_node(
    "reassess_severity", reassess_severity
)
builder.add_node(
    "scope_expansion",
    scope_expansion
)
builder.add_node(
    "score_candidates",
    score_candidates
)
builder.add_node(
    "build_llm_context",
    build_llm_context
)
builder.add_node(
    "build_evidence_pack",
    build_evidence_pack
)
builder.add_node(
    "semantic_correlate",
    semantic_correlate
)
builder.add_node(
    "integrate_targeted_evidence",
    integrate_targeted_evidence
)
builder.add_node(
    "reinvestigate_feedback",
    reinvestigate_feedback
)
builder.add_node(
    "interpret_incident",
    interpret_incident
)
builder.add_node(
    "human_review", human_review
)
builder.add_node(
    "deep_rca", deep_rca
)
builder.add_node(
    "draft_postmortem",
    draft_postmortem
)
builder.add_node(
    "publish", publish
)
builder.add_node(
    "publish_review", publish_review
)


builder.set_entry_point(
    "ingest_alert"
)

builder.add_edge(
    "ingest_alert",
    "classify_severity"
)

builder.add_edge(
    "classify_severity",
    "plan_collection"
)

builder.add_edge(
    "plan_collection",
    "gather_logs"
)
builder.add_edge(
    "plan_collection",
    "gather_metrics"
)
builder.add_edge(
    "plan_collection",
    "gather_deploys"
)

builder.add_edge(
    "gather_logs",
    "normalize_logs"
)

builder.add_edge(
    "normalize_logs",
    "aggregate_by_labels"
)
builder.add_edge(
    "gather_metrics",
    "aggregate_by_labels"
)
builder.add_edge(
    "gather_deploys",
    "aggregate_by_labels"
)

builder.add_edge(
    "aggregate_by_labels",
    "apply_detection_rules"
)
builder.add_edge(
    "apply_detection_rules",
    "enrich_groups"
)

builder.add_edge(
    "enrich_groups",
    "extract_features"
)

builder.add_edge(
    "extract_features",
    "correlate"
)

builder.add_edge(
    "correlate",
    "reassess_severity"
)

builder.add_edge(
    "reassess_severity",
    "scope_expansion"
)

builder.add_edge(
    "scope_expansion",
    "score_candidates"
)
builder.add_edge(
    "score_candidates",
    "build_llm_context"
)
builder.add_edge(
    "build_llm_context",
    "build_evidence_pack"
)

builder.add_edge(
    "build_evidence_pack",
    "semantic_correlate"
)

builder.add_edge(
    "semantic_correlate",
    "integrate_targeted_evidence"
)

builder.add_conditional_edges(
    "integrate_targeted_evidence",
    expansion_router,
    {
        "semantic_correlate":
        "semantic_correlate",
        "interpret_incident":
        "interpret_incident",
    },
)

builder.add_edge(
    "interpret_incident",
    "human_review"
)

builder.add_conditional_edges(
    "human_review",
    review_router,
    {
        "deep_rca": "deep_rca",
        "reinvestigate_feedback":
        "reinvestigate_feedback"
    }
)

builder.add_edge(
    "reinvestigate_feedback",
    "semantic_correlate"
)

builder.add_edge(
    "deep_rca",
    "draft_postmortem"
)

builder.add_edge(
    "draft_postmortem",
    "publish_review"
)

builder.add_conditional_edges(
    "publish_review",
    publish_review_router,
    {
        "publish": "publish",
        "end": END,
    },
)

builder.add_edge("publish", END)


checkpointer = build_checkpointer()

graph = builder.compile(
    checkpointer=checkpointer
)

graph_for_studio = builder.compile()
