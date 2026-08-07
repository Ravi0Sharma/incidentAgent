"""Shared remote-query budget and compact cache for both LLM nodes."""

import json

from utils.investigation_loop import (
    elapsed_seconds,
    initialize_loop,
    result_size_bytes,
)
from utils.model_usage import remaining_deadline_seconds
from utils.redaction import redact_data


TOOL_ARGUMENT_POLICY = {
    "discover_related_services": {},
    "search_logs": {
        "pattern": ("string", 240, None),
        "service": ("string", 128, None),
        "level": ("string", 16, {"error", "warn", "info", "debug"}),
    },
    "get_trace": {
        "trace_id": ("string", 128, None),
    },
    "get_log_context": {
        "event_id": ("string", 255, None),
    },
    "get_service_dependencies": {
        "service": ("string", 128, None),
    },
}


def validate_tool_request(name, args):
    """Fail closed before an LLM-selected tool can reach a connector."""
    if name not in TOOL_ARGUMENT_POLICY:
        return None, "tool is not allowlisted"
    if not isinstance(args, dict):
        return None, "tool arguments must be an object"
    policy = TOOL_ARGUMENT_POLICY[name]
    unexpected = sorted(set(args) - set(policy))
    if unexpected:
        return None, "unexpected tool arguments: " + ", ".join(unexpected[:3])
    normalized = {}
    for key, value in args.items():
        if value is None:
            continue
        expected_type, max_length, allowed = policy[key]
        if expected_type == "string" and not isinstance(value, str):
            return None, f"tool argument {key} must be a string"
        if len(value) > max_length:
            return None, f"tool argument {key} exceeds {max_length} characters"
        if allowed is not None and value.lower() not in allowed:
            return None, f"tool argument {key} is outside the allowed enum"
        normalized[key] = value.lower() if allowed is not None else value
    return normalized, None


def _cache_key(name, args):
    return name + ":" + json.dumps(
        args or {}, sort_keys=True, default=str
    )


def remote_cost(state, name, args):
    if name in {
        "discover_related_services",
        "get_log_context",
        "get_service_dependencies",
    }:
        return 0
    if name == "get_trace":
        scope = state.get("scope_expansion", {}) or {}
        related = [
            service for service in scope.get("services", [])
            if service != scope.get("alert_service")
        ]
        return min(len(related), 2)
    if name == "search_logs":
        scope = state.get("scope_expansion", {}) or {}
        service = (args or {}).get("service")
        return 0 if not service or service == scope.get("alert_service") else 1
    return 1


def compact_result(result):
    result = result if isinstance(result, dict) else {"result": str(result)}
    compact = {
        key: value
        for key, value in result.items()
        if key not in {"sample", "raw_samples", "services_checked"}
    }
    if result.get("sample"):
        sample_provenance = (
            result.get(
                "provenance", {}
            )
            or {}
        )
        compact["sample"] = [
            {
                "timestamp": item.get("timestamp"),
                "labels": item.get("labels", {}),
                "message": str(item.get("message", ""))[:240],
                "connector_metadata": (
                    item.get(
                        "connector_metadata"
                    )
                    or sample_provenance
                ),
            }
            for item in result["sample"][:3]
        ]
    if result.get("raw_samples"):
        compact["raw_samples"] = result["raw_samples"][:3]
    if result.get("services_checked"):
        compact["services_checked"] = [
            {
                "service": item.get("service"),
                "total_matched": item.get("total_matched"),
                "error": item.get("error"),
                "provenance":
                item.get("provenance"),
                "sample": [
                    {
                        "timestamp": sample.get(
                            "timestamp"
                        ),
                        "labels": sample.get(
                            "labels", {}
                        ),
                        "message": str(
                            sample.get(
                                "message", ""
                            )
                        )[:240],
                        "connector_metadata":
                        (
                            sample.get(
                                "connector_metadata"
                            )
                            or item.get(
                                "provenance"
                            )
                            or {}
                        ),
                    }
                    for sample in (
                        item.get(
                            "sample", []
                        )
                        or []
                    )[:2]
                ],
            }
            for item in result["services_checked"][:3]
        ]
    return redact_data(compact)


class ToolSession:
    def __init__(self, state):
        self.state = state
        self.budget = dict(state.get("investigation_budget", {}) or {})
        self.budget.setdefault("max_remote_units", 0)
        self.budget.setdefault("used_remote_units", 0)
        self.budget.setdefault("tool_cache", {})
        self.budget.setdefault("tool_history", [])
        self.budget["expansion_loop"] = initialize_loop(
            self.budget.get("expansion_loop")
        )

    def run(self, name, args, dispatch):
        args, policy_error = validate_tool_request(name, args or {})
        if policy_error:
            safe_args = args if isinstance(args, dict) else {}
            self._record(name, safe_args, 0, "policy_blocked", 0)
            return {
                "error": "tool policy violation",
                "reason": policy_error,
            }
        loop = self.budget["expansion_loop"]
        incident_remaining = remaining_deadline_seconds(
            (
                self.state.get("analysis_deadline", {})
                or {}
            ).get("deadline_at")
        )
        if (
            incident_remaining is not None
            and incident_remaining <= 0
        ):
            result = {
                "error": "incident analysis deadline exhausted",
            }
            self._record(name, args, 0, "blocked", 0)
            return result
        elapsed = elapsed_seconds(loop)
        loop["elapsed_seconds"] = round(elapsed, 3)
        if loop.get("stop_reason") and loop.get("round", 0) > 0:
            result = {
                "error": "investigation loop already stopped",
                "stop_reason": loop.get("stop_reason"),
            }
            self._record(name, args, 0, "blocked", 0)
            return result
        if elapsed >= loop["max_elapsed_seconds"]:
            result = {
                "error": "elapsed investigation budget exhausted",
                "max_elapsed_seconds": loop["max_elapsed_seconds"],
            }
            self._record(name, args, 0, "blocked", 0)
            return result

        key = _cache_key(name, args)
        cached = self.budget["tool_cache"].get(key)
        if cached is not None:
            result = cached.get("result", cached)
            self._record(name, args, 0, "cache", 0)
            return result

        cost = remote_cost(self.state, name, args)
        remaining = (
            self.budget["max_remote_units"]
            - self.budget["used_remote_units"]
        )
        if cost > remaining:
            result = {
                "error": "remote query budget exhausted",
                "required_units": cost,
                "remaining_units": max(remaining, 0),
            }
            self._record(name, args, 0, "blocked", 0)
            return result

        service = args.get("service")
        scope = self.state.get("scope_expansion", {}) or {}
        allowed = list(scope.get("services", []) or [])
        if len(allowed) > loop["max_services"]:
            allowed = allowed[:loop["max_services"]]
        if service and allowed and service not in allowed:
            result = {
                "error": "service is outside the bounded incident scope",
                "service": service,
            }
            self._record(name, args, 0, "blocked", 0)
            return result

        result = dispatch(self.state, name, args)
        compact = compact_result(result)
        size = result_size_bytes(compact)
        remaining_bytes = (
            loop["max_result_bytes"]
            - loop["used_result_bytes"]
        )
        if size > remaining_bytes:
            loop["used_result_bytes"] = loop["max_result_bytes"]
            result = {
                "error": "result byte budget exhausted",
                "result_bytes": size,
                "remaining_bytes": max(remaining_bytes, 0),
            }
            self.budget["used_remote_units"] += cost
            self._record(name, args, cost, "blocked", size)
            return result

        self.budget["used_remote_units"] += cost
        loop["used_result_bytes"] += size
        if len(self.budget["tool_cache"]) < 16:
            self.budget["tool_cache"][key] = {
                "result": compact,
            }
        self._record(name, args, cost, "executed", size)
        return compact

    def _record(self, name, args, cost, status, result_bytes):
        history = self.budget["tool_history"]
        if len(history) < 20:
            history.append({
                "tool": name,
                "args": redact_data(args),
                "remote_units": cost,
                "result_bytes": result_bytes,
                "status": status,
            })

    def snapshot(self):
        return self.budget
