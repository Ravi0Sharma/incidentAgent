import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from clients.openai_client import (
    LLMProviderError,
    create_completion,
    responses_tools,
    reset_circuit,
)
from clients import openai_client
from utils.model_usage import (
    ModelBudgetExceeded,
    append_usage,
    authorize_model_call,
    initialize_deadline,
    remaining_deadline_seconds,
    usage_entry,
)


class ModelUsageTests(unittest.TestCase):
    def tearDown(self):
        reset_circuit()

    @patch(
        "utils.model_usage.LLM_OUTPUT_USD_PER_MILLION_TOKENS",
        0,
    )
    @patch(
        "utils.model_usage.LLM_INPUT_USD_PER_MILLION_TOKENS",
        0,
    )
    def test_provider_reported_tokens_are_recorded_and_totaled(self):
        response = SimpleNamespace(
            id="chatcmpl-1",
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=30,
                total_tokens=150,
            ),
        )
        entry = usage_entry(
            response,
            stage="interpretation",
            model="test-model",
        )
        ledger = append_usage(None, [entry])
        self.assertTrue(entry["usage_available"])
        self.assertEqual(ledger["input_tokens"], 120)
        self.assertEqual(ledger["output_tokens"], 30)
        self.assertEqual(ledger["total_tokens"], 150)
        self.assertEqual(ledger["call_count"], 1)
        self.assertEqual(
            ledger["cost_status"],
            "pricing_not_configured",
        )

    def test_missing_provider_usage_is_explicit_not_estimated(self):
        entry = usage_entry(
            SimpleNamespace(id="local-1", usage=None),
            stage="semantic_correlation",
            model="local-model",
            reservation={
                "input_tokens": 40,
                "output_tokens": 20,
                "estimated_cost_usd": None,
            },
        )
        self.assertFalse(entry["usage_available"])
        self.assertEqual(entry["total_tokens"], 0)
        self.assertEqual(entry["budget_input_tokens"], 40)
        self.assertEqual(entry["budget_output_tokens"], 20)
        self.assertIsNone(entry["estimated_cost_usd"])

    @patch("utils.model_usage.LLM_MAX_CALLS_PER_INCIDENT", 1)
    def test_call_budget_blocks_after_actual_provider_attempt(self):
        existing = append_usage(None, [{
            "provider_call_made": True,
            "status": "succeeded",
            "input_tokens": 1,
            "output_tokens": 1,
            "budget_input_tokens": 1,
            "budget_output_tokens": 1,
        }])
        with self.assertRaisesRegex(
            ModelBudgetExceeded, "model_call_budget_exhausted"
        ):
            authorize_model_call(
                existing, [], input_value="next", max_output_tokens=1
            )

    @patch("utils.model_usage.LLM_MAX_INPUT_TOKENS_PER_INCIDENT", 3)
    def test_input_budget_uses_conservative_preflight_bound(self):
        with self.assertRaisesRegex(
            ModelBudgetExceeded, "model_input_token_budget_exhausted"
        ):
            authorize_model_call(
                None, [], input_value="four", max_output_tokens=0
            )

    @patch("utils.model_usage.LLM_MAX_COST_USD_PER_INCIDENT", 0.000001)
    @patch("utils.model_usage.LLM_OUTPUT_USD_PER_MILLION_TOKENS", 1.0)
    @patch("utils.model_usage.LLM_INPUT_USD_PER_MILLION_TOKENS", 1.0)
    def test_currency_budget_blocks_projected_cost(self):
        with self.assertRaisesRegex(
            ModelBudgetExceeded, "model_currency_budget_exhausted"
        ):
            authorize_model_call(
                None, [], input_value="input", max_output_tokens=10
            )

    @patch("utils.model_usage.LLM_MAX_CALLS_PER_INCIDENT", 0)
    @patch("clients.openai_client.client.responses.create")
    def test_hard_budget_blocks_before_provider_call(self, create):
        entries = []
        with self.assertRaisesRegex(
            LLMProviderError, "model_call_budget_exhausted"
        ):
            openai_client.create_response(
                "interpretation",
                model="test-model",
                input=[{"role": "user", "content": "hello"}],
                max_output_tokens=10,
                budget_entries=entries,
            )
        create.assert_not_called()
        self.assertEqual(entries[0]["status"], "blocked")
        ledger = append_usage(None, entries)
        self.assertTrue(ledger["budget_exhausted"])
        self.assertEqual(ledger["call_count"], 0)
        self.assertEqual(ledger["blocked_call_count"], 1)
        self.assertIn(
            "model_call_budget_exhausted", ledger["stop_reasons"]
        )

    @patch("clients.openai_client.LLM_RETRY_BACKOFF_SECONDS", 0)
    @patch("clients.openai_client.LLM_RETRY_ATTEMPTS", 1)
    @patch("clients.openai_client.client.responses.create")
    def test_each_failed_retry_is_reserved_and_counted(self, create):
        create.side_effect = RuntimeError("unavailable")
        entries = []
        with self.assertRaises(LLMProviderError):
            openai_client.create_response(
                "interpretation",
                model="test-model",
                input=[{"role": "user", "content": "hello"}],
                max_output_tokens=10,
                budget_entries=entries,
            )
        self.assertEqual(create.call_count, 2)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(item["status"] == "failed" for item in entries))
        ledger = append_usage(None, entries)
        self.assertEqual(ledger["call_count"], 2)
        self.assertEqual(ledger["failed_call_count"], 2)

    def test_responses_usage_and_tool_translation_are_supported(
        self,
    ):
        entry = usage_entry(
            SimpleNamespace(
                id="resp-1",
                usage=SimpleNamespace(
                    input_tokens=90,
                    output_tokens=20,
                    total_tokens=110,
                ),
            ),
            stage="interpretation",
            model="test-model",
        )
        self.assertEqual(
            entry["input_tokens"], 90
        )
        self.assertEqual(
            entry["output_tokens"], 20
        )
        tools = responses_tools([{
            "type": "function",
            "function": {
                "name": "search_logs",
                "description":
                "Search logs",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        }])
        self.assertEqual(
            tools[0]["name"],
            "search_logs",
        )
        self.assertFalse(
            tools[0]["strict"]
        )
        self.assertNotIn(
            "function", tools[0]
        )

    def test_deadline_contract_is_stable_and_reports_remaining_time(self):
        now = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)
        deadline = initialize_deadline(
            {"max_elapsed_seconds": 60},
            now=now,
        )
        self.assertEqual(
            deadline["schema_version"],
            "incident-analysis-deadline/v1",
        )
        remaining = remaining_deadline_seconds(
            deadline["deadline_at"],
            now=now,
        )
        self.assertEqual(remaining, 60)

    @patch("clients.openai_client.client.responses.create")
    def test_expired_incident_deadline_blocks_provider_call(self, create):
        with self.assertRaises(LLMProviderError):
            create_completion(
                "interpretation",
                deadline_at="2000-01-01T00:00:00Z",
                model="test-model",
                messages=[],
            )
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
