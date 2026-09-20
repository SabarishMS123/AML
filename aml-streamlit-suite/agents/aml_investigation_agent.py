"""
agents/aml_investigation_agent.py

The actual agent: an LLM tool-calling loop (Groq, OpenAI-compatible
function calling on llama-3.3-70b-versatile) that decides for itself which
of the three MCP tools to call, in what order, and how many times, before
producing a final structured investigation report.

This is the piece that turns the existing RAG + rule-engine pipeline into
a genuine agent: nothing here hardcodes "always fetch transactions, then
always search policy, then always call the LLM once" — the LLM sees the
tool list and the conversation so far, and decides on each turn whether it
needs another tool call or has enough to conclude.

    USER (Streamlit) -> run_investigation() -> Groq (decides tool) ->
    mcp_client.call_tool() -> mcp_server/server.py tool -> (DB / RAG) ->
    result fed back to Groq -> repeat until final JSON report
"""

from __future__ import annotations

import json
import logging
import os
from typing import Generator

from groq import Groq

from agents.agent_models import AgentStep, InvestigationResult, RiskUpdateRecommendation
from agents.agent_prompt import AGENT_SYSTEM_PROMPT
from mcp_client.agent_mcp_client import AUTO_EXECUTE_TOOLS, TOOL_SCHEMAS, call_tool

logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_TOOL_ITERATIONS = 6

# Events yielded from run_investigation are either an AgentStep (for live
# progress display) or, exactly once at the end, the InvestigationResult.
AgentEvent = AgentStep | InvestigationResult


def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in your .env file.")
    return Groq(api_key=api_key)


def _parse_final_report(raw_text: str) -> dict:
    """Defensively parse the agent's final JSON report, tolerating stray
    markdown fences the model might add despite instructions not to."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    return json.loads(cleaned)


def run_investigation(customer_id: str, user_request: str) -> Generator[AgentEvent, None, None]:
    """Run the agentic investigation loop, yielding AgentStep progress
    events as they happen and finally yielding the InvestigationResult.

    Usage (e.g. from Streamlit):
        for event in run_investigation(cust_id, request):
            if isinstance(event, InvestigationResult):
                final = event
            else:
                render_step(event)
    """
    result = InvestigationResult(customer_id=customer_id, user_request=user_request)

    start_step = AgentStep(
        kind="start",
        label="🤖 Agent started investigation",
        detail=f"Customer: {customer_id} — Request: {user_request}",
    )
    result.steps.append(start_step)
    yield start_step

    try:
        client = _get_groq_client()
    except EnvironmentError as exc:
        error_step = AgentStep(kind="error", label="❌ Configuration error", detail=str(exc))
        result.steps.append(error_step)
        result.error = str(exc)
        result.insufficient_information = True
        result.analysis = str(exc)
        yield error_step
        yield result
        return

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Customer ID: {customer_id}\nInvestigation request: {user_request}"},
    ]

    pending_recommendation: RiskUpdateRecommendation | None = None

    tool_use_failed_count = 0

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001
            exc_str = str(exc)
            if "tool_use_failed" in exc_str or "not in request.tools" in exc_str:
                tool_use_failed_count += 1
                if tool_use_failed_count <= 2:
                    logger.warning(
                        "Model attempted an unregistered tool call; retrying with tool_choice=none. Attempt %d",
                        tool_use_failed_count,
                    )
                    force_step = AgentStep(
                        kind="thinking",
                        label="🔄 Recovering — model used an unregistered tool, retrying with text mode",
                        detail="",
                    )
                    result.steps.append(force_step)
                    yield force_step
                    try:
                        completion = client.chat.completions.create(
                            model=GROQ_MODEL,
                            messages=messages,
                            tool_choice="none",
                            temperature=0.1,
                            max_tokens=1200,
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        error_step = AgentStep(
                            kind="error",
                            label="❌ LLM call failed (recovery)",
                            detail=str(retry_exc),
                        )
                        result.steps.append(error_step)
                        result.error = str(retry_exc)
                        result.insufficient_information = True
                        result.analysis = f"The investigation could not complete: {retry_exc}"
                        yield error_step
                        yield result
                        return
                    msg = completion.choices[0].message
                    raw_text = (msg.content or "").strip()
                    result.raw_report = raw_text
                    try:
                        parsed = _parse_final_report(raw_text)
                        result.risk_level = str(parsed.get("risk_level", "UNKNOWN")).upper()
                        result.insufficient_information = bool(parsed.get("insufficient_information", False))
                        result.suspicious_patterns = list(parsed.get("suspicious_patterns", []) or [])
                        result.evidence = list(parsed.get("evidence", []) or [])
                        result.policy_references = list(parsed.get("policy_references", []) or [])
                        result.analysis = str(parsed.get("analysis", ""))
                        result.recommended_action = str(parsed.get("recommended_action", ""))
                        update_rec = parsed.get("risk_update_recommendation")
                        if update_rec and isinstance(update_rec, dict):
                            result.risk_update_recommendation = pending_recommendation or RiskUpdateRecommendation(
                                customer_id=customer_id,
                                risk_level=str(update_rec.get("risk_level", "MEDIUM")).upper(),
                                reason=str(update_rec.get("reason", "")),
                            )
                    except (json.JSONDecodeError, TypeError, ValueError) as parse_exc:
                        logger.warning("Could not parse recovered agent final report as JSON: %s", parse_exc)
                        result.risk_level = "UNKNOWN"
                        result.insufficient_information = True
                        result.analysis = (
                            "The agent's final report could not be parsed after recovery. "
                            "Raw model output is shown below for manual review."
                        )
                        result.evidence = [raw_text[:1000]] if raw_text else []
                    final_step = AgentStep(
                        kind="final_report",
                        label="📄 Final investigation report generated",
                        detail=f"Risk level: {result.risk_level}",
                    )
                    result.steps.append(final_step)
                    yield final_step
                    yield result
                    return
            if tool_use_failed_count > 2:
                error_step = AgentStep(
                    kind="error",
                    label="❌ LLM call failed — persistent tool validation errors",
                    detail=exc_str,
                )
                result.steps.append(error_step)
                result.error = exc_str
                result.insufficient_information = True
                result.analysis = (
                    "The investigation could not complete: the model repeatedly attempted "
                    "to call an unregistered tool. " + exc_str
                )
                yield error_step
                yield result
                return

            error_step = AgentStep(kind="error", label="❌ LLM call failed", detail=str(exc))
            result.steps.append(error_step)
            result.error = str(exc)
            result.insufficient_information = True
            result.analysis = f"The investigation could not complete: {exc}"
            yield error_step
            yield result
            return
            
        msg = completion.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # No more tools requested — this should be the final JSON report.
            raw_text = (msg.content or "").strip()
            result.raw_report = raw_text
            try:
                parsed = _parse_final_report(raw_text)
                result.risk_level = str(parsed.get("risk_level", "UNKNOWN")).upper()
                result.insufficient_information = bool(parsed.get("insufficient_information", False))
                result.suspicious_patterns = list(parsed.get("suspicious_patterns", []) or [])
                result.evidence = list(parsed.get("evidence", []) or [])
                result.policy_references = list(parsed.get("policy_references", []) or [])
                result.analysis = str(parsed.get("analysis", ""))
                result.recommended_action = str(parsed.get("recommended_action", ""))

                update_rec = parsed.get("risk_update_recommendation")
                if update_rec and isinstance(update_rec, dict):
                    # Prefer the recommendation actually captured from a real
                    # tool call (guaranteed consistent customer_id); fall
                    # back to building one from the JSON field if the model
                    # described a recommendation without calling the tool.
                    result.risk_update_recommendation = pending_recommendation or RiskUpdateRecommendation(
                        customer_id=customer_id,
                        risk_level=str(update_rec.get("risk_level", "MEDIUM")).upper(),
                        reason=str(update_rec.get("reason", "")),
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("Could not parse agent final report as JSON: %s", exc)
                result.risk_level = "UNKNOWN"
                result.insufficient_information = True
                result.analysis = (
                    "The agent's final report could not be parsed as structured JSON. "
                    "Raw model output is shown below for manual review."
                )
                result.evidence = [raw_text[:1000]] if raw_text else []

            final_step = AgentStep(
                kind="final_report",
                label="📄 Final investigation report generated",
                detail=f"Risk level: {result.risk_level}",
            )
            result.steps.append(final_step)
            yield final_step
            yield result
            return

        # The LLM requested one or more tool calls — execute each in turn.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        known_tools = {"get_customer_transactions", "search_policy_docs", "update_customer_risk_score"}
        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            call_step = AgentStep(
                kind="tool_call",
                label=f"🔧 Tool selected: {tool_name}",
                detail=json.dumps(tool_args),
                tool_name=tool_name,
                tool_args=tool_args,
            )
            result.steps.append(call_step)
            yield call_step

            if tool_name not in known_tools:
                # The model tried to call a tool that doesn't exist (e.g. a
                # hallucinated "json" tool carrying the final report as its
                # arguments). Treat the arguments as the final report JSON,
                # finalize, and stop the loop rather than feeding an error back
                # and looping forever.
                raw_text = (msg.content or "").strip() or json.dumps(tool_args)
                result.raw_report = raw_text
                try:
                    parsed = tool_args if isinstance(tool_args, dict) else _parse_final_report(raw_text)
                    if not parsed:
                        parsed = _parse_final_report(raw_text)
                    result.risk_level = str(parsed.get("risk_level", "UNKNOWN")).upper()
                    result.insufficient_information = bool(parsed.get("insufficient_information", False))
                    result.suspicious_patterns = list(parsed.get("suspicious_patterns", []) or [])
                    result.evidence = list(parsed.get("evidence", []) or [])
                    result.policy_references = list(parsed.get("policy_references", []) or [])
                    result.analysis = str(parsed.get("analysis", ""))
                    result.recommended_action = str(parsed.get("recommended_action", ""))
                    update_rec = parsed.get("risk_update_recommendation")
                    if update_rec and isinstance(update_rec, dict):
                        result.risk_update_recommendation = pending_recommendation or RiskUpdateRecommendation(
                            customer_id=customer_id,
                            risk_level=str(update_rec.get("risk_level", "MEDIUM")).upper(),
                            reason=str(update_rec.get("reason", "")),
                        )
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    logger.warning("Could not parse agent final report as JSON: %s", exc)
                    result.risk_level = "UNKNOWN"
                    result.insufficient_information = True
                    result.analysis = (
                        "The agent's final report could not be parsed as structured JSON. "
                        "Raw model output is shown below for manual review."
                    )
                    result.evidence = [raw_text[:1000]] if raw_text else []

                tool_result = {
                    "status": "FINAL_REPORT",
                    "message": "Agent produced final report via non-tool message.",
                }
                result_step = AgentStep(
                    kind="tool_result",
                    label=f"✓ Final report received (model used unsupported tool '{tool_name}')",
                    detail="",
                    tool_name=tool_name,
                    tool_result=tool_result,
                )
                result.steps.append(result_step)
                yield result_step

                final_step = AgentStep(
                    kind="final_report",
                    label="📄 Final investigation report generated",
                    detail=f"Risk level: {result.risk_level}",
                )
                result.steps.append(final_step)
                yield final_step
                yield result
                return

            if tool_name == "update_customer_risk_score" and tool_name not in AUTO_EXECUTE_TOOLS:
                # Gated tool: do NOT execute. Queue it for human approval and
                # tell the LLM exactly that, so it doesn't assume success.
                pending_recommendation = RiskUpdateRecommendation(
                    customer_id=tool_args.get("customer_id", customer_id),
                    risk_level=str(tool_args.get("risk_level", "MEDIUM")).upper(),
                    reason=tool_args.get("reason", ""),
                )
                tool_result = {
                    "status": "PENDING_HUMAN_APPROVAL",
                    "message": (
                        "This risk update has been queued for compliance-officer "
                        "approval and has NOT been applied yet. Do not state in your "
                        "report that the customer's risk level has already changed."
                    ),
                }
            else:
                tool_result = call_tool(tool_name, **tool_args)

            result_step = AgentStep(
                kind="tool_result",
                label=f"✓ Result received from {tool_name}",
                detail="",
                tool_name=tool_name,
                tool_result=tool_result,
            )
            result.steps.append(result_step)
            yield result_step

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tool_name,
                "content": json.dumps(tool_result, default=str),
            })

        thinking_step = AgentStep(kind="thinking", label="🧠 Agent analyzing results")
        result.steps.append(thinking_step)
        yield thinking_step

    # Exceeded MAX_TOOL_ITERATIONS without a final report.
    result.truncated = True
    result.risk_level = "UNKNOWN"
    result.insufficient_information = True
    result.analysis = (
        f"The investigation used {MAX_TOOL_ITERATIONS} tool-call rounds without reaching "
        "a final conclusion. This may indicate the request needs to be narrowed, or that "
        "manual review is required."
    )
    truncated_step = AgentStep(kind="error", label="⚠️ Investigation truncated", detail=result.analysis)
    result.steps.append(truncated_step)
    yield truncated_step
    yield result
