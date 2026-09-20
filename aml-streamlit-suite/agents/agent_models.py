"""
agents/agent_models.py

Plain dataclasses used by the AML Compliance Investigation Agent.
Kept dependency-free (no Streamlit, no Groq, no Supabase imports) so they
can be reused by the agent loop, the audit-log service, and the Streamlit
UI without any import cycles.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentStep:
    """One event in the agent's trace, in the order it happened.

    kind is one of:
      "start"        - investigation kicked off
      "tool_call"     - the LLM decided to call a tool
      "tool_result"   - the tool finished and returned a result
      "thinking"      - the LLM is about to analyze a tool result (UI-only marker)
      "final_report"  - the agent produced its final structured report
      "error"         - something went wrong (bad tool args, JSON parse failure, etc.)
    """
    kind: str
    label: str
    detail: str = ""
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class RiskUpdateRecommendation:
    """A risk-score change the agent wants to make, pending human approval.
    Nothing in the database changes until a compliance officer clicks
    'Approve' in the UI, which triggers the real update_customer_risk_score
    tool call.
    """
    customer_id: str
    risk_level: str
    reason: str
    approved: bool = False


@dataclass
class InvestigationResult:
    investigation_id: str = field(default_factory=_new_id)
    customer_id: str = ""
    user_request: str = ""
    steps: list[AgentStep] = field(default_factory=list)

    # Parsed from the agent's final JSON report
    risk_level: str = "UNKNOWN"
    suspicious_patterns: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    policy_references: list[str] = field(default_factory=list)
    analysis: str = ""
    recommended_action: str = ""
    insufficient_information: bool = False

    risk_update_recommendation: RiskUpdateRecommendation | None = None
    raw_report: str = ""
    truncated: bool = False  # hit max tool-call iterations without a final report
    error: str | None = None

    created_at: str = field(default_factory=_now_iso)

    def tool_call_summary(self) -> list[dict]:
        """A compact, JSON-serializable trace of tool calls + results for
        the audit log (full transaction dumps are truncated so the log
        stays readable and small)."""
        summary = []
        for step in self.steps:
            if step.kind == "tool_call":
                summary.append({
                    "tool": step.tool_name,
                    "args": step.tool_args,
                })
            elif step.kind == "tool_result":
                result = step.tool_result or {}
                summary.append({
                    "tool_result_for": step.tool_name,
                    "result_preview": _preview(result),
                })
        return summary


def _preview(result: dict, max_chars: int = 400) -> str:
    text = str(result)
    return text if len(text) <= max_chars else text[:max_chars] + "…"
