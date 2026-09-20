"""
agents/test_agent_scenarios.py

Three required test scenarios for the AML Compliance Investigation Agent,
run with the Groq client and the MCP tool dispatcher both mocked — no API
key, no Supabase connection, and no network access needed. This tests the
agent LOOP itself (does it call the right tools, does it stop correctly,
does it gate the risk-update tool, does it handle a parse failure) rather
than the quality of any particular model's reasoning.

Run with:
    python -m unittest agents/test_agent_scenarios.py -v
or:
    pytest agents/test_agent_scenarios.py -v

For a real end-to-end check against live Groq + your Supabase data, use
the Streamlit "🤖 AI Investigation Agent" tab directly with a real
GROQ_API_KEY configured — that's the true integration test; this file
verifies the control flow around it.
"""

from __future__ import annotations

import json
import types
import unittest
from unittest.mock import patch

from agents.agent_models import InvestigationResult


def _fake_tool_call(call_id: str, name: str, arguments: dict):
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _fake_completion(content: str | None = None, tool_calls: list | None = None):
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


class _FakeGroqClient:
    """Returns pre-scripted completions in order, one per call to
    chat.completions.create, ignoring the actual messages sent (this test
    is about the agent loop's control flow, not model quality)."""

    def __init__(self, scripted_completions: list):
        self._queue = list(scripted_completions)
        self.calls = 0

        class _Completions:
            def create(inner_self, **kwargs):
                self.calls += 1
                if not self._queue:
                    raise AssertionError("Fake Groq client ran out of scripted completions")
                return self._queue.pop(0)

        self.chat = types.SimpleNamespace(completions=_Completions())


def _run_with_mocks(scripted_completions, tool_side_effect):
    """Runs run_investigation() with Groq and the MCP dispatcher mocked,
    collecting all yielded AgentStep events plus the final result."""
    from agents import aml_investigation_agent as agent_mod

    fake_client = _FakeGroqClient(scripted_completions)

    with patch.object(agent_mod, "_get_groq_client", return_value=fake_client), \
         patch.object(agent_mod, "call_tool", side_effect=tool_side_effect):
        events = list(agent_mod.run_investigation("CUST-TEST", "Investigate this customer."))

    steps = [e for e in events if not isinstance(e, InvestigationResult)]
    result = events[-1]
    assert isinstance(result, InvestigationResult)
    return steps, result


class TestNormalCustomerScenario(unittest.TestCase):
    """Scenario 1: normal activity -> LOW risk, no policy lookup needed."""

    def test_low_risk_no_flags(self):
        final_json = json.dumps({
            "risk_level": "LOW",
            "insufficient_information": False,
            "suspicious_patterns": [],
            "evidence": ["3 transactions, largest $850, all domestic."],
            "policy_references": [],
            "analysis": "Transaction volume and pattern are unremarkable for this customer profile.",
            "recommended_action": "No action required.",
            "risk_update_recommendation": None,
        })

        completions = [
            _fake_completion(tool_calls=[_fake_tool_call("call_1", "get_customer_transactions", {"customer_id": "CUST-TEST"})]),
            _fake_completion(content=final_json),
        ]

        def tool_side_effect(name, **kwargs):
            self.assertEqual(name, "get_customer_transactions")
            return {
                "customer": {"external_id": "CUST-TEST", "full_name": "Jane Normal"},
                "transactions": [{"transaction_id": "T1", "amount": 850, "currency": "USD"}],
                "transaction_count": 1,
            }

        steps, result = _run_with_mocks(completions, tool_side_effect)

        self.assertEqual(result.risk_level, "LOW")
        self.assertFalse(result.insufficient_information)
        self.assertIsNone(result.risk_update_recommendation)
        tool_call_steps = [s for s in steps if s.kind == "tool_call"]
        self.assertEqual(len(tool_call_steps), 1)
        self.assertEqual(tool_call_steps[0].tool_name, "get_customer_transactions")


class TestSuspiciousCustomerScenario(unittest.TestCase):
    """Scenario 2: structuring pattern -> policy lookup -> HIGH risk with a
    gated risk-update recommendation that must NOT be executed automatically."""

    def test_high_risk_with_gated_update(self):
        final_json = json.dumps({
            "risk_level": "HIGH",
            "insufficient_information": False,
            "suspicious_patterns": ["Multiple transactions just under $10,000 within days of each other."],
            "evidence": ["TXN-101: $9,400", "TXN-102: $9,600", "TXN-103: $9,800"],
            "policy_references": ["AML_Policy.pdf, p. 4: structuring definition"],
            "analysis": "The pattern of near-threshold transactions is consistent with structuring as defined in policy.",
            "recommended_action": "Escalate for manual SAR review.",
            "risk_update_recommendation": {"risk_level": "HIGH", "reason": "Suspected structuring pattern."},
        })

        completions = [
            _fake_completion(tool_calls=[_fake_tool_call("call_1", "get_customer_transactions", {"customer_id": "CUST-TEST"})]),
            _fake_completion(tool_calls=[_fake_tool_call("call_2", "search_policy_docs", {"query": "structuring thresholds"})]),
            _fake_completion(tool_calls=[_fake_tool_call(
                "call_3", "update_customer_risk_score",
                {"customer_id": "CUST-TEST", "risk_level": "HIGH", "reason": "Suspected structuring pattern."},
            )]),
            _fake_completion(content=final_json),
        ]

        calls_made = []

        def tool_side_effect(name, **kwargs):
            calls_made.append(name)
            if name == "get_customer_transactions":
                return {
                    "customer": {"external_id": "CUST-TEST", "full_name": "Sam Suspicious"},
                    "transactions": [
                        {"transaction_id": "TXN-101", "amount": 9400},
                        {"transaction_id": "TXN-102", "amount": 9600},
                        {"transaction_id": "TXN-103", "amount": 9800},
                    ],
                    "transaction_count": 3,
                }
            if name == "search_policy_docs":
                return {"query": "structuring thresholds", "matches": [
                    {"content": "Structuring is...", "document_name": "AML_Policy.pdf", "page_number": 4, "similarity": 0.41}
                ]}
            raise AssertionError(f"update_customer_risk_score should never reach call_tool(); got {name}")

        steps, result = _run_with_mocks(completions, tool_side_effect)

        self.assertEqual(result.risk_level, "HIGH")
        self.assertIsNotNone(result.risk_update_recommendation)
        self.assertEqual(result.risk_update_recommendation.risk_level, "HIGH")
        self.assertFalse(result.risk_update_recommendation.approved)
        # The gated tool must never reach the real dispatcher.
        self.assertNotIn("update_customer_risk_score", calls_made)
        self.assertEqual(calls_made, ["get_customer_transactions", "search_policy_docs"])


class TestInsufficientInformationScenario(unittest.TestCase):
    """Scenario 3: unknown customer -> agent must not hallucinate a risk
    level, must flag insufficient_information."""

    def test_unknown_customer(self):
        final_json = json.dumps({
            "risk_level": "UNKNOWN",
            "insufficient_information": True,
            "suspicious_patterns": [],
            "evidence": [],
            "policy_references": [],
            "analysis": "No customer record was found for the given ID, so no risk assessment can be made.",
            "recommended_action": "Verify the customer ID and confirm the customer has been onboarded.",
            "risk_update_recommendation": None,
        })

        completions = [
            _fake_completion(tool_calls=[_fake_tool_call("call_1", "get_customer_transactions", {"customer_id": "CUST-DOES-NOT-EXIST"})]),
            _fake_completion(content=final_json),
        ]

        def tool_side_effect(name, **kwargs):
            return {"error": "No customer found with external_id 'CUST-DOES-NOT-EXIST'."}

        steps, result = _run_with_mocks(completions, tool_side_effect)

        self.assertTrue(result.insufficient_information)
        self.assertEqual(result.risk_level, "UNKNOWN")
        self.assertIsNone(result.risk_update_recommendation)


class TestMalformedFinalReport(unittest.TestCase):
    """Control-flow edge case: the model ignores instructions and returns
    non-JSON prose as its final message. The agent must not crash — it
    should fall back to a safe, explicit 'could not parse' result."""

    def test_falls_back_gracefully_on_bad_json(self):
        completions = [
            _fake_completion(tool_calls=[_fake_tool_call("call_1", "get_customer_transactions", {"customer_id": "CUST-TEST"})]),
            _fake_completion(content="This customer looks fine, low risk, no need for JSON here."),
        ]

        def tool_side_effect(name, **kwargs):
            return {"customer": {"external_id": "CUST-TEST"}, "transactions": [], "transaction_count": 0}

        steps, result = _run_with_mocks(completions, tool_side_effect)

        self.assertEqual(result.risk_level, "UNKNOWN")
        self.assertTrue(result.insufficient_information)
        self.assertTrue(len(result.evidence) >= 1)  # raw text preserved for manual review


class _FakeGroqClientWithErrors:
    """Like _FakeGroqClient but some calls can raise exceptions
    (simulating Groq API rejecting an invalid tool call)."""

    def __init__(self, scripted_completions, errors=None):
        self._queue = list(scripted_completions)
        self._errors = list(errors or [])
        self.calls = 0

        class _Completions:
            def create(inner_self, **kwargs):
                self.calls += 1
                if self._errors and self.calls <= len(self._errors):
                    exc = self._errors[self.calls - 1]
                    if isinstance(exc, type):
                        raise exc()
                    raise exc
                if not self._queue:
                    raise AssertionError("Fake Groq client ran out of scripted completions")
                return self._queue.pop(0)

        self.chat = types.SimpleNamespace(completions=_Completions())


def _run_with_mocks_and_errors(scripted_completions, errors, tool_side_effect):
    """Runs run_investigation() with Groq (supporting errors) and MCP mocked."""
    from agents import aml_investigation_agent as agent_mod

    fake_client = _FakeGroqClientWithErrors(scripted_completions, errors)

    with patch.object(agent_mod, "_get_groq_client", return_value=fake_client), \
         patch.object(agent_mod, "call_tool", side_effect=tool_side_effect):
        events = list(agent_mod.run_investigation("CUST-TEST", "Investigate this customer."))

    steps = [e for e in events if not isinstance(e, InvestigationResult)]
    result = events[-1]
    assert isinstance(result, InvestigationResult)
    return steps, result


class TestBogusToolCall(unittest.TestCase):
    """Edge case: Groq hallucinates a tool call to a non-existent tool
    (e.g. "json") carrying the final report as its arguments. The agent
    must treat that as the final report and stop — not crash with a
    400 'tool not in request.tools' error."""

    def test_finalizes_on_unknown_tool_name(self):
        final_json = json.dumps({
            "risk_level": "LOW",
            "insufficient_information": False,
            "suspicious_patterns": [],
            "evidence": ["1 transaction, $500."],
            "policy_references": [],
            "analysis": "Activity is unremarkable.",
            "recommended_action": "No action required.",
            "risk_update_recommendation": None,
        })

        completions = [
            _fake_completion(tool_calls=[_fake_tool_call("call_1", "get_customer_transactions", {"customer_id": "CUST-TEST"})]),
            # Model hallucinates a "json" tool instead of returning plain text.
            _fake_completion(tool_calls=[_fake_tool_call("call_2", "json", {"risk_level": "LOW"})]),
        ]

        def tool_side_effect(name, **kwargs):
            self.assertEqual(name, "get_customer_transactions")
            return {"customer": {"external_id": "CUST-TEST"}, "transactions": [{"transaction_id": "T1", "amount": 500}], "transaction_count": 1}

        steps, result = _run_with_mocks(completions, tool_side_effect)

        self.assertEqual(result.risk_level, "LOW")
        self.assertFalse(result.insufficient_information)
        self.assertFalse(result.truncated)


class TestToolUseFailedRecovery(unittest.TestCase):
    """Real-world scenario: Groq API rejects a tool call with 400
    'tool_use_failed' because the model tried to call an unregistered
    tool (e.g. 'json'). The agent must recover by retrying with
    tool_choice='none' and producing a valid result."""

    def test_recovers_from_tool_use_failed(self):
        final_json = json.dumps({
            "risk_level": "LOW",
            "insufficient_information": False,
            "suspicious_patterns": [],
            "evidence": ["1 transaction, $500."],
            "policy_references": [],
            "analysis": "Activity is unremarkable after recovery.",
            "recommended_action": "No action required.",
            "risk_update_recommendation": None,
        })

        tool_use_error = Exception(
            "Tool call validation failed: attempted to call tool 'json' "
            "which was not in request.tools"
        )

        completions = [
            _fake_completion(content=final_json),
        ]

        def tool_side_effect(name, **kwargs):
            if name == "get_customer_transactions":
                return {
                    "customer": {"external_id": "CUST-TEST", "full_name": "Jane Recovery"},
                    "transactions": [{"transaction_id": "T1", "amount": 500, "currency": "USD"}],
                    "transaction_count": 1,
                }
            return {}

        steps, result = _run_with_mocks_and_errors(
            completions,
            [tool_use_error],
            tool_side_effect,
        )

        self.assertEqual(result.risk_level, "LOW")
        self.assertFalse(result.insufficient_information)
        self.assertFalse(result.truncated)
        self.assertIsNone(result.error)

    def test_fallback_after_repeated_tool_use_failed(self):
        """If tool_use_failed persists, the agent should still produce
        a safe fallback result rather than crash."""

        tool_use_error = Exception(
            "Tool call validation failed: attempted to call tool 'json' "
            "which was not in request.tools"
        )

        completions = [
            _fake_completion(content='{"risk_level": "LOW", "insufficient_information": false}'),
        ]

        def tool_side_effect(name, **kwargs):
            if name == "get_customer_transactions":
                return {
                    "customer": {"external_id": "CUST-TEST"},
                    "transactions": [],
                    "transaction_count": 0,
                }
            return {}

        # Simulate persistent failures (3+ attempts)
        steps, result = _run_with_mocks_and_errors(
            completions,
            [tool_use_error, tool_use_error, tool_use_error],
            tool_side_effect,
        )

        self.assertTrue(result.insufficient_information or result.risk_level in {"LOW", "UNKNOWN"})
        self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()
