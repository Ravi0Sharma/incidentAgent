from clients.openai_client import (
    LLMProviderError,
    create_completion,
    extract_text
)

from prompts.rca_prompt import (
    PROMPT
)

from settings import (
    OPENAI_MODEL,
    MAX_TOKENS_RCA,
    SKIP_LLM
)

from utils.stub_llm import (
    stub_rca
)
from utils.llm_context import (
    build_approved_context
)
from utils.untrusted_data import delimit
from utils.model_usage import append_usage


def deep_rca(state):

    chosen = state.get(
        "chosen_hypothesis", 1
    )

    if SKIP_LLM:
        return {
            "rca_chain":
            stub_rca(state, chosen)
        }

    prompt = PROMPT.format(
        chosen_hypothesis=chosen,
        approved_context=delimit(
            build_approved_context(
                state, chosen
            ),
            "approved_context",
        ),
        interpretation=delimit(
            state.get("interpretation", ""), "reviewed_interpretation"
        )
    )

    usage_entries = []
    try:
        response = create_completion(
            "rca",
            budget_ledger=state.get("model_usage_ledger"),
            budget_entries=usage_entries,
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=MAX_TOKENS_RCA,
            temperature=0.2
        )
    except LLMProviderError:
        return {
            "rca_chain": stub_rca(state, chosen),
            "model_usage_ledger": append_usage(
                state.get("model_usage_ledger"), usage_entries
            ),
        }

    return {
        "rca_chain": extract_text(response),
        "model_usage_ledger": append_usage(
            state.get("model_usage_ledger"), usage_entries
        ),
    }
