from clients.openai_client import (
    LLMProviderError,
    create_completion,
    extract_text
)

from prompts.postmortem_prompt import (
    PROMPT
)

from settings import (
    OPENAI_MODEL,
    MAX_TOKENS_POSTMORTEM,
    SKIP_LLM
)

from utils.stub_llm import (
    stub_postmortem
)
from utils.llm_context import (
    build_approved_context
)
from utils.untrusted_data import delimit
from utils.model_usage import append_usage


def draft_postmortem(state):

    chosen = state.get(
        "chosen_hypothesis", 1
    )

    bctx = state.get(
        "business_context", {}
    )

    if SKIP_LLM:
        return {
            "postmortem_draft":
            stub_postmortem(
                state, chosen
            )
        }

    prompt = PROMPT.format(
        chosen_hypothesis=chosen,
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
                state, chosen
            ),
            "approved_context",
        ),
        rca_chain=delimit(
            state.get("rca_chain", "(no 5-Whys available)"), "rca_chain"
        )
    )

    usage_entries = []
    try:
        response = create_completion(
            "postmortem",
            budget_ledger=state.get("model_usage_ledger"),
            budget_entries=usage_entries,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=(
                MAX_TOKENS_POSTMORTEM
            ),
            temperature=0.2
        )
    except LLMProviderError:
        return {
            "postmortem_draft": stub_postmortem(state, chosen),
            "model_usage_ledger": append_usage(
                state.get("model_usage_ledger"), usage_entries
            ),
        }

    return {
        "postmortem_draft": extract_text(response),
        "model_usage_ledger": append_usage(
            state.get("model_usage_ledger"), usage_entries
        ),
    }
