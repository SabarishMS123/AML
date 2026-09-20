"""
services/agent_audit.py

Persists every AML Compliance Investigation Agent run to the
`agent_investigations` table, so every tool call, every conclusion, and
every human approval decision is explainable after the fact — the whole
point of an audit trail on a compliance platform.

Lives in services/ (not agents/) to match the existing project convention:
agents/ holds agent reasoning/prompts/models, services/ holds anything that
talks to the database.
"""

from __future__ import annotations

from dataclasses import asdict

from agents.agent_models import InvestigationResult
from database.supabase_client import get_supabase_client


def log_investigation(result: InvestigationResult) -> str | None:
    """Persist a completed (or truncated/errored) investigation. Returns
    the database row id on success, or None if logging failed — logging
    failures never block the UI from showing the investigation result.
    """
    client = get_supabase_client()

    risk_update_rec = None
    if result.risk_update_recommendation:
        risk_update_rec = asdict(result.risk_update_recommendation)

    row = {
        "id": result.investigation_id,
        "customer_external_id": result.customer_id,
        "user_request": result.user_request,
        "tool_trace": result.tool_call_summary(),
        "risk_level": result.risk_level,
        "insufficient_information": result.insufficient_information,
        "suspicious_patterns": result.suspicious_patterns,
        "evidence": result.evidence,
        "policy_references": result.policy_references,
        "analysis": result.analysis,
        "recommended_action": result.recommended_action,
        "risk_update_recommendation": risk_update_rec,
        "risk_update_approved": bool(risk_update_rec and risk_update_rec.get("approved")),
        "raw_report": result.raw_report,
        "truncated": result.truncated,
    }

    try:
        resp = client.table("agent_investigations").insert(row).execute()
        return resp.data[0]["id"] if resp.data else result.investigation_id
    except Exception:  # noqa: BLE001
        # Auditability is important but must never crash the investigation
        # flow itself — the UI still shows the result even if this insert
        # fails (e.g. migration not yet applied).
        return None


def mark_risk_update_approved(investigation_id: str) -> bool:
    """Flip the audit row's approval flag after a human approves the
    recommended risk update in the UI. Returns True on success."""
    client = get_supabase_client()
    try:
        client.table("agent_investigations").update(
            {"risk_update_approved": True}
        ).eq("id", investigation_id).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def list_recent_investigations(limit: int = 10) -> list[dict]:
    """Recent investigations for the audit-trail viewer in the UI."""
    client = get_supabase_client()
    try:
        resp = (
            client.table("agent_investigations")
            .select("id, customer_external_id, user_request, risk_level, "
                     "risk_update_approved, truncated, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception:  # noqa: BLE001
        return []
