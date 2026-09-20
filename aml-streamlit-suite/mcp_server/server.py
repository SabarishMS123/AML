"""
mcp_server/server.py

FastMCP server exposing AML compliance tools over the Model Context
Protocol, so any MCP-compatible client (Claude Desktop, other agents,
IDE integrations, etc.) can query customer data, search policy docs,
and update risk scores.

Run with:
    python mcp_server/server.py

Or via the FastMCP CLI:
    fastmcp run mcp_server/server.py
"""

from __future__ import annotations

import os
import sys

# Allow running this file directly (python mcp_server/server.py) by making
# the project root importable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastmcp import FastMCP

from database.supabase_client import get_supabase_client
from services.rag_chat import retrieve_relevant_chunks

mcp = FastMCP("AML Compliance Suite")


@mcp.tool()
def get_customer_transactions(customer_id: str) -> dict:
    """Fetch a customer's profile and full transaction history.

    Args:
        customer_id: The customer's external_id (as used in uploaded CSVs),
            e.g. "CUST-00123".

    Returns:
        A dict with the customer profile and a list of their transactions.
    """
    client = get_supabase_client()

    cust_resp = (
        client.table("customers")
        .select("*")
        .eq("external_id", customer_id)
        .limit(1)
        .execute()
    )
    if not cust_resp.data:
        return {"error": f"No customer found with external_id '{customer_id}'."}

    customer = cust_resp.data[0]
    txns_resp = (
        client.table("transactions")
        .select("*")
        .eq("customer_id", customer["id"])
        .order("timestamp", desc=True)
        .execute()
    )

    return {
        "customer": customer,
        "transactions": txns_resp.data,
        "transaction_count": len(txns_resp.data),
    }


@mcp.tool()
def search_policy_docs(query: str, match_count: int = 5) -> dict:
    """Semantic search over uploaded AML policy documents.

    Reuses the exact same tuned retrieval pipeline as the Policy Chatbot
    tab (services/rag_chat.retrieve_relevant_chunks) — same similarity
    threshold, same keyword-search fallback, same page/document citation
    metadata — so there is a single RAG implementation used everywhere.

    Args:
        query: Natural-language question or topic to search policy text for.
        match_count: Maximum number of matching excerpts to return (default 5).

    Returns:
        A dict with a list of matching policy excerpts (content, document
        name, page number, similarity score) and their similarity scores.
    """
    chunks = retrieve_relevant_chunks(query, match_count=match_count)
    return {
        "query": query,
        "matches": [
            {
                "content": c.content,
                "document_name": c.document_name,
                "page_number": c.page_number,
                "similarity": c.similarity,
            }
            for c in chunks
        ],
    }


@mcp.tool()
def update_customer_risk_score(customer_id: str, risk_level: str, reason: str) -> dict:
    """Manually set a customer's risk level and log an audit reasoning entry.

    Args:
        customer_id: The customer's external_id, e.g. "CUST-00123".
        risk_level: One of "LOW", "MEDIUM", "HIGH".
        reason: A short justification for the risk level change (for the audit log).

    Returns:
        A dict confirming the update, or an error message.
    """
    risk_level = risk_level.upper().strip()
    if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
        return {"error": "risk_level must be one of LOW, MEDIUM, HIGH."}

    client = get_supabase_client()
    cust_resp = (
        client.table("customers")
        .select("id")
        .eq("external_id", customer_id)
        .limit(1)
        .execute()
    )
    if not cust_resp.data:
        return {"error": f"No customer found with external_id '{customer_id}'."}

    internal_id = cust_resp.data[0]["id"]

    client.table("customers").update({"risk_level": risk_level}).eq("id", internal_id).execute()
    client.table("risk_assessments").insert({
        "customer_id": internal_id,
        "risk_level": risk_level,
        "flags": [],
        "reasoning": f"Manual override via MCP tool: {reason}",
    }).execute()

    return {
        "success": True,
        "customer_id": customer_id,
        "new_risk_level": risk_level,
    }


if __name__ == "__main__":
    mcp.run()
