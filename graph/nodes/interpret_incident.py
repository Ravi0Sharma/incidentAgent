import json

from clients.openai_client import (
    LLMProviderError,
    create_response,
    extract_text,
    response_function_calls,
    response_output_items,
    responses_tools,
)

from prompts.interpretation_prompt import (
    PROMPT
)

from settings import (
    OPENAI_MODEL,
    MAX_TOKENS_INTERPRETATION,
    MAX_TOOL_CALLS,
    USE_TOOL_CALLING,
    SKIP_LLM
)

from utils.correlation_tools import (
    search_logs as scoped_search_logs,
)

from utils.interpretation_contract import (
    abstention_payload,
    deterministic_payload,
    extract_interpretation_json,
    render_grounded_interpretation,
    validate_and_ground,
)

from utils.tool_budget import (
    ToolSession,
)

from utils.llm_context import (
    budget_summary,
)
from utils.model_usage import (
    append_usage,
)
from utils.untrusted_data import delimit
from utils.redaction import redact_data


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_logs",
        "description": (
            "Search bounded incident "
            "logs by literal pattern, "
            "service, or level. Returns "
            "up to 10 sample matches "
            "and total count. Use only "
            "to strengthen or eliminate "
            "a specific hypothesis."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Literal pattern "
                        "(case-insensitive)"
                    )
                },
                "service": {
                    "type": "string",
                    "description": (
                        "Filter by "
                        "service label"
                    )
                },
                "level": {
                    "type": "string",
                    "enum": [
                        "error",
                        "warn",
                        "info",
                        "debug"
                    ]
                }
            }
        }
    }
}


def _build_prompt(state):

    feedback = state.get(
        "review_feedback", ""
    )

    if feedback:
        feedback_section = (
            "IMPORTANT: your previous "
            "interpretation was "
            "rejected by the on-call "
            "reviewer with this "
            f"feedback:\n\n{delimit(feedback, 'reviewer_feedback')}\n\n"
            "Rewrite the interpretation "
            "addressing this feedback."
        )
    else:
        feedback_section = ""

    return PROMPT.format(
        policy_profile=json.dumps(
            (state.get("skill_policy_profiles", {}) or {}).get(
                "interpretation", []
            ),
            ensure_ascii=False,
        ),
        decision_brief=delimit(
            state.get("decision_brief", {}), "decision_brief"
        ),
        tool_budget=json.dumps(
            budget_summary(
                state.get("investigation_budget", {})
            ),
            default=str,
            ensure_ascii=False,
        ),
        semantic_correlation=delimit(
            _semantic_summary(state), "semantic_correlation"
        ),
        max_tool_calls=(
            MAX_TOOL_CALLS
        ),
        feedback_section=(
            feedback_section
        )
    )


def _semantic_summary(state):
    report = state.get("semantic_correlation", {}) or {}
    return {
        "primary_chain": report.get("primary_chain", [])[:2],
        "alternative_links": report.get("alternative_links", [])[:2],
        "missing_evidence": report.get("missing_evidence", [])[:3],
        "tool_summary": [
            {
                "tool": item.get("tool"),
                "result_summary": item.get("result_summary"),
            }
            for item in report.get("searches_performed", [])[:3]
        ],
    }


def _abstention_interpretation(state):
    assessment = state.get("deterministic_assessment", {}) or {}
    reasons = assessment.get("abstain_reasons", []) or [
        "available evidence does not support a root-cause claim"
    ]
    window = (state.get("incident_window", {}) or {}).get("start", "unknown")
    return (
        "## TL;DR\n\n"
        "No supported root cause yet.\n\n"
        "## Evidence gaps\n\n- " + "\n- ".join(reasons) + "\n\n"
        "## Suggested next steps\n\n"
        "Verify the incident window (starting " + str(window) + ") and collect the "
        "smallest missing source or discriminating trace before proposing remediation."
    )


def _run_no_tools(
    prompt,
    deadline_at=None,
    budget_ledger=None,
    usage_entries=None,
):

    usage_entries = usage_entries if usage_entries is not None else []

    response = (
        create_response(
            "interpretation",
            deadline_at=deadline_at,
            budget_ledger=budget_ledger,
            budget_entries=usage_entries,
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_output_tokens=(
                MAX_TOKENS_INTERPRETATION
            ),
            reasoning={"effort": "low"},
            store=False,
        )
    )

    return (
        extract_text(response),
        [],
        usage_entries,
    )


def _dispatch_tool(state, name, args):

    if name != "search_logs":
        return {
            "error":
            f"unknown tool: {name}"
        }

    return scoped_search_logs(
        state,
        pattern=args.get("pattern"),
        service=args.get("service"),
        level=args.get("level")
    )


def _run_with_tools(prompt, state, usage_entries=None):

    input_items = [
        {
            "role": "user",
            "content": prompt
        }
    ]

    tool_traces = []
    remaining_calls = MAX_TOOL_CALLS
    session = ToolSession(state)
    usage_entries = usage_entries if usage_entries is not None else []
    budget_ledger = state.get("model_usage_ledger")
    deadline_at = (
        state.get("analysis_deadline", {})
        or {}
    ).get("deadline_at")

    for _ in range(
        MAX_TOOL_CALLS + 1
    ):

        try:
            response = (
                create_response(
                    "interpretation",
                    deadline_at=deadline_at,
                    budget_ledger=budget_ledger,
                    budget_entries=usage_entries,
                    model=OPENAI_MODEL,
                    input=input_items,
                    tools=responses_tools(
                        [SEARCH_TOOL]
                    ),
                    tool_choice=(
                        "auto"
                    ),
                    max_output_tokens=(
                        MAX_TOKENS_INTERPRETATION
                    ),
                    reasoning={
                        "effort": "low"
                    },
                    store=False,
                )
            )
        except Exception as e:
            if (
                isinstance(e, LLMProviderError)
                and "model_" in str(e)
                and "_budget_" in str(e)
            ):
                raise
            print(
                "[interpret_incident] "
                "tool calling not "
                "supported by model "
                f"({e}); falling back."
            )
            text, traces, _ = _run_no_tools(
                prompt,
                deadline_at,
                budget_ledger,
                usage_entries,
            )
            return (
                text,
                traces,
                session.snapshot(),
                usage_entries,
            )

        tool_calls = (
            response_function_calls(
                response
            )
        )

        if not tool_calls:
            return (
                extract_text(response),
                tool_traces,
                session.snapshot(),
                usage_entries,
            )

        selected_calls = tool_calls[:remaining_calls]
        input_items.extend(
            response_output_items(
                response
            )
        )

        for tc in selected_calls:

            try:
                args = json.loads(
                    tc.arguments
                    or "{}"
                )
            except (
                json.JSONDecodeError
            ):
                args = {}

            result = session.run(
                tc.name,
                args,
                _dispatch_tool,
            )

            tool_traces.append({
                "name":
                tc.name,
                "args": redact_data(args),
                "matched":
                result.get(
                    "total_matched"
                )
            })

            input_items.append({
                "type":
                "function_call_output",
                "call_id":
                tc.call_id,
                "output":
                delimit(
                    result,
                    "tool_result",
                ),
            })
            remaining_calls -= 1

        if remaining_calls <= 0:
            break

    print(
        "[interpret_incident] "
        "hit MAX_TOOL_CALLS, "
        "requesting final answer."
    )

    input_items.append({
        "role": "user",
        "content": (
            "You have used the "
            "maximum allowed searches. "
            "Produce the final "
            "interpretation now using "
            "the required output "
            "format."
        )
    })

    final = (
        create_response(
            "interpretation",
        deadline_at=deadline_at,
        budget_ledger=budget_ledger,
        budget_entries=usage_entries,
            model=OPENAI_MODEL,
            input=input_items,
            tools=responses_tools(
                [SEARCH_TOOL]
            ),
            max_output_tokens=(
                MAX_TOKENS_INTERPRETATION
            ),
            reasoning={"effort": "low"},
            store=False,
        )
    )
    return (
        extract_text(final),
        tool_traces,
        session.snapshot(),
        usage_entries,
    )


def interpret_incident(state):

    assessment = state.get("deterministic_assessment", {}) or {}
    if assessment.get("abstain"):
        structured, grounding = validate_and_ground(
            abstention_payload(
                "deterministic assessment requires abstention",
                state,
            ),
            state,
        )
        text = render_grounded_interpretation(
            structured,
            state,
        )
        return {
            "interpretation": text,
            "interpretation_structured": structured,
            "claim_grounding": grounding,
            "interpretation_attempts": state.get("interpretation_attempts", 0) + 1,
            "interpretation_tool_trace": [{"status": "abstained"}],
            "interpretation_quality": {
                "passed": True,
                "abstained": True,
                "warnings": grounding.get("warnings", []),
                "schema_version": grounding.get("schema_version"),
            },
        }

    if SKIP_LLM:
        attempts = state.get(
            "interpretation_attempts", 0
        ) + 1
        structured, grounding = validate_and_ground(
            deterministic_payload(
                state,
                limitation=(
                    "LLM was skipped; this review was rendered "
                    "from deterministic candidates."
                ),
            ),
            state,
        )
        text = render_grounded_interpretation(
            structured,
            state,
        )
        quality = {
            "passed": grounding.get("passed", False),
            "abstained": grounding.get("abstained", False),
            "warnings": grounding.get("warnings", []),
            "schema_version": grounding.get("schema_version"),
            "deterministic_only": True,
        }
        return {
            "interpretation":
            text,
            "interpretation_structured": structured,
            "claim_grounding": grounding,
            "interpretation_attempts":
            attempts,
            "interpretation_tool_trace":
            [],
            "interpretation_quality": quality,
        }

    prompt = _build_prompt(state)

    budget = state.get("investigation_budget", {}) or {}
    remaining_units = (
        budget.get("max_remote_units", 0)
        - budget.get("used_remote_units", 0)
    )
    usage_entries = []
    try:
        if USE_TOOL_CALLING and remaining_units > 0:
            (
                text,
                traces,
                updated_budget,
                usage_entries,
            ) = _run_with_tools(prompt, state, usage_entries)
        else:
            (
                text,
                traces,
                usage_entries,
            ) = _run_no_tools(
                prompt,
                (
                    state.get(
                        "analysis_deadline",
                        {},
                    )
                    or {}
                ).get("deadline_at"),
                state.get("model_usage_ledger"),
                usage_entries,
            )
            updated_budget = budget
    except LLMProviderError as exc:
        text = ""
        traces = [{"status": "degraded", "reason": str(exc)}]
        updated_budget = budget

    model_text_available = bool(
        text
    )
    provider_degraded = any(
        isinstance(item, dict)
        and item.get("status")
        == "degraded"
        for item in traces
    )
    parse_warning = None
    if text:
        try:
            payload = extract_interpretation_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            parse_warning = str(exc)
            payload = abstention_payload(
                "model output failed the typed JSON contract",
                state,
            )
    else:
        payload = deterministic_payload(
            state,
            limitation=(
                "Model provider was unavailable; this review "
                "contains deterministic candidates only."
            ),
        )
    structured, grounding = validate_and_ground(
        payload,
        state,
    )
    if parse_warning:
        grounding.setdefault("warnings", []).append(
            parse_warning
        )
        grounding["passed"] = False
    text = render_grounded_interpretation(
        structured,
        state,
    )
    quality = {
        "passed": grounding.get("passed", False),
        "abstained": grounding.get("abstained", False),
        "warnings": grounding.get("warnings", []),
        "schema_version": grounding.get("schema_version"),
        "typed_output": True,
        "provider_degraded":
        provider_degraded,
        "deterministic_only": (
            not model_text_available
        ),
    }
    attempts = state.get(
        "interpretation_attempts", 0
    ) + 1

    return {
        "interpretation": text,
        "interpretation_structured": structured,
        "claim_grounding": grounding,
        "interpretation_attempts":
        attempts,
        "interpretation_tool_trace":
        traces,
        "interpretation_quality": quality,
        "investigation_budget": updated_budget,
        "model_usage_ledger": append_usage(
            state.get("model_usage_ledger"),
            usage_entries,
        ),
    }
