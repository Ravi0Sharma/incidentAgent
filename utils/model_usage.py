"""Provider usage, hard incident budgets and a wall-clock deadline."""

from datetime import datetime, timedelta, timezone
import json

from settings import (
    INCIDENT_ANALYSIS_DEADLINE_SECONDS,
    LLM_INPUT_USD_PER_MILLION_TOKENS,
    LLM_MAX_CALLS_PER_INCIDENT,
    LLM_MAX_COST_USD_PER_INCIDENT,
    LLM_MAX_INPUT_TOKENS_PER_INCIDENT,
    LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT,
    LLM_MAX_TOTAL_TOKENS_PER_INCIDENT,
    LLM_OUTPUT_USD_PER_MILLION_TOKENS,
)


MODEL_USAGE_LEDGER_VERSION = "model-usage-ledger/v1"
ANALYSIS_DEADLINE_VERSION = "incident-analysis-deadline/v1"
MODEL_BUDGET_VERSION = "incident-model-budget/v1"


class ModelBudgetExceeded(RuntimeError):
    def __init__(self, reason):
        self.reason = str(reason)
        super().__init__(self.reason)


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None


def initialize_deadline(existing=None, now=None):
    existing = dict(existing or {})
    current = now or _now()
    seconds = max(
        float(
            existing.get(
                "max_elapsed_seconds",
                INCIDENT_ANALYSIS_DEADLINE_SECONDS,
            )
        ),
        1.0,
    )
    started = (
        parse_time(existing.get("started_at"))
        or current
    )
    deadline = (
        parse_time(existing.get("deadline_at"))
        or (started + timedelta(seconds=seconds))
    )
    return {
        "schema_version": ANALYSIS_DEADLINE_VERSION,
        "started_at": _iso(started),
        "deadline_at": _iso(deadline),
        "max_elapsed_seconds": seconds,
    }


def remaining_deadline_seconds(deadline_at, now=None):
    deadline = parse_time(deadline_at)
    if not deadline:
        return None
    return (deadline - (now or _now())).total_seconds()


def _field(value, name, default=0):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _finish_reason(response):
    status = getattr(response, "status", None)
    if status:
        return str(status)[:100]
    choices = getattr(response, "choices", None) or []
    if choices:
        value = getattr(choices[0], "finish_reason", None)
        if value:
            return str(value)[:100]
    return None


def usage_entry(
    response,
    *,
    stage,
    model,
    reservation=None,
    latency_ms=None,
    request_parameters=None,
):
    usage = getattr(response, "usage", None)
    prompt = int(
        _field(
            usage,
            "input_tokens",
            _field(
                usage,
                "prompt_tokens",
                0,
            ),
        )
        or 0
    )
    completion = int(
        _field(
            usage,
            "output_tokens",
            _field(
                usage,
                "completion_tokens",
                0,
            ),
        )
        or 0
    )
    total = int(
        _field(usage, "total_tokens", prompt + completion)
        or (prompt + completion)
    )
    input_rate = LLM_INPUT_USD_PER_MILLION_TOKENS
    output_rate = LLM_OUTPUT_USD_PER_MILLION_TOKENS
    pricing_configured = input_rate > 0 or output_rate > 0
    estimated_cost = (
        (
            prompt * input_rate
            + completion * output_rate
        )
        / 1_000_000
        if pricing_configured
        else None
    )
    return {
        "stage": stage,
        "provider": "openai-compatible",
        "model": model,
        "provider_request_id": getattr(response, "id", None),
        "usage_available": usage is not None,
        "provider_call_made": True,
        "status": "succeeded",
        "finish_reason": _finish_reason(response),
        "latency_ms": latency_ms,
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": total,
        "budget_input_tokens": (
            prompt
            if usage is not None
            else int((reservation or {}).get("input_tokens", 0))
        ),
        "budget_output_tokens": (
            completion
            if usage is not None
            else int((reservation or {}).get("output_tokens", 0))
        ),
        "request_parameters": dict(request_parameters or {}),
        "estimated_cost_usd": (
            round(estimated_cost, 8)
            if estimated_cost is not None
            else None
        ),
        "budget_cost_usd": (
            round(estimated_cost, 8)
            if estimated_cost is not None
            else (reservation or {}).get("estimated_cost_usd")
        ),
        "cost_status": (
            "configured_estimate"
            if pricing_configured
            else "pricing_not_configured"
        ),
    }


def failed_usage_entry(
    *,
    stage,
    model,
    reservation,
    latency_ms=None,
    error_type="provider_error",
    request_parameters=None,
):
    input_tokens = int((reservation or {}).get("input_tokens", 0))
    output_tokens = int((reservation or {}).get("output_tokens", 0))
    estimated_cost = _reservation_cost(input_tokens, output_tokens)
    return {
        "stage": stage,
        "provider": "openai-compatible",
        "model": model,
        "provider_request_id": None,
        "usage_available": False,
        "provider_call_made": True,
        "status": "failed",
        "finish_reason": str(error_type)[:100],
        "latency_ms": latency_ms,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "budget_input_tokens": input_tokens,
        "budget_output_tokens": output_tokens,
        "request_parameters": dict(request_parameters or {}),
        "estimated_cost_usd": estimated_cost,
        "budget_cost_usd": estimated_cost,
        "cost_status": (
            "configured_reservation"
            if estimated_cost is not None
            else "pricing_not_configured"
        ),
    }


def blocked_usage_entry(*, stage, model, reason, request_parameters=None):
    return {
        "stage": stage,
        "provider": "openai-compatible",
        "model": model,
        "provider_request_id": None,
        "usage_available": False,
        "provider_call_made": False,
        "status": "blocked",
        "finish_reason": None,
        "latency_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "budget_input_tokens": 0,
        "budget_output_tokens": 0,
        "request_parameters": dict(request_parameters or {}),
        "estimated_cost_usd": None,
        "budget_cost_usd": 0,
        "cost_status": "not_incurred",
        "stop_reason": str(reason)[:160],
    }


def estimate_input_token_upper_bound(value):
    """A conservative tokenizer-independent upper bound: UTF-8 bytes."""
    if value in (None, "", [], {}):
        return 0
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return len(encoded)


def _reservation_cost(input_tokens, output_tokens):
    if (
        LLM_INPUT_USD_PER_MILLION_TOKENS <= 0
        and LLM_OUTPUT_USD_PER_MILLION_TOKENS <= 0
    ):
        return None
    return round(
        (
            int(input_tokens) * LLM_INPUT_USD_PER_MILLION_TOKENS
            + int(output_tokens) * LLM_OUTPUT_USD_PER_MILLION_TOKENS
        ) / 1_000_000,
        8,
    )


def _budget_totals(existing=None, pending=None):
    calls = list((existing or {}).get("calls", []) or []) + list(pending or [])
    return {
        "call_count": sum(
            1 for item in calls if item.get("provider_call_made", True)
        ),
        "input_tokens": sum(
            int(item.get("budget_input_tokens", item.get("input_tokens", 0)) or 0)
            for item in calls
        ),
        "output_tokens": sum(
            int(item.get("budget_output_tokens", item.get("output_tokens", 0)) or 0)
            for item in calls
        ),
        "cost_usd": round(sum(
            float(
                item.get("budget_cost_usd", item.get("estimated_cost_usd", 0))
                or 0
            )
            for item in calls
        ), 8),
    }


def authorize_model_call(existing, pending, *, input_value, max_output_tokens):
    totals = _budget_totals(existing, pending)
    reserved_input = estimate_input_token_upper_bound(input_value)
    reserved_output = max(int(max_output_tokens or 0), 0)
    projected_input = totals["input_tokens"] + reserved_input
    projected_output = totals["output_tokens"] + reserved_output
    projected_total = projected_input + projected_output
    limits = {
        "max_calls": max(int(LLM_MAX_CALLS_PER_INCIDENT), 0),
        "max_input_tokens": max(int(LLM_MAX_INPUT_TOKENS_PER_INCIDENT), 0),
        "max_output_tokens": max(int(LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT), 0),
        "max_total_tokens": max(int(LLM_MAX_TOTAL_TOKENS_PER_INCIDENT), 0),
        "max_cost_usd": max(float(LLM_MAX_COST_USD_PER_INCIDENT), 0.0),
    }
    if totals["call_count"] >= limits["max_calls"]:
        raise ModelBudgetExceeded("model_call_budget_exhausted")
    if projected_input > limits["max_input_tokens"]:
        raise ModelBudgetExceeded("model_input_token_budget_exhausted")
    if projected_output > limits["max_output_tokens"]:
        raise ModelBudgetExceeded("model_output_token_budget_exhausted")
    if projected_total > limits["max_total_tokens"]:
        raise ModelBudgetExceeded("model_total_token_budget_exhausted")
    reservation_cost = _reservation_cost(reserved_input, reserved_output)
    if limits["max_cost_usd"] > 0:
        if reservation_cost is None:
            raise ModelBudgetExceeded("model_currency_budget_unenforceable")
        if totals["cost_usd"] + reservation_cost > limits["max_cost_usd"]:
            raise ModelBudgetExceeded("model_currency_budget_exhausted")
    return {
        "schema_version": MODEL_BUDGET_VERSION,
        "input_tokens": reserved_input,
        "output_tokens": reserved_output,
        "estimated_cost_usd": reservation_cost,
        "limits": limits,
    }


def append_usage(existing=None, entries=None):
    ledger = dict(existing or {})
    calls = list(ledger.get("calls", []) or [])
    calls.extend(list(entries or []))
    input_tokens = sum(
        int(item.get("input_tokens", 0) or 0)
        for item in calls
    )
    output_tokens = sum(
        int(item.get("output_tokens", 0) or 0)
        for item in calls
    )
    known_costs = [
        item.get("estimated_cost_usd")
        for item in calls
        if item.get("estimated_cost_usd") is not None
    ]
    budget_input_tokens = sum(
        int(item.get("budget_input_tokens", item.get("input_tokens", 0)) or 0)
        for item in calls
    )
    budget_output_tokens = sum(
        int(item.get("budget_output_tokens", item.get("output_tokens", 0)) or 0)
        for item in calls
    )
    budget_costs = [
        item.get("budget_cost_usd", item.get("estimated_cost_usd"))
        for item in calls
        if item.get("budget_cost_usd", item.get("estimated_cost_usd")) is not None
    ]
    limits = {
        "max_calls": max(int(LLM_MAX_CALLS_PER_INCIDENT), 0),
        "max_input_tokens": max(int(LLM_MAX_INPUT_TOKENS_PER_INCIDENT), 0),
        "max_output_tokens": max(int(LLM_MAX_OUTPUT_TOKENS_PER_INCIDENT), 0),
        "max_total_tokens": max(int(LLM_MAX_TOTAL_TOKENS_PER_INCIDENT), 0),
        "max_cost_usd": max(float(LLM_MAX_COST_USD_PER_INCIDENT), 0.0),
    }
    call_count = sum(
        1 for item in calls if item.get("provider_call_made", True)
    )
    budget_total_tokens = budget_input_tokens + budget_output_tokens
    budget_cost = (
        round(sum(float(value) for value in budget_costs), 8)
        if budget_costs
        else None
    )
    stop_reasons = [
        item.get("stop_reason")
        for item in calls
        if item.get("stop_reason")
    ]
    remaining = {
        "calls": max(limits["max_calls"] - call_count, 0),
        "input_tokens": max(
            limits["max_input_tokens"] - budget_input_tokens, 0
        ),
        "output_tokens": max(
            limits["max_output_tokens"] - budget_output_tokens, 0
        ),
        "total_tokens": max(
            limits["max_total_tokens"] - budget_total_tokens, 0
        ),
        "cost_usd": (
            round(max(limits["max_cost_usd"] - (budget_cost or 0), 0), 8)
            if limits["max_cost_usd"] > 0
            else None
        ),
    }
    return {
        "schema_version": MODEL_USAGE_LEDGER_VERSION,
        "calls": calls,
        "call_count": call_count,
        "blocked_call_count": sum(
            1 for item in calls if not item.get("provider_call_made", True)
        ),
        "failed_call_count": sum(
            1 for item in calls if item.get("status") == "failed"
        ),
        "usage_reported_calls": sum(
            1
            for item in calls
            if item.get("usage_available")
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "budget_input_tokens": budget_input_tokens,
        "budget_output_tokens": budget_output_tokens,
        "budget_total_tokens": budget_total_tokens,
        "budget_cost_usd": budget_cost,
        "budget_limits": limits,
        "budget_remaining": remaining,
        "budget_exhausted": bool(stop_reasons),
        "currency_budget_enabled": limits["max_cost_usd"] > 0,
        "stop_reasons": stop_reasons,
        "estimated_cost_usd": (
            round(sum(known_costs), 8)
            if known_costs
            else None
        ),
        "cost_status": (
            "configured_estimate"
            if known_costs
            else "pricing_not_configured"
        ),
    }
