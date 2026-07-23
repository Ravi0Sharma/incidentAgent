import json
import os
import sys


_HERE = os.path.dirname(
    os.path.abspath(__file__)
)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from graph.nodes.classify_severity import (
    classify_severity
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
from graph.nodes.apply_detection_rules import (
    apply_detection_rules
)
from graph.nodes.enrich_groups import (
    enrich_groups
)
from graph.nodes.correlate import (
    correlate
)
from graph.nodes.scope_expansion import (
    scope_expansion
)
from graph.nodes.build_evidence_pack import (
    build_evidence_pack
)
from graph.nodes.interpret_incident import (
    _build_prompt as build_interpret_prompt
)
from utils.stub_llm import (
    stub_semantic_correlation
)
from utils.llm_context import (
    build_approved_context
)
from utils.untrusted_data import (
    delimit
)
from prompts.rca_prompt import (
    PROMPT as RCA_PROMPT
)
from prompts.postmortem_prompt import (
    PROMPT as POSTMORTEM_PROMPT
)


# These are context-size regression guards, not incident-volume thresholds.
# Raw error volume is retained as aggregate counts while representative
# evidence remains bounded.
PROMPT_CHAR_BUDGETS = {
    "interpretation": 8000,
    "rca": 6000,
    "postmortem": 6000
}


def _build_state():
    with open("fixtures/latency_alert.json") as f:
        alert = json.load(f)

    state = {
        "alert": alert,
        "execution_log": []
    }

    for node in (
        classify_severity,
        gather_logs,
        gather_metrics,
        gather_deploys,
        normalize_logs,
        aggregate_by_labels,
        apply_detection_rules,
        enrich_groups,
        correlate,
        scope_expansion,
        build_evidence_pack
    ):
        state.update(node(state))

    state["semantic_correlation"] = (
        stub_semantic_correlation(state)
    )
    state[
        "semantic_correlation_tool_trace"
    ] = []

    return state


def main():
    state = _build_state()

    interpretation_prompt = (
        build_interpret_prompt(state)
    )

    fake_interpretation = (
        "## TL;DR\n"
        "Database connection pool exhausted "
        "after deploy. Evidence cites "
        "db-connection-pool-exhausted, "
        "deploy-regression, count=42."
    )

    rca_prompt = RCA_PROMPT.format(
        chosen_hypothesis=1,
        approved_context=delimit(
            build_approved_context(
                state, 1
            ),
            "approved_context",
        ),
        interpretation=delimit(
            fake_interpretation,
            "reviewed_interpretation",
        ),
    )

    bctx = state.get(
        "business_context", {}
    )
    postmortem_prompt = (
        POSTMORTEM_PROMPT.format(
            chosen_hypothesis=1,
            incident_id=state.get(
                "incident_id", "unknown"
            ),
            severity=state.get(
                "severity", "unknown"
            ),
            severity_reason=state.get(
                "severity_reason", ""
            ),
            service=bctx.get(
                "service", "unknown"
            ),
            tier=bctx.get("tier", "?"),
            customer_facing=bctx.get(
                "customer_facing", False
            ),
            owner=bctx.get(
                "owner", "unknown"
            ),
            approved_context=delimit(
                build_approved_context(
                    state, 1
                ),
                "approved_context",
            ),
            rca_chain=delimit(
                (
                    "## Surface symptom\n"
                    "Payments latency alert.\n\n"
                    "## Systemic root cause\n"
                    "Not established."
                ),
                "rca_chain",
            )
        )
    )

    prompts = {
        "interpretation":
        interpretation_prompt,
        "rca": rca_prompt,
        "postmortem": postmortem_prompt
    }

    failed = False
    for name, prompt in prompts.items():
        chars = len(prompt)
        approx_tokens = chars // 4
        print(
            f"{name}: chars={chars} "
            f"approx_tokens={approx_tokens}"
        )
        if chars > PROMPT_CHAR_BUDGETS[
            name
        ]:
            failed = True
            print(
                f"  over budget: "
                f"{chars}>"
                f"{PROMPT_CHAR_BUDGETS[name]}"
            )

        if "abc041def" in prompt:
            failed = True
            print(
                "  raw log sample leaked into prompt"
            )

    print(
        "evidence_pack: "
        f"chars={len(state.get('evidence_pack', ''))}"
    )
    print(
        "raw_logs_available_for_tools: "
        f"{state.get('raw_log_count', 0)}"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
