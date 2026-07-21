import json
import re

from clients.openai_client import (
    create_response,
    extract_text,
    response_function_calls,
    response_output_items,
    responses_tools,
)

from prompts.semantic_correlation_prompt import (
    PROMPT
)

from settings import (
    MAX_TOKENS_INTERPRETATION,
    MAX_TOOL_CALLS,
    OPENAI_MODEL,
    SKIP_LLM,
    USE_TOOL_CALLING
)

from utils.correlation_tools import (
    discover_related_services,
    get_log_context,
    get_service_dependencies,
    get_trace,
    search_logs
)

from utils.stub_llm import (
    stub_semantic_correlation
)

from utils.semantic_report import (
    validate_semantic_report,
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "discover_related_services",
            "description": (
                "Discover configured and "
                "observed services in the "
                "incident time window."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_logs",
            "description": (
                "Search bounded logs by "
                "pattern, service and level. "
                "Use only for concrete "
                "checks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string"
                    },
                    "service": {
                        "type": "string"
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_trace",
            "description": (
                "Find log samples for one "
                "trace_id or request_id "
                "across scoped services."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trace_id": {
                        "type": "string"
                    }
                },
                "required": [
                    "trace_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_log_context",
            "description": (
                "Inspect one event_id from "
                "the evidence pack."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string"
                    }
                },
                "required": [
                    "event_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": (
                "get_service_dependencies"
            ),
            "description": (
                "Return owner, tier, "
                "dependencies and related "
                "services."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string"
                    }
                }
            }
        }
    }
]


def _build_prompt(state):

    return PROMPT.format(
        policy_profile=json.dumps(
            (state.get("skill_policy_profiles", {}) or {}).get(
                "semantic", []
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
        feedback_section=delimit(
            state.get("investigation_request")
            or state.get("review_feedback", "(none)"),
            "reviewer_feedback",
        ),
    )


def _extract_json(text):

    if not text:
        raise ValueError(
            "empty semantic correlation response"
        )

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        re.DOTALL
    )
    if not match:
        raise ValueError(
            "semantic correlation response "
            "did not contain JSON"
        )

    return json.loads(
        match.group(0)
    )


def _fallback_report(error, raw=""):

    return {
        "primary_chain": [],
        "alternative_links": [],
        "missing_evidence": [
            (
                "semantic correlation failed: "
                f"{error}"
            )
        ],
        "searches_performed": [],
        "raw_response": raw
    }


def _result_summary(result):

    if not isinstance(result, dict):
        return str(result)[:180]

    if result.get("error"):
        return "error: " + str(
            result.get("error")
        )[:160]

    if "total_matched" in result:
        return (
            f"matched={result.get('total_matched')} "
            f"samples={result.get('sample_count')}"
        )

    if "configured_scope" in result:
        return (
            "configured="
            + ",".join(
                result.get(
                    "configured_scope", []
                )[:5]
            )
        )

    if "dependencies" in result:
        return (
            "dependencies="
            + ",".join(
                result.get(
                    "dependencies", []
                )[:5]
            )
        )

    return json.dumps(
        result,
        default=str
    )[:180]


def _dispatch_tool(state, name, args):

    if name == "discover_related_services":
        return discover_related_services(
            state
        )
    if name == "search_logs":
        return search_logs(
            state,
            pattern=args.get("pattern"),
            service=args.get("service"),
            level=args.get("level")
        )
    if name == "get_trace":
        return get_trace(
            state,
            trace_id=args.get("trace_id")
        )
    if name == "get_log_context":
        return get_log_context(
            state,
            event_id=args.get("event_id")
        )
    if name == "get_service_dependencies":
        return get_service_dependencies(
            state,
            service=args.get("service")
        )

    return {
        "error": f"unknown tool: {name}"
    }


def _run_no_tools(
    prompt,
    deadline_at=None,
    budget_ledger=None,
    usage_entries=None,
):

    usage_entries = usage_entries if usage_entries is not None else []

    response = create_response(
        "semantic_correlation",
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
        max_output_tokens=
        MAX_TOKENS_INTERPRETATION,
        reasoning={"effort": "low"},
        store=False,
    )

    text = extract_text(response)
    return (
        _extract_json(text),
        [],
        usage_entries,
    )


def _run_with_tools(state, prompt, usage_entries=None):

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

    for _ in range(MAX_TOOL_CALLS + 1):

        response = create_response(
            "semantic_correlation",
            deadline_at=deadline_at,
            budget_ledger=budget_ledger,
            budget_entries=usage_entries,
            model=OPENAI_MODEL,
            input=input_items,
            tools=responses_tools(
                TOOLS
            ),
            tool_choice="auto",
            max_output_tokens=
            MAX_TOKENS_INTERPRETATION,
            reasoning={"effort": "low"},
            store=False,
        )
        tool_calls = (
            response_function_calls(
                response
            )
        )

        if not tool_calls:
            text = extract_text(response)
            return (
                _extract_json(text),
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
            except json.JSONDecodeError:
                args = {}

            result = session.run(
                tc.name,
                args,
                _dispatch_tool,
            )
            summary = _result_summary(
                result
            )
            tool_traces.append({
                "tool": tc.name,
                "args": redact_data(args),
                "result_summary": summary,
                "result": redact_data(result),
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

    input_items.append({
        "role": "user",
        "content": (
            "You have used the maximum "
            "allowed tool calls. Return "
            "the final JSON now."
        )
    })

    final = create_response(
        "semantic_correlation",
        deadline_at=deadline_at,
        budget_ledger=budget_ledger,
        budget_entries=usage_entries,
        model=OPENAI_MODEL,
        input=input_items,
        tools=responses_tools(
            TOOLS
        ),
        max_output_tokens=
        MAX_TOKENS_INTERPRETATION,
        reasoning={"effort": "low"},
        store=False,
    )
    return (
        _extract_json(
            extract_text(final)
        ),
        tool_traces,
        session.snapshot(),
        usage_entries,
    )


def _deterministic_only_report(state):
    assessment = state.get("deterministic_assessment", {}) or {}
    return {
        "primary_chain": [],
        "alternative_links": [],
        "missing_evidence": [
            (
                "semantic tool pass skipped: "
                + assessment.get(
                    "expansion_reason",
                    "deterministic evidence was sufficient",
                )
            )
        ],
        "searches_performed": [],
    }


def semantic_correlate(state):

    budget = state.get("investigation_budget", {}) or {}
    if SKIP_LLM:
        report = (
            _deterministic_only_report(state)
            if budget.get("mode") == "deterministic_explanation"
            else stub_semantic_correlation(state)
        )
        return {
            "semantic_correlation":
            validate_semantic_report(report, state, []),
            "semantic_correlation_tool_trace": [],
            "investigation_budget": budget,
        }

    if budget.get("mode") == "deterministic_explanation":
        report = validate_semantic_report(
            _deterministic_only_report(state), state, []
        )
        return {
            "semantic_correlation": report,
            "semantic_correlation_tool_trace": [],
            "investigation_budget": budget,
        }

    prompt = _build_prompt(state)
    usage_entries = []

    try:
        if USE_TOOL_CALLING:
            (
                report,
                trace,
                updated_budget,
                usage_entries,
            ) = _run_with_tools(
                state,
                prompt,
                usage_entries,
            )
        else:
            (
                report,
                trace,
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
    except Exception as exc:
        print(
            "[semantic_correlate] failed; "
            f"falling back to empty report: {exc}"
        )
        report = _fallback_report(exc)
        trace = []
        updated_budget = budget

    report = validate_semantic_report(
        report, state, trace
    )

    return {
        "semantic_correlation": report,
        "semantic_correlation_tool_trace":
        trace,
        "investigation_budget": updated_budget,
        "model_usage_ledger": append_usage(
            state.get("model_usage_ledger"),
            usage_entries,
        ),
    }
