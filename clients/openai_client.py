import time

from openai import OpenAI

from settings import (
    OPENAI_BASE_URL,
    OPENAI_API_KEY,
    LLM_CIRCUIT_OPEN_SECONDS,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_BACKOFF_SECONDS,
    LLM_TIMEOUT_SECONDS,
    PROMPT_VERSION,
)
from utils.model_usage import (
    ModelBudgetExceeded,
    authorize_model_call,
    blocked_usage_entry,
    failed_usage_entry,
    remaining_deadline_seconds,
    usage_entry,
)


client = OpenAI(
    base_url=OPENAI_BASE_URL,
    api_key=OPENAI_API_KEY,
    timeout=LLM_TIMEOUT_SECONDS,
    max_retries=0,
)

_CIRCUIT = {"opened_until": 0.0}


class LLMProviderError(RuntimeError):
    pass


def reset_circuit():
    _CIRCUIT["opened_until"] = 0.0


def create_response(
    stage,
    *,
    deadline_at=None,
    budget_ledger=None,
    budget_entries=None,
    **kwargs,
):
    """One bounded policy for every Responses API request."""
    now = time.monotonic()
    if _CIRCUIT["opened_until"] > now:
        raise LLMProviderError(f"{stage}: provider circuit is open")

    last_error = None
    for attempt in range(LLM_RETRY_ATTEMPTS + 1):
        remaining = remaining_deadline_seconds(deadline_at)
        if remaining is not None and remaining <= 0:
            raise LLMProviderError(
                f"{stage}: incident analysis deadline exhausted"
            )
        request_timeout = (
            min(LLM_TIMEOUT_SECONDS, max(remaining, 0.001))
            if remaining is not None
            else LLM_TIMEOUT_SECONDS
        )
        parameters = {
            "max_output_tokens": int(kwargs.get("max_output_tokens", 0) or 0),
            "tool_count": len(kwargs.get("tools", []) or []),
            "store": bool(kwargs.get("store", False)),
            "reasoning_effort": (
                kwargs.get("reasoning", {}) or {}
            ).get("effort"),
            "prompt_version": PROMPT_VERSION,
            "retry_index": attempt,
        }
        try:
            reservation = authorize_model_call(
                budget_ledger,
                budget_entries,
                input_value=kwargs.get("input"),
                max_output_tokens=kwargs.get("max_output_tokens", 0),
            )
        except ModelBudgetExceeded as exc:
            if budget_entries is not None:
                budget_entries.append(blocked_usage_entry(
                    stage=stage,
                    model=kwargs.get("model"),
                    reason=exc.reason,
                    request_parameters=parameters,
                ))
            raise LLMProviderError(f"{stage}: {exc.reason}") from exc
        started = time.monotonic()
        try:
            response = client.responses.create(
                timeout=request_timeout,
                **kwargs,
            )
            if budget_entries is not None:
                budget_entries.append(usage_entry(
                    response,
                    stage=stage,
                    model=kwargs.get("model"),
                    reservation=reservation,
                    latency_ms=round((time.monotonic() - started) * 1000, 3),
                    request_parameters=parameters,
                ))
            reset_circuit()
            return response
        except Exception as exc:
            last_error = exc
            if budget_entries is not None:
                budget_entries.append(failed_usage_entry(
                    stage=stage,
                    model=kwargs.get("model"),
                    reservation=reservation,
                    latency_ms=round((time.monotonic() - started) * 1000, 3),
                    error_type=type(exc).__name__,
                    request_parameters=parameters,
                ))
            if attempt < LLM_RETRY_ATTEMPTS:
                time.sleep(LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))

    _CIRCUIT["opened_until"] = time.monotonic() + LLM_CIRCUIT_OPEN_SECONDS
    raise LLMProviderError(f"{stage}: provider request failed") from last_error


def responses_tools(tools):
    """Translate legacy Chat function declarations to Responses tools."""
    translated = []
    for tool in tools or []:
        function = (
            tool.get("function", {})
            if isinstance(tool, dict)
            else {}
        )
        if (
            tool.get("type")
            != "function"
            or not function
        ):
            translated.append(tool)
            continue
        translated.append({
            "type": "function",
            "name": function.get("name"),
            "description":
            function.get("description"),
            "parameters":
            function.get(
                "parameters", {}
            ),
            "strict": False,
        })
    return translated


def response_function_calls(response):
    return [
        item
        for item in (
            getattr(
                response, "output", []
            )
            or []
        )
        if getattr(
            item, "type", None
        )
        == "function_call"
    ]


def response_output_items(response):
    """Return SDK output items unchanged so reasoning context is preserved."""
    return list(
        getattr(
            response, "output", []
        )
        or []
    )


def create_completion(
    stage,
    *,
    deadline_at=None,
    **kwargs,
):
    """Compatibility wrapper for simple, non-tool legacy callers."""
    messages = kwargs.pop(
        "messages", []
    )
    max_tokens = kwargs.pop(
        "max_tokens", None
    )
    kwargs.pop(
        "temperature", None
    )
    tools = kwargs.pop(
        "tools", None
    )
    if tools:
        kwargs["tools"] = (
            responses_tools(tools)
        )
    if max_tokens is not None:
        kwargs[
            "max_output_tokens"
        ] = max_tokens
    return create_response(
        stage,
        deadline_at=deadline_at,
        budget_ledger=kwargs.pop("budget_ledger", None),
        budget_entries=kwargs.pop("budget_entries", None),
        input=messages,
        store=False,
        **kwargs,
    )


def extract_text(response):
    output_text = getattr(
        response,
        "output_text",
        None,
    )
    if output_text:
        return str(output_text)

    msg = (
        response
        .choices[0]
        .message
    )

    content = getattr(
        msg, "content", None
    ) or ""

    if content.strip():
        return content

    reasoning = getattr(
        msg,
        "reasoning_content",
        None
    ) or ""

    return reasoning
