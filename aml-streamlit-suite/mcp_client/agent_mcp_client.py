"""
mcp_client/agent_mcp_client.py

A deliberately lightweight "MCP client" for the AML Compliance
Investigation Agent.

Why this isn't a real MCP wire-protocol client
------------------------------------------------
A textbook MCP client talks to the MCP server over stdio or SSE as a
separate process. For a Streamlit request/response cycle, spinning up a
subprocess (and a client session, and a transport) on every investigation
would add real operational complexity for no functional benefit here — the
agent and the MCP server already live in the same Python process and the
same codebase.

Instead, this module imports the exact same tool functions that
`mcp_server/server.py` exposes over MCP for *external* clients (Claude
Desktop, another agent host, etc.), and calls them directly in-process.
There is exactly one implementation of each tool — this file adds zero new
business logic, it's purely a thin, uniform `call_tool(name, **kwargs)`
dispatcher so the agent loop doesn't need to know about three different
Python import paths.

If `mcp_server/server.py` is ever pointed at a real remote MCP server
instead, only this file needs to change (swap the dispatch body for an
actual MCP client session) — the agent loop calling `call_tool(...)`
would not need to change at all.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from mcp_server import server as mcp_server_module

logger = logging.getLogger(__name__)


def _resolve_callable(tool_obj: Any) -> Callable:
    """FastMCP's @mcp.tool() decorator, depending on version, either
    returns the original function unchanged or wraps it in a Tool-like
    object exposing the original under .fn / .func / .callback. Resolve
    whichever shape we got so this file keeps working across versions
    without pinning FastMCP internals.
    """
    for attr in ("fn", "func", "callback", "__wrapped__"):
        candidate = getattr(tool_obj, attr, None)
        if callable(candidate):
            return candidate
    if callable(tool_obj):
        return tool_obj
    raise TypeError(f"Could not resolve a callable MCP tool from {tool_obj!r}")


_TOOL_FUNCS = {
    "get_customer_transactions": _resolve_callable(mcp_server_module.get_customer_transactions),
    "search_policy_docs": _resolve_callable(mcp_server_module.search_policy_docs),
    "update_customer_risk_score": _resolve_callable(mcp_server_module.update_customer_risk_score),
}

# Tool schemas in OpenAI/Groq function-calling format, describing the same
# three tools to the LLM. Kept here (next to the dispatcher) rather than in
# the agent module so the tool *names* and *signatures* the LLM sees can
# never drift out of sync with what call_tool() actually knows how to run.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer_transactions",
            "description": (
                "Fetch a customer's profile and full transaction history. "
                "Call this first for almost any investigation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {
                        "type": "string",
                        "description": "The customer's external_id, e.g. 'CUST-00123'.",
                    }
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy_docs",
            "description": (
                "Semantic search over the bank's uploaded AML policy documents. "
                "Use this to ground a conclusion in an actual policy rule."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language description of the policy topic to search for.",
                    },
                    "match_count": {
                        "type": "integer",
                        "description": "Maximum number of policy excerpts to return.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_customer_risk_score",
            "description": (
                "Propose a new risk level for the customer. This does NOT write to the "
                "database immediately — it is queued for human compliance-officer "
                "approval in the UI."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "risk_level": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH"],
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short justification for the audit log.",
                    },
                },
                "required": ["customer_id", "risk_level", "reason"],
            },
        },
    },
]

# Tools the agent may call and have executed immediately. Anything not in
# this set (currently just update_customer_risk_score) is gated — see
# agents/aml_investigation_agent.py for the human-approval handling.
AUTO_EXECUTE_TOOLS = {"get_customer_transactions", "search_policy_docs"}


def call_tool(name: str, **kwargs) -> dict:
    """Execute one of the three MCP tools in-process and always return a
    JSON-serializable dict, even on failure, so the agent loop can safely
    feed the result straight back to the LLM.
    """
    func = _TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"Unknown tool '{name}'. Available tools: {sorted(_TOOL_FUNCS)}"}
    try:
        result = func(**kwargs)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool '%s' raised an exception with args %s", name, kwargs)
        return {"error": f"Tool '{name}' failed: {exc}"}
